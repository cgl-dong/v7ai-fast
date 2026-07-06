"""Cross-Encoder Reranker — BAAI/bge-reranker-base.

Precision-focused re-ranking after Dense+BM25 candidate retrieval.
Lazy-loaded singleton to avoid startup delay.
"""
import logging
import os
from typing import List, Optional

from app.core.settings import settings

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

logger = logging.getLogger(__name__)

_reranker_model = None


def get_reranker():
    """Lazy-load the Cross-Encoder reranker model."""
    global _reranker_model
    if _reranker_model is None:
        model_name = settings.rag_rerank_model
        logger.info(f"Loading reranker model: {model_name}")
        from sentence_transformers import CrossEncoder
        _reranker_model = CrossEncoder(model_name)
        logger.info(f"Reranker model loaded")
    return _reranker_model


def rerank(
    query: str,
    candidates: List[dict],
    top_n: Optional[int] = None,
) -> List[dict]:
    """Re-rank candidates using Cross-Encoder.

    Args:
        query: search query string
        candidates: list of {"content": str, ...} 
        top_n: number of results to keep (default from settings)

    Returns:
        candidates sorted by rerank score descending,
        each with "rerank_score" field added.
    """
    if not candidates:
        return []

    if top_n is None:
        top_n = settings.rag_rerank_top_n

    if not settings.rag_rerank_enabled:
        logger.info(f"[rerank] disabled, keeping top {top_n} by original order")
        return candidates[:top_n]

    try:
        model = get_reranker()
        # Build (query, document) pairs
        pairs = [(query, c["content"]) for c in candidates]
        scores = model.predict(pairs, show_progress_bar=False)

        # Attach scores and sort
        for i, c in enumerate(candidates):
            c["rerank_score"] = round(float(scores[i]), 4)

        candidates.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
        result = candidates[:top_n]

        if result:
            top_score = result[0].get("rerank_score", 0)
            logger.info(f"[rerank] {len(candidates)} candidates → top {top_n}, top_score={top_score:.4f}")
        return result
    except Exception as e:
        logger.warning(f"[rerank] failed: {e}, returning original order")
        logger.info("[rerank] hint: set rag_rerank_enabled=false in .env to disable, "
                     "or pre-download model: python -c \"from sentence_transformers import CrossEncoder; CrossEncoder('BAAI/bge-reranker-base')\"")
        return candidates[:top_n]
