"""Shared JSON read-path cache over Redis.

Used by taxonomy/summary/search routes. TTL-driven, miss-through on Redis
failure (Layer B — see openspec/changes/exception-handling-layering/).
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Any

import redis.asyncio as aioredis

from ..logging import log
from ..observability import get_cache_redis as get_redis
from ..observability import get_redis as get_state_redis
from ..config import settings

_revision_key = "il:data:revision"
_keys = ContextVar("read_cache_keys", default=None)


async def versioned_key(key, r):
    # Durable revision must not be evicted alongside disposable cache entries.
    state = get_state_redis() if settings.cache_redis_url else r
    revision = int(await state.get(_revision_key) or 0)
    resolved = key if revision == 0 else f"{key}:r{revision}"
    _keys.set({**(_keys.get() or {}), key: resolved})
    return resolved


async def cache_json_get(key: str, *, redis_client=None) -> Any | None:
    """Return deserialised value, or None on miss/Redis failure."""
    try:
        r = redis_client if redis_client is not None else get_redis()
        raw = await r.get(await versioned_key(key, r))
        if raw is None:
            return None
        return json.loads(raw)
    except (aioredis.RedisError, json.JSONDecodeError):
        _keys.set({**(_keys.get() or {}), key: None})
        log.warning("api.cache_get_failed", key=key, exc_info=True)
        return None


async def cache_json_set(key: str, value: Any, *, ttl_seconds: int, redis_client=None) -> None:
    try:
        r = redis_client if redis_client is not None else get_redis()
        captured = _keys.get() or {}
        resolved = captured[key] if key in captured else await versioned_key(key, r)
        if resolved is not None:
            # Write under the revision captured BEFORE SQL. A concurrent commit
            # cannot let an old response repopulate the new revision.
            await r.set(resolved, json.dumps(value, ensure_ascii=False), ex=ttl_seconds)
    except aioredis.RedisError:
        log.warning("api.cache_set_failed", key=key, exc_info=True)


async def invalidate_read_caches():
    """Advance the read revision; old keys expire by TTL without scanning."""
    try:
        r = get_state_redis() if settings.cache_redis_url else get_redis()
        await r.incr(_revision_key)
    except aioredis.RedisError:
        log.warning("api.cache_invalidation_failed", exc_info=True)
