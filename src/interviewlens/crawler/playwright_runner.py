"""Playwright-driven Nowcoder fetcher with cookie injection and retries."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from urllib.parse import urlparse

from playwright.async_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Page,
    Playwright,
    async_playwright,
)
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config import settings
from ..errors import swallow
from ..logging import log
from .cookie import parse_cookie_header
from .rate_limit import AsyncRateLimiter


@dataclass(slots=True)
class FetchResult:
    url: str
    final_url: str
    status: int
    title: str | None
    html: str


class NowcoderFetcher:
    """Reusable Playwright wrapper.

    Lifecycle::

        async with NowcoderFetcher() as f:
            result = await f.fetch(url)
    """

    def __init__(
        self,
        *,
        cookie_header: str | None = None,
        user_agent: str | None = None,
        headless: bool = True,
        timeout_ms: int = 30_000,
    ) -> None:
        self._cookie_header = cookie_header if cookie_header is not None else settings.nowcoder_cookie
        self._user_agent = user_agent or settings.nowcoder_user_agent
        self._headless = headless
        self._timeout_ms = timeout_ms

        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._limiter = AsyncRateLimiter(
            rate_per_sec=settings.crawler_rate_per_sec,
            jitter=(settings.crawler_jitter_min, settings.crawler_jitter_max),
        )

    # ---- lifecycle -----------------------------------------------------

    async def start(self) -> None:
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self._headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._context = await self._browser.new_context(
            user_agent=self._user_agent,
            locale="zh-CN",
            viewport={"width": 1366, "height": 900},
        )
        self._context.set_default_timeout(self._timeout_ms)
        await self._inject_cookies()
        log.info("fetcher.started", headless=self._headless)

    async def stop(self) -> None:
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        finally:
            self._context = None
            self._browser = None
            self._pw = None
            log.info("fetcher.stopped")

    async def __aenter__(self) -> "NowcoderFetcher":
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.stop()

    # ---- cookies -------------------------------------------------------

    async def _inject_cookies(self) -> None:
        assert self._context is not None
        if not self._cookie_header:
            log.warning("fetcher.no_cookie", hint="Anonymous mode; many pages will require login")
            return
        cookies = parse_cookie_header(self._cookie_header, domain=".nowcoder.com")
        if cookies:
            await self._context.add_cookies(cookies)
            log.info("fetcher.cookies_injected", count=len(cookies))

    # ---- fetch ---------------------------------------------------------

    async def fetch(self, url: str) -> FetchResult:
        assert self._context is not None, "fetcher not started"
        host = urlparse(url).hostname or ""
        if "nowcoder.com" not in host:
            raise ValueError(f"Refusing to fetch non-Nowcoder URL: {url}")

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(settings.crawler_max_retries),
            wait=wait_exponential(min=2, max=20),
            retry=retry_if_exception_type((PlaywrightError, asyncio.TimeoutError)),
            reraise=True,
        ):
            with attempt:
                async with self._limiter:
                    return await self._do_fetch(url)
        raise RuntimeError("unreachable")

    async def _do_fetch(self, url: str) -> FetchResult:
        assert self._context is not None
        page: Page = await self._context.new_page()
        try:
            log.info("fetch.start", url=url)
            response = await page.goto(url, wait_until="domcontentloaded")
            status = response.status if response is not None else 0
            await page.wait_for_load_state("networkidle", timeout=10_000)
            html = await page.content()
            title = await page.title()
            # Try to extract a more meaningful title for Nowcoder pages
            with swallow("fetch.h1_extract_failed", url=url):  # Layer D — UI best-effort
                h1 = await page.locator("h1").first.text_content(timeout=2000)
                if h1 and len(h1.strip()) > 5:
                    title = h1.strip()
            final_url = page.url
            log.info("fetch.done", url=url, final_url=final_url, status=status, bytes=len(html))
            return FetchResult(
                url=url,
                final_url=final_url,
                status=status,
                title=title,
                html=html,
            )
        finally:
            await page.close()


@asynccontextmanager
async def fetcher_session(**kwargs):
    """Convenience helper that yields a started NowcoderFetcher."""
    f = NowcoderFetcher(**kwargs)
    await f.start()
    try:
        yield f
    finally:
        await f.stop()
