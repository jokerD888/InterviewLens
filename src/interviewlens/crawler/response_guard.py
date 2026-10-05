"""Stop crawling on server blocks; do not mistake them for empty feeds."""

from __future__ import annotations

from urllib.parse import urlparse


class CrawlStoppedError(RuntimeError):
    def __init__(self, reason: str, *, retryable: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


def check_status(status: int) -> None:
    if status in (401, 403, 429):
        raise CrawlStoppedError(f"http_{status}")
    if not 200 <= status < 300:
        raise CrawlStoppedError(f"http_{status}", retryable=True)


def check_page(url: str, title: str, visible_text: str) -> None:
    path = urlparse(url).path.lower()
    if path.startswith(("/login", "/signin", "/passport", "/verify", "/captcha")):
        raise CrawlStoppedError("login_or_challenge")
    markers = ("访问过于频繁", "操作过于频繁", "安全验证", "请先登录", "登录后查看", "请输入验证码")
    if any(marker in title for marker in markers) or (
        len(visible_text) < 2000 and any(marker in visible_text for marker in markers)
    ):
        raise CrawlStoppedError("login_or_challenge")


def parse_records(data: object) -> list[dict]:
    if not isinstance(data, dict):
        raise CrawlStoppedError("invalid_api_response")
    if data.get("success") is False or data.get("code", 0) not in (0, "0"):
        raise CrawlStoppedError("api_rejected")
    body = data.get("data")
    if not isinstance(body, dict) or not isinstance(body.get("records"), list):
        raise CrawlStoppedError("invalid_api_response")
    records = body["records"]
    if any(not isinstance(record, dict) for record in records):
        raise CrawlStoppedError("invalid_api_record")
    return records
