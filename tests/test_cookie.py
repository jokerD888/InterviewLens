"""Unit tests for cookie parsing helper."""
from __future__ import annotations

from interviewlens.crawler.cookie import parse_cookie_header


def test_parse_basic() -> None:
    raw = "t=abc; SERVERID=xyz123; gr_user_id=u1"
    cookies = parse_cookie_header(raw)
    assert len(cookies) == 3
    by_name = {c["name"]: c["value"] for c in cookies}
    assert by_name["t"] == "abc"
    assert by_name["SERVERID"] == "xyz123"
    assert all(c["domain"] == ".nowcoder.com" for c in cookies)


def test_parse_handles_empty() -> None:
    assert parse_cookie_header("") == []
    assert parse_cookie_header(";; ;") == []


def test_parse_skips_malformed() -> None:
    cookies = parse_cookie_header("good=1; novalue; =stray; ok=2")
    names = sorted(c["name"] for c in cookies)
    assert names == ["good", "ok"]
