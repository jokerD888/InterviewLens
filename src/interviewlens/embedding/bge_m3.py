"""bge-m3 embedding loader. Singleton; loads on first call.

Why bge-m3:
- Best Chinese+English bilingual model in the public domain (2024-2025).
- 1024-dim, matches our pgvector schema and HNSW index.
- Auto-detects GPU (CUDA) with CPU fallback when EMBEDDING_DEVICE=auto.

``EMBEDDING_VERSION`` increments whenever the embedding contract changes.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Iterable

import httpx
import numpy as np

from ..config import settings
from ..logging import log

EMBEDDING_VERSION = 2

_model = None
_load_lock = asyncio.Lock()
_tokenizer = None
_tok_lock = asyncio.Lock()
_inferpilot_client: httpx.AsyncClient | None = None
_client_lock = asyncio.Lock()
_encode_lock = threading.Lock()


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
                trust_remote_code=False,
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
            return AutoTokenizer.from_pretrained(settings.embedding_model, trust_remote_code=False)

        _tokenizer = await asyncio.to_thread(_do_load)
        log.info("tokenizer.loaded", model=settings.embedding_model)
        return _tokenizer


async def get_inferpilot_client() -> httpx.AsyncClient:
    """Cached persistent HTTP client with keep-alive connection pooling."""
    global _inferpilot_client
    if _inferpilot_client is not None and not _inferpilot_client.is_closed:
        return _inferpilot_client
    async with _client_lock:
        if _inferpilot_client is not None and not _inferpilot_client.is_closed:
            return _inferpilot_client
        timeout = httpx.Timeout(connect=1.0, read=5.0, write=2.0, pool=5.0)
        limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
        _inferpilot_client = httpx.AsyncClient(timeout=timeout, limits=limits)
        return _inferpilot_client


async def _embed_batch_pytorch(items: list[str]) -> np.ndarray:
    """Fallback embedding using PyTorch SentenceTransformer (handles arbitrarily long sequences)."""
    if not items:
        return np.zeros((0, settings.embedding_dim), dtype=np.float32)
    model = await get_model()

    def _do_encode():
        # The lock lives in the actual thread, so cancellation of the awaiter
        # cannot let a second encode run while the first thread is still busy.
        with _encode_lock:
            return model.encode(
                items,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )

    arr = await asyncio.to_thread(_do_encode)
    return np.asarray(arr, dtype=np.float32)


async def _embed_chunk_inferpilot(
    client, inferpilot_url: str, token_ids_batch: list[list[int]]
) -> np.ndarray:
    """Send a single sub-batch (<=32 items, <=128 seq_len) to InferPilot C++ Server."""
    resp = await client.post(
        f"{inferpilot_url.rstrip('/')}/v1/embeddings",
        json={"model": settings.embedding_model, "input_ids": token_ids_batch},
    )
    if resp.status_code != 200:
        raise RuntimeError(f"InferPilot HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()["data"]
    embeddings = [item["embedding"] for item in data]
    arr = np.asarray(embeddings, dtype=np.float32)

    # Defensive validations: shape, finiteness, non-zero norm
    if arr.shape != (len(token_ids_batch), settings.embedding_dim):
        raise ValueError(
            f"InferPilot returned shape {arr.shape}, expected ({len(token_ids_batch)}, {settings.embedding_dim})"
        )
    if not np.all(np.isfinite(arr)):
        raise ValueError("InferPilot returned non-finite (NaN/Inf) values")
    norms = np.linalg.norm(arr, axis=1)
    if np.any(norms < 1e-4):
        raise ValueError("InferPilot returned zero or near-zero vectors")

    return arr


async def embed_texts(texts: Iterable[str]) -> np.ndarray:
    """Encode a list of texts → 2D numpy array (n, 1024), L2-normalised.

    Robust Architecture:
    1. Sub-batches items to <= 32 to respect C++ server engine batch profile.
    2. Identifies sequences > 128 tokens and routes them to full-sequence PyTorch (zero silent truncation).
    3. Executes short sequences (<= 128 tokens) on InferPilot C++ TensorRT engine.
    4. Automatically falls back to local PyTorch on any C++ connection or server failure.
    """
    MAX_INFERPILOT_BATCH = 32
    MAX_INFERPILOT_SEQ_LEN = 128

    items = list(texts)
    if not items:
        return np.zeros((0, settings.embedding_dim), dtype=np.float32)

    inferpilot_url = getattr(settings, "inferpilot_server_url", None)
    if not inferpilot_url:
        return await _embed_batch_pytorch(items)

    try:
        tokenizer = await get_tokenizer()
        # Fast Rust Tokenizer without silent truncation to measure true sequence lengths
        encoded = tokenizer(items, padding=False, truncation=False)
        input_ids_list = encoded["input_ids"]

        short_indices: list[int] = []
        long_indices: list[int] = []
        for idx, token_ids in enumerate(input_ids_list):
            if len(token_ids) <= MAX_INFERPILOT_SEQ_LEN:
                short_indices.append(idx)
            else:
                long_indices.append(idx)

        embeddings_result: list[np.ndarray | None] = [None] * len(items)

        # 1. Handle long sequences explicitly via full-context PyTorch (zero silent truncation)
        if long_indices:
            long_texts = [items[i] for i in long_indices]
            max_long_len = max(len(input_ids_list[i]) for i in long_indices)
            log.warning(
                "embed.long_text_fallback_to_pytorch",
                count=len(long_indices),
                max_tokens=max_long_len,
                threshold=MAX_INFERPILOT_SEQ_LEN,
            )
            long_vecs = await _embed_batch_pytorch(long_texts)
            for idx, vec in zip(long_indices, long_vecs, strict=True):
                embeddings_result[idx] = vec

        # 2. Handle short sequences via InferPilot C++ Server (chunked into batches of <= 32)
        if short_indices:
            client = await get_inferpilot_client()
            chunks_meta = []
            for chunk_start in range(0, len(short_indices), MAX_INFERPILOT_BATCH):
                chunk_indices = short_indices[chunk_start : chunk_start + MAX_INFERPILOT_BATCH]
                chunk_token_ids = [input_ids_list[i] for i in chunk_indices]
                chunks_meta.append((chunk_indices, chunk_token_ids))

            if len(chunks_meta) == 1:
                chunk_indices, chunk_token_ids = chunks_meta[0]
                chunk_vecs = await _embed_chunk_inferpilot(client, inferpilot_url, chunk_token_ids)
                for idx, vec in zip(chunk_indices, chunk_vecs, strict=True):
                    embeddings_result[idx] = vec
            else:
                tasks = [
                    _embed_chunk_inferpilot(client, inferpilot_url, chunk_tokens)
                    for _, chunk_tokens in chunks_meta
                ]
                results = await asyncio.gather(*tasks)
                for (chunk_indices, _), chunk_vecs in zip(chunks_meta, results, strict=True):
                    for idx, vec in zip(chunk_indices, chunk_vecs, strict=True):
                        embeddings_result[idx] = vec

        return np.asarray(embeddings_result, dtype=np.float32)

    except Exception as e:
        log.warning("embed.inferpilot_fallback", error=str(e))
        return await _embed_batch_pytorch(items)


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


async def close_client():
    global _inferpilot_client, _client_lock, _load_lock, _tok_lock
    client, _inferpilot_client = _inferpilot_client, None
    if client is not None:
        await client.aclose()
    _client_lock, _load_lock, _tok_lock = asyncio.Lock(), asyncio.Lock(), asyncio.Lock()


def reset_clients():
    global _inferpilot_client, _client_lock, _load_lock, _tok_lock, _model, _tokenizer
    _inferpilot_client = None
    _client_lock, _load_lock, _tok_lock = asyncio.Lock(), asyncio.Lock(), asyncio.Lock()
    _model, _tokenizer = None, None
