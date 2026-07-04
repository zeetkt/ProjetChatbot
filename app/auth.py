"""
Module d'authentification par cookie de session signe.

Utilise le systeme de "signed cookies" de la bibliotheque itsdangerous.
Plutot que de stocker des sessions en base de donnees ou en memoire,
on cree un token cryptographiquement signe que l'on stocke dans un cookie
HTTP-only chez le client. Le token contient une signature qui permet de
verifier son integrite et une date d'expiration qui limite sa duree de vie.

Avantage : pas besoin de base de donnees ou de cache Redis pour les sessions.
Inconvenient : on ne peut pas revoquer une session individuellement.

Fonctionnement :
1. L'utilisateur envoie son mot de passe via le formulaire de login.
2. Si le mot de passe est correct, on cree un token signe avec un session_id.
3. Le token est envoye au client dans un cookie HTTP-only (inaccessible
   depuis JavaScript, ce qui protege contre les vols via XSS).
4. A chaque requete, on verifie la validite du cookie et on extrait le session_id.
5. Pour se deconnecter, on supprime le cookie.
"""

from uuid import uuid4
from typing import Optional
from itsdangerous import URLSafeTimedSerializer
from fastapi import Request, HTTPException, Depends
from fastapi.responses import RedirectResponse
from starlette.status import HTTP_303_SEE_OTHER
import app.config as cfg


# ─── Initialisation du serializer ──────────────────────────────────────────────
# URLSafeTimedSerializer cree des tokens signes et horodates.
# - SECRET_KEY : cle secrete utilisee pour la signature (doit rester privee)
# - salt : "sel" ajoute pour eviter les attaques par reutilisation de signature
#          entre differentes fonctionnalites qui utiliseraient la meme cle
serializer = URLSafeTimedSerializer(cfg.SECRET_KEY, salt="auth-session")

# Nom du cookie HTTP qui contient le token de session
SESSION_COOKIE = "session_token"


def create_session_token() -> tuple[str, str]:
    """
    Cree un token de session signe avec un identifiant unique.

    Le token contient un dictionnaire avec "authenticated": True et un
    "session_id" (UUID v4), ainsi qu'un timestamp de creation et une
    signature cryptographique. Le session_id permet de lier l'historique
    des conversations a la session de l'utilisateur.

    Returns:
        tuple[str, str]: (token signe, session_id) — le token a stocker
        dans le cookie et l'identifiant de session.
    """
    session_id = str(uuid4())
    return serializer.dumps({"authenticated": True, "session_id": session_id}), session_id


def verify_session(request: Request) -> bool:
    """
    Verifie la validite du cookie de session dans la requete.

    Etapes :
    1. Recupere le cookie "session_token" depuis la requete.
    2. Si absent → echec (non authentifie).
    3. Tente de deserialiser le token avec verification de la signature
       et de la date d'expiration (SESSION_MAX_AGE).
    4. Si la signature est invalide ou le token expire → echec.

    Args:
        request: La requete HTTP entrante (contient les cookies).

    Returns:
        bool: True si le token est valide et non expire, False sinon.
    """
    return get_session_data(request) is not None


def get_session_data(request: Request) -> Optional[dict]:
    """
    Extrait les donnees du cookie de session si celui-ci est valide.

    Similaire a verify_session mais retourne le contenu du token
    (payload) plutot qu'un simple boolean. Utile pour recuperer
    le session_id stocke dans le token.

    Args:
        request: La requete HTTP entrante.

    Returns:
        Optional[dict]: Le contenu du token si valide (ex: {"authenticated": True,
        "session_id": "..."}), None si invalide ou absent.
    """
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        return serializer.loads(token, max_age=cfg.SESSION_MAX_AGE)
    except Exception:
        return None


async def get_session_id(request: Request, _=Depends(require_auth)) -> str:
    """
    Dépendance FastAPI qui retourne l'identifiant de session unique.

    Utilise require_auth pour garantir que l'utilisateur est authentifie,
    puis extrait le session_id du cookie. Ce session_id sert de cle
    pour recuperer l'historique de conversation.

    Compatibilite ascendante : si le cookie ne contient pas de session_id
    (anciens tokens crees avant l'ajout de cette fonctionnalite), on utilise
    le token lui-meme comme identifiant de session.

    Args:
        request: La requete HTTP entrante.
        _: Dependance d'authentification.

    Returns:
        str: L'identifiant unique de la session.

    Raises:
        HTTPException 401: Si l'utilisateur n'est pas authentifie.
    """
    data = get_session_data(request)
    if data is None:
        raise HTTPException(status_code=401, detail="Non authentifie.")
    session_id = data.get("session_id")
    if not session_id:
        session_id = request.cookies.get(SESSION_COOKIE, "")
    return session_id


async def require_auth(request: Request):
    """
    Dépendance FastAPI qui exige une authentification valide.

    A utiliser comme dependance sur les routes protegees :
        @router.get("/admin")
        async def admin_page(request: Request, _=Depends(require_auth)):
            ...

    Si l'utilisateur n'est pas authentifie, une exception HTTP 401 est levee,
    ce qui entraine une erreur 401 pour les appels API, ou peut etre attrape
    pour rediriger vers la page de login.

    Args:
        request: La requete HTTP entrante.

    Raises:
        HTTPException 401: Si l'utilisateur n'est pas authentifie.
    """
    if not verify_session(request):
        raise HTTPException(status_code=401, detail="Non authentifie.")


async def optional_auth(request: Request) -> bool:
    """
    Dépendance FastAPI pour verifier l'authentification sans bloquer.

    Utile pour les pages qui affichent un contenu different selon que
    l'utilisateur est connecte ou non (ex: page de login qui redirige
    si deja authentifie).

    Args:
        request: La requete HTTP entrante.

    Returns:
        bool: True si l'utilisateur est authentifie, False sinon.
    """
    return verify_session(request)
