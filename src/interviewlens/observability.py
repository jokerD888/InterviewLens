"""Observability layer: Langfuse client accessor + Redis-backed counters.

The module is import-safe even when Langfuse / Redis are misconfigured —
all helpers degrade to no-ops with a single warning rather than blowing up
the pipeline.
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import redis.asyncio as aioredis

from .config import settings
from .errors import aswallow, swallow
from .logging import log

try:
    from langfuse import Langfuse  # type: ignore
except Exception:  # noqa: BLE001  # ponytail: import-guard, broad by design
    Langfuse = None  # type: ignore


# ----------------------------------------------------------------- Langfuse

_langfuse_client: "Langfuse | None" = None
_langfuse_init_failed: bool = False


def get_langfuse() -> "Langfuse | None":
    """Lazy singleton. Returns None when SDK missing or keys are placeholder."""
    global _langfuse_client, _langfuse_init_failed
    if _langfuse_client is not None:
        return _langfuse_client
    if _langfuse_init_failed:
        return None
    if Langfuse is None:
        _langfuse_init_failed = True
        return None
    pk = settings.langfuse_public_key
    sk = settings.langfuse_secret_key
    if not pk or not sk or "REPLACE_ME" in pk or "REPLACE_ME" in sk:
        _langfuse_init_failed = True
        return None
    try:
        _langfuse_client = Langfuse(
            public_key=pk,
            secret_key=sk,
            host=settings.langfuse_host,
        )
        return _langfuse_client
    except Exception:  # noqa: BLE001  # ponytail: broad catch ok — observability must not break the pipeline
        log.warning("langfuse.init_failed", exc_info=True)
        _langfuse_init_failed = True
        return None


def langfuse_flush() -> None:
    client = get_langfuse()
    if client is not None:
        with swallow("langfuse.flush_failed"):  # Layer A
            client.flush()


# ------------------------------------------------------------------- Redis

_redis_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


# Redis key prefixes (kept short on purpose)
_KEY_CACHE_HIT = "il:metric:cache:hit"
_KEY_CACHE_MISS = "il:metric:cache:miss"
_KEY_TOKENS_PROMPT = "il:metric:tokens:prompt"
_KEY_TOKENS_COMPLETION = "il:metric:tokens:completion"
_KEY_NODE_DURATION = "il:metric:node:duration_ms"  # hash node→ms total
_KEY_NODE_RUNS = "il:metric:node:runs"  # hash node→count


async def incr_cache(hit: bool) -> None:
    async with aswallow("metric.incr_cache_failed"):  # Layer A
        r = get_redis()
        await r.incr(_KEY_CACHE_HIT if hit else _KEY_CACHE_MISS)


async def incr_tokens(*, prompt: int, completion: int) -> None:
    async with aswallow("metric.incr_tokens_failed"):  # Layer A
        r = get_redis()
        if prompt:
            await r.incrby(_KEY_TOKENS_PROMPT, prompt)
        if completion:
            await r.incrby(_KEY_TOKENS_COMPLETION, completion)


async def record_node(name: str, duration_ms: float) -> None:
    async with aswallow("metric.record_node_failed"):  # Layer A
        r = get_redis()
        pipe = r.pipeline()
        pipe.hincrbyfloat(_KEY_NODE_DURATION, name, duration_ms)
        pipe.hincrby(_KEY_NODE_RUNS, name, 1)
        await pipe.execute()


@dataclass
class MetricsSnapshot:
    cache_hit: int
    cache_miss: int
    tokens_prompt: int
    tokens_completion: int
    node_runs: dict[str, int]
    node_avg_ms: dict[str, float]

    @property
    def cache_total(self) -> int:
        return self.cache_hit + self.cache_miss

    @property
    def cache_hit_rate(self) -> float:
        return (self.cache_hit / self.cache_total) if self.cache_total else 0.0

    @property
    def tokens_total(self) -> int:
        return self.tokens_prompt + self.tokens_completion

    def estimated_cost_cny(
        self,
        *,
        price_in_per_million: float = 1.0,
        price_out_per_million: float = 2.0,
    ) -> float:
        """Rough DeepSeek-V3 default pricing (2025-06): 1元/2元 per million tokens."""
        return (
            self.tokens_prompt / 1_000_000 * price_in_per_million
            + self.tokens_completion / 1_000_000 * price_out_per_million
        )


async def fetch_metrics() -> MetricsSnapshot:
    r = get_redis()
    try:
        pipe = r.pipeline()
        pipe.get(_KEY_CACHE_HIT)
        pipe.get(_KEY_CACHE_MISS)
        pipe.get(_KEY_TOKENS_PROMPT)
        pipe.get(_KEY_TOKENS_COMPLETION)
        pipe.hgetall(_KEY_NODE_RUNS)
        pipe.hgetall(_KEY_NODE_DURATION)
        hit, miss, tp, tc, runs, durations = await pipe.execute()
    except Exception:  # noqa: BLE001  # ponytail: broad catch ok — observability must not break the pipeline
        log.warning("metric.fetch_failed", exc_info=True)
        return MetricsSnapshot(0, 0, 0, 0, {}, {})

    runs_int: dict[str, int] = {k: int(v) for k, v in (runs or {}).items()}
    durations_f: dict[str, float] = {k: float(v) for k, v in (durations or {}).items()}
    avg_ms = {k: durations_f.get(k, 0.0) / max(1, runs_int.get(k, 1)) for k in runs_int}

    return MetricsSnapshot(
        cache_hit=int(hit or 0),
        cache_miss=int(miss or 0),
        tokens_prompt=int(tp or 0),
        tokens_completion=int(tc or 0),
        node_runs=runs_int,
        node_avg_ms=avg_ms,
    )


async def reset_metrics() -> None:
    r = get_redis()
    async with aswallow("metric.reset_failed"):  # Layer A
        await r.delete(
            _KEY_CACHE_HIT,
            _KEY_CACHE_MISS,
            _KEY_TOKENS_PROMPT,
            _KEY_TOKENS_COMPLETION,
            _KEY_NODE_DURATION,
            _KEY_NODE_RUNS,
        )


# ------------------------------------------------------------- Span helper

@asynccontextmanager
async def node_span(
    *,
    node_name: str,
    trace: Any | None,
    input_payload: Any | None = None,
):
    """Wrap an agent node body so we record duration and Langfuse span."""
    start = time.perf_counter()
    span = None
    if trace is not None:
        with swallow("langfuse.span_create_failed", node=node_name):  # Layer A
            span = trace.span(name=node_name, input=input_payload)
    try:
        yield span
    except Exception as exc:
        if span is not None:
            with swallow("langfuse.span_end_failed", node=node_name):  # Layer A
                span.end(level="ERROR", status_message=str(exc))
        elapsed_ms = (time.perf_counter() - start) * 1000
        await record_node(node_name, elapsed_ms)
        raise
    else:
        if span is not None:
            with swallow("langfuse.span_end_failed", node=node_name):  # Layer A
                span.end()
        elapsed_ms = (time.perf_counter() - start) * 1000
        await record_node(node_name, elapsed_ms)
