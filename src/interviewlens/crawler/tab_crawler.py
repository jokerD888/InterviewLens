"""Tab content crawler: crawl mianjing posts from Nowcoder's tab/content API.

Endpoint: GET https://gw-c.nowcoder.com/api/sparta/home/tab/content
Parameters: pageNo=N, categoryType=1, tabId=818 (backend)

Unlike the job/list API (2000 post hard limit), this endpoint supports
unlimited pagination. Each post's detail page is visited to extract
full content and titles (especially for discuss-type posts where the
API record has no title field).

Usage:
    il tab-crawl --pages 5 --output data/tab_crawl.json
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from playwright.async_api import Error as PlaywrightError

from ..config import settings
from ..db import Post, session_scope
from ..errors import swallow
from ..logging import log
from .cleaner import strip_nowcoder_noise
from .playwright_runner import NowcoderFetcher

TAB_API = "https://gw-c.nowcoder.com/api/sparta/home/tab/content"
UTC8 = timezone(timedelta(hours=8))
DEFAULT_DELAY = 1.5
DEFAULT_PAGE_SIZE = 20


def _parse_posted_at_ms(ms: int | None) -> datetime | None:
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=UTC8).replace(tzinfo=None)


def _format_ts(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M")


def build_detail_url(record: dict) -> str | None:
    """Build correct detail page URL from a tab/content API record."""
    md = record.get("momentData") or {}
    uuid = md.get("uuid", "")
    content_type = record.get("contentType", 0)
    if content_type == 74 and uuid:
        return f"https://www.nowcoder.com/feed/main/detail/{uuid}"
    cid = str(record.get("contentId") or md.get("id", ""))
    return f"https://www.nowcoder.com/discuss/{cid}" if cid else None


def extract_post(record: dict, content: str = "", page_title: str = "") -> dict:
    """Extract all important fields from a raw API record into a flat dict.

    ``content`` and ``page_title`` are filled from the detail page visit.
    """
    md = record.get("momentData") or {}
    ub = record.get("userBrief") or {}
    fd = record.get("frequencyData") or {}
    created_ms = md.get("createdAt") or 0

    title = (md.get("title") or "").strip()
    if not title and page_title:
        title = page_title

    return {
        "title": title,
        "content": content.strip() if content else (md.get("content") or "").strip(),
        "detail_url": build_detail_url(record) or "",
        "created_at": _format_ts(_parse_posted_at_ms(created_ms)),
        "created_at_ms": created_ms,
        "author": ub.get("nickname") or "",
        "school": ub.get("educationInfo") or "",
        "major": ub.get("secondMajorName") or "",
        "auth_display": ub.get("authDisplayInfo") or "",
        "ip_location": md.get("ip4Location") or "",
        "view_count": fd.get("viewCnt") or 0,
        "like_count": fd.get("likeCnt") or 0,
        "comment_count": fd.get("totalCommentCnt") or fd.get("commentCnt") or 0,
        "content_type": record.get("contentType", 0),
        "content_id": str(record.get("contentId") or md.get("id", "")),
        "uuid": md.get("uuid", ""),
    }


async def fetch_tab_page(page_no: int, fetcher: NowcoderFetcher) -> list[dict]:
    """Fetch one page of the tab/content API using browser cookies."""
    page = await fetcher._context.new_page()
    try:
        url = f"{TAB_API}?pageNo={page_no}&categoryType=1&tabId=818"
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        text = await page.evaluate("() => document.body.innerText")
        data = json.loads(text)
        return data.get("data", {}).get("records") or []
    except (PlaywrightError, asyncio.TimeoutError, json.JSONDecodeError):
        # Layer C: network/render/JSON failures → empty page; selector bugs bubble.
        log.warning("tab.page_fetch_failed", page_no=page_no, exc_info=True)
        return []
    finally:
        await page.close()


async def fetch_detail(fetcher: NowcoderFetcher, detail_url: str) -> tuple[str, str]:
    """Visit a detail page and extract (content, page_title).

    Tries multiple CSS selectors for the Nowcoder post body.  When none
    match, falls back to body text but removes known UI noise elements
    (action bars, comment boxes, sidebar ads) before extraction.
    """
    page = await fetcher._context.new_page()
    try:
        await page.goto(detail_url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(2)
        content = await page.evaluate("""
            () => {
                // 1. Try specific content containers (newest → oldest DOM pattern)
                for (const sel of [
                    '.nc-slate-editor-content',
                    '.nc-post-content',
                    '[class*="post-content"]',
                    '[class*="feed-detail"] [class*="content"]',
                    'article',
                    '[class*="post-detail"]',
                ]) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText.trim().length > 50) return el.innerText;
                }

                // 2. Fallback: clone body, strip noise elements, then extract
                const clone = document.body.cloneNode(true);
                const noiseSelectors = [
                    '[class*="comment"]', '[class*="action"]', '[class*="sidebar"]',
                    '[class*="recommend"]', '[class*="ad-"]', '[class*="advert"]',
                    '.nc-post-action', '.nc-comment', '.post-action',
                    'nav', 'header', 'footer', 'aside',
                    '[class*="quick-reply"]', '[class*="emoji"]',
                ];
                for (const sel of noiseSelectors) {
                    clone.querySelectorAll(sel).forEach(el => el.remove());
                }
                const text = clone.innerText;
                return text.substring(0, 8000);
            }
        """)
        page_title = await page.evaluate("""
            () => {
                const h1 = document.querySelector('h1');
                if (h1) return h1.innerText.trim();
                const t = document.querySelector('.post-title, .discuss-title');
                if (t) return t.innerText.trim();
                return document.title;
            }
        """)
        await page.close()
        # Strip residual Nowcoder UI noise (action bars, ads, etc.)
        content = strip_nowcoder_noise(content or "")
        return content, page_title or ""
    except (PlaywrightError, asyncio.TimeoutError):
        # Layer C: render/network failures → empty; selector/AttributeError bubble.
        log.warning("tab.detail_fetch_failed", url=detail_url, exc_info=True)
        return "", ""
    finally:
        await page.close()


async def crawl_tab(
    *,
    pages: int = 5,
    output_path: str | None = None,
    save_to_db: bool = False,
    delay: float = DEFAULT_DELAY,
    stop_when_seen: bool = False,
) -> list[dict]:
    """Crawl posts from the tab/content API.

    Each post is written to ``output_path`` in real-time (JSON Lines format),
    so interrupted crawls don't lose data.  Ctrl+C safe.

    Args:
        pages: max API pages to fetch (0 = unlimited until empty pages).
        output_path: if set, writes each post as JSON Line immediately.
        save_to_db: if True, also persists posts to the PostgreSQL posts table.
        delay: seconds between detail page requests.
        stop_when_seen: incremental watermark for daily updates. When True,
            records whose URL already exists in the DB are dropped from the
            work-list, and discovery stops after 2 consecutive pages yield no
            new posts. Because the tab API is newest-first, this catches up to
            the previous run's high-water mark without a time cursor (robust to
            Nowcoder's pinned/recommended reordering).

    Returns:
        list of post dicts with full content.
    """
    all_records: list[dict] = []
    seen_ids: set[str] = set()
    page_no = 1

    # ── Setup output file ──
    out_file = None
    if output_path:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_file = out_path.open("w", encoding="utf-8")
        # Write header line with metadata
        header = json.dumps({
            "crawled_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "api_endpoint": TAB_API,
        }, ensure_ascii=False)
        out_file.write(header + "\n")
        out_file.flush()

    results: list[dict] = []
    fixed_titles = 0

    try:
        async with NowcoderFetcher() as fetcher:
            # ── Phase 1: discover via tab/content API ──
            log.info("tab_crawler.discover_start", pages=pages if pages > 0 else "unlimited")
            empty_streak = 0
            while pages == 0 or page_no <= pages:
                records = await fetch_tab_page(page_no, fetcher)
                if not records:
                    log.info("tab_crawler.empty_page", page_no=page_no)
                    break

                new = 0
                for r in records:
                    cid = str(r.get("contentId") or r.get("momentData", {}).get("id", ""))
                    if cid in seen_ids:
                        continue
                    seen_ids.add(cid)
                    if stop_when_seen:
                        # Incremental mode: skip posts already persisted.
                        detail_url = build_detail_url(r)
                        if detail_url and await _url_exists_in_db(detail_url):
                            continue
                    all_records.append(r)
                    new += 1

                log.info("tab_crawler.page", page_no=page_no, records=len(records), new=new, total=len(all_records))

                if new == 0:
                    empty_streak += 1
                    if empty_streak >= 2:
                        log.info("tab_crawler.discovery_done", reason="no new records for 2 pages")
                        break
                else:
                    empty_streak = 0

                page_no += 1
                await asyncio.sleep(0.3)

            log.info("tab_crawler.discovered", total=len(all_records))

            # ── Phase 2: fetch detail content (real-time write) ──
            for i, rec in enumerate(all_records):
                detail_url = build_detail_url(rec)
                content = ""
                page_title = ""

                if detail_url:
                    content, page_title = await fetch_detail(fetcher, detail_url)
                else:
                    content = (rec.get("momentData", {}) or {}).get("content") or ""

                api_title = ((rec.get("momentData") or {}).get("title") or "").strip()
                if not api_title and page_title:
                    fixed_titles += 1

                post = extract_post(rec, content, page_title)
                results.append(post)

                if save_to_db:
                    await _persist_post(post)

                # ── Real-time write to file ──
                if out_file:
                    out_file.write(json.dumps(post, ensure_ascii=False) + "\n")
                    out_file.flush()

                log.info(
                    "tab_crawler.post",
                    idx=i + 1,
                    total=len(all_records),
                    title=post["title"][:40],
                    chars=len(post["content"]),
                )
                await asyncio.sleep(delay)

    except KeyboardInterrupt:
        log.info("tab_crawler.interrupted", saved=len(results))
        print(f"\nInterrupted. {len(results)} posts saved.")
    finally:
        if out_file:
            # Write summary trailer
            trailer = json.dumps({"total": len(results), "finished_at": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False)
            out_file.write(trailer + "\n")
            out_file.close()
            log.info("tab_crawler.saved", path=str(out_path), posts=len(results), size=out_path.stat().st_size)

    log.info("tab_crawler.done", posts=len(results), fixed_titles=fixed_titles)
    return results


async def _url_exists_in_db(url: str) -> bool:
    """True if a post with this source_url is already persisted."""
    from sqlalchemy import select

    async with session_scope() as s:
        return (
            await s.execute(select(Post.id).where(Post.source_url == url))
        ).first() is not None


async def _persist_post(post: dict) -> int | None:
    """Upsert a crawled post into the posts table."""
    from sqlalchemy import select

    url = post.get("detail_url", "")
    if not url:
        return None

    async with session_scope() as s:
        existing = (await s.execute(select(Post).where(Post.source_url == url))).scalar_one_or_none()
        if existing:
            return existing.id

        created_str = post.get("created_at", "")
        posted_at = None
        if created_str:
            try:
                posted_at = datetime.strptime(created_str, "%Y-%m-%d %H:%M")
            except ValueError:
                pass

        p = Post(
            source_url=url,
            title=post.get("title", ""),
            cleaned_text=post.get("content", ""),
            posted_at=posted_at,
            extract_status="pending",
        )
        s.add(p)
        await s.flush()
        await s.commit()
        return p.id
