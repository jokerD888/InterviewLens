"""Polite async rate limiter: ensures ``rate_per_sec`` is not exceeded."""
from __future__ import annotations

import asyncio
import random
import time


class AsyncRateLimiter:
    """Token-bucket-ish limiter with optional jitter sleep on each acquire.

    Usage::

        limiter = AsyncRateLimiter(rate_per_sec=1.5, jitter=(2.0, 5.0))
        async with limiter:
            await fetch(...)
    """

    def __init__(
        self,
        *,
        rate_per_sec: float,
        jitter: tuple[float, float] | None = None,
    ) -> None:
        if rate_per_sec <= 0:
            raise ValueError("rate_per_sec must be positive")
        self._min_interval = 1.0 / rate_per_sec
        self._jitter = jitter
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            if self._jitter is not None:
                lo, hi = self._jitter
                if hi > lo > 0:
                    await asyncio.sleep(random.uniform(lo, hi))
            self._last = time.monotonic()

    async def __aenter__(self) -> "AsyncRateLimiter":
        await self.acquire()
        return self

    async def __aexit__(self, *_: object) -> None:
        return None
