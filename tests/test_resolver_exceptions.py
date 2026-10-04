"""Layer C contract: logic bugs must NOT be swallowed by the normalizer.

Verifies the exception-handling-layering spec REQ-2: in data paths, TypeError /
AttributeError / KeyError surface (bubble to the DLQ) instead of being silently
degraded. Only external/LLM failures (openai.APIError, RuntimeError, timeout)
are caught and downgraded to tier4.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import openai
import pytest

import interviewlens.normalizer.resolver as res


@pytest.mark.asyncio
async def test_logic_bug_bubbles_out_of_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    """A TypeError from call_tool must propagate, NOT be swallowed to tier4."""
    # Force the path to reach tier3 (LLM call): no alias hit, no canonicals.
    async def _no_alias(entity_type, alias):
        return None

    async def _no_canonicals(entity_type, alias):
        return []

    def _boom(**kwargs):
        raise TypeError("simulated logic bug — e.g. wrong kwarg shape")

    monkeypatch.setattr(res, "_lookup_alias", _no_alias)
    monkeypatch.setattr(res, "_search_canonicals", _no_canonicals)
    monkeypatch.setattr(res, "call_tool", _boom)

    with pytest.raises(TypeError, match="simulated logic bug"):
        await res.resolve_entity("company", "字节跳动")


@pytest.mark.asyncio
async def test_llm_failure_degrades_to_new_canonical(monkeypatch: pytest.MonkeyPatch) -> None:
    """An openai.APIError (external) IS swallowed → falls through to tier4 (new)."""
    async def _no_alias(entity_type, alias):
        return None

    async def _no_canonicals(entity_type, alias):
        return []

    def _api_error(**kwargs):
        raise openai.APIConnectionError(request=None)

    created: list[str] = []

    async def _persist_new(entity_type, alias, name):
        created.append(name)
        return res.ResolveResult(canonical_id=42, confidence=0.5, source="new")

    monkeypatch.setattr(res, "_lookup_alias", _no_alias)
    monkeypatch.setattr(res, "_search_canonicals", _no_canonicals)
    monkeypatch.setattr(res, "call_tool", _api_error)
    monkeypatch.setattr(res, "_persist_new_canonical", _persist_new)

    result = await res.resolve_entity("company", "字节跳动")
    assert result.source == "new"
    assert result.canonical_id == 42
    assert created  # a new canonical was created (degraded path taken)


@pytest.mark.asyncio
async def test_llm_id_for_wrong_entity_type_falls_back_to_new(monkeypatch: pytest.MonkeyPatch) -> None:
    """A guessed id must be validated against the requested entity table."""
    async def _no_alias(entity_type, alias):
        return None

    async def _no_canonicals(entity_type, alias):
        return []

    async def _wrong_id(entity_type, canonical_id):
        return False

    async def _persist_new(entity_type, alias, name):
        return res.ResolveResult(canonical_id=7, confidence=0.5, source="new")

    async def _tool(**kwargs):
        return SimpleNamespace(
            arguments={"decision": "match", "canonical_id": 99, "confidence": 0.95}
        )

    monkeypatch.setattr(res, "_lookup_alias", _no_alias)
    monkeypatch.setattr(res, "_search_canonicals", _no_canonicals)
    monkeypatch.setattr(res, "_canonical_exists", _wrong_id)
    monkeypatch.setattr(res, "call_tool", _tool)
    monkeypatch.setattr(res, "_persist_new_canonical", _persist_new)

    result = await res.resolve_entity("company", "未知公司")

    assert result == res.ResolveResult(canonical_id=7, confidence=0.5, source="new")


@pytest.mark.asyncio
async def test_alias_conflict_returns_database_winner(monkeypatch: pytest.MonkeyPatch) -> None:
    """A losing resolver must use the canonical already stored for the alias."""
    async def _no_alias(entity_type, alias):
        return None

    async def _top_canonical(entity_type, alias):
        return [{"id": 1, "canonical": "字节跳动", "similarity": 0.95}]

    async def _write_alias(entity_type, alias, canonical_id, confidence):
        return 2, 0.91, False

    monkeypatch.setattr(res, "_lookup_alias", _no_alias)
    monkeypatch.setattr(res, "_search_canonicals", _top_canonical)
    monkeypatch.setattr(res, "_write_alias", _write_alias)

    result = await res.resolve_entity("company", "字节")

    assert result == res.ResolveResult(canonical_id=2, confidence=0.91, source="alias")
