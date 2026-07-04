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
"""

import os
import re
from pathlib import Path
import app.config as cfg
from app.database import add_document_chunks


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
        fpath = os.path.join(directory, fname)
        if os.path.isfile(fpath) and Path(fname).suffix.lower() in cfg.ALLOWED_EXTENSIONS:
            try:
                count = ingest_file(fpath)
                results[fname] = count
            except Exception as e:
                results[fname] = f"Erreur : {e}"
    return results
