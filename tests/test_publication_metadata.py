from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from interviewlens.crawler.metadata_api import (
    detail_endpoint,
    fetch_job_page,
    parse_detail_metadata,
)
from interviewlens.crawler.record_metadata import page_fingerprint, publication_ms
from interviewlens.crawler.response_guard import CrawlStoppedError
from interviewlens.crawler.tab_crawler import extract_post

TS = int(datetime(2026, 7, 20, tzinfo=UTC).timestamp() * 1000)


@pytest.mark.parametrize("kind,field", [("momentData", "createdAt"), ("contentData", "createTime")])
def test_publication_fields_and_filter_timestamp_use_same_value(kind, field):
    record = {"contentId": "42", kind: {field: str(TS), "title": "面经"}}
    assert publication_ms(record) == TS
    assert extract_post(record)["created_at_ms"] == TS
    assert extract_post(record)["title"] == "面经"


@pytest.mark.parametrize("value", [None, "", "invalid", False, -10, 0, 999999999999999999])
def test_malformed_dates_remain_unknown(value):
    assert publication_ms({"contentData": {"createTime": value}}) is None


def test_never_use_edit_or_display_time_as_publication():
    assert publication_ms({"contentData": {"editTime": TS, "showTime": TS}}) is None


def test_page_identity_is_order_independent_and_ignores_counts():
    one = [{"contentId": "1"}, {"contentId": "2"}]
    two = [{"contentId": "2", "frequencyData": {"likeCnt": 20}}, {"contentId": "1"}]
    assert page_fingerprint(one) == page_fingerprint(two)
    assert page_fingerprint(one) != page_fingerprint([{"contentId": "3"}])
    assert page_fingerprint([{}]) is None


def test_detail_identity_is_verified_and_untrusted_hosts_never_requested():
    url = "https://www.nowcoder.com/discuss/42"
    data = {"success": True, "code": 0, "data": {"id": 42, "createTime": TS}}
    assert publication_ms(parse_detail_metadata(data, url)) == TS
    with pytest.raises(CrawlStoppedError, match="identity_mismatch"):
        parse_detail_metadata(data, "https://www.nowcoder.com/discuss/43")
    assert detail_endpoint("https://evil.example/discuss/42") is None
    assert detail_endpoint("https://www.nowcoder.com/discuss/comment/42") is None


async def test_current_job_selector_payload_and_shared_rate_limit():
    fetcher = MagicMock()
    fetcher._limiter.acquire = AsyncMock()
    response = MagicMock(status=200)
    response.json = AsyncMock(return_value={"data": {"records": [{"contentId": "42"}]}})
    fetcher._context.request.post = AsyncMock(return_value=response)
    await fetch_job_page(7, fetcher, job_id=11200, level=2)
    fetcher._limiter.acquire.assert_awaited_once()
    payload = fetcher._context.request.post.await_args.kwargs["data"]
    assert payload["jobId"] == 11200 and payload["level"] == 2 and payload["page"] == 7


async def test_metadata_server_block_is_not_unknown_date():
    from interviewlens.crawler.metadata_api import fetch_publication
    fetcher = MagicMock()
    fetcher._limiter.acquire = AsyncMock()
    fetcher._context.request.get = AsyncMock(return_value=MagicMock(status=429))
    with pytest.raises(CrawlStoppedError, match="http_429"):
        await fetch_publication("https://www.nowcoder.com/discuss/42", fetcher)


async def test_generic_page_upsert_persists_date_and_preserves_existing_date():
    from sqlalchemy.dialects import postgresql

    from interviewlens.db.repositories import upsert_raw_post
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one.return_value = 42
    session.execute.return_value = result
    published = datetime(2026, 7, 20)
    await upsert_raw_post(session, url="https://www.nowcoder.com/discuss/42",
        title="面经", raw_html="snapshot", posted_at=published)
    stmt = session.execute.await_args.args[0].compile(dialect=postgresql.dialect())
    assert stmt.params["posted_at"] == published
    assert "coalesce(posts.posted_at, excluded.posted_at)" in str(stmt)
