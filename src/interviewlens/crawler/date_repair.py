"""Recover only NULL publication dates, retaining evidence and all derived data."""

from __future__ import annotations

import json

import httpx
from sqlalchemy import text

from ..config import settings
from .backfill_store import BackfillStore
from .metadata_api import API_ROOT, JOB_HEADERS, detail_endpoint, parse_detail_metadata
from .rate_limit import AsyncRateLimiter
from .record_metadata import publication_datetime
from .response_guard import CrawlStoppedError, check_status


async def repair_dates(*, apply=False, fetch_missing=False, max_requests=30, engine=None,
                       progress=None, client_factory=None, limiter=None):
    if not 1 <= max_requests <= 150:
        raise ValueError("max_requests must be 1..150")
    if fetch_missing and not apply:
        raise ValueError("remote repair requires explicit --apply")
    report = {"status": "complete", "candidates": 0, "repaired": 0, "requests": 0,
              "unresolved": 0, "unavailable": 0, "apply": apply}
    store = BackfillStore(engine)
    limiter = limiter or AsyncRateLimiter(rate_per_sec=1 / 10, jitter=(1, 10))
    headers = {**JOB_HEADERS, "user-agent": settings.nowcoder_user_agent}
    if settings.nowcoder_cookie:
        headers["cookie"] = settings.nowcoder_cookie
    factory = client_factory or httpx.AsyncClient
    async with store.locked() as acquired:
        if not acquired:
            return {**report, "status": "locked"}
        async with store.connection.begin():
            rows = (await store.connection.execute(text("""
                SELECT p.id,p.source_url,q.record FROM posts p
                LEFT JOIN crawl_queue q ON q.url=p.source_url
                LEFT JOIN crawl_date_unavailable u ON u.post_id=p.id
                WHERE p.posted_at IS NULL AND u.post_id IS NULL ORDER BY p.id
            """))).mappings().all()
        async with factory(headers=headers, timeout=30) as client:
            for row in rows:
                record = row["record"] or {}
                if isinstance(record, str):
                    record = json.loads(record)
                date = publication_datetime(record)
                evidence_source = "saved_api_record"
                if date is None and fetch_missing and report["requests"] < max_requests:
                    endpoint = detail_endpoint(row["source_url"])
                    if endpoint:
                        try:
                            await limiter.acquire()
                            report["requests"] += 1
                            response = await client.get(API_ROOT + endpoint[0])
                            check_status(response.status_code)
                            record = parse_detail_metadata(response.json(), row["source_url"])
                            date = publication_datetime(record)
                            evidence_source = "detail_api"
                        except (httpx.HTTPError, ValueError) as exc:
                            report.update(status="stopped", reason=type(exc).__name__)
                        except CrawlStoppedError as exc:
                            if exc.reason == "post_unavailable":
                                report["unavailable"] += 1
                                async with store.connection.begin():
                                    await store.connection.execute(text("""
                                        INSERT INTO crawl_date_unavailable(post_id,reason)
                                        VALUES(:id,:reason) ON CONFLICT(post_id) DO NOTHING
                                    """), {"id": row["id"], "reason": exc.reason})
                            else:
                                report.update(status="stopped", reason=exc.reason)
                if date:
                    report["candidates"] += 1
                    if apply:
                        field = next((body, key) for body, key in (
                            ("momentData", "createdAt"), ("contentData", "createTime"))
                            if publication_datetime({body: record.get(body)}) == date)
                        evidence = json.dumps({"url": row["source_url"],
                            "field": ".".join(field), "value": record[field[0]][field[1]]})
                        async with store.connection.begin():
                            changed = (await store.connection.execute(text("""
                                UPDATE posts SET posted_at=:date WHERE id=:id AND posted_at IS NULL
                                RETURNING id
                            """), {"id": row["id"], "date": date})).first()
                            if changed:
                                await store.connection.execute(text("""
                                    INSERT INTO crawl_date_repairs(post_id,posted_at,evidence_source,evidence)
                                    VALUES(:id,:date,:source,:evidence)
                                    ON CONFLICT(post_id) DO UPDATE SET posted_at=EXCLUDED.posted_at,
                                        evidence_source=EXCLUDED.evidence_source,
                                        evidence=EXCLUDED.evidence,repaired_at=NOW()
                                """), {"id": row["id"], "date": date,
                                       "source": evidence_source, "evidence": evidence})
                                report["repaired"] += 1
                else:
                    report["unresolved"] += 1
                if progress:
                    progress({**report, "status": "running" if report["status"] == "complete" else report["status"],
                              "post_id": row["id"]})
                if report["status"] == "stopped":
                    break
        async with store.connection.begin():
            report["remaining_null"] = (await store.connection.execute(
                text("SELECT count(*) FROM posts WHERE posted_at IS NULL"))).scalar_one()
            report["unavailable_total"] = (await store.connection.execute(text(
                "SELECT count(*) FROM crawl_date_unavailable u JOIN posts p ON p.id=u.post_id "
                "WHERE p.posted_at IS NULL"))).scalar_one()
        if report["remaining_null"] and report["status"] == "complete":
            report["status"] = "partial"
    return report
