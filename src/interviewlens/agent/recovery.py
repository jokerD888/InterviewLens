"""Recovery helpers — re-run failed / pending posts through the graph."""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlmodel import select

from ..crawler import NowcoderFetcher
from ..db import Post, session_scope
from ..logging import log
from .graph import run_pipeline

# Bound provider work independently of crawler request spacing.
RESUME_CONCURRENCY = 4


async def resume_failed(
    *,
    statuses: tuple[str, ...] = ("failed", "pending"),
    limit: int = 50,
    use_cache: bool = True,
    fetcher: NowcoderFetcher | None = None,
    concurrency: int = RESUME_CONCURRENCY,
    stored_only: bool = False,
) -> list[dict]:
    """Re-run the graph for posts whose extract_status is in ``statuses``.

    A shared Playwright fetcher is reused across all retries to avoid the
    browser-startup cost on every URL.  Extractor LLM calls are run
    concurrently (controlled by ``concurrency``).
    """
    if limit <= 0 or concurrency <= 0:
        raise ValueError("limit and concurrency must be positive")
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    select(Post).from_statement(
                        text("""
                    SELECT p.* FROM posts p
                    LEFT JOIN post_processing pp ON pp.post_id=p.id
                    WHERE (p.extract_status = ANY(:statuses)
                       OR (pp.post_id IS NOT NULL AND pp.stages->>'index' IS DISTINCT FROM 'done'))
                      AND (NOT :stored OR NULLIF(p.cleaned_text,'') IS NOT NULL)
                      AND (pp.owner IS NULL OR pp.lease_until < NOW())
                    ORDER BY p.fetched_at DESC LIMIT :limit
                """)
                    ),
                    {"statuses": list(statuses), "limit": limit, "stored": stored_only},
                )
            )
            .scalars()
            .all()
        )

    if not rows:
        log.info("resume.empty", statuses=statuses)
        return []

    own_fetcher = fetcher is None and any(not row.cleaned_text for row in rows)
    if own_fetcher:
        fetcher = NowcoderFetcher()
        await fetcher.start()

    sem = asyncio.Semaphore(concurrency)

    async def _process_one(row: Post) -> dict:
        async with sem:
            try:
                final = await run_pipeline(
                    row.source_url, fetcher=fetcher, use_cache=use_cache, reuse_existing=True
                )
                return {
                    "post_id": row.id,
                    "url": row.source_url,
                    "skip_reason": final.get("skip_reason"),
                    "errors": final.get("errors", []),
                    "extracted": bool(final.get("extracted")),
                    "completed": not final.get("skip_reason") and not final.get("errors"),
                }
            except Exception as exc:  # noqa: BLE001  # ponytail: one post failing must not abort batch resume; broad catch intentional
                log.error("resume.row_failed", post_id=row.id, exc_info=True)
                return {"post_id": row.id, "url": row.source_url, "errors": [str(exc)]}

    try:
        summaries = await asyncio.gather(*(_process_one(row) for row in rows))
    finally:
        if own_fetcher and fetcher is not None:
            await fetcher.stop()
    return list(summaries)
