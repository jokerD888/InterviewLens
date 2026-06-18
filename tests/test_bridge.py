"""Bridge API unit tests — mocked answerer + httpx."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from interviewlens.api.routes_bridge import generate_answers, export_to_daily_prep


@pytest.mark.asyncio
async def test_generate_answers_uses_answerer(monkeypatch) -> None:
    """generate-answers calls answerer.generate_one for each question."""
    req_mock = MagicMock()
    req_mock.question_ids = [1, 2]

    # Mock session to return rows
    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def execute(self, sql, params):
            m = MagicMock()
            m.all.return_value = [
                (1, "什么是 GIL？", "Python"),
                (2, "TCP 三次握手", "网络"),
            ]
            return m

    fake_session = _FakeSession()

    async def fake_generate(*, content, category, trace=None):
        return f"答案: {content}"

    monkeypatch.setattr(
        "interviewlens.api.routes_bridge.session_scope",
        lambda: fake_session,
    )
    monkeypatch.setattr(
        "interviewlens.api.routes_bridge.generate_one",
        fake_generate,
    )

    resp = await generate_answers(req_mock)
    assert len(resp.answers) == 2
    assert resp.answers[0].generated_answer == "答案: 什么是 GIL？"
    assert resp.answers[0].question_id == 1
    assert resp.answers[1].generated_answer == "答案: TCP 三次握手"


@pytest.mark.asyncio
async def test_generate_answers_missing_question() -> None:
    """Missing question IDs get an error entry."""
    req_mock = MagicMock()
    req_mock.question_ids = [999]  # not in DB

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def execute(self, sql, params):
            m = MagicMock()
            m.all.return_value = []  # no results
            return m

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "interviewlens.api.routes_bridge.session_scope",
        lambda: _FakeSession(),
    )

    resp = await generate_answers(req_mock)
    assert len(resp.answers) == 1
    assert resp.answers[0].generated_answer is None
    assert resp.answers[0].error == "question not found"


@pytest.mark.asyncio
async def test_export_no_token_configured(monkeypatch) -> None:
    """Export fails with 502 when token is empty."""
    from interviewlens.api.routes_bridge import settings as bridge_settings
    monkeypatch.setattr(bridge_settings, "daily_prep_token", "")

    req_mock = MagicMock()
    req_mock.cards = []

    with pytest.raises(Exception) as exc_info:
        await export_to_daily_prep(req_mock)
    assert "Token" in str(exc_info.value.detail) or exc_info.value.status_code == 502
