"""Shared request scheduling across browsers, Celery workers and backfill."""

import asyncio
import random

from sqlalchemy import text

from ..db import session_scope
from .response_guard import CrawlStoppedError


class SiteLimiter:
    def __init__(self, local):
        self.local = local

    async def acquire(self):
        await self.local.acquire()
        async with session_scope() as session:
            row = (
                (
                    await session.execute(
                        text("""
                SELECT next_request_at,paused_reason,
                    paused_until>NOW() AS paused
                FROM site_request_state WHERE site='nowcoder' FOR UPDATE
            """)
                    )
                )
                .mappings()
                .one()
            )
            if row["paused"]:
                raise CrawlStoppedError(row["paused_reason"])
            delay = (
                await session.execute(
                    text("""
                UPDATE site_request_state SET
                    next_request_at=GREATEST(next_request_at,NOW())+
                        (:spacing * INTERVAL '1 second')
                WHERE site='nowcoder'
                RETURNING GREATEST(EXTRACT(EPOCH FROM
                    next_request_at-NOW())-:spacing,0)
            """),
                    {"spacing": 10 + random.uniform(1, 10)},
                )
            ).scalar_one()
        if delay:
            await asyncio.sleep(float(delay))

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *_):
        return None


async def pause_site(reason):
    if reason not in {"http_401", "http_403", "http_429", "login_or_challenge", "api_rejected"}:
        return
    async with session_scope() as session:
        await session.execute(
            text("""
            UPDATE site_request_state SET paused_until=NOW()+INTERVAL '1 hour',
                paused_reason=:reason WHERE site='nowcoder'
        """),
            {"reason": reason},
        )
