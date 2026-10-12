from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from interviewlens.api.app import app
from interviewlens.api.deps import get_session
from interviewlens.api.routes_position_editor import local_editor


def test_editor_requires_token_even_on_loopback(monkeypatch):
    from interviewlens.config import settings

    monkeypatch.setattr(settings, "admin_api_token", "test-" + "x" * 40)
    local_editor(
        Request(
            {
                "type": "http",
                "client": ("127.0.0.1", 50000),
                "headers": [(b"authorization", ("Bearer " + settings.admin_api_token).encode())],
            }
        )
    )
    with pytest.raises(HTTPException) as error:
        local_editor(
            Request(
                {
                    "type": "http",
                    "client": ("127.0.0.1", 50000),
                    "headers": [(b"origin", b"https://evil.example")],
                }
            )
        )
    assert error.value.status_code == 401


def test_editor_blocks_unauthenticated_remote_and_cross_site_writes(monkeypatch):
    from interviewlens.config import settings

    monkeypatch.setattr(settings, "admin_api_token", "test-" + "x" * 40)
    client = TestClient(app)
    assert client.get("/admin/position-posts").status_code == 401
    assert (
        client.put(
            "/admin/posts/1/position-profiles", headers={"Origin": "https://evil.example"}, json={}
        ).status_code
        == 401
    )


def test_editor_rejects_invalid_category_before_database_work():
    session = MagicMock()
    session.execute = AsyncMock()

    async def dependency():
        yield session

    app.dependency_overrides[get_session] = dependency
    app.dependency_overrides[local_editor] = lambda: None
    try:
        result = TestClient(app).put(
            "/admin/posts/1/position-profiles",
            json={"revision": "abc", "profiles": [{"category": "Java"}]},
        )
        assert result.status_code == 422
        session.execute.assert_not_awaited()
    finally:
        app.dependency_overrides.clear()
