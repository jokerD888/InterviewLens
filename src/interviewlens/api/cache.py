"""Shared JSON read-path cache over Redis.

Used by taxonomy/summary/search routes. TTL-driven, miss-through on Redis
failure (Layer B — see openspec/changes/exception-handling-layering/).
"""
from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

from ..logging import log
from ..observability import get_redis


async def cache_json_get(key: str) -> Any | None:
    """Return deserialised value, or None on miss/Redis failure."""
    try:
        r = get_redis()
        raw = await r.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except (aioredis.RedisError, json.JSONDecodeError):
        log.warning("api.cache_get_failed", key=key, exc_info=True)
        return None


async def cache_json_set(key: str, value: Any, *, ttl_seconds: int) -> None:
    try:
        r = get_redis()
        await r.set(key, json.dumps(value, ensure_ascii=False), ex=ttl_seconds)
    except aioredis.RedisError:
        log.warning("api.cache_set_failed", key=key, exc_info=True)
