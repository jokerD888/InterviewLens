"""The same publication/detail APIs used by Nowcoder's terminal frontend."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from .record_metadata import publication_ms
from .response_guard import CrawlStoppedError, check_status, parse_records

API_ROOT = "https://gw-c.nowcoder.com"
JOB_PATH = "/api/sparta/job-experience/experience/job/list"
JOB_HEADERS = {
    "origin": "https://www.nowcoder.com",
    "referer": "https://www.nowcoder.com/interview/center",
}


def detail_endpoint(url: str) -> tuple[str, str, str] | None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "www.nowcoder.com":
        return None
    match = re.fullmatch(r"/discuss/(\d+)/?", parsed.path)
    if match:
        return f"/api/sparta/detail/content-data/detail/{match[1]}", "contentData", match[1]
    match = re.fullmatch(r"/feed/main/detail/([a-fA-F0-9]{32})/?", parsed.path)
    if match:
        return f"/api/sparta/detail/moment-data/detail/{match[1]}", "momentData", match[1]
    return None


def parse_detail_metadata(payload: object, url: str) -> dict:
    endpoint = detail_endpoint(url)
    if not endpoint or not isinstance(payload, dict):
        raise CrawlStoppedError("invalid_detail_metadata")
    if payload.get("success") is False or payload.get("code", 0) not in (0, "0"):
        raise CrawlStoppedError("api_rejected")
    body = payload.get("data")
    if not isinstance(body, dict):
        raise CrawlStoppedError("invalid_detail_metadata")
    if (body.get("showMessage") or {}).get("showContent") is False:
        raise CrawlStoppedError("post_unavailable")
    _, kind, identity = endpoint
    actual = body.get("id") if kind == "contentData" else body.get("uuid")
    if str(actual).lower() != identity.lower():
        raise CrawlStoppedError("detail_identity_mismatch")
    return {kind: body}


async def fetch_publication(url: str, fetcher) -> int | None:
    endpoint = detail_endpoint(url)
    if not endpoint:
        return None
    await fetcher._limiter.acquire()
    response = await fetcher._context.request.get(API_ROOT + endpoint[0], headers=JOB_HEADERS)
    check_status(response.status)
    return publication_ms(parse_detail_metadata(await response.json(), url))


async def fetch_job_page(page_no: int, fetcher, *, job_id: int = -1, level: int = 1):
    await fetcher._limiter.acquire()
    response = await fetcher._context.request.post(
        API_ROOT + JOB_PATH, headers=JOB_HEADERS,
        data={"companyList": [], "jobId": job_id, "level": level,
              "order": 3, "page": page_no, "isNewJob": True},
    )
    check_status(response.status)
    return parse_records(await response.json())
