from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from interviewlens.llm import deepseek
from interviewlens.llm.budget import LLMLimitError


@pytest.mark.asyncio
async def test_budget_rejection_closes_generation_and_owned_root(monkeypatch):
    lf = MagicMock()
    create = AsyncMock(side_effect=LLMLimitError('limit reached'))
    monkeypatch.setattr(deepseek, 'get_langfuse', lambda: lf)
    monkeypatch.setattr(deepseek, 'get_client', lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    with pytest.raises(LLMLimitError):
        await deepseek.call_tool(messages=[], tools=[])
    create.assert_awaited_once()
    lf.trace.return_value.generation.return_value.end.assert_called_once_with(level='ERROR', status_message='LLMLimitError')
    lf.trace.return_value.end.assert_called_once()
    lf.flush.assert_called_once()


@pytest.mark.asyncio
async def test_success_ends_usage_and_leaves_borrowed_root_to_owner(monkeypatch):
    trace = MagicMock()
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[SimpleNamespace(function=SimpleNamespace(name='extract', arguments='{"ok":true}'))]))],
        usage=SimpleNamespace(model_dump=lambda: {'prompt_tokens': 4, 'completion_tokens': 6}),
        model_dump=lambda: {'ok': True},
    )
    monkeypatch.setattr(deepseek, 'get_langfuse', lambda: None)
    monkeypatch.setattr(deepseek, 'get_client', lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=response)))))
    result = await deepseek.call_tool(messages=[], tools=[], trace=trace)
    assert result.arguments == {'ok': True}
    trace.generation.return_value.end.assert_called_once_with(output={'ok': True}, usage={'prompt_tokens': 4, 'completion_tokens': 6})
    trace.end.assert_not_called()
