"""bge-m3 embedding loader. Singleton; loads on first call.

Why bge-m3:
- Best Chinese+English bilingual model in the public domain (2024-2025).
- 1024-dim, matches our pgvector schema and HNSW index.
- Auto-detects GPU (CUDA) with CPU fallback when EMBEDDING_DEVICE=auto.

``EMBEDDING_VERSION`` increments whenever the embedding contract changes.
"""
from __future__ import annotations

import asyncio
from typing import Iterable

import numpy as np

from ..config import settings
from ..logging import log

EMBEDDING_VERSION = 2

_model = None
_load_lock = asyncio.Lock()
_tokenizer = None
_tok_lock = asyncio.Lock()


def _resolve_device() -> str:
    """Auto-detect or honour explicit device setting."""
    wanted = settings.embedding_device
    if wanted == "cpu":
        return "cpu"
    if wanted == "cuda":
        try:
            import torch  # noqa: WPS433
        except ImportError:
            log.warning("embed.no_torch", fallback="cpu")
            return "cpu"
        if torch.cuda.is_available():
            log.info("embed.cuda_detected", gpu=torch.cuda.get_device_name(0))
            return "cuda"
        log.warning("embed.cuda_unavailable", fallback="cpu")
        return "cpu"
    # "auto" or anything else: detect
    try:
        import torch  # noqa: WPS433
    except ImportError:
        return "cpu"
    if torch.cuda.is_available():
        log.info("embed.cuda_detected", gpu=torch.cuda.get_device_name(0))
        return "cuda"
    log.info("embed.cpu_fallback")
    return "cpu"


async def get_model():
    """Lazy import sentence-transformers + load model (cached forever)."""
    global _model
    if _model is not None:
        return _model
    async with _load_lock:
        if _model is not None:
            return _model
        device = _resolve_device()
        log.info("embed.loading", model=settings.embedding_model, device=device)
        from sentence_transformers import SentenceTransformer  # noqa: WPS433

        def _do_load():
            return SentenceTransformer(
                settings.embedding_model,
                device=device,
            )

        _model = await asyncio.to_thread(_do_load)
        log.info("embed.loaded", model=settings.embedding_model)
        return _model


async def get_tokenizer():
    """Lazy import transformers + load fast tokenizer (cached forever)."""
    global _tokenizer
    if _tokenizer is not None:
        return _tokenizer
    async with _tok_lock:
        if _tokenizer is not None:
            return _tokenizer
        log.info("tokenizer.loading", model=settings.embedding_model)
        from transformers import AutoTokenizer  # noqa: WPS433

        def _do_load():
            return AutoTokenizer.from_pretrained(settings.embedding_model)

        _tokenizer = await asyncio.to_thread(_do_load)
        log.info("tokenizer.loaded", model=settings.embedding_model)
        return _tokenizer


async def embed_texts(texts: Iterable[str]) -> np.ndarray:
    """Encode a list of texts → 2D numpy array (n, 1024), L2-normalised."""
    items = list(texts)
    if not items:
        return np.zeros((0, settings.embedding_dim), dtype=np.float32)

    # 1. Try InferPilot High-Performance C++ Inference Engine (Fast Tokenizer + TensorRT)
    inferpilot_url = getattr(settings, "inferpilot_server_url", None)
    if inferpilot_url:
        try:
            tokenizer = await get_tokenizer()
            # Fast Rust Tokenizer executes in <0.5ms on CPU
            encoded = tokenizer(items, padding=False, truncation=True, max_length=128)
            token_ids_batch = encoded["input_ids"]

            import httpx
            # Strict, realistic timeouts: connect 0.5s, read 2.0s
            timeout = httpx.Timeout(connect=0.5, read=2.0, write=1.0, pool=2.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{inferpilot_url.rstrip('/')}/v1/embeddings",
                    json={"model": settings.embedding_model, "input_ids": token_ids_batch},
                )
                if resp.status_code == 200:
                    data = resp.json()["data"]
                    embeddings = [item["embedding"] for item in data]
                    arr = np.asarray(embeddings, dtype=np.float32)

                    # Defensive validations: shape, finiteness, non-zero norm
                    if arr.shape != (len(items), settings.embedding_dim):
                        raise ValueError(
                            f"InferPilot returned shape {arr.shape}, expected ({len(items)}, {settings.embedding_dim})"
                        )
                    if not np.all(np.isfinite(arr)):
                        raise ValueError("InferPilot returned non-finite (NaN/Inf) values")
                    norms = np.linalg.norm(arr, axis=1)
                    if np.any(norms < 1e-4):
                        raise ValueError("InferPilot returned zero or near-zero vectors")

                    return arr
                else:
                    log.warning(
                        "embed.inferpilot_http_error",
                        status_code=resp.status_code,
                        body=resp.text[:200],
                    )
        except Exception as e:
            log.warning("embed.inferpilot_fallback", error=str(e))

    # 2. Local Fallback: PyTorch SentenceTransformer
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
