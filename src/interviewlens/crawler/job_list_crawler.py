"""Job-list API crawler: complement to tab_crawler for deeper historical posts.

Endpoint: POST https://gw-c.nowcoder.com/api/sparta/job-experience/experience/job/list

Unlike tab/content (400 post cache, discuss+moment posts), this endpoint:
- Returns up to 2000 moment-type posts (contentType=74 only)
- Includes full content inline (no detail page visit needed → much faster)
- Supports date filtering via posted_at

Use as supplement when tab crawler's 400 posts aren't enough.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

from ..logging import log

API_URL = "https://gw-c.nowcoder.com/api/sparta/job-experience/experience/job/list"
UTC8 = timezone(timedelta(hours=8))
DEFAULT_DELAY = 1.0
MAX_PAGES = 100  # 2000 / 20 = 100 pages hard limit

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
    md = record.get("momentData") or {}
    ub = record.get("userBrief") or {}
    fd = record.get("frequencyData") or {}
    extra = record.get("extraInfo") or {}

    content_type = record.get("contentType", 0)
    uuid = md.get("uuid", "")
    content_id = extra.get("contentID_var") or str(md.get("id", ""))

    if content_type == 74 and uuid:
        detail_url = f"https://www.nowcoder.com/feed/main/detail/{uuid}"
    else:
        detail_url = f"https://www.nowcoder.com/discuss/{content_id}"

    created_ms = md.get("createdAt") or 0
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
) -> list[dict]:
    """Crawl posts from the job/list API (inline content, no detail page needed).

    Args:
        pages: max pages (each = ~20 posts, max 100 = 2000 posts).
        output_path: if set, writes each post as JSON Line immediately (interrupt-safe).
        since/until: naive datetime range filter.
        delay: seconds between pages.

    Returns:
        list of post dicts.
    """
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
        empty_streak = 0
        page = 1
        async with httpx.AsyncClient(timeout=30) as client:
            while page <= pages:
                payload = {
                    "companyList": [],
                    "jobId": 0,
                    "level": 3,
                    "order": 3,
                    "page": page,
                    "isNewJob": True,
                }
                try:
                    resp = await client.post(API_URL, headers=HEADERS, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                except (httpx.HTTPError, json.JSONDecodeError):
                    # Layer B: network/HTTP/JSON failure → stop paging; logic bugs bubble.
                    log.error("job_list.request_failed", page=page, exc_info=True)
                    break

                if not data.get("success") or data.get("code") != 0:
                    log.warning("job_list.bad_response", page=page)
                    break

                records = data.get("data", {}).get("records", [])
                if not records:
                    log.info("job_list.empty_page", page=page)
                    break

                # Check for early stop by date (newest-first ordering)
                last_record = records[-1]
                last_ts = (last_record.get("momentData") or {}).get("createdAt", 0)
                if since and last_ts:
                    last_dt = _parse_posted_at(last_ts)
                    if last_dt and last_dt < since:
                        log.info("job_list.since_reached", page=page, last_date=str(last_dt))

                new = 0
                for rec in records:
                    md = rec.get("momentData") or {}
                    cid = str(md.get("id", ""))
                    if not cid or cid in seen_ids:
                        continue
                    content = (md.get("content") or "").strip()
                    if not content:
                        continue
                    title = (md.get("title") or "").strip()
                    if not title:
                        continue

                    # Date filter
                    posted_at = _parse_posted_at(md.get("createdAt", 0))
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

                if new == 0:
                    empty_streak += 1
                    if empty_streak >= 2:
                        log.info("job_list.discovery_done", reason="no new records for 2 pages")
                        break
                else:
                    empty_streak = 0

                page += 1
                await asyncio.sleep(delay)

    except KeyboardInterrupt:
        log.info("job_list.interrupted", saved=len(all_results))
    finally:
        if out_file:
            trailer = json.dumps({
                "total": len(all_results),
                "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }, ensure_ascii=False)
            out_file.write(trailer + "\n")
            out_file.close()
            log.info("job_list.saved", path=str(out_path), posts=len(all_results), size=out_path.stat().st_size)

    log.info("job_list.done", posts=len(all_results))
    return all_results
