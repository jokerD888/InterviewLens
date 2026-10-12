"""Daily update orchestration — serial, run once a day via OS scheduler.

Chains the existing (idempotent) pipeline steps back to back:

    crawl (incremental) → extract/normalize/score → aggregate → answer

Saved author text can be processed independently of paused discovery. New
questions are indexed before aggregation; committed writes invalidate reads.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import suppress

import redis.asyncio as redis

from ..config import settings
from ..logging import log

_LOCK_KEY = "il:daily:lock"
_LOCK_TTL = 60 * 60 * 6  # 6h — a daily run finishing later than this is pathological


async def daily_update(*, with_answers: bool = True, with_crawl: bool = True) -> dict:
    """Run the full daily update chain once. Reentrancy-guarded via Redis.

    Returns a summary dict of per-step counts for logging / `il metrics`.
    """
    r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    # ponytail: single-node reentrancy lock; NX+TTL is enough for one cron box.
    owner = uuid.uuid4().hex
    if not await r.set(_LOCK_KEY, owner, nx=True, ex=_LOCK_TTL):
        log.warning("daily.locked", msg="another daily_update is running; skipping")
        await r.aclose()
        return {"skipped": "locked"}

    async def renew_lock():
        while True:
            await asyncio.sleep(60)
            renewed = await r.eval(
                """
                if redis.call('GET',KEYS[1]) == ARGV[1] then
                    return redis.call('EXPIRE',KEYS[1],ARGV[2])
                end
                return 0
            """,
                1,
                _LOCK_KEY,
                owner,
                _LOCK_TTL,
            )
            if not renewed:
                raise RuntimeError("Daily update lock lost")

    heartbeat = asyncio.create_task(renew_lock())
    parent = asyncio.current_task()

    def on_heartbeat_exit(task):
        if not task.cancelled() and task.exception() is not None and parent:
            parent.cancel("Daily update lease renewal failed")

    heartbeat.add_done_callback(on_heartbeat_exit)
    summary: dict = {}
    try:
        from ..agent.recovery import resume_failed
        from ..aggregator import aggregate_all
        from ..crawler.backfill import BackfillLimits, backfill_batch

        # 1. Share durable cursor, quotas and lock with manual backfill batches.
        crawl = (
            await backfill_batch(limits=BackfillLimits(daily=None))
            if with_crawl
            else {"status": "disabled", "saved": 0}
        )
        summary["crawl"] = crawl
        summary["crawled"] = crawl["saved"]
        log.info("daily.crawled", **crawl)
        # A paused/disconnected listing must not discard already saved author text.

        # 2. Extract/normalize/score every pending post from step 1.
        #    Bound extraction too; failed old work is retried explicitly via resume.
        resumed = await resume_failed(
            statuses=("pending",), limit=30, stored_only=crawl["status"] != "complete"
        )
        summary["processing_attempted"] = len(resumed)
        summary["extracted"] = sum(bool(row.get("completed")) for row in resumed)
        summary["processing_failed"] = sum(bool(row.get("errors")) for row in resumed)
        log.info("daily.extracted", n=len(resumed))

        from ..api.cache import invalidate_read_caches
        from ..embedding.backfill import backfill_embeddings

        indexed = await backfill_embeddings()
        summary["indexed"] = indexed.embedded
        await invalidate_read_caches()

        # 3. Recompute summaries for pairs whose question set changed (aggregate_one skips no-ops).
        aggregated = await aggregate_all()
        summary["aggregated"] = len(aggregated)
        log.info("daily.aggregated", n=len(aggregated))

        # 4. AI answers for questions whose answer_ai_version is behind.
        if with_answers:
            from ..answerer import run_answers

            outcome = await run_answers()
            summary["answered"] = getattr(outcome, "generated", None)
            log.info("daily.answered", outcome=str(outcome))

        await invalidate_read_caches()
        log.info("daily.done", **summary)
        return summary
    finally:
        heartbeat.cancel()
        try:
            with suppress(asyncio.CancelledError):
                await heartbeat
        finally:
            try:
                await r.eval(
                    """
                if redis.call('GET',KEYS[1]) == ARGV[1] then
                    return redis.call('DEL',KEYS[1])
                end
                return 0
            """,
                    1,
                    _LOCK_KEY,
                    owner,
                )
            finally:
                await r.aclose()
