"""Shared JSON read-path cache over Redis.

Used by taxonomy/summary/search routes. TTL-driven, miss-through on Redis
failure (Layer B — see openspec/changes/exception-handling-layering/).
"""

from __future__ import annotations

import json
import asyncio
from contextvars import ContextVar
from typing import Any

import redis.asyncio as aioredis

from ..logging import log
from ..observability import get_cache_redis as get_redis
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from ..db.session import get_engine

_keys = ContextVar("read_cache_keys", default=None)


async def read_revision() -> str:
    async def read():
        async with get_engine().connect() as conn:
            row = (await conn.execute(text("SELECT current_database(), epoch, revision FROM il_read_revision WHERE id=1"))).one()
            return f"{row[0]}:{row[1]}:{row[2]}"
    return await asyncio.wait_for(read(), timeout=2)


async def versioned_key(key, r):
    # Database triggers advance this generation in the business transaction.
    # Redis outages cannot lose invalidations. Never cache without a generation.
    revision = await read_revision()
    resolved = f"{key}:db:{revision}" if revision else key
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
    except (aioredis.RedisError, json.JSONDecodeError, SQLAlchemyError, TimeoutError):
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
    except (aioredis.RedisError, SQLAlchemyError, TimeoutError):
        log.warning("api.cache_set_failed", key=key, exc_info=True)


async def invalidate_read_caches():
    """Compatibility hook: migration 014 triggers invalidate at business commit.

    There is deliberately no second, fallible Redis write after committing SQL.
    """
