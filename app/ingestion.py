"""
Module d'ingestion de documents : parsing, decoupage (chunking) et indexation.

Ce module est responsable de la premiere etape du pipeline RAG :
convertir des fichiers bruts (PDF, DOCX, TXT, etc.) en chunks de texte
indexes dans la base vectorielle.

Flux de traitement pour un fichier :
1. parse_file()  → lit le fichier et extrait le texte brut
2. chunk_text()  → decoupe le texte en passages (chunks) avec chevauchement
3. add_document_chunks() → indexe les chunks dans ChromaDB (via database.py)

Ajouter un nouveau format de fichier :
1. Creer une fonction _parse_nouveau_format(filepath) -> str
2. Ajouter l'extension dans ALLOWED_EXTENSIONS dans config.py
3. Ajouter un appel a la nouvelle fonction dans parse_file()

Import de sites web :
- _fetch_page()   : telecharge une page web via HTTP
- _crawl_website(): parcourt un site en BFS (profondeur, max pages)
- _sanitize_url_path(): convertit une URL en nom de fichier lisible
- ingest_url()    : point d'entree principal (crawl + sauvegarde + indexation)
- Les metadonnees de crawl sont stockees dans .web_crawls.json
- Les pages sont sauvegardees en .html dans documents/
"""

import os
import re
import json
import secrets
import time as time_module
import logging
from pathlib import Path
from urllib.parse import urljoin, urlparse
import app.config as cfg
from app.database import add_document_chunks

logger = logging.getLogger(__name__)


# ─── Parsing des fichiers ──────────────────────────────────────────────────────

def parse_file(filepath: str) -> str:
    """
    Analyse un fichier et en extrait le texte brut, quel que soit son format.

    Agit comme un "dispatcher" qui oriente le fichier vers le parseur
    approprie en fonction de son extension.

    Args:
        filepath: Chemin complet vers le fichier a analyser.

    Returns:
        str: Le texte brut extrait du fichier.

    Raises:
        ValueError: Si l'extension du fichier n'est pas supportee.

    Extension supportees :
        .pdf  → PyPDF (lecteur PDF)
        .docx → python-docx (documents Word)
        .doc  → python-docx (ancien format Word)
        .md   → markdown + BeautifulSoup (Markdown)
        .html → BeautifulSoup (pages web)
        .htm  → BeautifulSoup (pages web)
        .txt  → lecture directe (texte brut)
    """
    ext = Path(filepath).suffix.lower()
    if ext == ".pdf":
        return _parse_pdf(filepath)
    elif ext in (".docx", ".doc"):
        return _parse_docx(filepath)
    elif ext == ".md":
        return _parse_markdown(filepath)
    elif ext in (".html", ".htm"):
        return _parse_html(filepath)
    elif ext == ".txt":
        return _parse_text(filepath)
    else:
        raise ValueError(f"Format non supporte : {ext}")


def _parse_pdf(filepath: str) -> str:
    """
    Extrait le texte d'un fichier PDF.

    Utilise PyPDF (ex-PyPDF2) pour lire le contenu textuel de chaque page.
    Note : les PDF contenant uniquement des images scannees (sans couche
    texte) ne produiront pas de texte. Un OCR serait necessaire dans ce cas.

    Args:
        filepath: Chemin vers le fichier PDF.

    Returns:
        str: Texte brut concatené de toutes les pages.
    """
    from pypdf import PdfReader
    reader = PdfReader(filepath)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _parse_docx(filepath: str) -> str:
    """
    Extrait le texte d'un fichier DOCX (Word).

    Utilise python-docx pour lire les paragraphes. Note : les tableaux
    et les en-tetes/pieds de page ne sont pas extraits.

    Args:
        filepath: Chemin vers le fichier DOCX.

    Returns:
        str: Texte brut de tous les paragraphes.
    """
    from docx import Document
    doc = Document(filepath)
    return "\n".join(p.text for p in doc.paragraphs)


def _parse_markdown(filepath: str) -> str:
    """
    Convertit un fichier Markdown en texte brut.

    Etapes :
    1. Lit le fichier .md
    2. Convertit le Markdown en HTML (via la bibliotheque markdown)
    3. Extrait le texte du HTML (via BeautifulSoup)

    Args:
        filepath: Chemin vers le fichier Markdown.

    Returns:
        str: Texte brut sans la syntaxe Markdown.
    """
    import markdown
    from bs4 import BeautifulSoup
    with open(filepath, encoding="utf-8") as f:
        html = markdown.markdown(f.read())
    return BeautifulSoup(html, "html.parser").get_text()


def _parse_html(filepath: str) -> str:
    """
    Extrait le texte d'un fichier HTML.

    Utilise BeautifulSoup pour parser le HTML et n'en extraire que
    le contenu textuel (supprime les balises, scripts, styles).

    Args:
        filepath: Chemin vers le fichier HTML.

    Returns:
        str: Texte brut extrait du document HTML.
    """
    from bs4 import BeautifulSoup
    with open(filepath, encoding="utf-8") as f:
        return BeautifulSoup(f.read(), "html.parser").get_text()


def _parse_text(filepath: str) -> str:
    """
    Lit un fichier texte brut.

    Simple lecture du fichier avec l'encodage UTF-8.

    Args:
        filepath: Chemin vers le fichier texte.

    Returns:
        str: Contenu du fichier.
    """
    with open(filepath, encoding="utf-8") as f:
        return f.read()


# ─── Decoupage en chunks (chunking) ────────────────────────────────────────────

def chunk_text(text: str, source: str) -> tuple[list[str], list[dict]]:
    """
    Decoupe un texte long en passages (chunks) de taille limitee.

    Strategie de decoupage :
    1. Nettoie le texte (supprime les sauts de ligne excessifs).
    2. Divise en phrases (base sur la ponctuation . ! ?).
    3. Groupe les phrases jusqu'a atteindre CHUNK_SIZE caracteres.
    4. Chaque chunk conserve un chevauchement (CHUNK_OVERLAP) avec le
       precedent pour ne pas perdre le contexte entre deux passages.

    Args:
        text: Le texte brut a decouper.
        source: Le nom du fichier source (stocke dans les metadonnees).

    Returns:
        tuple: (chunks, metadata_list)
            - chunks: Liste des textes decoupes.
            - metadata_list: Liste des dictionnaires de metadonnees,
              chaque entree contenant "source" et "chunk" (index).

    Note technique :
        Le chevauchement est calcule proportionnellement a CHUNK_OVERLAP
        (en pourcentage de CHUNK_SIZE). On reprend les derniers mots du
        chunk precedent pour assurer la continuite semantique.
    """
    # Nettoie le texte : supprime les suites de >2 sauts de ligne
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return [], []

    chunks = []
    metadata_list = []

    # Decoupage en phrases (approx. : point, point d'exclamation, point d'interrogation)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    current_chunk = ""
    current_size = 0
    chunk_index = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        sentence_len = len(sentence)

        # Si ajouter cette phrase depasse la taille maximale ET qu'on a
        # deja du contenu dans le chunk courant, on finalise le chunk
        if current_size + sentence_len > cfg.CHUNK_SIZE and current_chunk:
            chunks.append(current_chunk.strip())
            metadata_list.append({"source": source, "chunk": chunk_index})
            chunk_index += 1

            # Chevauchement : on reprend les derniers mots du chunk precedent
            overlap = _get_overlap(current_chunk)
            if overlap:
                current_chunk = overlap + " "
                current_size = len(current_chunk)
            else:
                current_chunk = ""
                current_size = 0

        current_chunk += sentence + " "
        current_size += sentence_len + 1

    # Dernier chunk (s'il reste du texte)
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
        metadata_list.append({"source": source, "chunk": chunk_index})

    return chunks, metadata_list


def _get_overlap(chunk: str) -> str:
    """
    Calcule le texte de chevauchement pour assurer la continuite.

    Prend un pourcentage du chunk precedent (defini par CHUNK_OVERLAP)
    pour le reporter au debut du chunk suivant.

    Args:
        chunk: Le texte du chunk precedent.

    Returns:
        str: Les derniers mots du chunk a reporter (ou "" si trop court).
    """
    words = chunk.split()
    overlap_words = max(1, int(len(words) * (cfg.CHUNK_OVERLAP / cfg.CHUNK_SIZE)))
    return " ".join(words[-overlap_words:]) if overlap_words < len(words) else ""


# ─── Fonctions d'ingestion de haut niveau ──────────────────────────────────────

def ingest_file(filepath: str) -> int:
    """
    Ingete un fichier unique dans la base vectorielle.

    Etapes :
    1. Parse le fichier pour en extraire le texte brut.
    2. Decoupe le texte en chunks.
    3. Indexe les chunks dans ChromaDB (avec leurs metadonnees).

    Args:
        filepath: Chemin absolu vers le fichier a ingerer.

    Returns:
        int: Nombre de chunks generes et indexes (0 si fichier vide).
    """
    source = Path(filepath).name
    text = parse_file(filepath)
    chunks, metadata = chunk_text(text, source)
    if chunks:
        add_document_chunks(chunks, metadata)
    return len(chunks)


def ingest_directory(directory: str = None) -> dict[str, int]:
    """
    Ingete tous les fichiers d'un dossier dans la base vectorielle.

    Parcourt recursivement le dossier et ingere chaque fichier dont
    l'extension est dans ALLOWED_EXTENSIONS.

    Cette fonction est appelee automatiquement au demarrage de
    l'application (dans main.py) pour re-indexer les documents
    qui auraient ete ajoutes pendant l'arret du serveur.

    Args:
        directory: Chemin du dossier a parcourir. Si None, utilise
                   cfg.DOCUMENTS_PATH.

    Returns:
        dict: Dictionnaire {nom_fichier: nombre_de_chunks} pour chaque
              fichier ingere, ou {nom_fichier: "Erreur: ..."} en cas d'echec.
    """
    if directory is None:
        directory = cfg.DOCUMENTS_PATH
    results = {}
    if not os.path.isdir(directory):
        return results
    for fname in sorted(os.listdir(directory)):
        if fname.startswith("."):
            continue
        fpath = os.path.join(directory, fname)
        if os.path.isfile(fpath) and Path(fname).suffix.lower() in cfg.ALLOWED_EXTENSIONS:
            try:
                count = ingest_file(fpath)
                results[fname] = count
            except Exception as e:
                results[fname] = f"Erreur : {e}"
    return results


# ─── Import de pages web / sites ───────────────────────────────────────────────

def _is_private_url(url: str) -> bool:
    """Verifie qu'une URL ne pointe pas vers une IP privee/reservee (anti-SSRF)."""
    import socket
    import ipaddress
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        return True
    # Resout le hostname en IPs
    try:
        addrs = socket.getaddrinfo(hostname, None)
    except Exception:
        return True  # Si on ne peut pas resoudre, on bloque par securite
    for addr in addrs:
        ip_str = addr[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return True
            # Cloud metadata / liens locaux
            if str(ip) == "169.254.169.254":
                return True
        except ValueError:
            return True
    return False


def _fetch_page(url: str) -> str | None:
    """Telecharge une page web et retourne son HTML (ou None si erreur)."""
    import httpx
    if _is_private_url(url):
        logger.warning("Blocage SSRF: %s", url)
        return None
    try:
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            current_url = url
            for _ in range(10):
                resp = client.get(
                    current_url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; SchoolBot/1.0)"},
                )
                if resp.status_code in (301, 302, 303, 307, 308):
                    current_url = str(resp.headers.get("location", ""))
                    if not current_url or _is_private_url(current_url):
                        logger.warning("Blocage SSRF redirect: %s", current_url)
                        return None
                    continue
                resp.raise_for_status()
                return resp.text
            logger.warning("Trop de redirections: %s", url)
            return None
    except Exception as e:
        logger.warning("Erreur fetch %s: %s", url, e)
        return None


def _sanitize_url_path(url: str) -> str:
    """Convertit un chemin d'URL en nom de fichier lisible."""
    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "")
    path = parsed.path.strip("/")
    if not path:
        path = "index"
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", path)
    safe = re.sub(r"_+", "_", safe).strip("_")
    return domain, safe


def _crawl_website(
    start_url: str,
    max_pages: int = 50,
    max_depth: int = 2,
) -> list[dict]:
    """
    Parcourt un site web en BFS jusqu'a max_pages pages et max_depth profondeur.

    Retourne une liste de dicts :
        {url, title, text_content, relative_path, depth}
    """
    from bs4 import BeautifulSoup
    parsed_start = urlparse(start_url)
    base_domain = parsed_start.netloc.replace("www.", "")

    visited: set[str] = set()
    pages: list[dict] = []
    queue: list[tuple[str, int]] = [(start_url, 0)]

    while queue and len(pages) < max_pages:
        url, depth = queue.pop(0)
        norm_url = url.rstrip("/")
        if norm_url in visited:
            continue
        visited.add(norm_url)

        logger.info("Crawl [%d/%d] profondeur=%d: %s", len(pages) + 1, max_pages, depth, url)
        html = _fetch_page(url)
        if html is None:
            continue

        soup = BeautifulSoup(html, "html.parser")
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)

        domain, rel_path = _sanitize_url_path(url)
        pages.append({
            "url": url,
            "title": title,
            "text_content": text,
            "relative_path": rel_path,
            "depth": depth,
        })

        if depth < max_depth and len(pages) < max_pages:
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"].strip()
                abs_url = urljoin(url, href)
                parsed = urlparse(abs_url)
                # Même domaine, protocole http(s), pas de fragments
                if parsed.netloc.replace("www.", "") != base_domain:
                    continue
                if parsed.scheme not in ("http", "https"):
                    continue
                if parsed.fragment:
                    continue
                # Ignore les téléchargements
                ext = Path(parsed.path).suffix.lower()
                if ext in (".pdf", ".docx", ".doc", ".zip", ".rar", ".mp4", ".mp3", ".png", ".jpg", ".jpeg", ".gif"):
                    continue
                normal = abs_url.rstrip("/")
                if normal not in visited and (normal, depth + 1) not in queue:
                    queue.append((normal, depth + 1))

        time_module.sleep(cfg.WEB_CRAWL_DELAY)

    return pages


# ─── Gestion des métadonnées de crawls ────────────────────────────────────────

_WEB_CRAWLS_FILE = ".web_crawls.json"


def _load_web_crawls() -> dict:
    """Charge le fichier de métadonnées des crawls."""
    path = os.path.join(cfg.DOCUMENTS_PATH, _WEB_CRAWLS_FILE)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Erreur chargement %s: %s", _WEB_CRAWLS_FILE, e)
        return {}


def _save_web_crawls(data: dict) -> None:
    """Sauvegarde le fichier de métadonnées des crawls."""
    os.makedirs(cfg.DOCUMENTS_PATH, exist_ok=True)
    path = os.path.join(cfg.DOCUMENTS_PATH, _WEB_CRAWLS_FILE)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        logger.error("Erreur sauvegarde %s: %s", _WEB_CRAWLS_FILE, e)


def remove_web_crawl(crawl_id: str) -> list[str]:
    """Supprime tous les fichiers d'un crawl et retourne la liste des noms."""
    data = _load_web_crawls()
    crawl = data.pop(crawl_id, None)
    if not crawl:
        return []
    filenames = [p["filename"] for p in crawl.get("pages", [])]
    for fname in filenames:
        fpath = os.path.join(cfg.DOCUMENTS_PATH, fname)
        if os.path.isfile(fpath):
            os.remove(fpath)
    _save_web_crawls(data)
    return filenames


def remove_webpage_from_crawl(filename: str) -> str | None:
    """Supprime une page d'un crawl. Retourne le crawl_id modifie ou None."""
    data = _load_web_crawls()
    for crawl_id, crawl in data.items():
        for i, page in enumerate(crawl.get("pages", [])):
            if page["filename"] == filename:
                crawl["pages"].pop(i)
                _save_web_crawls(data)
                return crawl_id
    return None


# ─── Ingestion d'une page web ─────────────────────────────────────────────────

def ingest_url(
    url: str,
    max_pages: int | None = None,
    max_depth: int | None = None,
) -> dict:
    """
    Importe une page web (ou un site complet) dans la base de connaissances.

    Etape :
    1. Crawle le site (BFS) jusqu'a max_pages pages.
    2. Sauvegarde chaque page en fichier HTML dans documents/.
    3. Indexe chaque fichier dans ChromaDB.
    4. Enregistre les metadonnees du crawl (.web_crawls.json).

    Args:
        url: URL de depart.
        max_pages: Nombre max de pages a crawler (defaut: cfg.WEB_CRAWL_MAX_PAGES).
        max_depth: Profondeur max de crawl (defaut: cfg.WEB_CRAWL_MAX_DEPTH).

    Returns:
        dict: {"crawl_id": str, "pages": int, "results": {filename: chunk_count}}
    """
    max_pages = max_pages or cfg.WEB_CRAWL_MAX_PAGES
    max_depth = max_depth or cfg.WEB_CRAWL_MAX_DEPTH

    crawl_id = secrets.token_hex(4)
    pages = _crawl_website(url, max_pages=max_pages, max_depth=max_depth)
    if not pages:
        return {"crawl_id": crawl_id, "pages": 0, "results": {}}

    os.makedirs(cfg.DOCUMENTS_PATH, exist_ok=True)
    domain = _sanitize_url_path(url)[0]
    results = {}

    for page in pages:
        rel_path = page["relative_path"]
        filename = f"{domain}__{rel_path}__{crawl_id}.html"
        filepath = os.path.join(cfg.DOCUMENTS_PATH, filename)
        html_content = f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><title>{page["title"]}</title></head>
<body><pre>{page["text_content"]}</pre></body>
</html>"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html_content)

        try:
            count = ingest_file(filepath)
            results[filename] = count
        except Exception as e:
            results[filename] = f"Erreur : {e}"

        page["filename"] = filename

    # Met à jour les métadonnées
    data = _load_web_crawls()
    data[crawl_id] = {
        "domain": domain,
        "url": url,
        "imported_at": time_module.strftime("%Y-%m-%dT%H:%M:%S"),
        "max_pages": max_pages,
        "max_depth": max_depth,
        "pages": [
            {
                "filename": p["filename"],
                "url": p["url"],
                "title": p["title"],
                "depth": p["depth"],
            }
            for p in pages
        ],
    }
    _save_web_crawls(data)

    return {"crawl_id": crawl_id, "pages": len(pages), "results": results}
