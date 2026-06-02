"""Async repositories — thin functions over SQLModel ORM."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from .models import Post


async def get_post_by_url(session: AsyncSession, url: str) -> Post | None:
    result = await session.execute(select(Post).where(Post.source_url == url))
    return result.scalar_one_or_none()


async def upsert_raw_post(
    session: AsyncSession,
    *,
    url: str,
    title: str | None,
    raw_html: str,
) -> Post:
    """Insert a new Post or update raw_html on an existing one.

    Returns the Post row (already flushed, with id populated).
    """
    existing = await get_post_by_url(session, url)
    now = datetime.now(timezone.utc)
    if existing is None:
        post = Post(
            source_url=url,
            title=title,
            raw_html=raw_html,
            fetched_at=now,
            extract_status="pending",
            extract_version=0,
        )
        session.add(post)
        await session.flush()
        return post

    existing.raw_html = raw_html
    existing.title = title or existing.title
    existing.fetched_at = now
    existing.extract_status = "pending"
    existing.extract_error = None
    await session.flush()
    return existing


async def set_cleaned_text(session: AsyncSession, post_id: int, text: str) -> None:
    await session.execute(
        update(Post)
        .where(Post.id == post_id)
        .values(cleaned_text=text)
    )


async def mark_extract_status(
    session: AsyncSession,
    post_id: int,
    *,
    status: str,
    error: str | None = None,
    version: int | None = None,
) -> None:
    values: dict[str, object] = {"extract_status": status, "extract_error": error}
    if version is not None:
        values["extract_version"] = version
    await session.execute(update(Post).where(Post.id == post_id).values(**values))
