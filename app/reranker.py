import logging
from sentence_transformers import CrossEncoder
import app.config as cfg

logger = logging.getLogger(__name__)

_RERANKER = None


def get_reranker():
    global _RERANKER
    if _RERANKER is None:
        logger.info("Chargement du reranker: %s", cfg.RERANKER_MODEL)
        _RERANKER = CrossEncoder(cfg.RERANKER_MODEL, max_length=512)
    return _RERANKER


def rerank(query: str, chunks: list[dict], top_k: int | None = None) -> list[dict]:
    if not chunks:
        return chunks

    model = get_reranker()
    # Filtrer les chunks sans contenu (None)
    chunks = [c for c in chunks if c.get("content")]
    if not chunks:
        return chunks

    pairs = [[query, c["content"]] for c in chunks]
    scores = model.predict(pairs, show_progress_bar=False)

    for c, s in zip(chunks, scores):
        c["rerank_score"] = float(s)

    chunks.sort(key=lambda c: c["rerank_score"], reverse=True)

    if top_k is not None:
        chunks = chunks[:top_k]

    return chunks
