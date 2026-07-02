"""End-to-end extract orchestration: post_id → LLM → persist questions."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import openai
from sqlmodel import select

from ..db import (
    Post,
    mark_extract_status,
    replace_questions,
    session_scope,
)
from .extractor import extract_from_text
from .prompts import get_extractor_prompt_version
from .schema import ExtractedPost
from ..logging import log


@dataclass(slots=True)
class ExtractOutcome:
    post_id: int
    success: bool
    questions_inserted: int = 0
    cache_hit: bool = False
    usage: dict | None = None
    model: str | None = None
    error: str | None = None
    parsed: ExtractedPost | None = None


async def extract_post(post_id: int, *, use_cache: bool = True) -> ExtractOutcome:
    """Read posts.cleaned_text → call Extractor → write questions table.

    Updates ``posts.extract_status`` to 'done' on success or 'failed' on error.
    Skips quietly when cleaned_text is missing.
    """
    async with session_scope() as session:
        post = (
            await session.execute(select(Post).where(Post.id == post_id))
        ).scalar_one_or_none()
        if post is None:
            return ExtractOutcome(post_id=post_id, success=False, error="post not found")
        cleaned = post.cleaned_text or ""

    if not cleaned.strip():
        async with session_scope() as session:
            await mark_extract_status(
                session, post_id, status="skipped", error="empty_cleaned_text"
            )
        return ExtractOutcome(
            post_id=post_id, success=False, error="empty_cleaned_text"
        )

    try:
        parsed, info = await extract_from_text(
            cleaned, post_id=post_id, use_cache=use_cache
        )
    except (openai.APIError, asyncio.TimeoutError, RuntimeError) as exc:
        # Layer C: external LLM/JSON failure → mark failed; logic bugs bubble.
        log.error("extract.failed", post_id=post_id, exc_info=True)
        async with session_scope() as session:
            await mark_extract_status(
                session,
                post_id,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
        return ExtractOutcome(
            post_id=post_id, success=False, error=f"{type(exc).__name__}: {exc}"
        )

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
        "extract.done",
        post_id=post_id,
        questions=inserted,
        cache_hit=info.get("cache_hit"),
        usage=info.get("usage"),
    )
    return ExtractOutcome(
        post_id=post_id,
        success=True,
        questions_inserted=inserted,
        cache_hit=bool(info.get("cache_hit")),
        usage=info.get("usage"),
        model=info.get("model"),
        parsed=parsed,
    )
