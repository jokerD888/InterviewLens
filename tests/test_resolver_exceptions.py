"""Layer C contract: logic bugs must NOT be swallowed by the normalizer.

Verifies the exception-handling-layering spec REQ-2: in data paths, TypeError /
AttributeError / KeyError surface (bubble to the DLQ) instead of being silently
degraded. Only external/LLM failures (openai.APIError, RuntimeError, timeout)
are caught and downgraded to tier4.
"""
from __future__ import annotations

import asyncio

import openai
import pytest

import interviewlens.normalizer.resolver as res


@pytest.mark.asyncio
async def test_logic_bug_bubbles_out_of_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    """A TypeError from call_tool must propagate, NOT be swallowed to tier4."""
    # Force the path to reach tier3 (LLM call): no alias hit, no canonicals.
    async def _no_alias(entity_type, alias):
        return None

    async def _no_canonicals(entity_type):
        return []

    def _boom(**kwargs):
        raise TypeError("simulated logic bug — e.g. wrong kwarg shape")

    monkeypatch.setattr(res, "_lookup_alias_dict", _no_alias)
    monkeypatch.setattr(res, "_list_canonicals", _no_canonicals)
    monkeypatch.setattr(res, "call_tool", _boom)

    with pytest.raises(TypeError, match="simulated logic bug"):
        await res.resolve_entity("company", "字节跳动")


@pytest.mark.asyncio
async def test_llm_failure_degrades_to_new_canonical(monkeypatch: pytest.MonkeyPatch) -> None:
    """An openai.APIError (external) IS swallowed → falls through to tier4 (new)."""
    async def _no_alias(entity_type, alias):
        return None

    async def _no_canonicals(entity_type):
        return []

    def _api_error(**kwargs):
        raise openai.APIConnectionError(request=None)

    created: list[str] = []

    async def _create(entity_type, name):
        created.append(name)
        return 42

    async def _write_alias(entity_type, alias, canonical_id, confidence):
        return None

    monkeypatch.setattr(res, "_lookup_alias_dict", _no_alias)
    monkeypatch.setattr(res, "_list_canonicals", _no_canonicals)
    monkeypatch.setattr(res, "call_tool", _api_error)
    monkeypatch.setattr(res, "_create_canonical", _create)
    monkeypatch.setattr(res, "_write_alias", _write_alias)

    result = await res.resolve_entity("company", "字节跳动")
    assert result.source == "new"
    assert result.canonical_id == 42
    assert created  # a new canonical was created (degraded path taken)
