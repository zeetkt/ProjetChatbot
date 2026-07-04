"""
Module principal du pipeline RAG (Retrieval Augmented Generation).

Le RAG est le coeur du chatbot. Il combine deux etapes :
1. RETRIEVAL (recherche) : trouve les passages pertinents dans la base
   vectorielle en fonction de la question de l'utilisateur.
2. GENERATION : envoie ces passages comme contexte a un LLM (OpenRouter)
   pour generer une reponse informee par les documents.

Pipeline complet :
    Question utilisateur
        → preuve OFFENSIVE_PATTERNS → refus direct (si match)
            → search_similar() → recupere les chunks pertinents
                → generate_answer() → envoie contexte + question au LLM
                    → streaming de la reponse vers l'interface

Gestion des erreurs :
    Les erreurs API (cle invalide, limite de taux, connexion) sont
    capturees et converties en messages explicites pour l'utilisateur.

Filtrage :
    Un pre-filtre regex bloque les questions contenant des motifs interdits
    (piratage, contenu illegal, etc.) avant meme d'appeler le LLM. Les
    questions refusees sont journalisees dans chat_logger.
"""

import logging
import re
from typing import AsyncGenerator
from openai import AuthenticationError, APIConnectionError, RateLimitError
from app.database import search_similar
from app.llm import generate_answer

logger = logging.getLogger(__name__)

# ─── Pre-filtre : motifs interdits (zéro appel LLM) ─────────────────────────ｐ
# Toute question contenant un de ces motifs est refusee immediatement et
# journalisee. La liste est volontairement petite et conservatrice :
# le LLM fait le gros du filtrage via le prompt systeme.
# Ajouter un motif ici uniquement pour les cas qu'on ne veut JAMAIS envoyer
# au LLM, meme pour analyse.
OFFENSIVE_PATTERNS = [
    r"pirat", r"crack", r"fissur",
    r"drogue", r"stup([ée])fiant",
    r"arme", r"explosif",
    r"contenu\s*(illegal|illicite)",
    r"violence", r"agression",
    r"contourn.*(regle|loi|securite)",
    r"ignor.*instruction",
    r"(?:tu|vous)\s+(?:es|etes|est)\s+(?:libre|sans\s+contrainte)",
]

# ─── Filtrage intelligent des documents par sujet ────────────────────────────
# Associe des mots-cles aux noms de documents pour ameliorer le RAG.
# Quand la question contient un mot-cle, on donne la priorite aux chunks
# du document correspondant via un filtre ChromaDB.
_TOPIC_KEYWORDS: dict[str, str] = {
    "cda": "CDA",
    "concepteur développeur": "CDA",
    "tssr": "TSSR",
    "technicien supérieur systèmes et réseaux": "TSSR",
    "samba": "Samba",
    "référentiel": "REAC",
    "reac": "REAC",
    "rncp31113": "RNCP31113",
    "rncp31114": "RNCP31114",
    "rncp 31113": "RNCP31113",
    "rncp 31114": "RNCP31114",
}


def _detect_topic_filter(question: str) -> dict | None:
    q = question.lower()
    for keyword, doc_slug in _TOPIC_KEYWORDS.items():
        if keyword in q:
            return {"source": {"$contains": doc_slug}}
    return None


def _dedup_chunks(chunks: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for c in chunks:
        h = hash(c["content"])
        if h not in seen:
            seen.add(h)
            result.append(c)
    return result


def _merge_dedup(filtered: list[dict], general: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for c in filtered + general:
        h = hash(c["content"])
        if h not in seen:
            seen.add(h)
            result.append(c)
    return result


async def ask(
    question: str,
    history: list[dict] | None = None,
) -> AsyncGenerator[str, None]:
    """
    Point d'entree principal du pipeline RAG.

    Enchaine la recherche vectorielle et la generation de reponse.
    Cette fonction est un generateur asynchrone qui produit les tokens
    de la reponse un par un (streaming).

    Deroulement :
    1. Recherche les 5 chunks les plus proches de la question.
    2. Si aucun chunk trouve → message informant qu'il faut importer des docs.
    3. Sinon → genere une reponse via le LLM avec le contexte et l'historique.
    4. En cas d'erreur API → message explicite (cle invalide, timeout, etc.).

    Args:
        question: La question posee par l'utilisateur (deja validee).
        history: Liste optionnelle des messages precedents de la conversation.

    Yields:
        str: Tokens de la reponse, ou message d'erreur, ou message
             d'information si la base est vide.

    Note sur la gestion d'erreurs :
        Les exceptions OpenRouter specifiques sont capturees pour donner
        un feedback utile a l'utilisateur. Les autres exceptions sont
        capturees generiquement pour eviter les erreurs 500 silencieuses.
    """
    # Etape 0 : Pre-filtre - motifs interdits
    # Note : le logging du refus est fait dans _stream_and_log (chat_router.py)
    question_lower = question.lower()
    for pattern in OFFENSIVE_PATTERNS:
        if re.search(pattern, question_lower):
            yield "Je ne peux pas repondre a cette question."
            return

    # Etape 1 : RETRIEVAL - recherche les chunks pertinents dans ChromaDB
    TOP_K = 10

    # Si la question mentionne un document specifique, on cible sa source
    topic_filter = _detect_topic_filter(question)
    if topic_filter:
        filtered = search_similar(question, k=TOP_K, where=topic_filter)
        general = search_similar(question, k=TOP_K)
        context_chunks = _merge_dedup(filtered, general)
    else:
        context_chunks = search_similar(question, k=TOP_K)

    context_chunks = _dedup_chunks(context_chunks)

    # Si aucun document n'est indexe, on informe l'utilisateur
    if not context_chunks:
        yield ("Aucun document n'a ete trouve dans la base de connaissances. "
               "Veuillez d'abord importer des cours ou documents.")
        return

    # Etape 2 : GENERATION - envoie le contexte + historique au LLM et streame la reponse
    try:
        async for token in generate_answer(question, context_chunks, history=history):
            yield token
    except AuthenticationError:
        yield "Erreur : la cle API OpenRouter n'est pas valide ou n'est pas configuree."
    except RateLimitError:
        yield "Erreur : limite de taux OpenRouter depassee. Reessaie dans quelques instants."
    except APIConnectionError:
        yield "Erreur : impossible de contacter OpenRouter. Verifie ta connexion internet."
    except Exception as e:
        logger.error("Erreur generation reponse: %s", e, exc_info=True)
        yield "Erreur lors de la generation de la reponse. Reessaie ou contacte l'administrateur."
