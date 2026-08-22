"""Public embedding API."""
from .backfill import (
    BackfillStats,
    CanonicalBackfillStats,
    backfill_canonical_embeddings,
    backfill_embeddings,
)
from .bge_m3 import cosine, cosine_matrix, embed_texts, get_model

__all__ = [
    "BackfillStats",
    "CanonicalBackfillStats",
    "backfill_canonical_embeddings",
    "backfill_embeddings",
    "cosine",
    "cosine_matrix",
    "embed_texts",
    "get_model",
]
