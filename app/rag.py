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
import os
import re
from pathlib import Path
from typing import AsyncGenerator
from openai import AuthenticationError, APIConnectionError, RateLimitError
import app.config as cfg
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
# Au lieu de mots-cles en dur, on extrait automatiquement les slugs de sujets
# depuis les noms de fichiers dans le dossier documents. Par exemple :
#   "REAC_CDA_V04_24052023.pdf" → extrait "CDA", "REAC"
#   "2.2.1 - Cours - TP - Samba_V2023.docx" → extrait "Samba"
# Cela permet d'ajouter des documents sans modifier le code.
_GENERIC_WORDS = frozenset({
    "cours", "tp", "td", "exo", "corrige", "v0", "v1", "v2", "v3", "v4",
    "v5", "new", "old", "draft", "final", "revision", "reac",
})


def _get_file_slugs() -> dict[str, str]:
    """Extrait des mots-cles de sujet depuis les noms de fichiers documents."""
    slugs: dict[str, str] = {}
    docs_path = cfg.DOCUMENTS_PATH
    if not os.path.isdir(docs_path):
        return slugs
    for fname in os.listdir(docs_path):
        name = Path(fname).stem
        parts = re.split(r'[_\-.\s]+', name)
        for part in parts:
            word = part.strip()
            lo = word.lower()
            if (word.isalpha() and len(lo) >= 3
                    and lo not in _GENERIC_WORDS
                    and lo not in slugs):
                slugs[lo] = word  # garde la casse originale
    return slugs


def _detect_topic(question: str, history: list[dict] | None = None) -> str | None:
    q = question.lower()

    # 1. Mots-cles extraits automatiquement des noms de fichiers
    for keyword, slug in _get_file_slugs().items():
        if keyword in q:
            return slug

    # 2. Heritage depuis l'historique conversationnel
    if history:
        for msg in reversed(history):
            if msg.get("role") == "user":
                t = _detect_topic(msg.get("content", ""))
                if t:
                    return t
    return None


def _merge_dedup(a: list[dict], b: list[dict]) -> list[dict]:
    seen = set()
    result = a[:]
    for c in result:
        seen.add(hash(c["content"]))
    for c in b:
        h = hash(c["content"])
        if h not in seen:
            seen.add(h)
            result.append(c)
    return result


def _diversify_chunks(
    chunks: list[dict],
    topic: str | None = None,
    max_per_source: int = 4,
    max_total: int = 10,
) -> list[dict]:
    # 1. Separer les chunks du document cible et des autres
    target = []
    others = []
    topic_lower = topic.lower() if topic else None
    for c in chunks:
        src = c["metadata"].get("source", "").lower()
        if topic_lower and topic_lower in src:
            target.append(c)
        else:
            others.append(c)

    # 2. Prendre max max_per_source de chaque source dans le meme ordre
    def sample(source_list, label):
        seen = set()
        result = []
        per_source = {}
        for c in source_list:
            src = c["metadata"].get("source", "")
            if src not in per_source:
                per_source[src] = []
            # Dedup par contenu
            h = hash(c["content"])
            if h not in seen:
                seen.add(h)
                per_source[src].append(c)
        for src_list in per_source.values():
            result.extend(src_list[:max_per_source])
        return result

    result = sample(target, "target") + sample(others, "others")
    return result[:max_total]


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
    # Les documents REAC contiennent beaucoup de texte boiteux (definitions
    # repetees), donc on cherche tres large (k=50) pour trouver assez de
    # chunks uniques apres deduplication et diversification par source.
    # Si un sujet est detecte (CDA, TSSR...), on lance une seconde requete.
    topic = _detect_topic(question, history=history)
    context_chunks = search_similar(question, k=50)
    if topic:
        extra = search_similar(topic, k=25)
        context_chunks = _merge_dedup(context_chunks, extra)
    max_per = 6 if topic else 4
    context_chunks = _diversify_chunks(context_chunks, topic=topic, max_per_source=max_per, max_total=15)

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
