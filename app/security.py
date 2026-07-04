"""
Module de securite pour l'application FastAPI.

Fournit :
1. Rate limiting (limitation du nombre de requetes) via slowapi
2. Middleware qui ajoute des en-tetes de securite a chaque reponse HTTP
3. Validation du contenu des messages utilisateur
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware


# ─── Rate Limiter global ────────────────────────────────────────────────────────
# Limiteur de requetes base sur l'adresse IP du client.
# get_remote_address extrait l'IP du client depuis la requete.
# default_limits fixe la limite par defaut a 60 requetes par minute.
# Des limites plus strictes sont appliquees individuellement sur les routes
# sensibles (login : 5/min, chat : 30/min, upload : 10/min).
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware FastAPI qui ajoute des en-tetes de securite a chaque reponse.

    Ce middleware est execute pour chaque requete HTTP. Il intercepte la reponse
    avant qu'elle ne soit envoyee au client et y ajoute des headers qui
    renforcent la securite contre les attaques courantes (XSS, clickjacking, etc.).

    Bonnes pratiques OWASP https://owasp.org/www-project-secure-headers/
    """

    async def dispatch(self, request: Request, call_next):
        """
        Traite chaque requete et ajoute les headers de securite.
        
        Args:
            request: La requete HTTP entrante.
            call_next: Fonction qui appelle le middleware suivant ou la route.
            
        Returns:
            Response: La reponse HTTP avec les headers de securite ajoutes.
        """
        # Laisse le reste de l'application traiter la requete normalement
        response = await call_next(request)

        # ─── En-tetes de securite HTTP ──────────────────────────────────────
        # X-Content-Type-Options: empeche le navigateur de deviner le type MIME
        # (evite les attaques de "MIME sniffing")
        response.headers["X-Content-Type-Options"] = "nosniff"

        # X-Frame-Options: empeche l'affichage du site dans une iframe
        # (protege contre le clickjacking)
        response.headers["X-Frame-Options"] = "DENY"

        # X-XSS-Protection: active le filtre XSS integre des navigateurs
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Referrer-Policy: controle les informations envoyees dans l'en-tete Referer
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions-Policy: desactive les fonctionnalites du navigateur inutiles
        # (camera, microphone, geolocalisation) pour reduire la surface d'attaque
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        # Strict-Transport-Security: force HTTPS pendant 1 an (inclus subdomaines)
        # Preload possible si le domaine est soumis aux preload lists HSTS
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # Cache-Control: empeche la mise en cache des pages sensibles
        response.headers["Cache-Control"] = "no-store"

        # Content-Security-Policy: limite les sources autorisees pour
        # scripts, styles, connexions, etc. Empeche l'execution de
        # scripts injectes (XSS) meme si une faille existe ailleurs.
        # 'unsafe-inline' est necessaire car le JS est inline dans chat.html.
        # En production avec un build step, on pourrait utiliser un nonce.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "form-action 'self'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'"
        )

        return response


def validate_message_content(content: str) -> str:
    """
    Nettoie et valide le contenu d'un message utilisateur.

    Applique les controles suivants :
    - Suppression des espaces superflus (strip)
    - Rejet des messages vides
    - Rejet des messages trop longs (> 10 000 caracteres)

    Args:
        content: Le message brut envoye par l'utilisateur.

    Returns:
        str: Le message nettoye.

    Raises:
        HTTPException 400: Si le message est vide ou trop long.
    """
    content = content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Le message ne peut pas etre vide.")
    if len(content) > 10000:
        raise HTTPException(status_code=400, detail="Le message est trop long (max 10000 caracteres).")
    return content
