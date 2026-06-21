"""Discover Nowcoder interview posts via the gw-c API gateway or Playwright 面经 tab.

Two modes:
- ``discover_and_fetch()`` — hits gw-c API directly (fast, moment-type posts only)
- ``discover_and_fetch_mianjing()`` — clicks 面经 tab via Playwright (covers moment + discuss)
  plus AI-based filtering via DeepSeek to exclude non-面经 posts.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlmodel import text

from ..config import settings
from ..db import Post, session_scope
from ..logging import log
from ..llm.deepseek import get_client

API_URL = "https://gw-c.nowcoder.com/api/sparta/job-experience/experience/job/list"

# Known job IDs (discovered via browser DevTools when switching position filter)
JOB_IDS: dict[str, int] = {
    "backend": 818,   # 后端开发
    "frontend": 819,  # 前端开发
    "test": 820,      # 测试开发
    "ai": 898,        # 人工智能
}

HEADERS_FACTORY = lambda: {
    "content-type": "application/json",
    "origin": "https://www.nowcoder.com",
    "referer": "https://www.nowcoder.com/",
    "user-agent": settings.nowcoder_user_agent,
}

UTC8 = timezone(timedelta(hours=8))


def _parse_posted_at(ts_ms: int | None) -> datetime | None:
    if not ts_ms:
        return None
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC8).replace(tzinfo=None)


async def discover_and_fetch(
    *,
    job: str = "backend",
    pages: int = 5,
    order: int = 3,  # 3 = newest first
    level: int = 3,  # 3 = all levels
    company_list: list[str] | None = None,
    delay: float = 1.5,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[int]:
    """Call gw-c API, persist posts, return list of post_ids.

    Each API response already contains the full post text (momentData.content),
    so we write cleaned_text directly and skip Playwright crawling.

    ``since`` / ``until`` (naive datetimes) filter by posted_at before persistence.
    API returns newest-first, so ``since`` also triggers an early stop.
    """
    job_id = JOB_IDS.get(job, 0)  # 0 = all jobs (API ignores jobId filter)
    payload_base = {
        "companyList": company_list or [],
        "jobId": job_id,
        "level": level,
        "order": order,
        "isNewJob": True,
    }

    all_ids: list[int] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(30)) as client:
        for page in range(1, pages + 1):
            payload = {**payload_base, "page": page}
            try:
                resp = await client.post(
                    API_URL,
                    headers=HEADERS_FACTORY(),
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                log.error("api_discover.request_failed", page=page, err=str(exc))
                continue

            if not data.get("success") or data.get("code") != 0:
                log.warning("api_discover.bad_response", page=page, code=data.get("code"), msg=data.get("msg"))
                break

            records = data.get("data", {}).get("records", [])
            if not records:
                log.info("api_discover.empty_page", page=page)
                break

            page_ids = await _persist_records(records, since=since, until=until)
            all_ids.extend(page_ids)
            log.info("api_discover.page", page=page, saved=len(page_ids), total_so_far=len(all_ids))

            # Early stop: newest-first ordering → when the last record is older than since, we're done.
            if since and records:
                last_record = records[-1]
                last_ts = (last_record.get("momentData", {}) or {}).get("createdAt", 0)
                if last_ts:
                    last_dt = _parse_posted_at(last_ts)
                    if last_dt and last_dt < since:
                        log.info("api_discover.since_reached", page=page, last_date=str(last_dt))
                        break

            await asyncio.sleep(delay)

    return all_ids


async def _persist_records(
    records: list[dict],
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[int]:
    """Write API records into posts table. Skips duplicates by source_url.

    ``since`` / ``until`` (naive datetimes) filter which records to persist.
    """
    ids: list[int] = []
    async with session_scope() as s:
        for r in records:
            md = r.get("momentData", {})
            extra = r.get("extraInfo", {})
            content_type = r.get("contentType", 0)
            uuid_val = md.get("uuid", "")
            content_id = extra.get("contentID_var") or str(md.get("id", ""))
            if content_type == 74 and uuid_val:
                url = f"https://www.nowcoder.com/feed/main/detail/{uuid_val}"
            else:
                url = f"https://www.nowcoder.com/discuss/{content_id}"
            title = md.get("title") or md.get("newTitle") or ""
            content = md.get("content") or ""
            posted_at = _parse_posted_at(md.get("createdAt", 0))

            if not content.strip():
                continue
            if not title.strip():
                continue

            # Date range filter
            if posted_at is not None:
                if since is not None and posted_at < since:
                    continue
                if until is not None and posted_at > until:
                    continue

            # Upsert: skip if URL already exists
            existing = (
                await s.execute(select(Post).where(Post.source_url == url))
            ).scalar_one_or_none()
            if existing is not None:
                ids.append(existing.id)
                continue

            post = Post(
                source_url=url,
                title=title,
                cleaned_text=content,
                posted_at=posted_at,
                extract_status="pending",
            )
            s.add(post)
            await s.flush()
            ids.append(post.id)

        await s.commit()
    return ids


# ═══════════════════════════════════════════════════════════════════
# 面经 tab 模式 — Playwright 点击 tab + AI 过滤
# ═══════════════════════════════════════════════════════════════════

MIANJING_FILTER_PROMPT = """判断以下牛客网帖子是否为面试经验（面经）。

是面经：包含公司名称、面试轮次、面试问题、技术考题等。
不是面经：简历点评、薪资讨论、实习吐槽、情感帖、内推信息。

标题：{title}
正文前 500 字：{content}

只回答一个字：是 或 否"""


async def filter_is_mianjing_post(title: str, content: str) -> bool:
    """用 DeepSeek AI (call_tool) 判断帖子是否为真实面经。

    Returns:
        True if the post is a genuine interview experience.
    """
    try:
        from ..llm.deepseek import call_tool

        result = await call_tool(
            messages=[{"role": "user", "content": MIANJING_FILTER_PROMPT.format(
                title=title, content=content[:500]
            )}],
            tools=[{
                "type": "function",
                "function": {
                    "name": "classify",
                    "description": "分类帖子是否为面经",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "is_mianjing": {"type": "boolean", "description": "是否为面经"},
                            "reason": {"type": "string", "description": "简短理由"},
                        },
                        "required": ["is_mianjing"],
                    },
                },
            }],
            tool_choice={"type": "function", "function": {"name": "classify"}},
            temperature=0.0,
            max_tokens=100,
            trace_name="mianjing_filter",
        )
        return result.arguments.get("is_mianjing", False)
    except Exception as exc:
        log.warning("mianjing_filter.ai_error", err=str(exc))
        return _keyword_is_mianjing(title, content)


def _keyword_is_mianjing(title: str, content: str) -> bool:
    """关键词回退判断（AI 不可用时）。"""
    text = title + " " + content[:500]
    score = 0
    for kw in ["面经", "一面", "二面", "三面", "四面", "手撕", "八股",
               "凉经", "算法题", "场景题", "反问"]:
        if kw in text:
            score += 3
    for kw in ["自我介绍", "面试官提问", "面试过程", "技术面", "hr面", "笔试"]:
        if kw in text:
            score += 2
    for kw in ["面试", "offer", "实习", "岗位"]:
        if kw in text:
            score += 1
    exclude = ["内推码", "内推链接", "简历点评", "工资条", "匿名发布功能"]
    for kw in exclude:
        if kw in text:
            score -= 4
    return score >= 4


# ─── 面经 tab URL 发现 ──────────────────────────────────

DISCUSS_RE = re.compile(r'/discuss/(\d{15,20})')
FEED_RE = re.compile(r'/feed/main/detail/([\w-]+)')


async def discover_urls_from_mianjing(pages: int) -> list[str]:
    """打开首页 → 点击面经 tab → 滚动加载 → 提取 discuss/feed URL。

    需要有效的 NOWCODER_COOKIE 环境变量。
    """
    from .playwright_runner import NowcoderFetcher

    all_urls: dict[str, None] = {}
    async with NowcoderFetcher() as fetcher:
        page = await fetcher._context.new_page()

        # 1. 打开首页
        await page.goto("https://www.nowcoder.com/", wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        await asyncio.sleep(1)

        # 2. 关弹窗
        try:
            await page.locator(".el-dialog__close").first.click(force=True, timeout=2000)
            await asyncio.sleep(0.5)
        except Exception:
            pass

        # 3. 点击面经 tab
        mj_tab = page.get_by_text("面经", exact=True).first
        if await mj_tab.count() == 0:
            log.error("mianjing_discover.no_tab", msg="未找到面经 tab，请检查登录态")
            await page.close()
            return []
        await mj_tab.click(force=True, timeout=5000)
        await asyncio.sleep(2)
        log.info("mianjing_discover.tab_clicked", url=page.url)

        # 4. 滚动加载
        for i in range(pages):
            html = await page.content()
            for pat in (DISCUSS_RE, FEED_RE):
                for m in pat.findall(html):
                    url = f"https://www.nowcoder.com/discuss/{m}" if pat is DISCUSS_RE else f"https://www.nowcoder.com/feed/main/detail/{m}"
                    all_urls[url] = None
            log.info("mianjing_discover.scroll", round=i+1, total=len(all_urls))
            if i < pages - 1:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(2.5)

        await page.close()

    return list(all_urls.keys())


async def discover_and_fetch_mianjing(
    *,
    pages: int = 3,
    ai_filter: bool = True,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[int]:
    """完整面经 tab 流程：发现 URL → AI 过滤 → 抓取内容 → 写入 PG。

    ``since`` / ``until``: filter persisted posts by posted_at (extracted from page HTML).

    Returns:
        list of post_ids persisted.
    """
    from .playwright_runner import NowcoderFetcher

    # 阶段 1: 发现 URL
    urls = await discover_urls_from_mianjing(pages)
    log.info("mianjing.discovered", count=len(urls))
    if not urls:
        return []

    # 阶段 2: 逐篇抓取 + AI 过滤 + 写入
    ids: list[int] = []
    async with NowcoderFetcher() as fetcher:
        for i, url in enumerate(urls):
            try:
                result = await fetcher.fetch(url)
                if "内容不存在" in result.html:
                    log.info("mianjing.fetch_skip", url=url, reason="内容不存在")
                    continue

                # 提取标题和正文
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(result.html, "html.parser")
                title = result.title or ""
                h1 = soup.find("h1")
                if h1:
                    title = h1.get_text(strip=True) or title

                # 正文
                content = ""
                for sel in ("article", "[class*='content']", ".post-topic-content", ".nc-post-content"):
                    el = soup.select_one(sel)
                    if el:
                        txt = el.get_text("\n", strip=True)
                        if len(txt) > 50:
                            content = txt
                            break
                if not content:
                    # 最后的 fallback: 取 body 文本
                    body = soup.find("body")
                    if body:
                        txt = body.get_text("\n", strip=True)
                        # 取前 5000 字符作为正文
                        content = txt[:5000] if len(txt) > 50 else ""
                if not content:
                    log.info("mianjing.fetch_skip", url=url, reason="无正文")
                    continue

                # 尝试提取发布时间（meta / text 里的日期）
                posted_at = _extract_posted_at_from_page(soup)

                # 日期过滤
                if posted_at is not None:
                    if since is not None and posted_at < since:
                        log.info("mianjing.fetch_skip", url=url, reason=f"too old: {posted_at}")
                        continue
                    if until is not None and posted_at > until:
                        log.info("mianjing.fetch_skip", url=url, reason=f"too new: {posted_at}")
                        continue

                # AI 过滤
                if ai_filter:
                    is_mj = await filter_is_mianjing_post(title, content)
                    if not is_mj:
                        log.info("mianjing.ai_reject", url=url, title=title[:40])
                        continue
                    log.info("mianjing.ai_accept", url=url, title=title[:40])

                # 写入数据库
                async with session_scope() as s:
                    existing = (await s.execute(
                        select(Post).where(Post.source_url == result.final_url)
                    )).scalar_one_or_none()
                    if existing:
                        ids.append(existing.id)
                        continue
                    post = Post(
                        source_url=result.final_url,
                        title=title,
                        cleaned_text=content,
                        posted_at=posted_at,
                        extract_status="pending",
                    )
                    s.add(post)
                    await s.flush()
                    ids.append(post.id)
                    await s.commit()

                log.info("mianjing.persisted", url=result.final_url, i=i+1, total=len(urls))

            except Exception as exc:
                log.error("mianjing.fetch_error", url=url, err=str(exc))
                continue

            await asyncio.sleep(1.5)

    log.info("mianjing.done", discovered=len(urls), persisted=len(ids))
    return ids


_DATE_RE = re.compile(
    r"((?:20\d{2})[-/年](?:0?[1-9]|1[0-2])[-/月](?:0?[1-9]|[12]\d|3[01])日?)"
)


def _extract_posted_at_from_page(soup) -> datetime | None:
    """Try to extract posted_at from page HTML (meta tags or text)."""
    # 1) meta tags
    for meta_sel in ('meta[property="article:published_time"]', 'meta[name="pubdate"]'):
        el = soup.select_one(meta_sel)
        if el and el.get("content"):
            try:
                return datetime.fromisoformat(el["content"].replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                pass

    # 2) text date patterns: "2026-01-15" or "2026年1月15日"
    text = soup.get_text(" ", strip=True)[:3000]
    for m in _DATE_RE.finditer(text):
        raw = m.group(1)
        # Normalize Chinese date → ISO
        raw = raw.replace("年", "-").replace("月", "-").replace("日", "")
        try:
            return datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            continue

    return None
