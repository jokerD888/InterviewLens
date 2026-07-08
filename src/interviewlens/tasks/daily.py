"""Daily update orchestration — serial, run once a day via OS scheduler.

Chains the existing (idempotent) pipeline steps back to back:

    crawl (incremental) → extract/normalize/score → aggregate → answer

Nothing here is new logic; it just sequences functions that already exist.
Read-path caches are TTL-driven (<=1h), so no cache invalidation is needed —
users see new content on their next refresh once these steps have written to
the DB.
"""
from __future__ import annotations

import redis

from ..config import settings
from ..logging import log

_LOCK_KEY = "il:daily:lock"
_LOCK_TTL = 60 * 60 * 6  # 6h — a daily run finishing later than this is pathological


async def daily_update(*, with_answers: bool = True) -> dict:
    """Run the full daily update chain once. Reentrancy-guarded via Redis.

    Returns a summary dict of per-step counts for logging / `il metrics`.
    """
    r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    # ponytail: single-node reentrancy lock; NX+TTL is enough for one cron box.
    if not r.set(_LOCK_KEY, "1", nx=True, ex=_LOCK_TTL):
        log.warning("daily.locked", msg="another daily_update is running; skipping")
        return {"skipped": "locked"}

    summary: dict = {}
    try:
        from ..aggregator import aggregate_all
        from ..agent.recovery import resume_failed
        from ..crawler.tab_crawler import crawl_tab

        # 1. Incremental crawl — stop once we catch up to the DB high-water mark.
        crawled = await crawl_tab(pages=0, save_to_db=True, stop_when_seen=True)
        summary["crawled"] = len(crawled)
        log.info("daily.crawled", n=len(crawled))

        # 2. Extract/normalize/score every pending post from step 1.
        #    limit is generous — a day's new posts should fit comfortably.
        resumed = await resume_failed(statuses=("pending", "failed"), limit=500)
        summary["extracted"] = len(resumed)
        log.info("daily.extracted", n=len(resumed))

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

        log.info("daily.done", **summary)
        return summary
    finally:
        r.delete(_LOCK_KEY)
