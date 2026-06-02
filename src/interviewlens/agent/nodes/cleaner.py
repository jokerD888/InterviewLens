"""Cleaner node — converts raw_html to cleaned_text, persists, may early-exit."""
from __future__ import annotations

from typing import Any

from ...crawler import clean_html
from ...db import mark_extract_status, session_scope, set_cleaned_text
from ...logging import log
from ...observability import node_span
from ..state import PipelineState

NODE_NAME = "cleaner"


async def run(
    state: PipelineState,
    *,
    min_chars: int = 200,
    trace: Any | None = None,
) -> PipelineState:
    log.info("node.start", node=NODE_NAME, post_id=state.get("post_id"))
    raw_html = state.get("raw_html") or ""
    post_id = state.get("post_id")

    async with node_span(
        node_name=NODE_NAME,
        trace=trace,
        input_payload={"post_id": post_id, "html_bytes": len(raw_html)},
    ):
        if not raw_html or post_id is None:
            return {
                "current_node": NODE_NAME,
                "skip_reason": "no_raw_html",
                "errors": [*state.get("errors", []), "cleaner: no raw_html"],
            }

        cleaned = clean_html(raw_html, url=state.get("final_url") or state.get("url"))

        if cleaned.char_count < min_chars:
            async with session_scope() as session:
                await mark_extract_status(
                    session,
                    post_id,
                    status="skipped",
                    error=f"too_short:{cleaned.char_count}<{min_chars}",
                )
            log.warning(
                "node.cleaner.skipped_short",
                post_id=post_id,
                chars=cleaned.char_count,
            )
            return {
                "current_node": NODE_NAME,
                "cleaned_text": cleaned.text,
                "char_count": cleaned.char_count,
                "skip_reason": "too_short",
            }

        async with session_scope() as session:
            await set_cleaned_text(session, post_id, cleaned.text)

        log.info("node.done", node=NODE_NAME, post_id=post_id, chars=cleaned.char_count)
        return {
            "current_node": NODE_NAME,
            "cleaned_text": cleaned.text,
            "char_count": cleaned.char_count,
        }
