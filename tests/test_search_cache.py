"""Tests for /posts/search two-layer Redis cache (openchange: search-result-caching).

Uses a dict-backed fake redis + monkeypatched embed_texts/session, so no real
Redis/pgvector/bge-m3 needed.
"""
from __future__ import annotations

import base64
import json

import numpy as np
import pytest

import interviewlens.api.routes_search as rs


# ----------------------------------------------------------- fake redis


class _FakeRedis:
    """Minimal async redis backed by an in-memory dict."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value


class _ExplodingRedis(_FakeRedis):
    async def get(self, key: str) -> str | None:
        raise rs.aioredis.RedisError("simulated connection failure")

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        raise rs.aioredis.RedisError("simulated connection failure")


# ----------------------------------------------------------- helpers


def _row(qid: int) -> dict:
    return {
        "id": qid,
        "post_id": 1,
        "round_no": 1,
        "round_type": "技术",
        "content": f"question {qid}",
        "category": "Java",
        "answer_brief": "brief",
        "answer_ai": None,
        "quality_score": 80,
        "source_url": "http://x",
        "similarity": 0.9,
    }


class _FakeMappings:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def all(self) -> list[dict]:
        return self._rows


class _FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self._m = _FakeMappings(rows)

    def mappings(self) -> _FakeMappings:
        return self._m


class _FakeSession:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.calls = 0

    async def execute(self, sql, params):
        self.calls += 1
        return _FakeResult(list(self._rows))


async def _noop_incr_cache(hit: bool) -> None:
    return None


def _patch(monkeypatch, fake_redis, embed_calls=None):
    monkeypatch.setattr(rs, "get_redis", lambda: fake_redis)
    monkeypatch.setattr(rs, "incr_cache", _noop_incr_cache)

    call_count = {"n": 0}

    async def _fake_embed(texts):
        call_count["n"] += 1
        return np.array([[0.1, 0.2, 0.3]], dtype=np.float32)

    monkeypatch.setattr(rs, "embed_texts", _fake_embed)
    return call_count


# ----------------------------------------------------------- tests


@pytest.mark.asyncio
async def test_result_cache_hit_skips_embed_and_db(monkeypatch):
    fake = _FakeRedis()
    cc = _patch(monkeypatch, fake)
    # pre-seed a result-cache entry
    rkey = rs._result_key("分布式锁", {
        "company": None, "position": None, "min_quality": 0, "limit": 20
    })
    fake.store[rkey] = json.dumps([_row(1), _row(2)], ensure_ascii=False)

    session = _FakeSession([_row(99)])
    # pass all params explicitly — FastAPI Query() defaults don't resolve on direct call
    out = await rs.search(
        "分布式锁", company=None, position=None, min_quality=0, limit=20, session=session
    )

    assert len(out) == 2
    assert out[0].id == 1
    assert cc["n"] == 0          # embed_texts NOT called
    assert session.calls == 0    # DB NOT queried


@pytest.mark.asyncio
async def test_embed_cache_hit_skips_embed_texts(monkeypatch):
    """Same query, two different filters → embed_texts called once."""
    fake = _FakeRedis()
    cc = _patch(monkeypatch, fake)
    # pre-seed embedding cache
    ekey = rs._embed_key("JVM GC")
    vec = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    fake.store[ekey] = base64.b64encode(vec.tobytes()).decode("ascii")

    s1 = _FakeSession([_row(1)])
    s2 = _FakeSession([_row(2)])
    await rs.search("JVM GC", company="字节", position=None, min_quality=0, limit=20, session=s1)
    await rs.search("JVM GC", company="腾讯", position=None, min_quality=0, limit=20, session=s2)

    assert cc["n"] == 0          # embedding cache hit both times
    assert s1.calls == 1 and s2.calls == 1  # DB queried both (different filters)


@pytest.mark.asyncio
async def test_redis_failure_miss_through(monkeypatch):
    """Redis errors → fall through to embed + DB; no exception raised."""
    fake = _ExplodingRedis()
    cc = _patch(monkeypatch, fake)

    session = _FakeSession([_row(1)])
    out = await rs.search(
        "JVM", company=None, position=None, min_quality=0, limit=20, session=session
    )

    assert len(out) == 1
    assert cc["n"] == 1          # embed_texts called (cache unusable)
    assert session.calls == 1    # DB queried


@pytest.mark.asyncio
async def test_vector_roundtrip_lossless():
    """base64(float32) → float32 reproduces the original bit-for-bit."""
    vec = np.array([0.0123, -0.0456, 0.789, 1e-7], dtype=np.float32)
    blob = base64.b64encode(vec.tobytes()).decode("ascii")
    back = np.frombuffer(base64.b64decode(blob), dtype=np.float32)
    assert np.array_equal(vec, back)


@pytest.mark.asyncio
async def test_cache_disabled_skips_redis(monkeypatch):
    """search_cache_enabled=False → no cache reads, always embed + DB."""
    fake = _FakeRedis()
    cc = _patch(monkeypatch, fake)
    monkeypatch.setattr(rs.settings, "search_cache_enabled", False)

    session = _FakeSession([_row(1)])
    out = await rs.search(
        "JVM", company=None, position=None, min_quality=0, limit=20, session=session
    )

    assert len(out) == 1
    assert cc["n"] == 1
    assert session.calls == 1
    assert fake.store == {}      # nothing written to cache
