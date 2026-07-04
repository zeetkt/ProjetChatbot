"""
Routeur d'authentification : login et logout.

Gere les pages et actions liees a l'authentification :
- GET  /login  : affiche le formulaire de connexion
- POST /login  : verifie le mot de passe et cree la session
- GET  /logout : detruit la session et redirige vers le login

Securite :
- Rate limiting strict sur le formulaire de login (5 tentatives/minute/IP)
- Pas de message indiquant si le mot de passe est correct ou non
  (juste "Mot de passe incorrect" dans les deux cas)
- Cookie de session : HTTP-only, SameSite=Strict
- Si l'utilisateur est deja connecte, il est redirige vers le chat
"""

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.status import HTTP_303_SEE_OTHER
from slowapi import Limiter
from slowapi.util import get_remote_address
import app.config as cfg
from app.auth import create_session_token, verify_session, SESSION_COOKIE, require_auth

# ─── Initialisation du routeur ─────────────────────────────────────────────────
router = APIRouter()

# Configuration du moteur de templates Jinja2 (pour les pages HTML)
templates = Jinja2Templates(directory="app/templates")

# Rate limiter specifique pour le login (5 tentatives par minute par IP)
# Plus restrictif que la limite globale pour empecher les attaques brute-force
login_limiter = Limiter(key_func=get_remote_address, default_limits=["5/minute"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, already_auth: bool = Depends(verify_session)):
    """
    Affiche la page de connexion.

    Si l'utilisateur est deja authentifie via un cookie de session valide,
    il est directement redirige vers la page principale du chat.

    Args:
        request: La requete HTTP entrante.
        already_auth: Boolen determine par la dependance verify_session.
                      Si True, l'utilisateur a deja une session valide.

    Returns:
        HTMLResponse: La page de login ou une redirection vers le chat.
    """
    if already_auth:
        return RedirectResponse(url="/", status_code=HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login", response_class=HTMLResponse)
@login_limiter.limit("5/minute")  # 5 tentatives de connexion par minute max
async def login_post(
    request: Request,
    password: str = Form(...),  # Valeur du champ "password" du formulaire
):
    """
    Traite la soumission du formulaire de connexion.

    Compare le mot de passe fourni avec celui stocke dans la configuration
    (variable d'environnement CHAT_PASSWORD).

    Si le mot de passe est correct :
    1. Cree un token de session signe (via itsdangerous).
    2. Stocke le token dans un cookie HTTP-only avec SameSite=Strict.
    3. Redirige l'utilisateur vers la page principale du chat.

    Si le mot de passe est incorrect :
    1. Re-affiche la page de login avec un message d'erreur generique.

    Securite :
    - Le cookie est HTTP-only (pas accessible depuis JavaScript)
    - SameSite=Strict (pas envoye sur les requetes cross-site)
    - Le cookie n'est pas Secure (on est en HTTP, pas HTTPS) - a ameliorer
      si un domaine avec HTTPS est ajouté

    Args:
        request: La requete HTTP entrante.
        password: Le mot de passe saisi par l'utilisateur (du formulaire).

    Returns:
        HTMLResponse: Redirection vers / si succes, ou page de login avec erreur.
    """
    if password == cfg.CHAT_PASSWORD:
        # Mot de passe correct → creation de la session
        token, session_id = create_session_token()
        response = RedirectResponse(url="/", status_code=HTTP_303_SEE_OTHER)
        response.set_cookie(
            key=SESSION_COOKIE,
            value=token,
            max_age=cfg.SESSION_MAX_AGE,  # 24h
            httponly=True,                  # Inaccessible depuis JavaScript
            samesite="strict",              # Protege contre les attaques CSRF
            secure=False,                   # False : pas de HTTPS (TODO: mettre True si HTTPS)
        )
        return response

    # Mot de passe incorrect → on re-affiche le formulaire avec une erreur
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": "Mot de passe incorrect."}, status_code=401
    )


@router.get("/logout")
async def logout():
    """
    Deconnecte l'utilisateur en supprimant le cookie de session.

    Le cookie est supprime en le remplacant par un cookie vide avec
    une date d'expiration passee (ce qui force le navigateur a le supprimer).

    Returns:
        RedirectResponse: Redirection vers la page de login.
    """
    response = RedirectResponse(url="/login", status_code=HTTP_303_SEE_OTHER)
    response.delete_cookie(key=SESSION_COOKIE, httponly=True, samesite="strict")
    return response
