"""
Routeur d'administration : gestion des documents.

Gere les routes liees a l'administration des documents :
- GET  /admin          : affiche le tableau de bord admin
- POST /admin/upload   : importe un nouveau fichier
- POST /admin/delete/  : supprime un fichier

L'acces a toutes ces routes est protege par l'authentification.
Seuls les utilisateurs connectes peuvent gerer les documents.
"""

import os
import logging
from pathlib import Path
from fastapi import APIRouter, Request, UploadFile, File, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.status import HTTP_303_SEE_OTHER
import app.config as cfg
from app.auth import require_auth
from app.security import limiter
from app.ingestion import ingest_file
from app.database import get_document_count
from app.chat_logger import get_logs

logger = logging.getLogger(__name__)

# ─── Initialisation du routeur ─────────────────────────────────────────────────
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, _=Depends(require_auth)):
    """
    Affiche le tableau de bord d'administration.

    Cette page permet aux administrateurs de :
    - Voir le nombre total de passages indexes.
    - Uploader de nouveaux documents.
    - Voir la liste des fichiers deja importes.
    - Supprimer des fichiers.

    Args:
        request: La requete HTTP entrante.
        _: Dependance d'authentification.

    Returns:
        HTMLResponse: La page d'administration HTML.
    """
    doc_count = get_document_count()

    # Recupere la liste des fichiers deja importes
    os.makedirs(cfg.DOCUMENTS_PATH, exist_ok=True)
    files = sorted(os.listdir(cfg.DOCUMENTS_PATH)) if os.path.isdir(cfg.DOCUMENTS_PATH) else []

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "document_count": doc_count,
            "files": files,
            "message": None,
            "config": cfg,  # Passe la config pour acceder a MAX_UPLOAD_SIZE_MB dans le template
        },
    )


@router.post("/admin/upload")
@limiter.limit("10/minute")  # Maximum 10 uploads par minute par IP
async def upload_file(
    request: Request,
    file: UploadFile = File(...),  # Fichier envoye via le formulaire
    _=Depends(require_auth),
):
    """
    Importe un nouveau fichier dans la base de connaissances.

    Etapes realisees :
    1. Verifie que l'extension du fichier est autorisee.
    2. Verifie que la taille du fichier ne depasse pas la limite.
    3. Sauvegarde le fichier dans le dossier documents/.
    4. Parse le fichier, decoupe en chunks, indexe dans ChromaDB.
    5. Affiche un message de succes avec le nombre de passages indexes.

    Securite :
    - Verification de l'extension (pas seulement du MIME type)
    - Limitation de taille
    - Nombre d'uploads limite (rate limiting)
    - Si l'analyse echoue, le fichier est supprime (pas de fichier orphelin)

    Args:
        request: La requete HTTP entrante.
        file: Le fichier uploade (UploadFile FastAPI).
        _: Dependance d'authentification.

    Returns:
        HTMLResponse: Re-affiche la page admin avec un message de succes/erreur.

    Raises:
        HTTPException 400: Si l'extension n'est pas autorisee ou fichier trop volumineux.
        HTTPException 500: Si l'analyse du fichier echoue.
    """
    # ─── Validation du nom de fichier (anti path traversal) ────────────────
    raw_filename = file.filename or ""
    # Supprime tout chemin relatif pour ne garder que le nom de base
    safe_filename = Path(raw_filename).name
    if not safe_filename or safe_filename != Path(raw_filename).parts[-1]:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide.")
    # Rejette les noms avec slash, backslash, ou ..
    if "/" in raw_filename or "\\" in raw_filename or ".." in raw_filename:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide.")

    # ─── Validation de l'extension ──────────────────────────────────────────
    ext = Path(safe_filename).suffix.lower()
    if ext not in cfg.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Format non supporte : {ext}. Formats acceptes : {', '.join(cfg.ALLOWED_EXTENSIONS)}",
        )

    # ─── Validation de la taille ────────────────────────────────────────────
    content = await file.read()
    if len(content) > cfg.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Fichier trop volumineux (max {cfg.MAX_UPLOAD_SIZE_MB} Mo).",
        )

    # ─── Sauvegarde du fichier ──────────────────────────────────────────────
    os.makedirs(cfg.DOCUMENTS_PATH, exist_ok=True)
    dest = os.path.join(cfg.DOCUMENTS_PATH, safe_filename)
    with open(dest, "wb") as f:
        f.write(content)

    # ─── Indexation dans ChromaDB ──────────────────────────────────────────
    try:
        chunk_count = ingest_file(dest)
    except Exception as e:
        os.remove(dest)
        logger.error("Erreur analyse fichier %s: %s", safe_filename, e)
        raise HTTPException(status_code=500, detail="Erreur lors de l'analyse du fichier. Format peut-etre corrompu ou non supporte.")

    # ─── Retourne la page admin avec le message de succes ──────────────────
    doc_count = get_document_count()
    files = sorted(os.listdir(cfg.DOCUMENTS_PATH))
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "document_count": doc_count,
            "files": files,
            "message": f"✓ {safe_filename} importe avec succes ({chunk_count} passages indexes).",
            "config": cfg,
        },
    )


@router.post("/admin/delete/{filename}")
@limiter.limit("30/minute")
async def delete_file(
    request: Request,
    filename: str,
    _=Depends(require_auth),
):
    """
    Supprime un fichier importe.

    Note importante : cette fonction supprime uniquement le fichier
    du dossier documents/. Elle ne supprime PAS les chunks de la
    base vectorielle ChromaDB. Les embeddings restent donc presents
    et peuvent encore etre retrouves par les requetes.
    (TODO : ajouter la suppression des chunks associes dans ChromaDB)

    Args:
        request: La requete HTTP entrante.
        filename: Le nom du fichier a supprimer (extrait de l'URL).
        _: Dependance d'authentification.

    Returns:
        RedirectResponse: Redirige vers le tableau de bord admin.
    """
    # Sanitize : interdit les chemins relatifs (path traversal)
    safe_name = Path(filename).name
    if safe_name != filename or ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide.")
    filepath = os.path.join(cfg.DOCUMENTS_PATH, safe_name)
    # Verifie que le fichier est bien dans le dossier autorise
    if not os.path.realpath(filepath).startswith(os.path.realpath(cfg.DOCUMENTS_PATH)):
        raise HTTPException(status_code=400, detail="Nom de fichier invalide.")
    if os.path.isfile(filepath):
        os.remove(filepath)
    return RedirectResponse(url="/admin", status_code=HTTP_303_SEE_OTHER)


@router.get("/admin/logs", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def admin_logs(
    request: Request,
    days: int = 7,
    _=Depends(require_auth),
):
    """
    Affiche les logs des conversations du chat.

    Page d'administration qui liste les derniers echanges
    (question + reponse) classes par date decroissante.

    Args:
        request: La requete HTTP entrante.
        days: Nombre de jours a remonter (defaut: 7, depuis le query param ?days=).
        _: Dependance d'authentification.

    Returns:
        HTMLResponse: La page des logs.
    """
    days = max(1, min(days, 365))
    entries = get_logs(days=days, limit=200)
    doc_count = get_document_count()
    return templates.TemplateResponse(
        "logs.html",
        {
            "request": request,
            "document_count": doc_count,
            "entries": entries,
            "days": days,
            "config": cfg,
        },
    )
