"""
Module de generation d'embeddings (representations vectorielles).

Ce module encapsule l'utilisation de la bibliotheque sentence-transformers
pour convertir du texte en vecteurs numeriques (embeddings). Ces vecteurs
permettent de mesurer la similarite semantique entre differents textes
en comparant la distance cosine entre leurs embeddings.

L'embedding est une etape cruciale du pipeline RAG :
1. A l'indexation : chaque chunk de document est converti en vecteur
   et stocke dans ChromaDB avec son vecteur.
2. A la recherche : la question de l'utilisateur est convertie en vecteur,
   et ChromaDB retrouve les chunks les plus proches semantiquement.

Le modele utilise est multilingue (paraphrase-multilingual-MiniLM-L12-v2)
et supporte le francais. Il est charge en memoire une seule fois (caching)
et reste resident pour toute la duree de vie de l'application.

Poids du modele : environ 470 Mo (telecharge au premier demarrage uniquement).
"""

from sentence_transformers import SentenceTransformer
from functools import lru_cache
import app.config as cfg


@lru_cache(maxsize=1)
def load_model() -> SentenceTransformer:
    """
    Charge le modele sentence-transformers avec mise en cache.

    Le decorateur @lru_cache garantit que le modele n'est charge qu'une seule
    fois, meme si cette fonction est appelee depuis plusieurs endroits.
    Le modele est telecharge depuis Hugging Face Hub au premier appel,
    puis reste en memoire.

    Note : Le premier chargement peut prendre 10-30 secondes selon la
    connexion internet et la puissance de la machine (telechargement
    du modele depuis Hugging Face).

    Returns:
        SentenceTransformer: Le modele charge et pret a l'emploi.
    """
    return SentenceTransformer(cfg.EMBEDDING_MODEL)


class EmbeddingFunction:
    """
    Fonction d'embedding compatible avec l'API ChromaDB.

    ChromaDB attend une fonction d'embedding avec la signature :
        __call__(self, input: List[str]) -> List[List[float]]

    Cette classe implemente cette interface. Elle utilise le modele
    sentence-transformers pour generer les embeddings.

    Les embeddings sont normalises (norme L2 = 1) pour pouvoir utiliser
    la distance cosinus via un simple produit scalaire (plus rapide).

    Usage:
        embedding_fn = EmbeddingFunction()
        vectors = embedding_fn(["texte 1", "texte 2"])
    """

    def __call__(self, input: list[str]) -> list[list[float]]:
        """
        Convertit une liste de textes en vecteurs d'embedding.

        Args:
            input: Liste de textes a encoder (ex: chunks de documents).

        Returns:
            Liste de vecteurs (list[list[float]]). Chaque vecteur a une
            dimension de 384 (pour le modele MiniLM).

        Note technique :
            - show_progress_bar=False : pas de barre de progression (logs)
            - normalize_embeddings=True : normalise les vecteurs pour que
              le produit scalaire soit equivalent a la similarite cosinus
        """
        model = load_model()
        return model.encode(input, show_progress_bar=False, normalize_embeddings=True).tolist()


# Instance unique de la fonction d'embedding, utilisee dans toute l'application
# (notamment dans database.py pour la creation de la collection ChromaDB)
embedding_function = EmbeddingFunction()
