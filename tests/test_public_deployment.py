from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
import redis.asyncio as redis
from starlette.requests import Request

from interviewlens.api.app import app
from interviewlens.api.deps import get_session
from interviewlens.api.public_data import public_profile
from interviewlens.api.schemas import QuestionOut, FeedQuestionOut
from interviewlens.api import resource_guard as guard
from interviewlens.config import Settings, settings


@pytest.mark.parametrize("url", ["/companies?limit=-1", "/positions?offset=-1", "/positions?limit=501", "/posts/search?q=redis&min_quality=101", "/posts?offset=99999999999999999999", "/posts/99999999999999999999999", "/posts/-1/position-profiles", "/companies/999999999999999999999999/positions"])
def test_bad_pagination_rejected_without_sql(url):
    session = MagicMock()
    session.execute = AsyncMock()
    async def dependency():
        yield session
    app.dependency_overrides[get_session] = dependency
    try:
        assert TestClient(app).get(url).status_code == 422
        session.execute.assert_not_awaited()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("url", ["/summaries", "/summaries/Foo/Bar", "/summaries/Foo/Bar/questions", "/bridge/generate-answers", "/api/bridge/generate-answers"])
def test_all_summary_and_generation_aliases_require_admin(monkeypatch, url):
    monkeypatch.setattr(settings, "admin_api_token", "t" * 64)
    client = TestClient(app)
    result = client.post(url, json={"question_ids": [1]}) if "bridge" in url else client.get(url)
    assert result.status_code == 401
    assert result.headers["cache-control"] == "no-store"


def test_public_profile_does_not_serialize_page_evidence_or_arbitrary_metadata():
    payload = dict(category="后端", status="classified", source="declared", skills=["Java"], raw_title="private", evidence=[dict(field="skills", value="Java", quote="window.envInfo userId educationInfo", source="declared")])
    result = public_profile(payload)
    assert result["skills"] == ["Java"]
    assert "evidence" not in result and "raw_title" not in result
    assert "window.envInfo" not in str(result)


@pytest.mark.parametrize("model", [QuestionOut, FeedQuestionOut])
def test_page_context_accidentally_copied_into_derived_answers_is_not_public(model):
    result = model(id=1, post_id=2, content="问题", answer_brief="window.envInfo = {rawNickname: 'private'}", answer_ai="原有题解")
    assert "private" not in result.model_dump_json()
    assert result.answer_brief is None and result.answer_ai is None


@pytest.mark.asyncio
async def test_search_timeout_keeps_inference_slot_until_computation_really_finishes(monkeypatch):
    monkeypatch.setattr(settings, "search_concurrency", 1)
    monkeypatch.setattr(settings, "search_timeout_seconds", 0.02)
    finished = asyncio.Event()
    async def operation():
        await finished.wait()
        return 1
    try:
        with pytest.raises(HTTPException) as timed_out:
            await guard.bounded_search_embed(operation)
        assert timed_out.value.status_code == 504
        with pytest.raises(HTTPException) as busy:
            await guard.bounded_search_embed(operation)
        assert busy.value.status_code == 503
        assert len(guard._jobs) == 1
    finally:
        finished.set()
        await asyncio.gather(*list(guard._jobs))
    await asyncio.sleep(0)
    assert not guard._jobs


@pytest.mark.asyncio
async def test_request_cancellation_keeps_slot(monkeypatch):
    finished = asyncio.Event()
    async def operation():
        await finished.wait()
    request = asyncio.create_task(guard.bounded_search_embed(operation))
    await asyncio.sleep(0)
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert len(guard._jobs) == 1
    finished.set()
    await asyncio.gather(*list(guard._jobs))
    await asyncio.sleep(0)
    assert not guard._jobs


@pytest.mark.asyncio
async def test_rate_limit_ignores_spoofed_forwarded_ip_and_fails_closed(monkeypatch):
    r = MagicMock()
    r.eval = AsyncMock(return_value=[13, 42])
    monkeypatch.setattr(guard, "get_redis", lambda: r)
    monkeypatch.setattr(settings, "trusted_search_proxy", "")
    scope = {"type": "http", "method": "GET", "path": "/posts/search", "query_string": b"", "headers": [(b"x-forwarded-for", b"1.2.3.4"), (b"x-il-client-ip", b"1.2.3.4")], "client": ("8.8.8.8", 123), "server": ("api", 8000), "scheme": "http"}
    with pytest.raises(HTTPException) as limited:
        await guard.check_rate(Request(scope))
    assert limited.value.status_code == 429
    assert limited.value.headers["Retry-After"] == "42"
    assert "1.2.3.4" not in str(r.eval.call_args)
    r.eval.side_effect = redis.ConnectionError()
    with pytest.raises(HTTPException) as unavailable:
        await guard.check_rate(Request(scope))
    assert unavailable.value.status_code == 503


def test_production_rejects_insecure_defaults():
    with pytest.raises(ValueError, match="credential"):
        Settings(_env_file=None, app_env="production", admin_api_token="short")
