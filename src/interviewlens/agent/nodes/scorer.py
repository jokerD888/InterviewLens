"""Scorer node — pure function, runs after Normalizer."""

from __future__ import annotations

from typing import Any

from ...db import session_scope, set_content_score
from ...logging import log
from ...observability import node_span
from ...scoring import CONTENT_SCORE_VERSION, score_content
from ..processing import fence_state
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

        breakdown = score_content(state.get("extracted"))

        async with session_scope() as session:
            await fence_state(session, state)
            await set_content_score(
                session,
                post_id,
                breakdown.total,
                version=CONTENT_SCORE_VERSION,
            )

        log.info(
            "node.done",
            node=NODE_NAME,
            post_id=post_id,
            **breakdown.as_dict(),
            content_score_version=CONTENT_SCORE_VERSION,
        )
        return {
            "current_node": NODE_NAME,
            "content_score": breakdown.total,
            "content_score_breakdown": breakdown.as_dict(),
            # Compatibility for callers that still read the old pipeline key.
            "quality_score": breakdown.total,
            "score_breakdown": breakdown.as_dict(),
        }
