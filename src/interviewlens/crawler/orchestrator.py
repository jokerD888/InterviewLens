"""End-to-end orchestration: fetch → clean → persist (D2 scope only)."""
from __future__ import annotations

from dataclasses import dataclass

from .playwright_runner import NowcoderFetcher
from .cleaner import clean_html
from ..db import (
    mark_extract_status,
    session_scope,
    set_cleaned_text,
    upsert_raw_post,
)
from ..logging import log


@dataclass(slots=True)
class CrawlOutcome:
    post_id: int
    url: str
    final_url: str
    title: str | None
    char_count: int
    skipped: bool = False
    skip_reason: str | None = None


async def crawl_one(
    url: str,
    *,
    fetcher: NowcoderFetcher | None = None,
    min_chars: int = 200,
) -> CrawlOutcome:
    """Fetch a single Nowcoder URL and persist raw_html + cleaned_text.

    If ``fetcher`` is omitted, a one-shot Playwright session is created.
    """
    own_fetcher = fetcher is None
    if own_fetcher:
        fetcher = NowcoderFetcher()
        await fetcher.start()
    assert fetcher is not None

    try:
        result = await fetcher.fetch(url)
        cleaned = clean_html(result.html, url=result.final_url)

        async with session_scope() as session:
            post = await upsert_raw_post(
                session,
                url=result.final_url,
                title=result.title or cleaned.title,
                raw_html=result.html,
            )
            assert post.id is not None

            if cleaned.char_count < min_chars:
                await mark_extract_status(
                    session,
                    post.id,
                    status="skipped",
                    error=f"too_short:{cleaned.char_count}<{min_chars}",
                )
                log.warning(
                    "crawl.skipped_short",
                    url=url,
                    post_id=post.id,
                    chars=cleaned.char_count,
                )
                return CrawlOutcome(
                    post_id=post.id,
                    url=url,
                    final_url=result.final_url,
                    title=post.title,
                    char_count=cleaned.char_count,
                    skipped=True,
                    skip_reason="too_short",
                )

            await set_cleaned_text(session, post.id, cleaned.text)

        log.info(
            "crawl.persisted",
            url=url,
            post_id=post.id,
            chars=cleaned.char_count,
        )
        return CrawlOutcome(
            post_id=post.id,
            url=url,
            final_url=result.final_url,
            title=post.title,
            char_count=cleaned.char_count,
        )
    finally:
        if own_fetcher:
            await fetcher.stop()
