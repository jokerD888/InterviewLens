"""Public embedding API."""
from .backfill import (
    BackfillStats,
    CanonicalBackfillStats,
    backfill_canonical_embeddings,
    backfill_embeddings,
)
from .bge_m3 import EMBEDDING_VERSION, cosine, cosine_matrix, embed_texts, get_model

__all__ = [
    "BackfillStats",
    "CanonicalBackfillStats",
    "EMBEDDING_VERSION",
    "backfill_canonical_embeddings",
    "backfill_embeddings",
    "cosine",
    "cosine_matrix",
    "embed_texts",
    "get_model",
]
