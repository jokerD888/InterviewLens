"""Playwright-driven Nowcoder fetcher with cookie injection and retries."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from playwright.async_api import (
    Error as PlaywrightError,
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
from .response_guard import CrawlStoppedError, check_page, check_status
from .site_limiter import SiteLimiter, pause_site
from .urls import allowed_request_url, validate_page_url


@dataclass(slots=True)
class FetchResult:
    url: str
    final_url: str
    status: int
    title: str | None
    html: str
    published_ms: int | None = None


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
        limiter: AsyncRateLimiter | None = None,
    ) -> None:
        self._cookie_header = (
            cookie_header if cookie_header is not None else settings.nowcoder_cookie
        )
        self._user_agent = user_agent or settings.nowcoder_user_agent
        self._headless = headless
        self._timeout_ms = timeout_ms

        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._limiter = SiteLimiter(
            limiter
            or AsyncRateLimiter(
                rate_per_sec=settings.crawler_rate_per_sec,
                jitter=(settings.crawler_jitter_min, settings.crawler_jitter_max),
            )
        )

    # ---- lifecycle -----------------------------------------------------

    async def start(self) -> None:
        try:
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=self._headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            self._context = await self._browser.new_context(
                user_agent=self._user_agent,
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                viewport={"width": 1366, "height": 900},
            )
            self._context.set_default_timeout(self._timeout_ms)
            await self._inject_cookies()
            await self._context.route("**/*", self._guard_route)
            log.info("fetcher.started", headless=self._headless)
        except BaseException:
            await self.stop()
            raise

    async def stop(self) -> None:
        cancelled = None
        try:
            for resource, method in (
                (self._context, "close"),
                (self._browser, "close"),
                (self._pw, "stop"),
            ):
                if resource is None:
                    continue
                try:
                    await asyncio.wait_for(getattr(resource, method)(), timeout=5)
                except asyncio.CancelledError as exc:
                    cancelled = exc
                except Exception:
                    log.warning("fetcher.close_failed", resource=method, exc_info=True)
        finally:
            self._context = None
            self._browser = None
            self._pw = None
            log.info("fetcher.stopped")
        if cancelled:
            raise cancelled

    async def __aenter__(self) -> "NowcoderFetcher":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        try:
            if isinstance(exc, CrawlStoppedError):
                await pause_site(exc.reason)
        finally:
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
        validate_page_url(url)

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(settings.crawler_max_retries),
            wait=wait_exponential(min=2, max=20),
            retry=retry_if_exception_type((PlaywrightError, asyncio.TimeoutError)),
            reraise=True,
        ):
            with attempt:
                async with self._limiter:
                    try:
                        return await self._do_fetch(url)
                    except CrawlStoppedError as exc:
                        await pause_site(exc.reason)
                        raise
        raise RuntimeError("unreachable")

    async def _guard_route(self, route):
        # Apply before requesting any redirect target or page subresource.
        # Third-party scripts/media are unnecessary for author-text extraction.
        from urllib.parse import urlparse
        from .urls import ALLOWED_HOSTS

        request = route.request
        safe_navigation = (
            not request.is_navigation_request() or urlparse(request.url).hostname in ALLOWED_HOSTS
        )
        if safe_navigation and allowed_request_url(request.url):
            await route.continue_()
        else:
            await route.abort("blockedbyclient")

    async def _do_fetch(self, url: str) -> FetchResult:
        assert self._context is not None
        page: Page = await self._context.new_page()
        try:
            log.info("fetch.start", url=url)
            response = await page.goto(url, wait_until="domcontentloaded")
            status = response.status if response is not None else 0
            check_status(status)
            validate_page_url(page.url)
            await page.wait_for_load_state("networkidle", timeout=10_000)
            html = await page.content()
            title = await page.title()
            check_page(page.url, title, await page.locator("body").inner_text())
            # Try to extract a more meaningful title for Nowcoder pages
            with swallow("fetch.h1_extract_failed", url=url):  # Layer D — UI best-effort
                h1 = await page.locator("h1").first.text_content(timeout=2000)
                if h1 and len(h1.strip()) > 5:
                    title = h1.strip()
            final_url = page.url
            from .metadata_api import fetch_publication

            published_ms = await fetch_publication(final_url, self)
            log.info("fetch.done", url=url, final_url=final_url, status=status, bytes=len(html))
            return FetchResult(
                url=url,
                final_url=final_url,
                status=status,
                title=title,
                html=html,
                published_ms=published_ms,
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
