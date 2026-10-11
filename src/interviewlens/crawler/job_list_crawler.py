"""Job-list API export with current taxonomy parameters and repeated-page detection.

Both discussions and moments are supported. Server totalPage is not proof
that all those pages are accessible; repeated pages mean an incomplete scan.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from ..config import settings
from ..logging import log
from .rate_limit import AsyncRateLimiter
from .record_metadata import page_fingerprint, publication_ms
from .response_guard import CrawlStoppedError, check_status, parse_records

API_URL = "https://gw-c.nowcoder.com/api/sparta/job-experience/experience/job/list"
UTC8 = timezone(timedelta(hours=8))
DEFAULT_DELAY = 1.0
MAX_PAGES = 100  # Local request budget, not a claimed server hard limit

HEADERS = {
    "content-type": "application/json",
    "origin": "https://www.nowcoder.com",
    "referer": "https://www.nowcoder.com/interview/center",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "x-requested-with": "XMLHttpRequest",
}


def _parse_posted_at(ts_ms: int | None) -> datetime | None:
    if not ts_ms:
        return None
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC8).replace(tzinfo=None)


def _format_ts(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""


def extract_post(record: dict) -> dict:
    """Extract post fields from a job/list API record."""
    md = record.get("momentData") or record.get("contentData") or {}
    ub = record.get("userBrief") or {}
    fd = record.get("frequencyData") or {}
    extra = record.get("extraInfo") or {}

    content_type = record.get("contentType", 0)
    uuid = md.get("uuid", "")
    content_id = record.get("contentId") or extra.get("contentID_var") or str(md.get("id", ""))

    if content_type == 74 and uuid:
        detail_url = f"https://www.nowcoder.com/feed/main/detail/{uuid}"
    else:
        detail_url = f"https://www.nowcoder.com/discuss/{content_id}"

    created_ms = publication_ms(record) or 0
    posted_at = _parse_posted_at(created_ms)

    return {
        "title": (md.get("title") or md.get("newTitle") or "").strip(),
        "content": (md.get("content") or "").strip(),
        "detail_url": detail_url,
        "created_at": _format_ts(posted_at),
        "created_at_ms": created_ms,
        "author": ub.get("nickname") or "",
        "school": ub.get("educationInfo") or "",
        "major": ub.get("secondMajorName") or "",
        "auth_display": ub.get("authDisplayInfo") or "",
        "ip_location": md.get("ip4Location") or "",
        "view_count": fd.get("viewCnt") or 0,
        "like_count": fd.get("likeCnt") or 0,
        "comment_count": fd.get("totalCommentCnt") or fd.get("commentCnt") or 0,
        "content_type": content_type,
        "content_id": str(content_id),
        "uuid": uuid,
    }


async def crawl_job_list(
    *,
    pages: int = MAX_PAGES,
    output_path: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    delay: float = DEFAULT_DELAY,
    job_id: int = -1,
    job_level: int = 1,
) -> list[dict]:
    """Crawl posts from the job/list API (inline content, no detail page needed).

    Args:
        pages: maximum list requests; never interpreted as full-history coverage.
        output_path: if set, writes each post as JSON Line immediately (interrupt-safe).
        since/until: naive datetime range filter.
        delay: seconds between pages.

    Returns:
        list of post dicts.
    """
    if not 1 <= pages <= 500 or job_level not in (1, 2, 3):
        raise ValueError("pages must be 1..500; job_level must be 1..3")
    limiter = AsyncRateLimiter(rate_per_sec=1 / max(10.0, delay), jitter=(1, 10))
    stop_reason = "page_budget"
    fingerprints: set[str] = set()
    all_results: list[dict] = []
    seen_ids: set[str] = set()

    # ── Setup output file ──
    out_file = None
    if output_path:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_file = out_path.open("w", encoding="utf-8")
        header = json.dumps({
            "crawled_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "api_endpoint": API_URL,
            "source": "job_list",
        }, ensure_ascii=False)
        out_file.write(header + "\n")
        out_file.flush()

    try:
        page = 1
        headers = {**HEADERS, "user-agent": settings.nowcoder_user_agent}
        if settings.nowcoder_cookie:
            headers["cookie"] = settings.nowcoder_cookie
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            while page <= pages:
                payload = {
                    "companyList": [],
                    "jobId": job_id,
                    "level": job_level,
                    "order": 3,
                    "page": page,
                    "isNewJob": True,
                }
                try:
                    await limiter.acquire()
                    resp = await client.post(API_URL, json=payload)
                    check_status(resp.status_code)
                    resp.raise_for_status()
                    data = resp.json()
                except (httpx.HTTPError, json.JSONDecodeError):
                    # Layer B: network/HTTP/JSON failure → stop paging; logic bugs bubble.
                    log.error("job_list.request_failed", page=page, exc_info=True)
                    stop_reason = "request_failed"
                    break

                records = parse_records(data)
                if not records:
                    stop_reason = "empty_page"
                    break
                fingerprint = page_fingerprint(records)
                if fingerprint and fingerprint in fingerprints:
                    stop_reason = "pagination_repeated"
                    log.warning("job_list.incomplete_scan", page=page, reason=stop_reason)
                    break
                if fingerprint:
                    fingerprints.add(fingerprint)

                new = 0
                for rec in records:
                    md = rec.get("momentData") or rec.get("contentData") or {}
                    cid = extract_post(rec)["detail_url"]
                    if not cid or cid in seen_ids:
                        continue
                    content = (md.get("content") or "").strip()
                    if not content:
                        continue
                    title = (md.get("title") or "").strip()
                    if not title:
                        continue

                    # Date filter
                    posted_at = _parse_posted_at(publication_ms(rec))
                    if posted_at:
                        if since and posted_at < since:
                            continue
                        if until and posted_at > until:
                            continue

                    seen_ids.add(cid)
                    post = extract_post(rec)
                    all_results.append(post)
                    new += 1

                    if out_file:
                        out_file.write(json.dumps(post, ensure_ascii=False) + "\n")
                        out_file.flush()

                log.info("job_list.page", page=page, records=len(records), new=new, total=len(all_results))

                # Filtering a page outside until does not mean there are no
                # older matches. Only raw page identities detect pagination loops.
                page += 1

    except CrawlStoppedError as exc:
        stop_reason = exc.reason
        raise
    except KeyboardInterrupt:
        stop_reason = "interrupted"
        log.info("job_list.interrupted", saved=len(all_results))
    finally:
        if out_file:
            trailer = json.dumps({
                "total": len(all_results),
                "stop_reason": stop_reason,
                "complete": stop_reason == "empty_page",
                "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }, ensure_ascii=False)
            out_file.write(trailer + "\n")
            out_file.close()
            log.info("job_list.saved", path=str(out_path), posts=len(all_results), size=out_path.stat().st_size)

    log.info("job_list.done", posts=len(all_results))
    return all_results
