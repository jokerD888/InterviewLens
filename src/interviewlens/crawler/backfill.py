"""Bounded, restartable harvesting. Does not invoke extraction or AI generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .backfill_store import BackfillStore
from .playwright_runner import NowcoderFetcher
from .rate_limit import AsyncRateLimiter
from .response_guard import CrawlStoppedError
from .tab_crawler import extract_post, fetch_detail, fetch_tab_page


@dataclass(frozen=True)
class BackfillLimits:
    batch: int = 30
    daily: int = 100
    pages: int = 3
    cooldown: int = 3600

    def __post_init__(self):
        if not 1 <= self.batch <= 30 or not 1 <= self.daily <= 100:
            raise ValueError("batch must be 1..30; daily must be 1..100")
        if not 3 <= self.pages <= 5 or self.cooldown < 3600:
            raise ValueError("pages must be 3..5; cooldown must be at least 3600 seconds")


def make_fetcher():
    # Shared by discovery and details. First request also receives jitter.
    # 8-second minimum plus 1..7 seconds jitter, avoiding bursts between endpoints.
    return NowcoderFetcher(limiter=AsyncRateLimiter(rate_per_sec=1 / 8, jitter=(1, 7)))


async def backfill_batch(
    *,
    since: datetime | None = None,
    limits: BackfillLimits | None = None,
    resume_paused: bool = False,
    retry_failed: bool = False,
    store=None,
    fetcher_factory=None,
) -> dict:
    limits = limits or BackfillLimits()
    if since is not None and (since.tzinfo is None or since.utcoffset() is None):
        raise ValueError("since must include timezone")
    store = store if store is not None else BackfillStore()
    fetcher_factory = fetcher_factory or make_fetcher
    result = {"status": "complete", "discovered_pages": 0, "attempted": 0, "saved": 0}
    async with store.locked() as acquired:
        if not acquired:
            return {**result, "status": "locked"}
        status, _ = await store.begin_batch(since, limits.cooldown, resume_paused)
        if status != "ready":
            return {**result, "status": status, **await store.snapshot()}
        if retry_failed:
            await store.retry_failed()
        await store.mark_existing()
        state = await store.snapshot()
        if state["today_attempts"] >= limits.daily:
            return {**result, "status": "daily_limit", **state}
        current_url = None
        try:
            async with fetcher_factory() as fetcher:
                pending = await store.pending(limits.batch)
                if not pending:
                    progress = await store.start_scan()
                    # Revisit two pages to tolerate modest insertions/reordering. Always
                    # advance at least one page (pages>=3). Existing URLs never end a scan.
                    first = max(1, progress["next_page"] - 2)
                    for page in range(first, first + limits.pages):
                        records = await fetch_tab_page(page, fetcher)
                        await store.enqueue_page(records, page, progress["since_at"])
                        result["discovered_pages"] += 1
                        if not records:
                            break
                    pending = await store.pending(limits.batch)
                for item in pending:
                    current_url = item["url"]
                    if not await store.reserve_attempt(current_url, limits.daily):
                        result["status"] = "daily_limit"
                        break
                    result["attempted"] += 1
                    content, title = await fetch_detail(fetcher, current_url)
                    if not content.strip():
                        raise CrawlStoppedError("empty_detail", retryable=True)
                    post = extract_post(item["record"], content, title)
                    result["saved"] += int(await store.finish(current_url, post))
                    current_url = None
        except CrawlStoppedError as exc:
            await store.fail(current_url, exc.reason, pause=not exc.retryable)
            result.update(status="stopped", reason=exc.reason)
        # Cancellation and unexpected errors propagate: already committed queue/cursor
        # and attempt reservations survive; lock and browser are released by contexts.
        return {**result, **await store.snapshot()}
