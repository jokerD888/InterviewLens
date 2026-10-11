"""Short PostgreSQL transactions under a session-level, cross-process crawl lock."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy import text

from ..db.session import get_engine
from .record_metadata import page_fingerprint, publication_datetime
from .response_guard import CrawlStoppedError
from .tab_crawler import build_detail_url

SOURCE = "nowcoder-tab-818"
LOCK_KEY = 492041818


class BackfillStore:
    def __init__(self, engine=None, *, lock_key: int = LOCK_KEY, source: str = SOURCE):
        self.source = source
        self.engine = engine if engine is not None else get_engine()
        self.lock_key = lock_key
        self.connection = None

    @asynccontextmanager
    async def locked(self):
        async with self.engine.connect() as connection:
            acquired = None
            try:
                acquired = (
                    await connection.execute(
                        text("SELECT pg_try_advisory_lock(:key)"), {"key": self.lock_key}
                    )
                ).scalar_one()
                await connection.commit()
                if not acquired:
                    yield False
                    return
                self.connection = connection
                yield True
            finally:
                try:
                    await connection.rollback()
                    if acquired is None:
                        # Cancellation may interrupt the response after PostgreSQL acquired
                        # the lock. Close this session when acquisition outcome is unknown.
                        await connection.invalidate()
                    elif acquired:
                        await connection.execute(
                            text("SELECT pg_advisory_unlock(:key)"), {"key": self.lock_key}
                        )
                        await connection.commit()
                except BaseException:
                    # Never put a connection carrying a session lock back into the pool.
                    await connection.invalidate()
                    raise
                finally:
                    self.connection = None

    async def begin_batch(self, since: datetime | None, cooldown: int, resume: bool):
        async with self.connection.begin():
            await self.connection.execute(
                text("""
                INSERT INTO crawl_progress(source,since_at)
                SELECT :source, COALESCE(CAST(:since AS timestamptz),
                    (SELECT COALESCE(MAX(posted_at), NOW() - INTERVAL '90 days')
                     - INTERVAL '7 days' FROM posts))
                ON CONFLICT DO NOTHING
            """),
                {"source": self.source, "since": since},
            )
            row = (
                (
                    await self.connection.execute(
                        text("""
                SELECT *, (last_batch_at IS NOT NULL AND
                    last_batch_at + :cooldown * INTERVAL '1 second' > NOW()) AS cooling
                FROM crawl_progress WHERE source=:source
            """),
                        {"source": self.source, "cooldown": cooldown},
                    )
                )
                .mappings()
                .one()
            )
            if since is not None and since != row["since_at"]:
                raise ValueError(
                    "since differs from persisted campaign; keep its original boundary"
                )
            if row["cooling"]:
                return "cooldown", dict(row)
            if row["paused_reason"] and not resume:
                return "paused", dict(row)
            await self.connection.execute(
                text("""
                UPDATE crawl_progress SET last_batch_at=NOW(),paused_reason=NULL
                WHERE source=:source
            """),
                {"source": self.source},
            )
            return "ready", dict(row)

    async def pending(self, limit: int):
        async with self.connection.begin():
            rows = (
                (
                    await self.connection.execute(
                        text("""
                SELECT url,record,attempts FROM crawl_queue
                WHERE source=:source AND status='pending'
                ORDER BY queued_at,url LIMIT :limit
            """),
                        {"source": self.source, "limit": limit},
                    )
                )
                .mappings()
                .all()
            )
            return [dict(row) for row in rows]

    async def start_scan(self):
        async with self.connection.begin():
            await self.connection.execute(text("""
                DELETE FROM crawl_scan_pages WHERE source=:source AND EXISTS(
                    SELECT 1 FROM crawl_progress WHERE source=:source AND completed=TRUE)
            """), {"source": self.source})
            await self.connection.execute(
                text("""
                UPDATE crawl_progress SET completed=FALSE,next_page=1
                WHERE source=:source AND completed=TRUE
            """),
                {"source": self.source},
            )
            row = (
                (
                    await self.connection.execute(
                        text("""
                SELECT next_page,since_at FROM crawl_progress WHERE source=:source
            """),
                        {"source": self.source},
                    )
                )
                .mappings()
                .one()
            )
            return dict(row)

    async def enqueue_page(self, records: list[dict], page: int, since: datetime):

        async with self.connection.begin():
            fingerprint = page_fingerprint(records)
            # Same page on a later run is intentional overlap; another page with
            # identical identities signals a clamped/repeated server response.
            repeated = await self.connection.execute(text("""
                SELECT page FROM crawl_scan_pages
                WHERE source=:source AND page<>:page AND fingerprint=:fingerprint
                LIMIT 1
            """), {"source": self.source, "page": page, "fingerprint": fingerprint})
            if fingerprint and repeated.first():
                raise CrawlStoppedError("pagination_repeated")
            dates = [date for record in records if (date := publication_datetime(record))]
            await self.connection.execute(text("""
                INSERT INTO crawl_scan_pages(source,page,fingerprint,oldest_at,newest_at)
                VALUES(:source,:page,:fingerprint,:oldest,:newest)
                ON CONFLICT(source,page) DO UPDATE SET fingerprint=EXCLUDED.fingerprint,
                    oldest_at=EXCLUDED.oldest_at,newest_at=EXCLUDED.newest_at,scanned_at=NOW()
            """), {"source": self.source, "page": page, "fingerprint": fingerprint,
                   "oldest": min(dates) if dates else None, "newest": max(dates) if dates else None})
            for record in records:
                url = build_detail_url(record)
                published = publication_datetime(record)
                if not url or (published and published < since):
                    continue
                await self.connection.execute(
                    text("""
                    INSERT INTO crawl_queue(url,source,record)
                    SELECT :url,:source,CAST(:record AS jsonb)
                    WHERE NOT EXISTS(SELECT 1 FROM posts WHERE source_url=:url)
                    ON CONFLICT(url) DO NOTHING
                """),
                    {"url": url, "source": self.source, "record": json.dumps(record)},
                )
            await self.connection.execute(
                text("""
                UPDATE crawl_progress SET next_page=GREATEST(next_page,:next),completed=:empty
                WHERE source=:source
            """),
                {"source": self.source, "next": page + 1, "empty": not records},
            )

    async def reserve_attempt(self, url: str, daily_limit: int):
        # Charge before navigation: failures and process crashes consume the budget too.
        async with self.connection.begin():
            spent = (await self.connection.execute(text("""
                SELECT COALESCE(SUM(detail_attempts),0) FROM crawl_daily_budget
                WHERE day=(NOW() AT TIME ZONE 'Asia/Shanghai')::date
            """))).scalar_one()
            # All sources are under the same advisory lock. Partitioning the
            # discovery feed must not multiply the application's daily quota.
            if spent >= daily_limit:
                return False
            charged = (
                await self.connection.execute(
                    text("""
                INSERT INTO crawl_daily_budget(source,day,detail_attempts)
                VALUES(:source,(NOW() AT TIME ZONE 'Asia/Shanghai')::date,1)
                ON CONFLICT(source,day) DO UPDATE
                SET detail_attempts=crawl_daily_budget.detail_attempts+1
                WHERE crawl_daily_budget.detail_attempts < :limit
                RETURNING detail_attempts
            """),
                    {"source": self.source, "limit": daily_limit},
                )
            ).first()
            if not charged:
                return False
            await self.connection.execute(
                text("""
                UPDATE crawl_queue SET attempts=attempts+1 WHERE url=:url AND status='pending'
            """),
                {"url": url},
            )
            return True

    async def mark_existing(self):
        async with self.connection.begin():
            await self.connection.execute(
                text("""
                UPDATE crawl_queue q SET status='done',last_error=NULL
                WHERE q.source=:source AND q.status='pending'
                AND EXISTS(SELECT 1 FROM posts p WHERE p.source_url=q.url)
            """),
                {"source": self.source},
            )
            # Attempts already charged before a crashed navigation remain charged.
            await self.connection.execute(
                text("""
                UPDATE crawl_queue SET status='failed',last_error=COALESCE(last_error,'attempts_exhausted')
                WHERE source=:source AND status='pending' AND attempts>=3
            """),
                {"source": self.source},
            )

    async def retry_failed(self):
        async with self.connection.begin():
            await self.connection.execute(
                text("""
                UPDATE crawl_queue SET status='pending',attempts=0,last_error=NULL
                WHERE source=:source AND status='failed'
            """),
                {"source": self.source},
            )

    async def finish(self, url: str, post: dict):

        timestamp = post.get("created_at_ms")
        posted_at = datetime.fromtimestamp(timestamp / 1000, UTC) if timestamp else None
        async with self.connection.begin():
            inserted = (
                await self.connection.execute(
                    text("""
                INSERT INTO posts(source_url,title,cleaned_text,posted_at,extract_status)
                VALUES(:url,:title,:content,:date,'pending')
                ON CONFLICT(source_url) DO NOTHING RETURNING id
            """),
                    {
                        "url": url,
                        "title": post["title"],
                        "content": post["content"],
                        "date": posted_at,
                    },
                )
            ).first()
            await self.connection.execute(
                text("""
                UPDATE crawl_queue SET status='done',last_error=NULL WHERE url=:url
            """),
                {"url": url},
            )
            return inserted is not None

    async def fail(self, url: str | None, reason: str, *, pause: bool):
        async with self.connection.begin():
            if url:
                await self.connection.execute(
                    text("""
                    UPDATE crawl_queue SET last_error=:reason,
                        status=CASE WHEN attempts>=3 THEN 'failed' ELSE 'pending' END
                    WHERE url=:url
                """),
                    {"url": url, "reason": reason},
                )
            if pause:
                await self.connection.execute(
                    text("""
                    UPDATE crawl_progress SET paused_reason=:reason WHERE source=:source
                """),
                    {"reason": reason, "source": self.source},
                )

    async def snapshot(self):
        async with self.connection.begin():
            row = (
                (
                    await self.connection.execute(
                        text("""
                SELECT p.next_page,p.completed,p.since_at,p.paused_reason,p.last_batch_at,
                    (SELECT COUNT(*) FROM crawl_queue q WHERE q.source=p.source
                        AND q.status='pending') AS pending,
                    (SELECT COUNT(*) FROM crawl_queue q WHERE q.source=p.source
                        AND q.status='failed') AS failed,
                    COALESCE((SELECT SUM(detail_attempts) FROM crawl_daily_budget b
                        WHERE b.day=(NOW() AT TIME ZONE 'Asia/Shanghai')::date),0)
                        AS today_attempts
                FROM crawl_progress p WHERE source=:source
            """),
                        {"source": self.source},
                    )
                )
                .mappings()
                .first()
            )
            return dict(row) if row else {}
