"""Read-only browser acceptance: run against a running local web/API pair.

PYTHONPATH=src python tests/browser_admin_access.py --base-url http://127.0.0.1:3013
Requires Playwright Chromium and the configured ADMIN_API_TOKEN. Never writes
posts or starts crawl/LLM jobs; a simulated 401 tests session expiry locally.
"""

import argparse
import asyncio
import json

import httpx
from playwright.async_api import async_playwright, expect

from interviewlens.config import settings


async def main(base_url):
    assert len(settings.admin_api_token) >= 32, "Configure ADMIN_API_TOKEN before acceptance"
    base_url = base_url.rstrip("/")
    async with httpx.AsyncClient(trust_env=False) as client:
        for path in ("health", "jobs", "metrics", "position-posts"):
            response = await client.get(f"{base_url}/api/admin/{path}")
            assert response.status_code == 401, f"Unauthorized admin read accepted: {path}"

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            requests = []
            page.on("request", lambda r: requests.append(r.url) if "/api/admin/" in r.url else None)

            async def local_only(route):
                if route.request.url.startswith(base_url + "/"):
                    await route.continue_()
                else:
                    await route.abort()

            await page.route("**/*", local_only)

            async def assert_public_navigation():
                await expect(page.locator("nav")).to_be_visible()
                await expect(page.locator('nav a[href="/admin"]')).to_have_count(0)
                await expect(page.get_by_role("button", name="管理登录", exact=True)).to_have_count(
                    0
                )
                await expect(page.get_by_text("机房", exact=True)).to_have_count(0)

            for path in ("/", "/feed", "/search"):
                await page.goto(base_url + path, wait_until="domcontentloaded")
                await assert_public_navigation()
            assert not requests, "Public pages issued administrator requests"

            login_heading = page.get_by_role("heading", name="后台管理登录", exact=True)
            dashboard_heading = page.get_by_role("heading", name="管理后台", exact=True)
            await page.goto(base_url + "/admin", wait_until="domcontentloaded")
            await expect(login_heading).to_be_visible()
            await expect(page.get_by_text("手动入库", exact=True)).to_have_count(0)
            assert not requests, "Unsigned admin page loaded private data"
            robots = await page.locator('meta[name="robots"]').get_attribute("content")
            assert "noindex" in robots and "nofollow" in robots

            await page.get_by_label("管理员凭据", exact=True).fill(
                "invalid-credential-for-browser-acceptance"
            )
            await page.get_by_role("button", name="登录", exact=True).click()
            await expect(page.locator('section p[role="alert"]')).to_contain_text("凭据无效")
            await expect(dashboard_heading).to_have_count(0)
            assert all(url.endswith("/api/admin/health") for url in requests)

            async def login():
                await page.get_by_label("管理员凭据", exact=True).fill(settings.admin_api_token)
                await page.get_by_role("button", name="登录", exact=True).click()
                await expect(dashboard_heading).to_be_visible()
                await expect(page.get_by_text("postgres", exact=True)).to_be_visible()

            await login()
            await page.goto(base_url + "/", wait_until="domcontentloaded")
            await assert_public_navigation()
            await page.goto(base_url + "/admin", wait_until="domcontentloaded")
            await expect(dashboard_heading).to_be_visible()
            before_refresh = len(requests)
            await page.reload(wait_until="domcontentloaded")
            await expect(dashboard_heading).to_be_visible()
            assert len(requests) > before_refresh, "Restored token was not revalidated"

            async def expired(route):
                await route.fulfill(
                    status=401,
                    content_type="application/json",
                    body='{"detail":"Administrator login required"}',
                )

            await page.route("**/api/admin/health", expired)
            await page.evaluate("window.dispatchEvent(new Event('focus'))")
            await expect(login_heading).to_be_visible(timeout=12_000)
            await expect(page.locator('section p[role="alert"]')).to_contain_text("登录已失效")
            assert await page.evaluate("sessionStorage.getItem('il-admin-token') === null")
            await expect(page.get_by_text("手动入库", exact=True)).to_have_count(0)
            await page.unroute("**/api/admin/health", expired)

            await login()
            await page.get_by_role("button", name="退出登录", exact=True).click()
            await expect(login_heading).to_be_visible()
            await expect(page.get_by_text("postgres", exact=True)).to_have_count(0)
            assert await page.evaluate("sessionStorage.getItem('il-admin-token') === null")
            await page.reload(wait_until="domcontentloaded")
            await expect(login_heading).to_be_visible()
            await expect(dashboard_heading).to_have_count(0)

            print(
                json.dumps(
                    {
                        "public_navigation": "passed",
                        "unsigned_dashboard": "blocked",
                        "invalid_login": "blocked",
                        "valid_login": "passed",
                        "restore_validation": "passed",
                        "session_expiry": "passed",
                        "logout": "passed",
                        "direct_api_unauthorized": "blocked",
                        "mutations_performed": 0,
                    }
                )
            )
        finally:
            await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3013")
    args = parser.parse_args()
    try:
        asyncio.run(main(args.base_url))
    except Exception as exc:
        # Browser call logs must never print a credential if a fill action fails.
        detail = str(exc)
        if settings.admin_api_token:
            detail = detail.replace(settings.admin_api_token, "[REDACTED]")
        raise RuntimeError(detail) from None
