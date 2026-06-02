"""Scorer node — pure function, runs after Normalizer."""
from __future__ import annotations

from typing import Any

from sqlmodel import select

from ...db import Post, session_scope, set_quality_score
from ...logging import log
from ...observability import node_span
from ...scoring import score_extracted
from ..state import PipelineState

NODE_NAME = "scorer"


async def run(state: PipelineState, *, trace: Any | None = None) -> PipelineState:
    post_id = state.get("post_id")
    log.info("node.start", node=NODE_NAME, post_id=post_id)

    async with node_span(
        node_name=NODE_NAME,
        trace=trace,
        input_payload={"post_id": post_id},
    ):
        if state.get("skip_reason") or post_id is None:
            return {"current_node": NODE_NAME}

        # Need posted_at for the recency component.
        async with session_scope() as session:
            post = (
                await session.execute(select(Post).where(Post.id == post_id))
            ).scalar_one_or_none()

        posted_at = post.posted_at if post is not None else None
        breakdown = score_extracted(state.get("extracted"), posted_at=posted_at)

        async with session_scope() as session:
            await set_quality_score(session, post_id, breakdown.total)

        log.info(
            "node.done",
            node=NODE_NAME,
            post_id=post_id,
            **breakdown.as_dict(),
        )
        return {
            "current_node": NODE_NAME,
            "quality_score": breakdown.total,
            "score_breakdown": breakdown.as_dict(),
        }
