"""Close clients in their owning loop and drop inherited references after fork."""

from __future__ import annotations

import asyncio

from .logging import log


async def close_clients():
    from . import observability
    from .db.session import dispose_engine
    from .embedding import bge_m3
    from .llm import cache, deepseek

    # One close failure must not prevent the remaining clients being closed.
    results = await asyncio.gather(
        observability.close_redis(),
        cache.close_redis(),
        deepseek.aclose(),
        bge_m3.close_client(),
        dispose_engine(),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, BaseException):
            log.warning("client.close_failed", error=type(result).__name__)


def reset_after_fork():
    from . import observability
    from .embedding import bge_m3
    from .llm import cache, deepseek

    observability._redis_client = None
    observability._cache_client = None
    observability._langfuse_client = None
    observability._langfuse_init_failed = False
    cache._redis = None
    deepseek._client = None
    bge_m3.reset_clients()
