import json
from datetime import datetime
from unittest.mock import AsyncMock

import httpx

from interviewlens.crawler import job_list_crawler as crawler


async def test_until_filtered_pages_do_not_stop_discovery_and_repeated_pages_do(tmp_path, monkeypatch):
    requested = []
    rows = {
        1: [{"contentId": 1, "contentData": {"id": 1, "title": "面经", "content": "正文",
             "createTime": 1785600000000}}],
        2: [{"contentId": 2, "contentData": {"id": 2, "title": "面经", "content": "正文",
             "createTime": 1785600000000}}],
        3: [{"contentId": 3, "contentData": {"id": 3, "title": "面经", "content": "正文",
             "createTime": 1784505600000}}],
    }

    def respond(request):
        payload = json.loads(request.content)
        requested.append(payload)
        return httpx.Response(200, json={"success": True, "code": 0,
            "data": {"records": rows.get(payload["page"], rows[3]), "totalPage": 500}})

    original = httpx.AsyncClient
    monkeypatch.setattr(crawler.httpx, "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    monkeypatch.setattr(crawler.AsyncRateLimiter, "acquire", AsyncMock())
    path = tmp_path / "export.jsonl"
    result = await crawler.crawl_job_list(pages=10, until=datetime(2026, 7, 25),
        output_path=str(path))
    assert len(result) == 1 and result[0]["content_id"] == "3"
    assert [payload["page"] for payload in requested] == [1, 2, 3, 4]
    assert requested[0]["jobId"] == -1 and requested[0]["level"] == 1
    trailer = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    assert trailer["stop_reason"] == "pagination_repeated" and trailer["complete"] is False
