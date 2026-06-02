"""Lightweight API tests using starlette's TestClient.

We override the DB session dependency with a stub so the tests don't need
Postgres up. This isolates routing/serialisation logic.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

# Stub embedding before the API imports it during app load — the lifespan
# coroutine will call get_model() and we don't want to load bge-m3.
import interviewlens.embedding.bge_m3 as bge


async def _fake_get_model():
    return None


bge.get_model = _fake_get_model  # type: ignore[assignment]

from interviewlens.api.app import app  # noqa: E402
from interviewlens.api.deps import get_session  # noqa: E402


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self


class FakeSession:
    """Minimal AsyncSession-shaped stub. Returns canned data for known SQL."""

    def __init__(self, plans: dict[str, list]):
        self._plans = plans

    async def execute(self, stmt, params=None):
        text = str(stmt).lower()
        for key, rows in self._plans.items():
            if key in text:
                return FakeResult(rows)
        return FakeResult([])


def _override_session_with(plans: dict[str, list]):
    async def _gen() -> AsyncIterator[FakeSession]:
        yield FakeSession(plans)

    return _gen


def test_root_lists_endpoints() -> None:
    with TestClient(app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "InterviewLens"
        assert "/companies" in body["endpoints"]


def test_companies_with_counts() -> None:
    rows = [
        (1, "字节跳动", "互联网", 10),
        (2, "腾讯", "互联网", 7),
    ]
    app.dependency_overrides[get_session] = _override_session_with({"from companies": rows})
    try:
        with TestClient(app) as client:
            resp = client.get("/companies")
            assert resp.status_code == 200
            data = resp.json()
            assert data[0]["canonical"] == "字节跳动"
            assert data[0]["post_count"] == 10
    finally:
        app.dependency_overrides.clear()


def test_summary_404_when_missing() -> None:
    app.dependency_overrides[get_session] = _override_session_with({})
    try:
        with TestClient(app) as client:
            resp = client.get("/summaries/Foo/Bar?period=2025Q2")
            assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()
