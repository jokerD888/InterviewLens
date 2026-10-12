"""Bounded, restartable harvesting. Does not invoke extraction or AI generation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from .backfill_store import BackfillStore
from .metadata_api import fetch_job_page, fetch_publication
from .playwright_runner import NowcoderFetcher
from .rate_limit import AsyncRateLimiter
from .response_guard import CrawlStoppedError
from .tab_crawler import extract_post, fetch_detail, fetch_tab_page


@dataclass(frozen=True)
class BackfillLimits:
    batch: int = 30
    daily: int | None = 100
    pages: int = 3
    cooldown: int = 3600
    continuous: bool = False

    def __post_init__(self):
        if not 1 <= self.batch <= 30 or (self.daily is not None and not 1 <= self.daily <= 100):
            raise ValueError("batch must be 1..30; daily must be 1..100 or None (unlimited)")
        if not 3 <= self.pages <= 5:
            raise ValueError("pages must be 3..5")
        if self.continuous:
            if self.cooldown != 0:
                raise ValueError("continuous batches must use cooldown=0")
        elif self.cooldown < 3600:
            raise ValueError("cooldown must be at least 3600 seconds outside continuous mode")


def make_fetcher():
    # Shared by discovery and details. First request also receives jitter.
    # 10-second minimum plus 1..10 seconds jitter, avoiding bursts between endpoints.
    return NowcoderFetcher(limiter=AsyncRateLimiter(rate_per_sec=1 / 10, jitter=(1, 10)))


async def backfill_batch(
    *,
    since: datetime | None = None,
    limits: BackfillLimits | None = None,
    resume_paused: bool = False,
    retry_failed: bool = False,
    listing: str = "tab",
    job_id: int = -1,
    job_level: int = 1,
    pending_only: bool = False,
    store=None,
    fetcher_factory=None,
    progress: Callable[[str, dict], None] | None = None,
) -> dict:
    if listing not in ("tab", "job") or job_level not in (1, 2, 3):
        raise ValueError("listing must be tab/job; job_level must be 1..3")
    limits = limits or BackfillLimits()
    if since is not None and (since.tzinfo is None or since.utcoffset() is None):
        raise ValueError("since must include timezone")
    store = store if store is not None else (BackfillStore() if listing == "tab" else
        BackfillStore(source=f"nowcoder-job-v2-{job_id}-{job_level}"))
    fetcher_factory = fetcher_factory or make_fetcher
    result = {"status": "complete", "discovered_pages": 0, "attempted": 0, "saved": 0}
    def emit(event, **fields):
        if progress is not None:
            progress(event, fields)

    async with store.locked() as acquired:
        if not acquired:
            return {**result, "status": "locked"}
        if pending_only:
            status, _ = await store.begin_batch(since, limits.cooldown, False, drain_pending=True)
        else:
            status, _ = await store.begin_batch(since, limits.cooldown, resume_paused)
        if status != "ready":
            return {**result, "status": status, **await store.snapshot()}
        if retry_failed:
            await store.retry_failed()
        await store.mark_existing()
        state = await store.snapshot()
        if limits.daily is not None and state["today_attempts"] >= limits.daily:
            return {**result, "status": "daily_limit", **state}
        if pending_only and not state["pending"]:
            return {**result, "status": "drained", **state}
        current_url = None
        emit("batch_start", pending=state["pending"], today_attempts=state["today_attempts"])
        try:
            async with fetcher_factory() as fetcher:
                pending = await store.pending(limits.batch)
                if not pending and not pending_only:
                    cursor = await store.start_scan()
                    # Revisit two pages to tolerate modest insertions/reordering. Always
                    # advance at least one page (pages>=3). Existing URLs never end a scan.
                    first = max(1, cursor["next_page"] - 2)
                    for page in range(first, first + limits.pages):
                        emit("page_start", page=page)
                        records = (await fetch_tab_page(page, fetcher) if listing == "tab" else
                            await fetch_job_page(page, fetcher, job_id=job_id, level=job_level))
                        await store.enqueue_page(records, page, cursor["since_at"])
                        result["discovered_pages"] += 1
                        emit("page_done", page=page, records=len(records))
                        if not records:
                            break
                    pending = await store.pending(limits.batch)
                for index, item in enumerate(pending, 1):
                    if result["attempted"] >= limits.batch:
                        result["status"] = "batch_limit"
                        break
                    current_url = item["url"]
                    if not await store.reserve_attempt(current_url, limits.daily):
                        result["status"] = "daily_limit"
                        break
                    result["attempted"] += 1
                    emit("detail_start", index=index, limit=len(pending), url=current_url)
                    content, title = await fetch_detail(fetcher, current_url)
                    if not content.strip():
                        raise CrawlStoppedError("empty_detail", retryable=True)
                    post = extract_post(item["record"], content, title)
                    if not post["created_at_ms"]:
                        # A metadata fallback is another detail request, and
                        # consumes the same daily request budget before navigation.
                        if result["attempted"] >= limits.batch:
                            result["status"] = "batch_limit"
                        elif await store.reserve_attempt(current_url, limits.daily):
                            result["attempted"] += 1
                            post["created_at_ms"] = await fetch_publication(current_url, fetcher)
                        else:
                            result["status"] = "daily_limit"
                    result["saved"] += int(await store.finish(current_url, post))
                    emit("detail_done", saved=result["saved"], title=post["title"])
                    current_url = None
                    if result["status"] in ("daily_limit", "batch_limit"):
                        break
        except CrawlStoppedError as exc:
            await store.fail(current_url, exc.reason, pause=not exc.retryable)
            result.update(status="stopped", reason=exc.reason)
            emit("stopped", reason=exc.reason)
        # Cancellation and unexpected errors propagate: already committed queue/cursor
        # and attempt reservations survive; lock and browser are released by contexts.
        if pending_only and result["status"] in ("complete", "batch_limit"):
            result["status"] = "drained"
        return {**result, **await store.snapshot()}
