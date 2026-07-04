"""
Module d'interaction avec la base vectorielle ChromaDB.

ChromaDB est une base de donnees vectorielle qui permet de stocker et
de rechercher des documents par similarite semantique. Contrairement
a une base de donnees traditionnelle qui cherche par mots-cles, ChromaDB
compare la "signification" des textes grace aux embeddings.

Architecture du stockage :
- ChromaDB est utilisee en mode "PersistentClient" : les donnees sont
  sauvegardees sur le disque dans le dossier defini par CHROMA_DB_PATH.
- Les documents sont stockes dans une "collection" (analogue a une table).
- Chaque entree contient :
  - Un texte (le chunk de document)
  - Un vecteur d'embedding (generé automatiquement)
  - Des metadonnees (source du document, numero de chunk)
  - Un identifiant unique

Fonctionnalites :
- add_document_chunks : indexe de nouveaux chunks dans la base
- search_similar : recherche les chunks les plus proches d'une question
- get_document_count : retourne le nombre total de chunks indexes
"""

import os
import chromadb
import chromadb.config
from chromadb import Collection
from chromadb.errors import InvalidCollectionException
from functools import lru_cache
import app.config as cfg
from app.embeddings import embedding_function


@lru_cache(maxsize=1)
def get_client() -> chromadb.ClientAPI:
    """
    Cree ou recupere le client ChromaDB (persistant).

    Le client ChromaDB en mode persistant stocke les donnees sur le disque
    dans le dossier specifie par CHROMA_DB_PATH. Les donnees survivent ainsi
    aux redemarrages du conteneur Docker.

    Le decorateur @lru_cache garantit qu'un seul client est cree pour toute
    la duree de vie de l'application (pattern Singleton).

    Returns:
        chromadb.ClientAPI: Le client ChromaDB pret a l'emploi.
    """
    os.makedirs(cfg.CHROMA_DB_PATH, exist_ok=True)
    return chromadb.PersistentClient(
        path=cfg.CHROMA_DB_PATH,
        settings=chromadb.config.Settings(
            anonymized_telemetry=False  # Desactive la telemetrie
        ),
    )


def get_collection() -> Collection:
    """
    Recupere ou cree la collection ChromaDB.

    Si la collection "school_docs" existe deja dans la base (par exemple
    apres un redemarrage), on la recupere. Sinon, on la cree avec la
    fonction d'embedding personnalisee.

    IMPORTANT : ChromaDB ne persiste pas les fonctions d'embedding custom
    entre les sessions. On utilise get_or_create_collection() pour forcer
    l'utilisation de notre EmbeddingFunction (sentence-transformers)
    meme sur une collection existante.

    Note : On ne met pas cette fonction en cache (@lru_cache) car la
    collection pourrait etre modifiee entre deux appels (ajout de donnees).

    Returns:
        Collection: L'objet collection ChromaDB.
    """
    client = get_client()
    return client.get_or_create_collection(
        name=cfg.COLLECTION_NAME,
        embedding_function=embedding_function,
    )


def add_document_chunks(chunks: list[str], metadata_list: list[dict]) -> list[str]:
    """
    Ajoute des chunks de document a la base vectorielle.

    Chaque chunk est automatiquement converti en embedding par la fonction
    d'embedding de la collection (sentence-transformers).

    Si un chunk avec le meme identifiant existe deja, il est remplace
    (utile pour re-indexer un document mis a jour).

    Args:
        chunks: Liste des textes (chunks) a indexer.
        metadata_list: Liste des dictionnaires de metadonnees associes.
            Chaque dictionnaire peut contenir par exemple :
            - "source": nom du fichier d'origine
            - "chunk": numero du chunk dans le document

    Returns:
        list[str]: Liste des identifiants uniques attribues aux chunks.

    Note technique :
        Les identifiants sont generes a partir d'un hash du contenu pour
        permettre la deduplication. Si le meme texte est re-ajoute (avec
        le meme hash), il remplace l'ancienne version.
    """
    collection = get_collection()

    # Genere un identifiant unique pour chaque chunk base sur son contenu
    ids = [f"doc_{hash(chunk)}_{i}" for i, chunk in enumerate(chunks)]

    # Supprime les eventuels doublons (meme contenu deja indexe)
    existing = collection.get(ids=ids)
    if existing["ids"]:
        collection.delete(ids=existing["ids"])

    # Ajoute les nouveaux chunks a la collection
    collection.add(documents=chunks, metadatas=metadata_list, ids=ids)
    return ids


def search_similar(query: str, k: int = 5, where: dict | None = None) -> list[dict]:
    """
    Recherche les chunks les plus proches semantiquement d'une requete.

    Cette fonction est le coeur du RAG (Retrieval Augmented Generation) :
    1. La requete utilisateur est convertie en embedding.
    2. ChromaDB compare cet embedding a tous ceux de la collection.
    3. Les k chunks les plus proches (similarite cosinus) sont retournes.
    4. Ces chunks serviront de contexte pour le LLM.

    Le parametre optionnel `where` permet de filtrer par metadonnees
    (ex: {"source": {"$contains": "CDA"}}).

    Args:
        query: La question ou requete de l'utilisateur.
        k: Nombre de chunks a retourner (defaut: 5).
        where: Filtre optionnel sur les metadonnees (format ChromaDB).

    Returns:
        list[dict]: Liste des chunks trouves, chacun contenant :
            - "content": le texte du chunk
            - "metadata": les metadonnees (source, chunk, ...)
            - "distance": score de similarite (0 = parfait, plus = moins similaire)
    """
    collection = get_collection()
    params = {"query_texts": [query], "n_results": k}
    if where:
        params["where"] = where
    results = collection.query(**params)

    documents = []
    if results["documents"]:
        for i, doc in enumerate(results["documents"][0]):
            documents.append({
                "content": doc,
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distance": results["distances"][0][i] if results["distances"] else 0,
            })
    return documents


def get_document_count() -> int:
    """
    Retourne le nombre total de chunks indexes dans la collection.

    Ce nombre est affiche dans l'interface pour informer l'utilisateur
    de l'etat de la base de connaissances.

    Returns:
        int: Nombre de chunks dans la collection (0 si vide).
    """
    collection = get_collection()
    return collection.count()
