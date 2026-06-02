"""bge-m3 embedding loader. Singleton; loads on first call.

Why bge-m3:
- Best Chinese+English bilingual model in the public domain (2024-2025).
- 1024-dim, matches our pgvector schema and HNSW index.
- CPU-runnable in fp32; for low-memory boxes set EMBEDDING_DEVICE=cpu and
  the model auto-falls back. GPU acceleration is automatic when CUDA visible.
"""
from __future__ import annotations

import asyncio
from typing import Iterable

import numpy as np

from ..config import settings
from ..logging import log

_model = None
_load_lock = asyncio.Lock()


async def get_model():
    """Lazy import sentence-transformers + load model (cached forever)."""
    global _model
    if _model is not None:
        return _model
    async with _load_lock:
        if _model is not None:
            return _model
        log.info("embed.loading", model=settings.embedding_model, device=settings.embedding_device)
        from sentence_transformers import SentenceTransformer  # noqa: WPS433

        # Run blocking load in thread to keep the event loop responsive.
        def _do_load():
            return SentenceTransformer(
                settings.embedding_model,
                device=settings.embedding_device,
            )

        _model = await asyncio.to_thread(_do_load)
        log.info("embed.loaded", model=settings.embedding_model)
        return _model


async def embed_texts(texts: Iterable[str]) -> np.ndarray:
    """Encode a list of texts → 2D numpy array (n, 1024), L2-normalised."""
    items = list(texts)
    if not items:
        return np.zeros((0, settings.embedding_dim), dtype=np.float32)

    model = await get_model()

    def _do_encode():
        return model.encode(
            items,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

    arr = await asyncio.to_thread(_do_encode)
    return np.asarray(arr, dtype=np.float32)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity assuming both already L2-normalised."""
    return float(np.dot(a, b))


def cosine_matrix(query: np.ndarray, gallery: np.ndarray) -> np.ndarray:
    """Pairwise cosine for L2-normalised inputs.

    query:   (n, d)
    gallery: (m, d)
    return:  (n, m)
    """
    if query.size == 0 or gallery.size == 0:
        return np.zeros((query.shape[0], gallery.shape[0]), dtype=np.float32)
    return query @ gallery.T
