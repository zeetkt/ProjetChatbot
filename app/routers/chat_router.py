"""
Routeur de chat : interface de discussion et API de streaming.

Gere les routes liees au chat :
- GET  /         : affiche l'interface de chat (page HTML)
- POST /api/chat : API de streaming qui retourne la reponse du LLM

Le streaming est implemente avec Server-Sent Events (SSE) :
- Le client envoie une question via POST
- Le serveur repond avec un flux text/event-stream
- Chaque token est envoye dans un event "data:" au format JSON
- La fin du flux est signalee par "data: [DONE]"

Format SSE envoye au client :
    data: {"token": "Bonjour"}
    data: {"token": " !"}
    data: {"token": " Voici"}
    ...
    data: [DONE]

Chaque conversation (question + reponse complete) est automatiquement
enregistree dans les logs via app.chat_logger.
"""

import json
from typing import AsyncGenerator
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.status import HTTP_303_SEE_OTHER
from pydantic import BaseModel
from app.auth import require_auth, get_session_id, verify_session
from app.security import limiter, validate_message_content
from app.chat_logger import log_conversation, log_refused
from app.database import get_document_count
from app.rag import ask
from app.chat_history import add_message, get_history
import app.config as cfg

# ─── Initialisation du routeur ─────────────────────────────────────────────────
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


class ChatRequest(BaseModel):
    """
    Modele Pydantic pour valider le corps de la requete de chat.

    Pydantic valide automatiquement les données envoyées par le client :
    - Le champ "message" doit etre present et etre une chaine de caracteres.
    - Le champ "model" est optionnel (modele OpenRouter choisi par l'utilisateur).
    - Si le format JSON est invalide, FastAPI renvoie une erreur 422.
    """
    message: str
    model: str | None = None
    use_safety: bool = False


@router.get("/", response_class=HTMLResponse)
async def chat_page(request: Request):
    """
    Affiche la page principale du chat.

    Si l'utilisateur n'est pas connecte, redirige vers /login.
    """
    if not verify_session(request):
        return RedirectResponse(url="/login", status_code=HTTP_303_SEE_OTHER)
    doc_count = get_document_count()
    return templates.TemplateResponse(
        "chat.html", {
            "request": request,
            "document_count": doc_count,
            "models": cfg.AVAILABLE_MODELS,
            "default_model": cfg.OPENROUTER_MODEL,
        }
    )


@router.post("/api/chat")
@limiter.limit("30/minute")  # Maximum 30 questions par minute par IP
async def chat_api(
    request: Request,
    body: ChatRequest,
    session_id: str = Depends(get_session_id),
):
    """
    API de chat avec streaming (Server-Sent Events).

    Point d'entrée pour les questions des utilisateurs.
    Retourne un flux SSE (text/event-stream) contenant les tokens
    de la reponse generes par le pipeline RAG.

    Deroulement :
    1. Valide et nettoie le message utilisateur.
    2. Recupere l'historique de la session en cours.
    3. Lance le pipeline RAG (recherche + generation LLM) avec l'historique.
    4. Streame chaque token de la reponse au format SSE.
    5. Sauvegarde la question et la reponse dans l'historique de session.

    Args:
        request: La requete HTTP entrante.
        body: Corps de la requete JSON valide par Pydantic (contient "message").
        session_id: Identifiant de session extrait du cookie (dependance).

    Returns:
        StreamingResponse: Flux SSE contenant les tokens de la reponse.
            Le client doit lire le flux avec l'API ReadableStream
            (voir chat.html pour l'implementation cote navigateur).
    """
    # Validation et nettoyage du message
    question = validate_message_content(body.message)

    # Charge l'historique des echanges precedents de cette session
    history = get_history(session_id)

    # Lance le streaming avec journalisation et sauvegarde d'historique
    return StreamingResponse(
        _stream_and_log(question, history, session_id, model=body.model, use_safety=body.use_safety),
        media_type="text/event-stream",
    )


# ─── Fonction interne de streaming avec journalisation ───────────────────────

async def _stream_and_log(
    question: str,
    history: list[dict],
    session_id: str,
    model: str | None = None,
    use_safety: bool = False,
) -> AsyncGenerator[str, None]:
    """
    Streame la reponse RAG et journalise la conversation a la fin.

    Accumule tous les tokens de la reponse au fur et a mesure,
    les envoie au client via SSE, puis ecrit l'echange complet
    (question + reponse) dans le fichier de logs et sauvegarde
    dans l'historique de session.

    Meme les messages d'erreur ou l'absence de documents sont logges.

    Args:
        question: La question de l'utilisateur (deja validee).
        history: Historique des echanges precedents de cette session.
        session_id: Identifiant de session pour la sauvegarde d'historique.

    Yields:
        str: Lignes au format SSE (data: {...}) pour chaque token.
    """
    full_answer = ""

    # Collecte les tokens generes par le pipeline RAG (avec historique)
    async for token in ask(question, history=history, model=model, use_safety=use_safety):
        full_answer += token
        yield f"data: {json.dumps({'token': token})}\n\n"

    yield "data: [DONE]\n\n"

    # Journalisation : refuse si le pre-filtre a bloque, normale sinon
    REFUSED_PREFIX = "Je ne peux pas repondre"
    if full_answer.startswith(REFUSED_PREFIX):
        log_refused(question, "pre-filtre: motif interdit")
    else:
        log_conversation(question, full_answer)
        # Sauvegarde dans l'historique de session pour le contexte
        add_message(session_id, "user", question)
        add_message(session_id, "assistant", full_answer)
