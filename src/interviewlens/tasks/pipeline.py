"""Pipeline tasks. Each task is sync at the Celery boundary but bridges into
asyncio internally so we can reuse the rest of the codebase as-is.

Tasks:
- crawl_url: run the full LangGraph pipeline for one URL
- enqueue_listing: discover URLs and fan out crawl_url tasks
- aggregate_pair: run Aggregator for one (company, position, period)

Dead-letter:
- Failed tasks (after retries) are pushed to a Redis list ``il:dlq:{task}``
  so an operator can inspect and re-enqueue with ``il dlq`` later.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import redis

from ..config import settings
from ..logging import log
from .celery_app import celery_app


def _run_async(coro: Any) -> Any:
    """Run an async coroutine inside a Celery sync task safely."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Nested loop — schedule via threadsafe future. Rare in workers.
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            return future.result()
    except RuntimeError:
        pass
    return asyncio.run(coro)


def _dlq_push(task_name: str, payload: dict) -> None:
    try:
        r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        r.rpush(f"il:dlq:{task_name}", json.dumps(payload, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        log.warning("dlq.push_failed", task=task_name, err=str(exc))


# ----------------------------------------------------------------- crawl_url

@celery_app.task(
    name="il.crawl_url",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=5,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=3,
    acks_late=True,
)
def crawl_url(self, url: str, *, skip_normalize: bool = False) -> dict:
    """Run the LangGraph pipeline for one URL."""
    from ..agent import run_pipeline
    from ..crawler import NowcoderFetcher

    async def _go() -> dict:
        fetcher = NowcoderFetcher()
        await fetcher.start()
        try:
            final = await run_pipeline(
                url,
                fetcher=fetcher,
                use_cache=True,
                skip_normalize=skip_normalize,
            )
        finally:
            await fetcher.stop()
        return {
            "url": url,
            "post_id": final.get("post_id"),
            "skip_reason": final.get("skip_reason"),
            "errors": final.get("errors"),
            "quality_score": final.get("quality_score"),
            "company_ids": final.get("company_ids"),
            "position_ids": final.get("position_ids"),
        }

    try:
        return _run_async(_go())
    except Exception as exc:
        if self.request.retries >= (self.max_retries or 0):
            _dlq_push(
                "il.crawl_url",
                {"url": url, "error": f"{type(exc).__name__}: {exc}", "skip_normalize": skip_normalize},
            )
        raise


# --------------------------------------------------------------- enqueue_listing

@celery_app.task(name="il.enqueue_listing")
def enqueue_listing(pages: int = 1, source: str = "experience", skip_normalize: bool = False) -> dict:
    """Discover URLs from listing pages and dispatch ``crawl_url`` per item."""
    from ..crawler import NowcoderFetcher, discover_from_listing

    async def _go() -> list[str]:
        fetcher = NowcoderFetcher()
        await fetcher.start()
        try:
            return await discover_from_listing(source=source, pages=pages, fetcher=fetcher)
        finally:
            await fetcher.stop()

    urls = _run_async(_go())
    log.info("listing.discovered", n=len(urls), pages=pages)

    enqueued = 0
    for url in urls:
        crawl_url.delay(url, skip_normalize=skip_normalize)
        enqueued += 1
    return {"discovered": len(urls), "enqueued": enqueued}


# ------------------------------------------------------------- aggregate_pair

@celery_app.task(
    name="il.aggregate_pair",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=10,
    retry_backoff_max=300,
    max_retries=2,
)
def aggregate_pair(self, company: str, position: str, period: str | None = None) -> dict:
    from ..aggregator import aggregate_one

    async def _go() -> dict:
        outcome = await aggregate_one(
            company=company, position=position, period=period
        )
        return {
            "company": company,
            "position": position,
            "period": outcome.period,
            "samples": outcome.sample_count,
            "skip_reason": outcome.skip_reason,
            "written": outcome.written,
        }

    try:
        return _run_async(_go())
    except Exception as exc:
        if self.request.retries >= (self.max_retries or 0):
            _dlq_push(
                "il.aggregate_pair",
                {"company": company, "position": position, "period": period, "error": str(exc)},
            )
        raise


# ----------------------------------------------------------------- DLQ ops

def dlq_list(task_name: str = "il.crawl_url", limit: int = 50) -> list[dict]:
    r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    raw = r.lrange(f"il:dlq:{task_name}", 0, limit - 1) or []
    return [json.loads(x) for x in raw]


def dlq_drain(task_name: str = "il.crawl_url", limit: int = 50) -> int:
    """Pop up to ``limit`` items off the DLQ and re-enqueue them as fresh tasks."""
    r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    drained = 0
    for _ in range(limit):
        raw = r.lpop(f"il:dlq:{task_name}")
        if raw is None:
            break
        payload = json.loads(raw)
        if task_name == "il.crawl_url":
            crawl_url.delay(payload.get("url"), skip_normalize=payload.get("skip_normalize", False))
        elif task_name == "il.aggregate_pair":
            aggregate_pair.delay(
                payload.get("company"),
                payload.get("position"),
                payload.get("period"),
            )
        drained += 1
    return drained


def dlq_clear(task_name: str) -> int:
    r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return int(r.delete(f"il:dlq:{task_name}"))
