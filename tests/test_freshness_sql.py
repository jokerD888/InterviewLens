"""Read-only PostgreSQL regression coverage for freshness bind parameters."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from interviewlens.scoring import freshness_case_sql, score_freshness


@pytest.mark.asyncio
@pytest.mark.parametrize("days_old", [None, 0, 90, 91, 180, 181, 360, 361, 720, 721])
async def test_freshness_sql_matches_python_on_postgres(days_old: int | None) -> None:
    database_url = os.environ.get("INTERVIEWLENS_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set INTERVIEWLENS_TEST_DATABASE_URL to run PostgreSQL coverage")

    as_of = datetime(2026, 10, 4, tzinfo=UTC)
    posted_at = None if days_old is None else as_of - timedelta(days=days_old)
    expression = freshness_case_sql(posted_at_sql="post.posted_at")
    query = text(
        f"SELECT {expression} FROM "
        "(VALUES (CAST(:posted_at AS TIMESTAMP WITH TIME ZONE))) AS post(posted_at)"
    )
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            result = await connection.scalar(query, {"posted_at": posted_at, "as_of": as_of})
        assert result == score_freshness(posted_at, as_of=as_of)
    finally:
        await engine.dispose()
