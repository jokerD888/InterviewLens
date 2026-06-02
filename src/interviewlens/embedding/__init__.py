"""Public embedding API."""
from .bge_m3 import cosine, cosine_matrix, embed_texts, get_model

__all__ = ["cosine", "cosine_matrix", "embed_texts", "get_model"]
