"""Extractor node — wraps llm.extract_from_text for the graph."""
from __future__ import annotations

from typing import Any

from ...db import mark_extract_status, session_scope
from ...db.repositories import replace_questions
from ...llm import extract_from_text, get_extractor_prompt_version
from ...logging import log
from ...observability import node_span
from ..state import PipelineState

NODE_NAME = "extractor"


async def run(
    state: PipelineState,
    *,
    use_cache: bool = True,
    trace: Any | None = None,
) -> PipelineState:
    post_id = state.get("post_id")
    cleaned = state.get("cleaned_text") or ""
    log.info("node.start", node=NODE_NAME, post_id=post_id)

    async with node_span(
        node_name=NODE_NAME,
        trace=trace,
        input_payload={"post_id": post_id, "chars": len(cleaned)},
    ):
        if state.get("skip_reason"):
            return {"current_node": NODE_NAME}

        if post_id is None or not cleaned.strip():
            return {
                "current_node": NODE_NAME,
                "errors": [*state.get("errors", []), "extractor: no cleaned_text"],
                "skip_reason": "no_cleaned_text",
            }

        try:
            parsed, info = await extract_from_text(
                cleaned, post_id=post_id, use_cache=use_cache, trace=trace
            )
        except Exception as exc:  # noqa: BLE001
            log.error("node.extractor.failed", post_id=post_id, err=str(exc))
            async with session_scope() as session:
                await mark_extract_status(
                    session,
                    post_id,
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
            return {
                "current_node": NODE_NAME,
                "errors": [*state.get("errors", []), f"extractor: {exc}"],
                "skip_reason": "extract_failed",
            }

        rounds_json = [r.model_dump() for r in parsed.rounds]
        async with session_scope() as session:
            inserted = await replace_questions(session, post_id, rounds_json)
            await mark_extract_status(
                session,
                post_id,
                status="done",
                error=None,
                version=get_extractor_prompt_version(),
            )

        log.info(
            "node.done",
            node=NODE_NAME,
            post_id=post_id,
            questions=inserted,
            cache_hit=info.get("cache_hit"),
        )
        return {
            "current_node": NODE_NAME,
            "extracted": parsed.model_dump(),
            "extract_usage": info.get("usage"),
            "extract_cache_hit": bool(info.get("cache_hit")),
        }
