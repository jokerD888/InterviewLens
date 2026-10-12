"""Compatibility entry point using the durable pipeline shared by Celery/resume."""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import select

from ..config import settings
from ..db import Post, mark_extract_status, session_scope
from .schema import ExtractedPost


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
    """Process stored text, including recoverable normalization/scoring/indexing."""
    async with session_scope() as session:
        post = (await session.execute(select(Post).where(Post.id == post_id))).scalar_one_or_none()
        if post is None:
            return ExtractOutcome(post_id=post_id, success=False, error="post not found")
        if not (post.cleaned_text or "").strip():
            await mark_extract_status(
                session, post_id, status="skipped", error="empty_cleaned_text"
            )
            return ExtractOutcome(post_id=post_id, success=False, error="empty_cleaned_text")
        url = post.source_url
    # Lazy import avoids the graph -> extractor -> llm import cycle.
    from ..agent.graph import run_pipeline

    final = await run_pipeline(url, use_cache=use_cache, reuse_existing=True)
    parsed = ExtractedPost.model_validate(final["extracted"]) if final.get("extracted") else None
    error = final.get("skip_reason") or "; ".join(final.get("errors") or [])
    return ExtractOutcome(
        post_id=post_id,
        success=not bool(error),
        questions_inserted=parsed.total_questions if parsed else 0,
        cache_hit=bool(final.get("extract_cache_hit")),
        usage=final.get("extract_usage"),
        model=settings.deepseek_model_chat,
        error=error or None,
        parsed=parsed,
    )
