"""Embedding service using HuggingFace sentence-transformers."""
import os
from typing import List

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

_embedding_model = None


def get_embedding_model():
    """Lazy-load the sentence-transformers embedding model."""
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedding_model


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Generate embeddings for a list of texts.
    Returns list of float lists, each 384-dim.
    """
    model = get_embedding_model()
    embeddings = model.encode(texts, normalize_embeddings=True)
    return embeddings.tolist()


def embed_single(text: str) -> List[float]:
    """Generate embedding for a single text."""
    return embed_texts([text])[0]
