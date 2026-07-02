"""Tests for taxonomy/summary read-path cache (openchange: search-result-caching).

Covers /companies, /companies/{id}/positions, /positions, /summaries,
/summaries/{company}/{position}. Uses dict-backed fake redis + fake session.
"""
from __future__ import annotations

import json
from datetime import datetime

import pytest

import interviewlens.api.routes_taxonomy as tax
import interviewlens.api.routes_summary as summ
from interviewlens.api import cache as cachemod


# ----------------------------------------------------------- fakes


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value


class _ExplodingRedis(_FakeRedis):
    async def get(self, key):
        raise cachemod.aioredis.RedisError("boom")

    async def set(self, key, value, ex=None):
        raise cachemod.aioredis.RedisError("boom")


class _Scalars:
    def __init__(self, rows): self._rows = rows
    def all(self): return self._rows


class _Result:
    def __init__(self, rows=None, scalars_rows=None, first_row=None, mappings_rows=None):
        self._rows = rows or []
        self._scalars = _Scalars(scalars_rows or [])
        self._first = first_row
        self._mappings = mappings_rows or []
    def all(self): return self._rows
    def scalars(self): return self._scalars
    def first(self): return self._first
    def mappings(self):
        class _M:
            def __init__(s, rows): s._rows = rows
            def all(s): return s._rows
        return _M(self._mappings)


class _FakeSession:
    """Records execute calls; returns configurable results."""
    def __init__(self):
        self.calls = 0
        self.rows = []           # for .all()
        self.scalars_rows = []   # for .scalars().all()
        self.first_row = None
        self.mappings_rows = []
    async def execute(self, stmt, params=None):
        self.calls += 1
        return _Result(
            rows=self.rows, scalars_rows=self.scalars_rows,
            first_row=self.first_row, mappings_rows=self.mappings_rows,
        )


async def _noop_incr(hit): return None


def _patch(monkeypatch, fake_redis):
    monkeypatch.setattr(cachemod, "get_redis", lambda: fake_redis)
    monkeypatch.setattr(tax, "incr_cache", _noop_incr)
    monkeypatch.setattr(summ, "incr_cache", _noop_incr)


# ----------------------------------------------------------- /companies


@pytest.mark.asyncio
async def test_companies_cache_hit_skips_db(monkeypatch):
    fake = _FakeRedis()
    _patch(monkeypatch, fake)
    key = tax._key("companies", {"limit": 100, "offset": 0, "with_counts": True})
    fake.store[key] = json.dumps([
        {"id": 1, "canonical": "字节", "industry": "互联网", "post_count": 5}
    ], ensure_ascii=False)

    session = _FakeSession()
    out = await tax.list_companies(limit=100, offset=0, with_counts=True, session=session)

    assert len(out) == 1 and out[0].canonical == "字节"
    assert session.calls == 0   # DB skipped


@pytest.mark.asyncio
async def test_companies_cache_miss_queries_db_and_writes(monkeypatch):
    fake = _FakeRedis()
    _patch(monkeypatch, fake)
    session = _FakeSession()
    session.rows = [(1, "字节", "互联网", 5), (2, "腾讯", "互联网", 3)]

    out = await tax.list_companies(limit=100, offset=0, with_counts=True, session=session)

    assert len(out) == 2
    assert session.calls == 1
    has_key = any("il:api:companies:" in k for k in fake.store)
    assert has_key


@pytest.mark.asyncio
async def test_companies_redis_failure_miss_through(monkeypatch):
    fake = _ExplodingRedis()
    _patch(monkeypatch, fake)
    session = _FakeSession()
    session.rows = [(1, "字节", "互联网", 5)]

    out = await tax.list_companies(limit=100, offset=0, with_counts=True, session=session)

    assert len(out) == 1   # fell through to DB, no exception


# ----------------------------------------------------------- /companies/{id}/positions


@pytest.mark.asyncio
async def test_company_positions_cache_hit(monkeypatch):
    fake = _FakeRedis()
    _patch(monkeypatch, fake)
    key = tax._key("company_positions", {"company_id": 7})
    fake.store[key] = json.dumps([
        {"company_id": 7, "company_name": "字节", "position_id": 3,
         "position_name": "后端", "post_count": 4}
    ], ensure_ascii=False)

    session = _FakeSession()
    out = await tax.list_company_positions(company_id=7, session=session)

    assert len(out) == 1 and out[0].position_name == "后端"
    assert session.calls == 0


# ----------------------------------------------------------- /summaries


@pytest.mark.asyncio
async def test_summaries_cache_hit(monkeypatch):
    fake = _FakeRedis()
    _patch(monkeypatch, fake)
    key = summ._key("summaries", {
        "company": None, "position": None, "period": None, "limit": 50
    })
    fake.store[key] = json.dumps([
        {"id": 1, "company": "字节", "position": "后端", "period": "all",
         "sample_count": 10, "content_md": "# x", "updated_at": "2026-01-01T00:00:00"}
    ], ensure_ascii=False)

    session = _FakeSession()
    out = await summ.list_summaries(
        company=None, position=None, period=None, limit=50, session=session
    )

    assert len(out) == 1 and out[0].company == "字节"
    assert session.calls == 0


@pytest.mark.asyncio
async def test_summary_single_cache_hit(monkeypatch):
    fake = _FakeRedis()
    _patch(monkeypatch, fake)
    key = summ._key("summary", {"company": "字节", "position": "后端", "period": "all"})
    fake.store[key] = json.dumps({
        "id": 1, "company": "字节", "position": "后端", "period": "all",
        "sample_count": 10, "content_md": "# x", "updated_at": "2026-01-01T00:00:00"
    }, ensure_ascii=False)

    session = _FakeSession()
    out = await summ.get_summary(company="字节", position="后端", period="all", session=session)

    assert out.company == "字节"
    assert session.calls == 0


@pytest.mark.asyncio
async def test_summary_404_not_cached(monkeypatch):
    """When DB returns None, 404 is raised and nothing is written to cache."""
    fake = _FakeRedis()
    _patch(monkeypatch, fake)
    session = _FakeSession()
    session.first_row = None

    with pytest.raises(Exception):  # HTTPException
        await summ.get_summary(company="x", position="y", period="all", session=session)

    assert fake.store == {}
