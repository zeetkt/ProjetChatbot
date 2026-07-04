"""
Point d'entree de l'application FastAPI.

Ce module cree et configure l'instance de l'application FastAPI.
Il est lance par uvicorn au demarrage du conteneur :
    uvicorn app.main:app --host 0.0.0.0 --port 8000

Initialisations effectuees au demarrage :
1. Creation des dossiers de stockage (chroma_db, documents) s'ils n'existent pas.
2. Montage du dossier de fichiers statiques (CSS).
3. Enregistrement des routeurs (auth, chat, admin).
4. Configuration du rate limiter global.
5. Ajout du middleware de securite (headers HTTP).
6. Indexation automatique des documents presents dans le dossier documents/.

Ordre des routeurs important :
- auth_router en premier (pour que /login soit disponible avant les routes protegees)
- chat_router (routes / et /api/chat)
- admin_router (routes /admin/*)
"""

import os
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from starlette.status import HTTP_303_SEE_OTHER
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
import app.config as cfg
from app.security import limiter, SecurityHeadersMiddleware
from app.auth import verify_session
from app.routers import auth_router, chat_router, admin_router
from app.ingestion import ingest_directory

# ─── Creation de l'application FastAPI ─────────────────────────────────────────
app = FastAPI(
    title="Chatbot Ecole - RAG",
    description=(
        "Chatbot pedagogique avec RAG (Retrieval Augmented Generation). "
        "Utilise OpenRouter (Gemma 4 12B) et ChromaDB pour repondre "
        "aux questions des eleves basees sur les cours de l'ecole."
    ),
    version="1.0.0",
    docs_url=None,
    openapi_url=None,
)

# ─── Configuration du rate limiter ────────────────────────────────────────────
# slowapi necessite que l'instance limiter soit attachee a l'etat de l'app
app.state.limiter = limiter

# Gestionnaire d'exception pour les depassements de limite de taux
# Renvoie une reponse 429 (Too Many Requests) automatiquement
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ─── Middleware de securite ────────────────────────────────────────────────────
# Ajoute des en-tetes de securite (XSS, clickjacking, etc.) a chaque reponse
app.add_middleware(SecurityHeadersMiddleware)

# ─── Dossiers de stockage ─────────────────────────────────────────────────────
os.makedirs(cfg.CHROMA_DB_PATH, exist_ok=True)
os.makedirs(cfg.DOCUMENTS_PATH, exist_ok=True)

# ─── Fichiers statiques ───────────────────────────────────────────────────────
# Le dossier app/static/ contient style.css et sera accessible via /static/
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# ─── Enregistrement des routeurs ──────────────────────────────────────────────
app.include_router(auth_router.router)  # /login, /logout
app.include_router(chat_router.router)  # /, /api/chat
app.include_router(admin_router.router)  # /admin, /admin/upload, /admin/delete/...


@app.on_event("startup")
async def startup():
    """
    Initialisation executee au demarrage de l'application.

    Actions :
    - Parcourt le dossier documents/ et re-indexe automatiquement tous
      les fichiers qui y sont presents. Cela permet de conserver les
      donnees entre les redemarrages (les fichiers uploads persistent
      grace au volume Docker monte sur /app/documents).

    Note :
        ingest_directory() est synchrone mais appelee dans un contexte
        asynchrone. C'est volontaire : l'indexation initiale doit etre
        terminee avant que l'application ne commence a servir des requetes.
    """
    ingest_directory(cfg.DOCUMENTS_PATH)


@app.on_event("shutdown")
async def shutdown():
    """Nettoie les ressources au shutdown (Playwright browser)."""
    try:
        from app.browser import close as close_browser
        close_browser()
    except Exception:
        pass
