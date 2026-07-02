"""Self-check for the swallow() degradation helper (openchange: exception-handling-layering).

We assert behavior (exception swallowed / propagated) rather than structlog internals.
structlog renders via its own processor chain (ConsoleRenderer/JSONRenderer) to stdout,
so caplog.records does not capture it — that's expected, not a bug.
"""
from __future__ import annotations

import pytest

from interviewlens.errors import aswallow, swallow


def test_swallow_swallows_exception() -> None:
    """An exception inside swallow() must NOT propagate — that's its whole job."""
    with swallow("test.something_failed"):
        raise ValueError("boom")


def test_swallow_no_exception_is_noop() -> None:
    """Happy path: body runs, return value preserved, nothing thrown."""
    result = []
    with swallow("test.something_failed"):
        result.append(1 + 1)
    assert result == [2]


def test_swallow_accepts_extra_fields() -> None:
    """Keyword fields (entity=, id=, ...) pass through to the log call without error."""
    with swallow("test.with_fields", entity="company", alias="字节", count=3):
        raise RuntimeError("x")


@pytest.mark.asyncio
async def test_aswallow_swallows_exception() -> None:
    async with aswallow("test.async_failed"):
        raise ValueError("async boom")


@pytest.mark.asyncio
async def test_aswallow_no_exception_is_noop() -> None:
    out = []
    async with aswallow("test.async_ok"):
        out.append("ran")
    assert out == ["ran"]


def test_unrelated_exception_outside_swallow_still_propagates() -> None:
    """swallow only catches what's inside its block — outside raises normally."""
    with pytest.raises(KeyError):
        with swallow("test.inside"):
            pass  # no error here
        raise KeyError("outside")  # this must propagate
