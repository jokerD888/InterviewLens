"""Extractor node — wraps llm.extract_from_text for the graph."""

from __future__ import annotations

import asyncio
from typing import Any

import openai
from pydantic import ValidationError

from ...crawler.cleaner import strip_nowcoder_noise
from ...db import mark_extract_status, session_scope, set_interview_date
from ...db.position_profiles import save_profiles
from ...db.repositories import replace_questions
from ...llm import extract_from_text, get_extractor_prompt_version
from ...logging import log
from ...observability import node_span
from ..processing import fence_state, save_extraction
from ..state import PipelineState

NODE_NAME = "extractor"


async def run(
    state: PipelineState,
    *,
    use_cache: bool = True,
    trace: Any | None = None,
) -> PipelineState:
    post_id = state.get("post_id")
    cleaned = strip_nowcoder_noise(state.get("cleaned_text") or "")
    if state.get("title"):
        cleaned = f"{state['title']}\n{cleaned}"
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
        except (openai.APIError, asyncio.TimeoutError, RuntimeError, ValidationError) as exc:
            # Layer C: external LLM/JSON failure → mark post failed, skip;
            # logic bugs (TypeError/AttributeError) bubble up to the DLQ.
            log.error("node.extractor.failed", post_id=post_id, exc_info=True)
            async with session_scope() as session:
                await fence_state(session, state)
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
            await fence_state(session, state)
            refs = {}
            inserted = await replace_questions(session, post_id, rounds_json, question_refs=refs)
            if state.get("processing_owner"):
                from sqlalchemy import text

                await session.execute(
                    text("DELETE FROM post_question_refs WHERE post_id=:id"), {"id": post_id}
                )
                for (ri, qi), question in refs.items():
                    await session.execute(
                        text("""
                        INSERT INTO post_question_refs(post_id,round_index,question_index,question_id)
                        VALUES(:post,:round,:question,:id)
                    """),
                        {"post": post_id, "round": ri, "question": qi, "id": question.id},
                    )
            await save_profiles(session, post_id, parsed.position_profiles, cleaned)
            await save_extraction(
                session, post_id, state.get("processing_owner"), parsed.model_dump()
            )
            await set_interview_date(session, post_id, parsed.interview_date)
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
