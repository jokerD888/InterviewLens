"""Answerer unit tests — cache + per-question generation, no real LLM/DB."""
from __future__ import annotations

import pytest

import interviewlens.answerer.answerer as ans


@pytest.mark.asyncio
async def test_generate_one_uses_cache(monkeypatch) -> None:
    # cache_get returns a hit → no LLM call
    async def fake_get(key):
        return {"answer": "缓存答案"}

    called = {"llm": False}

    def fake_client():
        called["llm"] = True
        raise AssertionError("LLM should not be called on cache hit")

    monkeypatch.setattr(ans, "cache_get", fake_get)
    monkeypatch.setattr(ans, "get_client", fake_client)

    out = await ans.generate_one(content="什么是 GIL？", category="Python")
    assert out == "缓存答案"
    assert called["llm"] is False


@pytest.mark.asyncio
async def test_generate_one_calls_llm_on_miss(monkeypatch) -> None:
    async def fake_get(key):
        return None

    sets = {}

    async def fake_set(key, value, **kw):
        sets[key] = value

    class _Msg:
        content = "生成的答案"

    class _Choice:
        message = _Msg()

    class _Usage:
        def model_dump(self):
            return {"prompt_tokens": 10, "completion_tokens": 20}

    class _Resp:
        choices = [_Choice()]
        usage = _Usage()

    class _Completions:
        async def create(self, **kw):
            return _Resp()

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    async def fake_incr(**kw):
        return None

    monkeypatch.setattr(ans, "cache_get", fake_get)
    monkeypatch.setattr(ans, "cache_set", fake_set)
    monkeypatch.setattr(ans, "get_client", lambda: _Client())
    monkeypatch.setattr(ans, "incr_tokens", fake_incr)

    out = await ans.generate_one(content="什么是 GIL？", category="Python")
    assert out == "生成的答案"
    assert len(sets) == 1


@pytest.mark.asyncio
async def test_generate_one_none_on_api_failure(monkeypatch) -> None:
    async def fake_get(key):
        return None

    def fake_client():
        raise RuntimeError("API down")

    monkeypatch.setattr(ans, "cache_get", fake_get)
    monkeypatch.setattr(ans, "get_client", fake_client)

    out = await ans.generate_one(content="某题", category=None)
    assert out is None


def test_answer_outcome_defaults() -> None:
    outcome = ans.AnswerOutcome()
    assert outcome.generated == 0
    assert outcome.cache_hits == 0
    assert outcome.skipped == 0
    assert outcome.failed == 0
