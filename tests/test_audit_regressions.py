"""Fault-injection regression tests for the 2026-10-13 audit."""

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest
from billiard.exceptions import SoftTimeLimitExceeded
from fastapi.testclient import TestClient

from interviewlens.aggregator.aggregator import _cluster_questions
from interviewlens.api.app import app
from interviewlens.config import settings
from interviewlens.crawler.urls import allowed_request_url, validate_post_url


@pytest.mark.parametrize(
    "url",
    [
        "https://nowcoder.com.attacker.invalid/discuss/123",
        "http://www.nowcoder.com/discuss/123",
        "https://127.0.0.1/discuss/123",
        "https://www.nowcoder.com:444/discuss/123",
        "https://user:secret@www.nowcoder.com/discuss/123",
        "https://www.nowcoder.com/login",
    ],
)
def test_untrusted_post_urls_rejected(url):
    with pytest.raises(ValueError):
        validate_post_url(url)


def test_post_boundary_and_subresources():
    validate_post_url("https://www.nowcoder.com/discuss/123")
    assert allowed_request_url("https://gw-c.nowcoder.com/api/sparta/detail")
    assert not allowed_request_url("https://169.254.169.254/latest/meta-data")


def test_admin_and_bridge_require_credentials_before_side_effects(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_token", "audit-test-" + "x" * 40)
    enqueue = MagicMock()
    monkeypatch.setattr("interviewlens.tasks.crawl_url.delay", enqueue)
    with TestClient(app) as client:
        assert (
            client.post(
                "/admin/ingest", json={"url": "https://www.nowcoder.com/discuss/123"}
            ).status_code
            == 401
        )
        assert (
            client.post("/bridge/generate-answers", json={"question_ids": [1]}).status_code == 401
        )
        assert client.delete("/admin/dlq/il.crawl_url").status_code == 401
        assert client.post("/api/bridge/export", json={"cards": []}).status_code == 401
        assert (
            client.post(
                "/admin/ingest",
                headers={"Authorization": "Bearer " + settings.admin_api_token},
                json={"url": "https://nowcoder.com.attacker.invalid/discuss/123"},
            ).status_code
            == 422
        )
    enqueue.assert_not_called()


def test_anchored_clusters_prevent_transitive_drift():
    vectors = {
        i + 1: np.array([np.cos(a), np.sin(a)], dtype=np.float32)
        for i, a in enumerate(np.deg2rad([0, 18, 36]))
    }
    questions = [{"id": i, "post_id": i, "content": str(i), "content_score": 50} for i in vectors]
    forward = _cluster_questions(questions, vectors, threshold=0.92, block_size=1)
    backward = _cluster_questions(questions[::-1], vectors, threshold=0.92, block_size=2)
    assert forward == backward
    assert sorted(c["freq"] for c in forward) == [1, 2]
    for cluster in forward:
        assert all(vectors[cluster["id"]] @ vectors[i] >= 0.92 for i in cluster["member_ids"])


def test_soft_timeout_waits_for_async_cleanup(monkeypatch):
    from interviewlens.tasks.pipeline import BackgroundLoopWorker

    entered, cleanup = threading.Event(), threading.Event()
    original = asyncio.run_coroutine_threadsafe

    async def work():
        entered.set()
        try:
            await asyncio.sleep(60)
        finally:
            await asyncio.sleep(0.02)
            cleanup.set()

    def schedule(coro, loop):
        future = original(coro, loop)

        class SoftFuture:
            def result(self, timeout):
                assert entered.wait(2)
                raise SoftTimeLimitExceeded()

            def cancel(self):
                return future.cancel()

        return SoftFuture()

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", schedule)
    with pytest.raises(SoftTimeLimitExceeded):
        BackgroundLoopWorker.run_coroutine(work())
    assert cleanup.is_set()


async def test_normalization_failure_does_not_replace_old_links(monkeypatch):
    from interviewlens.agent.nodes import normalizer

    monkeypatch.setattr(
        normalizer, "resolve_entity", AsyncMock(side_effect=RuntimeError("provider unavailable"))
    )
    write = AsyncMock()
    monkeypatch.setattr(normalizer, "save_post_companies", write)
    with pytest.raises(RuntimeError):
        await normalizer.run(
            {"post_id": 1, "extracted": {"companies": ["A"], "positions": ["后端"]}}
        )
    write.assert_not_awaited()


def test_dlq_publisher_failure_retains_item(monkeypatch):
    from interviewlens.tasks import pipeline

    redis = MagicMock()
    redis.lmove.return_value = '{"url":"https://www.nowcoder.com/discuss/123"}'
    monkeypatch.setattr(pipeline.redis.Redis, "from_url", lambda *a, **kw: redis)
    monkeypatch.setattr(
        pipeline.crawl_url, "delay", MagicMock(side_effect=RuntimeError("broker down"))
    )
    with pytest.raises(RuntimeError):
        pipeline.dlq_drain()
    redis.eval.assert_called_once()
    redis.lrem.assert_not_called()
    redis.reset_mock()
    with pytest.raises(ValueError):
        pipeline.dlq_drain("unknown.task")
    redis.lmove.assert_not_called()


async def test_budget_exhaustion_never_calls_provider(monkeypatch):
    from interviewlens.llm import budget

    redis = MagicMock()
    redis.eval = AsyncMock(return_value=-2)
    monkeypatch.setattr(budget, "get_redis", lambda: redis)
    provider = AsyncMock()
    with pytest.raises(budget.LLMLimitError):
        await budget.guarded_create(provider, messages=[], max_tokens=100)
    provider.assert_not_awaited()


async def test_budget_storage_failure_fails_closed(monkeypatch):
    from redis.exceptions import ConnectionError
    from interviewlens.llm import budget
    redis = MagicMock()
    redis.eval = AsyncMock(side_effect=ConnectionError("offline"))
    monkeypatch.setattr(budget, "get_redis", lambda: redis)
    provider=AsyncMock()
    with pytest.raises(budget.LLMLimitError,match="unavailable"):
        await budget.guarded_create(provider,messages=[])
    provider.assert_not_awaited()


async def test_cache_invalidation_does_not_allow_stale_repopulation(monkeypatch):
    from interviewlens.api import cache
    class Redis:
        def __init__(self): self.values={}
        async def get(self,key): return self.values.get(key)
        async def set(self,key,value,**kw): self.values[key]=value
        async def incr(self,key): self.values[key]=int(self.values.get(key) or 0)+1
    redis=Redis()
    monkeypatch.setattr(cache,"get_redis",lambda:redis)
    revision=[0]
    async def read_revision(): return str(revision[0])
    monkeypatch.setattr(cache,"read_revision",read_revision)
    key="il:api:audit-race"
    assert await cache.cache_json_get(key) is None
    revision[0] += 1  # the business transaction commits its revision trigger
    await cache.invalidate_read_caches()
    await cache.cache_json_set(key,["stale"],ttl_seconds=60)
    assert await cache.cache_json_get(key) is None
    await cache.cache_json_set(key,["current"],ttl_seconds=60)
    assert await cache.cache_json_get(key)==["current"]


async def test_resource_allowlist_never_allows_external_navigation():
    from interviewlens.crawler.playwright_runner import NowcoderFetcher
    fetcher=NowcoderFetcher()
    route=MagicMock()
    route.request.url="https://static.nowcoder.com/app.js"
    route.request.is_navigation_request.return_value=False
    route.continue_,route.abort=AsyncMock(),AsyncMock()
    await fetcher._guard_route(route)
    route.continue_.assert_awaited_once()
    route.request.is_navigation_request.return_value=True
    await fetcher._guard_route(route)
    route.abort.assert_awaited_once()


async def test_budget_counts_failed_tool_output_usage_and_releases_slot(monkeypatch):
    from interviewlens.llm import budget

    redis = MagicMock()
    redis.eval, redis.incrby, redis.zrem = AsyncMock(return_value=1), AsyncMock(), AsyncMock()
    monkeypatch.setattr(budget, "get_redis", lambda: redis)
    metrics = AsyncMock()
    monkeypatch.setattr(budget, "incr_tokens", metrics)
    response = MagicMock()
    response.usage.model_dump.return_value = {"prompt_tokens": 10, "completion_tokens": 20}
    await budget.guarded_create(AsyncMock(return_value=response), messages=[], max_tokens=100)
    metrics.assert_awaited_once_with(prompt=10, completion=20)
    redis.zrem.assert_awaited_once()
