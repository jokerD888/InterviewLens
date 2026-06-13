"""Async repositories — thin functions over SQLModel ORM."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from .models import Post, PostCompanyPosition, Question


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
    now = datetime.now(timezone.utc).replace(tzinfo=None)
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
    # Only reset status for posts that weren't successfully extracted before
    if existing.extract_status not in ("done",):
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


async def set_quality_score(session: AsyncSession, post_id: int, score: int) -> None:
    await session.execute(
        update(Post).where(Post.id == post_id).values(quality_score=score)
    )


async def replace_questions(
    session: AsyncSession,
    post_id: int,
    rounds: list[dict],
) -> int:
    """Drop existing questions for a post and insert the new round/question rows.

    ``rounds`` is the JSON-shaped list from ExtractedPost. Embedding stays NULL
    here — D6 will backfill it. Returns total inserted question count.
    """
    await session.execute(delete(Question).where(Question.post_id == post_id))
    inserted = 0
    for r in rounds:
        round_no = int(r.get("round_no") or 1)
        round_type = r.get("round_type")
        for q in r.get("questions") or []:
            content = (q.get("content") or "").strip()
            if not content:
                continue
            session.add(
                Question(
                    post_id=post_id,
                    round_no=round_no,
                    round_type=round_type,
                    content=content,
                    category=q.get("category"),
                    answer_brief=q.get("answer_brief"),
                )
            )
            inserted += 1
    await session.flush()
    return inserted


async def replace_post_links(
    session: AsyncSession,
    post_id: int,
    *,
    company_ids: list[int],
    position_ids: list[int],
) -> int:
    """Replace post_company_position rows for ``post_id``.

    Cartesian product of (company × position) — required by the schema. Returns
    the number of rows inserted (deduplicated).
    """
    await session.execute(
        delete(PostCompanyPosition).where(PostCompanyPosition.post_id == post_id)
    )
    seen: set[tuple[int, int]] = set()
    pairs: list[dict] = []
    for cid in company_ids or []:
        for pid in position_ids or []:
            if (cid, pid) in seen:
                continue
            seen.add((cid, pid))
            pairs.append(
                {"post_id": post_id, "company_id": cid, "position_id": pid}
            )
    if not pairs:
        return 0
    stmt = pg_insert(PostCompanyPosition).values(pairs).on_conflict_do_nothing()
    await session.execute(stmt)
    await session.flush()
    return len(pairs)
