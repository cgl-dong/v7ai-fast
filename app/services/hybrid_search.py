"""Hybrid Search: BM25 (keyword) + Dense (vector) → RRF fusion.

Uses jieba for Chinese word segmentation and rank_bm25 for scoring.
"""
import logging
import re
from typing import List, Optional

import jieba

logger = logging.getLogger(__name__)

# ── Tokenizer ──────────────────────────────────────────────────────

# Chinese chars pattern for char-level fallback
_CN_CHAR = re.compile(r'[\u4e00-\u9fff]')


def tokenize(text: str) -> List[str]:
    """Tokenize Chinese text with jieba, keeping alphanumeric intact.

    Returns list of lowercase tokens (words / characters).
    """
    if not text:
        return []
    # Use jieba search mode for better recall
    words = list(jieba.cut_for_search(text))
    # Filter: keep meaningful tokens, drop pure punctuation
    result = []
    for w in words:
        w = w.strip().lower()
        if not w:
            continue
        # Keep if: CJK, alphanumeric, or mixed (e.g. "v7ai")
        has_cjk = bool(_CN_CHAR.search(w))
        has_alnum = bool(re.search(r'[a-z0-9]', w))
        if has_cjk or has_alnum:
            result.append(w)
    return result


def tokens_to_str(tokens: List[str]) -> str:
    """Join tokens with space for DB storage."""
    return " ".join(tokens)


def str_to_tokens(s: str) -> List[str]:
    """Parse space-separated token string back to list."""
    if not s:
        return []
    return s.split(" ")


# ── BM25 Index ─────────────────────────────────────────────────────

class BM25Index:
    """In-memory BM25 index with jieba tokenization."""

    def __init__(self):
        self._corpus: List[List[str]] = []       # tokenized docs
        self._ids: List[int] = []                # chunk IDs
        self._bm25 = None
        self._dirty = True

    def add(self, chunk_id: int, tokens: List[str]):
        """Add a document to the index."""
        self._corpus.append(tokens)
        self._ids.append(chunk_id)
        self._dirty = True

    def _ensure_built(self):
        if self._dirty and self._corpus:
            from rank_bm25 import BM25Okapi
            self._bm25 = BM25Okapi(self._corpus)
            self._dirty = False

    def search(self, query: str, top_k: int = 20) -> List[tuple]:
        """Search BM25, returns [(chunk_id, score), ...]."""
        self._ensure_built()
        if not self._bm25:
            return []
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        scores = self._bm25.get_scores(query_tokens)
        # Build (id, score) pairs and sort descending
        results = [(self._ids[i], float(scores[i])) for i in range(len(scores))]
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def clear(self):
        self._corpus = []
        self._ids = []
        self._bm25 = None
        self._dirty = True

    def __len__(self):
        return len(self._corpus)


# Global singleton — rebuilt on each search from DB
_bm25_index: Optional[BM25Index] = None


def get_bm25_index() -> BM25Index:
    global _bm25_index
    if _bm25_index is None:
        _bm25_index = BM25Index()
    return _bm25_index


def build_bm25_from_db(chunks: List[dict]):
    """Rebuild BM25 index from DB chunk rows.

    Each chunk dict: {"id": int, "tokens": str}
    """
    bm25 = get_bm25_index()
    bm25.clear()
    for c in chunks:
        token_list = str_to_tokens(c.get("tokens", ""))
        if token_list:
            bm25.add(c["id"], token_list)
    logger.info(f"[bm25] index built: {len(bm25)} documents")


# ── RRF Fusion ─────────────────────────────────────────────────────

def rrf_fusion(
    dense_results: List[dict],
    bm25_results: List[dict],
    k: int = 60,
    top_k: int = 20,
) -> List[dict]:
    """Reciprocal Rank Fusion — merge dense + BM25 results.

    RRF(d) = Σ 1/(k + rank_i(d))

    Args:
        dense_results: [{"id": ..., "content": ..., "similarity": ..., ...}, ...]
        bm25_results: [{"id": ..., "content": ..., "score": ..., ...}, ...]
        k: RRF constant (default 60)
        top_k: number of merged results to return
    """
    scores = {}
    docs = {}

    # Dense rank
    for rank, doc in enumerate(dense_results):
        doc_id = doc["id"]
        scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank + 1)
        docs[doc_id] = doc

    # BM25 rank
    for rank, doc in enumerate(bm25_results):
        doc_id = doc["id"]
        scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank + 1)
        if doc_id not in docs:
            docs[doc_id] = doc

    # Sort by RRF score descending
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    result = []
    for doc_id, rrf_score in ranked[:top_k]:
        doc = docs[doc_id].copy()
        doc["rrf_score"] = round(rrf_score, 6)
        result.append(doc)

    logger.info(f"[rrf] dense={len(dense_results)}, bm25={len(bm25_results)}, merged={len(result)}")
    return result
