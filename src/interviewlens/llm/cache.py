"""Redis-backed cache for LLM call results, keyed by prompt-hash + version."""
from __future__ import annotations

import hashlib
import json
from typing import Any

import redis.asyncio as aioredis

from ..config import settings
from ..logging import log

_redis: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def make_cache_key(*, namespace: str, payload: Any, version: int | str) -> str:
    """Stable key from canonical JSON of ``payload``."""
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    return f"il:llm:{namespace}:v{version}:{digest}"


async def cache_get(key: str) -> dict | None:
    # Layer B: only Redis/JSON failures degrade to a miss; logic bugs bubble.
    try:
        r = _get_redis()
        s = await r.get(key)
        if s is None:
            return None
        return json.loads(s)
    except (aioredis.RedisError, json.JSONDecodeError):
        log.warning("cache.get_failed", exc_info=True)
        return None


async def cache_set(key: str, value: dict, *, ttl_seconds: int = 60 * 60 * 24 * 30) -> None:
    try:
        r = _get_redis()
        await r.set(key, json.dumps(value, ensure_ascii=False), ex=ttl_seconds)
    except aioredis.RedisError:
        log.warning("cache.set_failed", exc_info=True)


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
