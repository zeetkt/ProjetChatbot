"""
Routeur d'administration : gestion des documents.

Gere les routes liees a l'administration des documents :
- GET  /admin                  : affiche le tableau de bord admin
- POST /admin/upload           : importe des fichiers (multi)
- POST /admin/import-url       : importe une page web / site
- POST /admin/delete/{filename}  : supprime un fichier
- POST /admin/delete-webpage/{filename} : supprime une page web d'un crawl
- POST /admin/delete-website/{crawl_id} : supprime tout un site importe

L'acces a toutes ces routes est protege par l'authentification.
"""

import os
import logging
from pathlib import Path
from typing import List
from fastapi import APIRouter, Request, UploadFile, File, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.status import HTTP_303_SEE_OTHER
import app.config as cfg
from app.auth import require_auth
from app.security import limiter
from app.ingestion import ingest_file, ingest_url, remove_web_crawl, remove_webpage_from_crawl, _load_web_crawls
from app.database import get_document_count, delete_document_by_sources
from app.chat_logger import get_logs

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _get_admin_context(request: Request, message: str | None = None):
    """Génère le contexte partagé pour les pages admin."""
    doc_count = get_document_count()
    os.makedirs(cfg.DOCUMENTS_PATH, exist_ok=True)
    raw_files = sorted(os.listdir(cfg.DOCUMENTS_PATH)) if os.path.isdir(cfg.DOCUMENTS_PATH) else []
    files = [f for f in raw_files if not f.startswith(".")]
    web_crawls = _load_web_crawls()
    return {
        "request": request,
        "document_count": doc_count,
        "files": files,
        "web_crawls": web_crawls,
        "message": message,
        "config": cfg,
    }


def _validate_filename(raw_filename: str) -> str:
    """Valide et nettoie un nom de fichier (anti path traversal)."""
    safe = Path(raw_filename).name
    if not safe or safe != Path(raw_filename).parts[-1]:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide.")
    if "/" in raw_filename or "\\" in raw_filename or ".." in raw_filename:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide.")
    return safe


def _validate_and_save_file(content: bytes, safe_filename: str) -> str:
    """Sauvegarde un fichier valide dans documents/."""
    os.makedirs(cfg.DOCUMENTS_PATH, exist_ok=True)
    dest = os.path.join(cfg.DOCUMENTS_PATH, safe_filename)
    with open(dest, "wb") as f:
        f.write(content)
    return dest


# ─── Page d'accueil admin ─────────────────────────────────────────────────────

@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, _=Depends(require_auth)):
    return templates.TemplateResponse("admin.html", _get_admin_context(request))


# ─── Upload multi-fichiers ────────────────────────────────────────────────────

@router.post("/admin/upload")
@limiter.limit("10/minute")
async def upload_files(
    request: Request,
    files: List[UploadFile] = File(...),
    _=Depends(require_auth),
):
    if len(files) > cfg.MAX_FILES_PER_UPLOAD:
        raise HTTPException(
            status_code=400,
            detail=f"Trop de fichiers (max {cfg.MAX_FILES_PER_UPLOAD}).",
        )

    results: list[dict] = []

    for file in files:
        raw_filename = file.filename or ""
        try:
            safe_filename = _validate_filename(raw_filename)
            ext = Path(safe_filename).suffix.lower()
            if ext not in cfg.ALLOWED_EXTENSIONS:
                results.append({
                    "name": raw_filename,
                    "success": False,
                    "error": f"Format non supporte : {ext}",
                })
                continue

            content = await file.read()
            if len(content) > cfg.MAX_UPLOAD_SIZE:
                results.append({
                    "name": safe_filename,
                    "success": False,
                    "error": f"Fichier trop volumineux (max {cfg.MAX_UPLOAD_SIZE_MB} Mo).",
                })
                continue

            dest = _validate_and_save_file(content, safe_filename)
            chunk_count = ingest_file(dest)
            results.append({
                "name": safe_filename,
                "success": True,
                "chunks": chunk_count,
            })
        except Exception as e:
            logger.error("Erreur upload %s: %s", raw_filename, e)
            results.append({
                "name": raw_filename,
                "success": False,
                "error": "Erreur lors de l'analyse du fichier.",
            })

    ctx = _get_admin_context(request, message=f"{sum(1 for r in results if r['success'])} fichier(s) importe(s) sur {len(results)}.")
    ctx["upload_results"] = results
    return templates.TemplateResponse("admin.html", ctx)


# ─── Import de site web (URL) ─────────────────────────────────────────────────

@router.post("/admin/import-url")
@limiter.limit("5/minute")
async def import_url(
    request: Request,
    url: str = Form(...),
    depth: int = Form(cfg.WEB_CRAWL_MAX_DEPTH),
    max_pages: int = Form(cfg.WEB_CRAWL_MAX_PAGES),
    _=Depends(require_auth),
):
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL invalide. Doit commencer par http:// ou https://")
    depth = max(0, min(depth, 5))
    max_pages = max(1, min(max_pages, 200))

    try:
        result = ingest_url(url, max_pages=max_pages, max_depth=depth)
        n = result.get("pages", 0)
        if n == 0:
            msg = f"Aucune page n'a pu etre importee depuis {url}."
        else:
            ok = sum(1 for v in result["results"].values() if isinstance(v, int))
            msg = f"✓ {n} page(s) importee(s) depuis {url} ({ok} indexees avec succes, crawl_id: {result['crawl_id']})."
    except Exception as e:
        logger.error("Erreur import url %s: %s", url, e)
        msg = f"Erreur lors de l'import de {url} : {e}"

    ctx = _get_admin_context(request, message=msg)
    ctx["upload_results"] = []
    return templates.TemplateResponse("admin.html", ctx)


# ─── Suppression d'un fichier ─────────────────────────────────────────────────

@router.post("/admin/delete/{filename}")
@limiter.limit("30/minute")
async def delete_file(
    request: Request,
    filename: str,
    _=Depends(require_auth),
):
    safe_name = _validate_filename(filename)
    filepath = os.path.join(cfg.DOCUMENTS_PATH, safe_name)
    if not os.path.realpath(filepath).startswith(os.path.realpath(cfg.DOCUMENTS_PATH)):
        raise HTTPException(status_code=400, detail="Nom de fichier invalide.")

    # Supprime les chunks de ChromaDB
    deleted = delete_document_by_sources([safe_name])

    # Supprime le fichier
    if os.path.isfile(filepath):
        os.remove(filepath)

    # Nettoie les métadonnées de crawl si besoin
    remove_webpage_from_crawl(safe_name)

    ctx = _get_admin_context(
        request,
        message=f"✓ {safe_name} supprime ({deleted} passage(s) supprime(s) de la base).",
    )
    return templates.TemplateResponse("admin.html", ctx)


# ─── Suppression d'une page web d'un crawl ────────────────────────────────────

@router.post("/admin/delete-webpage/{filename}")
@limiter.limit("30/minute")
async def delete_webpage(
    request: Request,
    filename: str,
    _=Depends(require_auth),
):
    safe_name = _validate_filename(filename)
    filepath = os.path.join(cfg.DOCUMENTS_PATH, safe_name)
    if not os.path.realpath(filepath).startswith(os.path.realpath(cfg.DOCUMENTS_PATH)):
        raise HTTPException(status_code=400, detail="Nom de fichier invalide.")

    deleted = delete_document_by_sources([safe_name])
    if os.path.isfile(filepath):
        os.remove(filepath)
    remove_webpage_from_crawl(safe_name)

    ctx = _get_admin_context(
        request,
        message=f"✓ Page {safe_name} supprimee ({deleted} passage(s)).",
    )
    return templates.TemplateResponse("admin.html", ctx)


# ─── Suppression d'un site complet ────────────────────────────────────────────

@router.post("/admin/delete-website/{crawl_id}")
@limiter.limit("30/minute")
async def delete_website(
    request: Request,
    crawl_id: str,
    _=Depends(require_auth),
):
    filenames = remove_web_crawl(crawl_id)
    total = 0
    for fname in filenames:
        total += delete_document_by_sources([fname])

    ctx = _get_admin_context(
        request,
        message=f"✓ Site supprime ({len(filenames)} fichier(s), {total} passage(s)).",
    )
    return templates.TemplateResponse("admin.html", ctx)


# ─── Logs ─────────────────────────────────────────────────────────────────────

@router.get("/admin/logs", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def admin_logs(
    request: Request,
    days: int = 7,
    _=Depends(require_auth),
):
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
