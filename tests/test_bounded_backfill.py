"""Safety and restart behavior without real website or model calls."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from interviewlens.crawler import backfill, tab_crawler
from interviewlens.crawler.backfill import BackfillLimits
from interviewlens.crawler.response_guard import CrawlStoppedError, check_page, parse_records


@pytest.mark.parametrize(
    "kwargs",
    [
        {"batch": 31},
        {"batch": 0},
        {"daily": 101},
        {"daily": 0},
        {"pages": 2},
        {"pages": 6},
        {"cooldown": 3599},
    ],
)
def test_limits_reject_unsafe_configuration(kwargs):
    with pytest.raises(ValueError):
        BackfillLimits(**kwargs)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"success": False, "data": {"records": []}},
        {"code": 401, "data": {"records": []}},
        {"data": {"records": "wrong"}},
        {"data": {"records": [None]}},
    ],
)
def test_rejections_are_not_empty_feed(payload):
    with pytest.raises(CrawlStoppedError):
        parse_records(payload)


def test_valid_empty_page_and_full_interview_content():
    assert parse_records({"success": True, "code": 0, "data": {"records": []}}) == []
    check_page("https://www.nowcoder.com/discuss/1", "安全工程师面经", "如何设计验证码服务")
    with pytest.raises(CrawlStoppedError):
        check_page("https://www.nowcoder.com/login", "", "")
    with pytest.raises(CrawlStoppedError):
        check_page("https://www.nowcoder.com/discuss/1", "", "访问过于频繁")


@pytest.mark.parametrize("detail", [False, True])
async def test_http_429_stops_and_closes_page_once(detail):
    page = MagicMock()
    page.goto = AsyncMock(return_value=MagicMock(status=429))
    page.close = AsyncMock()
    fetcher = MagicMock()
    fetcher._context.new_page = AsyncMock(return_value=page)
    fetcher._limiter.acquire = AsyncMock()
    with pytest.raises(CrawlStoppedError, match="http_429"):
        if detail:
            await tab_crawler.fetch_detail(fetcher, "https://www.nowcoder.com/discuss/1")
        else:
            await tab_crawler.fetch_tab_page(1, fetcher)
    fetcher._limiter.acquire.assert_awaited_once()
    page.close.assert_awaited_once()


def fake_store(*, status="ready", attempts=0, pending=None):
    store = MagicMock()

    @asynccontextmanager
    async def locked():
        yield True

    store.locked = locked
    store.begin_batch = AsyncMock(return_value=(status, {}))
    store.mark_existing = AsyncMock()
    store.retry_failed = AsyncMock()
    store.snapshot = AsyncMock(return_value={"today_attempts": attempts, "pending": 0})
    store.pending = AsyncMock(return_value=pending or [])
    store.start_scan = AsyncMock(
        return_value={
            "next_page": 9,
            "since_at": datetime(2026, 7, 8, tzinfo=UTC),
        }
    )
    store.enqueue_page = AsyncMock()
    store.reserve_attempt = AsyncMock(return_value=True)
    store.finish = AsyncMock(return_value=True)
    store.fail = AsyncMock()
    return store


@pytest.mark.parametrize("status,attempts", [("cooldown", 0), ("paused", 0), ("ready", 100)])
async def test_no_browser_requests_during_cooldown_pause_or_daily_limit(status, attempts):
    factory = MagicMock()
    report = await backfill.backfill_batch(
        store=fake_store(status=status, attempts=attempts),
        fetcher_factory=factory,
    )
    assert report["status"] == ("daily_limit" if status == "ready" else status)
    factory.assert_not_called()


@asynccontextmanager
async def fake_fetcher():
    yield object()


async def test_scan_advances_past_already_seen_pages(monkeypatch):
    store = fake_store()
    fetch = AsyncMock(return_value=[{"contentId": "already-in-db"}])
    monkeypatch.setattr(backfill, "fetch_tab_page", fetch)
    report = await backfill.backfill_batch(store=store, fetcher_factory=fake_fetcher)
    assert [call.args[0] for call in fetch.await_args_list] == [7, 8, 9]
    assert report["discovered_pages"] == 3
    assert store.enqueue_page.await_count == 3


@pytest.mark.parametrize("retryable", [False, True])
async def test_detail_error_charges_before_request_and_stops_batch(monkeypatch, retryable):
    items = [{"url": f"https://www.nowcoder.com/discuss/{i}", "record": {}} for i in range(2)]
    store = fake_store(pending=items)
    calls = []

    async def reserve(*_args):
        calls.append("reserve")
        return True

    async def fail_fetch(*_args):
        calls.append("fetch")
        raise CrawlStoppedError("blocked", retryable=retryable)

    store.reserve_attempt.side_effect = reserve
    monkeypatch.setattr(backfill, "fetch_detail", fail_fetch)
    report = await backfill.backfill_batch(store=store, fetcher_factory=fake_fetcher)
    assert calls == ["reserve", "fetch"]
    assert report["attempted"] == 1
    assert report["status"] == "stopped"
    store.fail.assert_awaited_once_with(items[0]["url"], "blocked", pause=not retryable)
    store.finish.assert_not_awaited()


async def test_cancellation_propagates_and_releases_browser_and_lock(monkeypatch):
    events = []
    store = fake_store(pending=[{"url": "https://www.nowcoder.com/discuss/1", "record": {}}])

    @asynccontextmanager
    async def locked():
        try:
            yield True
        finally:
            events.append("unlock")

    @asynccontextmanager
    async def browser():
        try:
            yield object()
        finally:
            events.append("close")

    store.locked = locked
    monkeypatch.setattr(backfill, "fetch_detail", AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await backfill.backfill_batch(store=store, fetcher_factory=browser)
    assert events == ["close", "unlock"]
    store.reserve_attempt.assert_awaited_once()
    store.finish.assert_not_awaited()


async def test_daily_stop_skips_model_pipeline_and_releases_redis_lock(monkeypatch):
    from interviewlens.agent import recovery
    from interviewlens.tasks import daily

    redis = MagicMock()
    redis.set.return_value = True
    monkeypatch.setattr(daily.redis.Redis, "from_url", lambda *_args, **_kwargs: redis)
    monkeypatch.setattr(
        backfill, "backfill_batch", AsyncMock(return_value={"status": "stopped", "saved": 0})
    )
    resume = AsyncMock()
    monkeypatch.setattr(recovery, "resume_failed", resume)
    report = await daily.daily_update(with_answers=False)
    assert report["crawl"]["status"] == "stopped"
    resume.assert_not_awaited()
    redis.delete.assert_called_once()


async def test_daily_success_limits_extraction_to_pending_30(monkeypatch):
    from interviewlens import aggregator
    from interviewlens.agent import recovery
    from interviewlens.tasks import daily

    redis = MagicMock()
    redis.set.return_value = True
    monkeypatch.setattr(daily.redis.Redis, "from_url", lambda *_args, **_kwargs: redis)
    monkeypatch.setattr(
        backfill, "backfill_batch", AsyncMock(return_value={"status": "complete", "saved": 2})
    )
    resume = AsyncMock(return_value=[])
    monkeypatch.setattr(recovery, "resume_failed", resume)
    monkeypatch.setattr(aggregator, "aggregate_all", AsyncMock(return_value=[]))
    await daily.daily_update(with_answers=False)
    resume.assert_awaited_once_with(statuses=("pending",), limit=30)


async def test_pacer_spaces_requests_and_adds_jitter(monkeypatch):
    from interviewlens.crawler import rate_limit

    clock = [100.0]
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(rate_limit.asyncio, "sleep", sleep)
    monkeypatch.setattr(rate_limit.random, "uniform", lambda *_args: 3.0)
    limiter = backfill.make_fetcher()._limiter
    await limiter.acquire()
    first = clock[0]
    await limiter.acquire()
    assert clock[0] - first == 11
    assert sleeps == [3.0, 8.0, 3.0]


def test_cli_rejects_unbounded_export_and_invalid_dates():
    from typer.testing import CliRunner

    from interviewlens.cli import app

    runner = CliRunner()
    for arguments in (
        ["tab-crawl", "--pages", "0"],
        ["tab-crawl", "--save-db"],
        ["backfill-crawl", "--batch", "31"],
        ["backfill-crawl", "--since", "bad-date"],
        ["batch", "--pages", "0"],
    ):
        assert runner.invoke(app, arguments).exit_code != 0
