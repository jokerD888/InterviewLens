"""
牛客网面经爬虫 (Playwright 版 - 单会话)
打开首页 → 点击"面经" tab → 滚动加载 → 提取 URL → 逐篇抓取正文

用法：
    python nc_spider.py           → 爬 2 页面经流
    python nc_spider.py 3         → 爬 3 页面经流
    python nc_spider.py 3 --urls  → 仅发现 URL
需要：NOWCODER_COOKIE 环境变量
"""

import asyncio
import json
import os
import re
import sys
from urllib.parse import urljoin

OUTPUT_FILE = "nc_interviews.jsonl"
CHECKPOINT_FILE = "nc_checkpoint.json"
SAVE_EVERY = 5
TIMEOUT = 30_000
NETWORK_TIMEOUT = 15_000
DELAY = 1.5

DISCUSS_RE = re.compile(r'/discuss/(\d{15,20})')
FEED_RE = re.compile(r'/feed/main/detail/([\w-]+)')
HREF_RE = re.compile(r'href=["\\\']([^"\\\']+)["\\\']')


def parse_cookies(raw: str) -> list[dict]:
    cs = []
    for chunk in (raw or "").split(";"):
        chunk = chunk.strip()
        if "=" not in chunk:
            continue
        k, _, v = chunk.partition("=")
        k = k.strip()
        if k:
            cs.append({"name": k, "value": v.strip(), "domain": ".nowcoder.com",
                        "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax"})
    return cs


def extract_urls(html: str) -> list[str]:
    found = {}
    for pat in (DISCUSS_RE, FEED_RE):
        for m in pat.findall(html):
            url = f"https://www.nowcoder.com/discuss/{m}" if pat is DISCUSS_RE else f"https://www.nowcoder.com/feed/main/detail/{m}"
            found[url] = None
    return list(found.keys())


async def fetch_post(page, url: str) -> dict | None:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT)
        try:
            await page.wait_for_load_state("networkidle", timeout=NETWORK_TIMEOUT)
        except:
            pass

        html = await page.content()
        if "内容不存在" in html or "页面找不到了" in html:
            return None

        title = ""
        try:
            el = await page.query_selector("h1")
            if el:
                title = (await el.text_content() or "").strip()
        except:
            pass

        content = ""
        for s in [".post-topic-content", "article", '[class*="content"]']:
            try:
                el = await page.query_selector(s)
                if el:
                    t = (await el.text_content() or "").strip()
                    if len(t) > 50:
                        content = t
                        break
            except:
                pass
        if not content:
            return None

        author = ""
        try:
            el = await page.query_selector('[class*="nickname"], [class*="userName"], .post-user-name')
            if el:
                author = (await el.text_content() or "").strip()
        except:
            pass

        return {"url": page.url, "title": title, "content": content, "author": author}
    except Exception as e:
        print(f"      [ERR] {e}")
        return None


# ─── 断点 ──────────────────────────────────────────────
def load_cp():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"discovered_urls": [], "fetched_urls": [], "fetched_count": 0}


def save_cp(discovered, fetched_urls, fetched_count):
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump({"discovered_urls": discovered, "fetched_urls": fetched_urls, "fetched_count": fetched_count}, f, ensure_ascii=False)


def save_posts(posts, mode="a"):
    with open(OUTPUT_FILE, mode, encoding="utf-8") as f:
        for p in posts:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")


# ─── 主流程 ────────────────────────────────────────────

async def main_async(scrolls: int, urls_only: bool = False):
    cookie = os.environ.get("NOWCODER_COOKIE", "")
    if not cookie:
        print("[ERROR] 未设置 NOWCODER_COOKIE")
        return

    cp = load_cp()

    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
            locale="zh-CN", viewport={"width": 1366, "height": 900},
        )
        await ctx.add_cookies(parse_cookies(cookie))
        print(f"[INFO] Cookie 已注入")

        # ── 阶段 1: 发现 URL ──
        if cp.get("discovered_urls"):
            urls = cp["discovered_urls"]
            print(f"[DISCOVER] 复用断点: {len(urls)} URL")
        else:
            page = await ctx.new_page()
            await page.goto("https://www.nowcoder.com/", wait_until="domcontentloaded", timeout=TIMEOUT)
            try:
                await page.wait_for_load_state("networkidle", timeout=NETWORK_TIMEOUT)
            except:
                pass
            await asyncio.sleep(1)

            uid = await page.evaluate("() => localStorage.getItem('nc_userId')")
            print(f"[LOGIN] nc_userId={uid} {'✅' if uid and uid != '-1' else '❌'}")

            try:
                await page.locator(".el-dialog__close").first.click(force=True, timeout=2000)
                await asyncio.sleep(0.5)
            except:
                pass

            # 点击面经
            print("[TAB] 点击面经...")
            await page.get_by_text("面经", exact=True).first.click(force=True, timeout=5000)
            await asyncio.sleep(2)
            print(f"       URL: {page.url}")

            # 滚动加载
            all_urls = {}
            for i in range(scrolls):
                html = await page.content()
                for u in extract_urls(html):
                    all_urls[u] = None
                print(f"       滚动 {i+1}/{scrolls}: {len(all_urls)} URL")
                if i < scrolls - 1:
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(2.5)

            urls = list(all_urls.keys())
            print(f"\n[DISCOVER] 共 {len(urls)} 个面经 URL")
            save_cp(urls, [], 0)
            await page.close()

        if urls_only:
            for u in urls:
                print(f"  {u}")
            await ctx.close()
            await browser.close()
            return

        # ── 阶段 2: 抓取（用项目自带的 NowcoderFetcher）──
        from interviewlens.crawler.playwright_runner import NowcoderFetcher, FetchResult
        from bs4 import BeautifulSoup

        already = set(cp.get("fetched_urls", []))
        remaining = [u for u in urls if u not in already]
        print(f"[FETCH] 已抓 {len(already)}，待抓 {len(remaining)}")

        if not remaining:
            await ctx.close()
            await browser.close()
            return

        buf = []
        fc = cp.get("fetched_count", 0)
        fu = list(cp.get("fetched_urls", []))

        async with NowcoderFetcher() as nf:
            for i, url in enumerate(remaining):
                print(f"[{i+1}/{len(remaining)}] {url.split('/')[-1]}", flush=True)
                fu.append(url)
                try:
                    r: FetchResult = await nf.fetch(url)
                    if '内容不存在' in r.html:
                        print(f"         ⏭️  内容不存在")
                        continue

                    soup = BeautifulSoup(r.html, 'html.parser')
                    title = (soup.find('h1') or '').text.strip() if soup.find('h1') else r.title
                    # 正文
                    content = ''
                    for s in ['.post-topic-content', 'article', '[class*="content"]']:
                        el = soup.select_one(s)
                        if el and len(el.text.strip()) > 50:
                            content = el.text.strip()
                            break
                    if not content:
                        print(f"         ⏭️  无正文")
                        continue

                    author = ''
                    au = soup.select_one('[class*="nickname"], [class*="userName"], .post-user-name')
                    if au:
                        author = au.text.strip()

                    post = {'url': r.final_url, 'title': title, 'content': content, 'author': author}
                    buf.append(post)
                    fc += 1
                    print(f"         ✅ {title[:50]}")
                except Exception as e:
                    print(f"         ❌ {e}")

                if len(buf) >= SAVE_EVERY:
                    mode = "w" if not os.path.exists(OUTPUT_FILE) or os.path.getsize(OUTPUT_FILE) == 0 else "a"
                    save_posts(buf, mode)
                    print(f"  💾 {len(buf)} 条")
                    save_cp(urls, fu, fc)
                    buf = []
                if i < len(remaining) - 1:
                    await asyncio.sleep(DELAY)

        if buf:
            mode = "w" if not os.path.exists(OUTPUT_FILE) or os.path.getsize(OUTPUT_FILE) == 0 else "a"
            save_posts(buf, mode)
            save_cp(urls, fu, fc)

        await page.close()
        await ctx.close()
        await browser.close()

    print(f"\n{'=' * 50}")
    print(f"✅ 完成！{cp.get('fetched_count', 0) + (fc - cp.get('fetched_count', 0))} 条面经 → {os.path.abspath(OUTPUT_FILE)}")
    print(f"{'=' * 50}")


def main():
    scrolls = 2
    urls_only = False
    args = sys.argv[1:]
    if "--urls" in args:
        urls_only = True
        args.remove("--urls")
    if args:
        try:
            scrolls = int(args[0])
        except ValueError:
            print("用法: python nc_spider.py [滚动次数] [--urls]")
            return
    asyncio.run(main_async(scrolls, urls_only))


if __name__ == "__main__":
    main()
