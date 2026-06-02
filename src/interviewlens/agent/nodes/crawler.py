"""Crawler node — fetches the URL via Playwright and persists raw_html.

If the URL has been crawled successfully before (cleaned_text non-empty),
the node returns the existing post_id and skips refetching when ``reuse``
is True.
"""
from __future__ import annotations

from typing import Any

from sqlmodel import select

from ...crawler import NowcoderFetcher
from ...db import (
    Post,
    session_scope,
    upsert_raw_post,
)
from ...logging import log
from ...observability import node_span
from ..state import PipelineState

NODE_NAME = "crawler"


async def run(
    state: PipelineState,
    *,
    fetcher: NowcoderFetcher | None = None,
    reuse: bool = True,
    trace: Any | None = None,
) -> PipelineState:
    url = state["url"]
    log.info("node.start", node=NODE_NAME, url=url)
    state["current_node"] = NODE_NAME

    async with node_span(node_name=NODE_NAME, trace=trace, input_payload={"url": url}):
        if reuse:
            async with session_scope() as session:
                existing = (
                    await session.execute(select(Post).where(Post.source_url == url))
                ).scalar_one_or_none()
                if existing is not None and existing.raw_html and existing.cleaned_text:
                    log.info(
                        "node.crawler.reuse",
                        post_id=existing.id,
                        chars=len(existing.cleaned_text),
                    )
                    return {
                        "post_id": existing.id,
                        "raw_html": existing.raw_html,
                        "cleaned_text": existing.cleaned_text,
                        "title": existing.title,
                        "final_url": existing.source_url,
                    }

        own_fetcher = fetcher is None
        if own_fetcher:
            fetcher = NowcoderFetcher()
            await fetcher.start()
        assert fetcher is not None

        try:
            result = await fetcher.fetch(url)
        finally:
            if own_fetcher:
                await fetcher.stop()

        async with session_scope() as session:
            post = await upsert_raw_post(
                session,
                url=result.final_url,
                title=result.title,
                raw_html=result.html,
            )
            post_id = post.id

        log.info("node.done", node=NODE_NAME, post_id=post_id, bytes=len(result.html))
        return {
            "post_id": post_id,
            "raw_html": result.html,
            "title": result.title,
            "final_url": result.final_url,
        }
