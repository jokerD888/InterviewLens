"""Tests for the listing-page URL extractor (no network)."""
from __future__ import annotations

from interviewlens.crawler.discover import _extract_urls

SAMPLE = """
<html><body>
<a href="/discuss/123456789">面经 1</a>
<a href="https://www.nowcoder.com/discuss/987654321?from=feed">面经 2</a>
<a href="/feed/main/detail/abc-123-def">feed</a>
<a href="/profile/foo">noise</a>
<script>
  var url = "https://www.nowcoder.com/discuss/55555555";
  window.urls = [{href: "/discuss/77777777"}];
</script>
</body></html>
"""


def test_extract_classic_discuss() -> None:
    urls = _extract_urls(SAMPLE, "https://www.nowcoder.com")
    assert "https://www.nowcoder.com/discuss/123456789" in urls
    assert "https://www.nowcoder.com/discuss/987654321" in urls
    assert "https://www.nowcoder.com/discuss/55555555" in urls
    assert "https://www.nowcoder.com/discuss/77777777" in urls


def test_extract_feed_detail() -> None:
    urls = _extract_urls(SAMPLE, "https://www.nowcoder.com")
    assert any("feed/main/detail/abc-123-def" in u for u in urls)


def test_extract_drops_unrelated() -> None:
    urls = _extract_urls(SAMPLE, "https://www.nowcoder.com")
    assert all("/profile/" not in u for u in urls)


def test_extract_dedup() -> None:
    html = '<a href="/discuss/1"></a><a href="/discuss/1?ref=x"></a>'
    urls = _extract_urls(html, "https://www.nowcoder.com")
    # Both should collapse via the ?-strip guard
    assert urls.count("https://www.nowcoder.com/discuss/1") == 1
