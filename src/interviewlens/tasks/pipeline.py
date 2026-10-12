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
import concurrent.futures
import json
import threading
from typing import Any

import redis
from celery.signals import worker_process_init, worker_process_shutdown

from ..config import settings
from ..logging import log
from .celery_app import celery_app


class BackgroundLoopWorker:
    """Maintains a persistent, dedicated event loop thread inside the Celery worker process.

    This prevents:
    1. 'Event loop is closed' errors caused by asyncio.run() destroying loops while
       global AsyncEngine connection pools retain pooled connections bound to old loops.
    2. Same-thread deadlocks when calling run_coroutine_threadsafe.
    """

    _instance: BackgroundLoopWorker | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="CeleryAsyncWorkerLoop",
        )
        self.thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    @classmethod
    def get_loop(cls) -> asyncio.AbstractEventLoop:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance.loop

    @classmethod
    def run_coroutine(cls, coro: Any, timeout: float | None = 220.0) -> Any:
        loop = cls.get_loop()
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if current_loop is loop:
            coro.close()
            raise RuntimeError("Cannot invoke _run_async from inside the worker event loop thread")

        started = threading.Event()
        cleaned = threading.Event()

        async def supervised():
            started.set()
            try:
                return await coro
            finally:
                cleaned.set()

        wrapper = supervised()
        try:
            future = asyncio.run_coroutine_threadsafe(wrapper, loop)
        except BaseException:
            wrapper.close()
            coro.close()
            raise
        try:
            return future.result(timeout=timeout)
        except BaseException as exc:
            # Includes Celery SoftTimeLimitExceeded and caller interruption.
            # A cancelled concurrent future alone does not mean async finally
            # blocks (transaction rollback, lease release) have finished.
            future.cancel()
            if started.is_set():
                if not cleaned.wait(timeout=10):
                    log.error("worker.cancel_cleanup_timeout")
            else:
                # Cancellation may precede the wrapper's first step.
                loop.call_soon_threadsafe(lambda: coro.close() if not started.is_set() else None)
            if isinstance(exc, (TimeoutError, concurrent.futures.TimeoutError)):
                raise TimeoutError(
                    f"Task execution timed out after {timeout} seconds and was cancelled."
                ) from exc
            raise


@worker_process_init.connect
def _reset_worker_loop_and_db(**kwargs: Any) -> None:
    """Reset worker state after Celery prefork child process initialization."""
    from ..db.session import reset_engine

    reset_engine()
    BackgroundLoopWorker._instance = None
    BackgroundLoopWorker._lock = threading.Lock()
    from ..lifecycle import reset_after_fork

    reset_after_fork()


@worker_process_shutdown.connect
def _close_worker_clients(**kwargs: Any) -> None:
    instance = BackgroundLoopWorker._instance
    if instance is None:
        return
    from ..lifecycle import close_clients

    try:
        BackgroundLoopWorker.run_coroutine(close_clients(), timeout=10)
    finally:
        instance.loop.call_soon_threadsafe(instance.loop.stop)
        instance.thread.join(timeout=2)
        if not instance.thread.is_alive():
            instance.loop.close()
            BackgroundLoopWorker._instance = None


def _run_async(coro: Any, timeout: float | None = 220.0) -> Any:
    """Run an async coroutine safely inside a persistent background event loop."""
    return BackgroundLoopWorker.run_coroutine(coro, timeout=timeout)


def _dlq_push(task_name: str, payload: dict) -> None:
    # Layer B: only Redis/JSON failures degrade; logic bugs bubble.
    try:
        r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        r.rpush(f"il:dlq:{task_name}", json.dumps(payload, ensure_ascii=False))
    except (redis.RedisError, json.JSONDecodeError, TypeError):
        log.warning("dlq.push_failed", task=task_name, exc_info=True)


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
def crawl_url(self, url: str) -> dict:
    """Run the LangGraph pipeline for one URL."""
    from ..agent import run_pipeline

    async def _go() -> dict:
        final = await run_pipeline(url, use_cache=True)
        if final.get("errors"):
            raise RuntimeError("Post processing failed: " + "; ".join(final["errors"]))
        return {
            "url": url,
            "post_id": final.get("post_id"),
            "skip_reason": final.get("skip_reason"),
            "errors": final.get("errors"),
            "content_score": final.get("content_score"),
            "company_ids": final.get("company_ids"),
            "position_ids": final.get("position_ids"),
        }

    try:
        return _run_async(_go())
    except Exception as exc:  # noqa: BLE001  # ponytail: Celery task boundary — catch-all + DLQ + re-raise for retry
        log.error("crawl_url.failed", url=url, exc_info=True)
        if self.request.retries >= (self.max_retries or 0):
            _dlq_push(
                "il.crawl_url",
                {"url": url, "error": f"{type(exc).__name__}: {exc}"},
            )
        raise


# --------------------------------------------------------------- enqueue_listing


@celery_app.task(name="il.enqueue_listing")
def enqueue_listing(pages: int = 1, source: str = "experience") -> dict:
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
        crawl_url.delay(url)
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
        outcome = await aggregate_one(company=company, position=position, period=period)
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
    except Exception as exc:  # noqa: BLE001  # ponytail: Celery task boundary — catch-all + DLQ + re-raise for retry
        log.error("aggregate_pair.failed", company=company, position=position, exc_info=True)
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
    if task_name not in {"il.crawl_url", "il.aggregate_pair"}:
        raise ValueError(f"Unknown replay task: {task_name}")
    r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    key = f"il:dlq:{task_name}"
    processing_key = key + ":processing"
    drained = 0
    for _ in range(limit):
        # LMOVE is atomic: crashes retain the item in processing for inspection.
        raw = r.lmove(key, processing_key, "LEFT", "RIGHT")
        if raw is None:
            break
        try:
            payload = json.loads(raw)
            if task_name == "il.crawl_url":
                crawl_url.delay(payload["url"])
            else:
                aggregate_pair.delay(payload["company"], payload["position"], payload.get("period"))
        except BaseException:
            # Restore to the front atomically; leave processing intact on Redis failure.
            r.eval(
                """
                if redis.call('LREM', KEYS[1], 1, ARGV[1]) == 1 then
                    redis.call('LPUSH', KEYS[2], ARGV[1])
                end
            """,
                2,
                processing_key,
                key,
                raw,
            )
            raise
        r.lrem(processing_key, 1, raw)
        drained += 1
    return drained


def dlq_clear(task_name: str) -> int:
    r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return int(r.delete(f"il:dlq:{task_name}"))


def dlq_restore(task_name: str, limit: int = 50) -> int:
    """Restore crash leftovers after replay publishers have been stopped."""
    if task_name not in {"il.crawl_url", "il.aggregate_pair"}:
        raise ValueError(f"Unknown replay task: {task_name}")
    with redis.Redis.from_url(settings.redis_url, decode_responses=True) as r:
        key = f"il:dlq:{task_name}"
        restored = 0
        for _ in range(limit):
            if r.lmove(key + ":processing", key, "LEFT", "RIGHT") is None:
                break
            restored += 1
        return restored
