"""Exercise real JSON cache serialization and parsing of company position dates."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from interviewlens.api import cache, routes_taxonomy


@pytest.mark.asyncio
@pytest.mark.parametrize("latest", [datetime(2026, 7, 15, tzinfo=UTC), None])
async def test_company_positions_datetime_survives_cache_roundtrip(monkeypatch, latest):
    store = {}

    async def save(key, value, ex=None):
        store[key] = value

    redis = MagicMock()
    redis.get = AsyncMock(side_effect=lambda key: store.get(key))
    redis.set = AsyncMock(side_effect=save)
    monkeypatch.setattr(cache, "get_redis", lambda: redis)
    monkeypatch.setattr(routes_taxonomy, "incr_cache", AsyncMock())
    monkeypatch.setattr(routes_taxonomy.settings, "search_cache_enabled", True)
    result = MagicMock()
    result.mappings.return_value.all.return_value = [
        {
            "company_id": 1,
            "company_name": "字节跳动",
            "position_id": 2,
            "position_name": "后端开发",
            "post_count": 4,
            "avg_quality": 43,
            "latest_posted_at": latest,
        }
    ]
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    first = await routes_taxonomy.list_company_positions(company_id=1, session=session)
    second = await routes_taxonomy.list_company_positions(company_id=1, session=session)
    assert first == second
    assert second[0].latest_posted_at == latest
    session.execute.assert_awaited_once()
    redis.set.assert_awaited_once()


@pytest.fixture(autouse=True)
def fake_database_revision(monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr("interviewlens.api.cache.read_revision", AsyncMock(return_value=""))
