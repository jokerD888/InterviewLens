"""Degradation helpers: swallow exceptions WITH a traceback.

Only for Layer A (observability) / Layer D (ops probes) — places where a failure
must not break the main flow but still needs to be diagnosable.

Layer B (infra clients) and Layer C (data paths) catch concrete exception
families instead — see openspec/changes/exception-handling-layering/.
"""
from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from typing import Any

from .logging import log


@contextmanager
def swallow(event: str, **fields: Any):
    """Swallow any exception, log it WITH traceback.

    Usage::

        with swallow("metric.incr_cache_failed"):
            await r.incr(key)

    Keeps an ``error=<str(exc)>`` field for back-compat with grep scripts, and
    adds ``exc_info=True`` so structlog's StackInfoRenderer emits the full trace.
    """
    try:
        yield
    except Exception as exc:  # noqa: BLE001  # ponytail: intentional broad catch — degradation layer
        log.warning(event, **fields, error=str(exc), exc_info=True)


@asynccontextmanager
async def aswallow(event: str, **fields: Any):
    """Async variant of :func:`swallow`."""
    try:
        yield
    except Exception as exc:  # noqa: BLE001  # ponytail: intentional broad catch — degradation layer
        log.warning(event, **fields, error=str(exc), exc_info=True)
