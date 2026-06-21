"""Recovery helpers — re-run failed / pending posts through the graph."""
from __future__ import annotations

import asyncio

from sqlmodel import select

from ..crawler import NowcoderFetcher
from ..db import Post, session_scope
from ..logging import log
from .graph import build_graph
from .state import make_initial_state

# DeepSeek flash allows 2500 concurrent; we use a conservative 20
RESUME_CONCURRENCY = 20


async def resume_failed(
    *,
    statuses: tuple[str, ...] = ("failed", "pending"),
    limit: int = 50,
    use_cache: bool = True,
    fetcher: NowcoderFetcher | None = None,
    concurrency: int = RESUME_CONCURRENCY,
) -> list[dict]:
    """Re-run the graph for posts whose extract_status is in ``statuses``.

    A shared Playwright fetcher is reused across all retries to avoid the
    browser-startup cost on every URL.  Extractor LLM calls are run
    concurrently (controlled by ``concurrency``).
    """
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(Post)
                .where(Post.extract_status.in_(statuses))  # type: ignore[attr-defined]
                .order_by(Post.fetched_at.desc())
                .limit(limit)
            )
        ).scalars().all()

    if not rows:
        log.info("resume.empty", statuses=statuses)
        return []

    own_fetcher = fetcher is None
    if own_fetcher:
        fetcher = NowcoderFetcher()
        await fetcher.start()

    app = build_graph(fetcher=fetcher, use_cache=use_cache, reuse_existing=True)
    sem = asyncio.Semaphore(concurrency)

    async def _process_one(row: Post) -> dict:
        async with sem:
            try:
                final = await app.ainvoke(make_initial_state(row.source_url, post_id=row.id))
                return {
                    "post_id": row.id,
                    "url": row.source_url,
                    "skip_reason": final.get("skip_reason"),
                    "errors": final.get("errors", []),
                    "extracted": bool(final.get("extracted")),
                }
            except Exception as exc:  # noqa: BLE001
                log.error("resume.row_failed", post_id=row.id, err=str(exc))
                return {"post_id": row.id, "url": row.source_url, "errors": [str(exc)]}

    try:
        summaries = await asyncio.gather(*(_process_one(row) for row in rows))
    finally:
        if own_fetcher and fetcher is not None:
            await fetcher.stop()
    return list(summaries)
