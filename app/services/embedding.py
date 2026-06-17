"""Embedding service using BAAI/bge-base-zh-v1.5 for Chinese text.

Model:  BAAI/bge-base-zh-v1.5
Dim:    768
Note:   Uses instruction prefix for queries (asymmetric encoding per BAAI convention).
"""
import logging
import os
from typing import List

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

logger = logging.getLogger("v7ai-fast.embedding")

EMBEDDING_DIM = 768
EMBEDDING_MODEL_NAME = "BAAI/bge-base-zh-v1.5"
_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："

_embedding_model = None


def get_embedding_model():
    """Lazy-load the sentence-transformers embedding model."""
    global _embedding_model
    if _embedding_model is None:
        logger.info(f"Loading embedding model: {EMBEDDING_MODEL_NAME}")
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        logger.info(f"Embedding model loaded, dim={EMBEDDING_DIM}")
    return _embedding_model


def embed_documents(texts: List[str]) -> List[List[float]]:
    """Generate embeddings for documents (indexing). No instruction prefix.

    Returns list of float lists, each 768-dim.
    """
    logger.debug(f"Embedding {len(texts)} documents")
    model = get_embedding_model()
    embeddings = model.encode(texts, normalize_embeddings=True)
    logger.debug(f"Embedded {len(texts)} documents -> {len(embeddings)} vectors")
    return embeddings.tolist()


def embed_query(text: str) -> List[float]:
    """Generate embedding for a single query. Uses BAAI instruction prefix
    so that query and document embeddings sit in the same aligned space.

    Returns a 768-dim float list.
    """
    logger.debug(f"Embedding query: {text[:80]}...")
    model = get_embedding_model()
    embedding = model.encode(
        text,
        prompt=_QUERY_INSTRUCTION,
        normalize_embeddings=True,
    )
    return embedding.tolist()


# ── Backward-compat aliases ─────────────────────────────────────────

def embed_texts(texts: List[str]) -> List[List[float]]:
    """Alias — same as embed_documents. Used by indexer for batch indexing."""
    return embed_documents(texts)


def embed_single(text: str) -> List[float]:
    """Generate embedding for a single text (no instruction — document mode)."""
    return embed_documents([text])[0]
