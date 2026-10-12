"""Automatic answer tracing must cover real calls and degrade independently."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import openai
import pytest

import interviewlens.answerer.answerer as ans


@pytest.fixture
def dependencies(monkeypatch):
    lf = MagicMock()
    create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="new answer"))],
            usage=SimpleNamespace(
                model_dump=lambda: {"prompt_tokens": 10, "completion_tokens": 20}
            ),
        )
    )
    monkeypatch.setattr(ans, "cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(ans, "cache_set", AsyncMock())
    monkeypatch.setattr(ans, "get_langfuse", lambda: lf)
    monkeypatch.setattr(
        ans,
        "get_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        ),
    )
    return lf, create


@pytest.mark.asyncio
async def test_automatic_trace_records_output_usage_and_flushes(dependencies):
    lf, create = dependencies
    assert await ans.generate_one(content="question", category=None) == "new answer"
    create.assert_awaited_once()
    assert create.call_args.kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    lf.trace.assert_called_once()
    generation = lf.trace.return_value.generation.return_value
    generation.end.assert_called_once_with(
        output="new answer",
        usage={"prompt_tokens": 10, "completion_tokens": 20},
    )
    lf.flush.assert_called_once()


@pytest.mark.asyncio
async def test_supplied_trace_is_used_without_creating_or_flushing_owner(dependencies):
    lf, _ = dependencies
    trace = MagicMock()
    assert await ans.generate_one(content="question", category=None, trace=trace) == "new answer"
    lf.trace.assert_not_called()
    lf.flush.assert_not_called()
    trace.generation.return_value.end.assert_called_once()


@pytest.mark.asyncio
async def test_cache_hit_does_not_create_billable_generation(dependencies, monkeypatch):
    lf, create = dependencies
    monkeypatch.setattr(ans, "cache_get", AsyncMock(return_value={"answer": "cached"}))
    assert await ans.generate_one(content="question", category=None) == "cached"
    create.assert_not_awaited()
    lf.trace.assert_not_called()


@pytest.mark.asyncio
async def test_api_failure_ends_trace_and_flushes(dependencies):
    lf, create = dependencies
    create.side_effect = openai.APIError("offline", request=MagicMock(), body=None)
    assert await ans.generate_one(content="question", category=None) is None
    lf.trace.return_value.generation.return_value.end.assert_called_once_with(
        level="ERROR",
        status_message="APIError",
    )
    lf.flush.assert_called_once()


@pytest.mark.asyncio
async def test_observability_failure_does_not_break_generation(dependencies):
    lf, _ = dependencies
    lf.trace.side_effect = RuntimeError("trace unavailable")
    lf.flush.side_effect = RuntimeError("flush unavailable")
    assert await ans.generate_one(content="question", category=None) == "new answer"


@pytest.mark.asyncio
async def test_empty_answer_is_recorded_as_failure_and_not_cached(dependencies):
    lf, create = dependencies
    create.return_value.choices[0].message.content = ""
    assert await ans.generate_one(content="question", category=None) is None
    lf.trace.return_value.generation.return_value.end.assert_called_once_with(
        output="",
        usage={"prompt_tokens": 10, "completion_tokens": 20},
        level="ERROR",
        status_message="Empty answer",
    )
    ans.cache_set.assert_not_awaited()


@pytest.mark.asyncio
async def test_truncated_answer_is_not_cached_as_complete(dependencies):
    lf, create = dependencies
    create.return_value.choices[0].finish_reason = "length"
    assert await ans.generate_one(content="question", category=None) is None
    lf.trace.return_value.generation.return_value.end.assert_called_once_with(
        output="",
        usage={"prompt_tokens": 10, "completion_tokens": 20},
        level="ERROR",
        status_message="Truncated answer",
    )
    ans.cache_set.assert_not_awaited()
