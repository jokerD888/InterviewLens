"""Discover Nowcoder discussion URLs from list/feed pages.

Strategy:
- ``discover_from_listing(category, pages)`` opens the discussion listing page
  multiple times with ``page=N`` query, collects all anchors that point to
  ``/discuss/<id>`` or ``/feed/main/detail/<id>`` patterns, deduplicates.
- Resilient to layout shifts: we don't depend on hand-picked CSS selectors,
  just regex-match the URL shape after taking ``page.content()``.

Note: The listing API gates with the same cookie. If you only have a guest
cookie you'll get rate-limited fast — the AsyncRateLimiter applies.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from .playwright_runner import NowcoderFetcher
from .response_guard import CrawlStoppedError, check_status

DISCUSS_PATTERNS = [
    re.compile(r"https?://(?:www\.)?nowcoder\.com/discuss/(\d+)"),
    re.compile(r"https?://(?:www\.)?nowcoder\.com/feed/main/detail/([\w-]+)"),
]


def _extract_urls(html: str, base: str) -> list[str]:
    found: dict[str, None] = {}
    # ``href="..."`` and ``href='...'`` and bare URLs in JSON islands
    href_re = re.compile(r'href=["\']([^"\']+)["\']')
    for raw in href_re.findall(html):
        url = urljoin(base, raw)
        for pat in DISCUSS_PATTERNS:
            if pat.match(url):
                found[url.split("?")[0]] = None
                break
    # also catch URLs in inline JSON / script blobs
    for pat in DISCUSS_PATTERNS:
        for url in pat.findall(html):
            full = urljoin(base, "/discuss/" + url) if pat is DISCUSS_PATTERNS[0] else \
                   urljoin(base, "/feed/main/detail/" + url)
            found[full] = None
    # JSON/script islands may contain quoted relative paths rather than href=.
    for path in re.findall(
        r"""["'](/(?:discuss/\d+|feed/main/detail/[\w-]+))(?:[?#][^"']*)?["']""", html
    ):
        found[urljoin(base, path)] = None
    return list(found.keys())


async def discover_from_listing(
    *,
    source: str = "experience",
    pages: int = 1,
    fetcher: NowcoderFetcher | None = None,
) -> list[str]:
    """Walk N listing pages and return collected discussion URLs.

    ``source`` selects the listing page:
      - "experience"   → /discuss?type=2&order=3 (讨论区-面经tab，推荐)
      - "interview"    → /?type=818_1 (首页混流，含热榜)
    """
    own_fetcher = fetcher is None
    if not 1 <= pages <= 500:
        raise ValueError("pages must be 1..500")
    if own_fetcher:
        fetcher = NowcoderFetcher()
        await fetcher.start()
    assert fetcher is not None

    base = "https://www.nowcoder.com"
    urls: dict[str, None] = {}
    seen_pages: set[frozenset[str]] = set()
    try:
        for page in range(1, pages + 1):
            if source == "interview":
                url = f"{base}/?type=818_1&page={page}"
            else:
                url = f"{base}/discuss?type=2&order=3&pageSize=30&page={page}"
            result = await fetcher.fetch(url)
            check_status(result.status)
            discovered = _extract_urls(result.html, base)
            identities = frozenset(discovered)
            if identities and identities in seen_pages:
                raise CrawlStoppedError("pagination_repeated")
            if identities:
                seen_pages.add(identities)
            for u in discovered:
                urls[u] = None
    finally:
        if own_fetcher:
            await fetcher.stop()
    return list(urls.keys())
