"""Public API admission control. No unbounded inference request queue.

Production runs one API process (see Compose). Redis rate counters are shared.
A timed-out/disconnected HTTP request does not release an inference slot until
the underlying task finishes: asyncio cancellation cannot stop a torch thread.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import socket
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

import redis.asyncio as redis
from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from ..config import settings
from ..observability import get_redis

_RATE = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return {n, redis.call('TTL', KEYS[1])}
"""
_jobs: set[asyncio.Task] = set()
_job_started: dict[asyncio.Task, float] = {}
_proxy_addresses: set[str] = set()
_proxy_refreshed = 0.0
T = TypeVar("T")


async def check_rate(request: Request):
    # Uvicorn only trusts proxy headers from explicitly configured proxy IPs.
    # Never read X-Forwarded-For here or trust arbitrary HTTP headers.
    ip = request.client.host if request.client else "unknown"
    # Caddy overwrites this private header with its socket peer. Trust it only
    # if the actual backend peer resolves to the configured internal proxy.
    global _proxy_addresses, _proxy_refreshed
    forwarded = request.headers.get("x-il-client-ip")
    if forwarded and settings.trusted_search_proxy:
        if time.monotonic() - _proxy_refreshed > 30:
            try:
                def resolve_proxies():
                    return [entry for name in settings.trusted_search_proxy.split(",") if name.strip()
                            for entry in socket.getaddrinfo(name.strip(), None)]
                entries = await asyncio.to_thread(resolve_proxies)
                _proxy_addresses = {entry[4][0] for entry in entries}
                _proxy_refreshed = time.monotonic()
            except OSError:
                _proxy_addresses = set()
        if ip in _proxy_addresses:
            try:
                ip = str(ipaddress.ip_address(forwarded))
            except ValueError:
                raise HTTPException(400, "Invalid proxy address") from None
    address = hashlib.sha256(ip.encode()).hexdigest()[:32]
    search = request.url.path.rstrip("/") == "/posts/search"
    limit = settings.search_requests_per_minute if search else settings.public_requests_per_minute
    bucket = "search" if search else "http"
    try:
        count, ttl = await get_redis().eval(_RATE, 1, f"il:rate:{bucket}:{address}", 60)
    except redis.RedisError:
        raise HTTPException(503, "Request protection temporarily unavailable", headers={"Retry-After": "10"}) from None
    if count > limit:
        raise HTTPException(429, "Too many requests", headers={"Retry-After": str(max(1, ttl))})


class PublicResourceGuard(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if len(request.scope.get("query_string", b"")) > 8192:
            return JSONResponse({"detail": "Query too large"}, status_code=414)
        length = request.headers.get("content-length", "0")
        if not length.isdigit() or int(length) > 1_048_576:
            return JSONResponse({"detail": "Request body too large"}, status_code=413)
        if settings.app_env == "production" and request.url.path not in ("/", "/health/live", "/health/ready"):
            try:
                await check_rate(request)
            except HTTPException as exc:
                return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
        response = await call_next(request)
        if request.url.path.startswith(("/admin", "/bridge", "/api/bridge", "/summaries")):
            response.headers["Cache-Control"] = "no-store"
        return response


async def bounded_search_embed(operation: Callable[[], Awaitable[T]]) -> T:
    if len(_jobs) >= settings.search_concurrency:
        raise HTTPException(503, "Search is busy; try again shortly", headers={"Retry-After": "3"})
    task = asyncio.create_task(operation())
    _jobs.add(task)
    _job_started[task] = time.monotonic()

    def finished(job):
        _jobs.discard(job)
        _job_started.pop(job, None)
        # Consume late failures after an HTTP timeout/disconnect.
        if not job.cancelled():
            job.exception()

    task.add_done_callback(finished)
    try:
        return await asyncio.wait_for(asyncio.shield(task), settings.search_timeout_seconds)
    except TimeoutError:
        raise HTTPException(504, "Search timed out; try again shortly", headers={"Retry-After": "5"}) from None


def inference_healthy() -> bool:
    # An abandoned HTTP request must not hide a permanently stuck torch job.
    maximum_age = max(120, settings.search_timeout_seconds * 2)
    return all(time.monotonic() - started < maximum_age for started in _job_started.values())
