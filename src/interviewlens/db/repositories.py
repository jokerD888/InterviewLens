"""Async repositories — thin functions over SQLModel ORM."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import case, delete, func, update
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
    posted_at: datetime | None = None,
) -> Post:
    """Insert a new Post or update raw_html on an existing one.

    Returns the Post row (already flushed, with id populated).
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    stmt = pg_insert(Post).values(
        source_url=url,
        title=title,
        raw_html=raw_html,
        posted_at=posted_at,
        fetched_at=now,
        extract_status="pending",
        extract_version=0,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["source_url"],
        set_={
            "title": func.coalesce(stmt.excluded.title, Post.title),
            "raw_html": stmt.excluded.raw_html,
            "posted_at": func.coalesce(Post.posted_at, stmt.excluded.posted_at),
            "fetched_at": stmt.excluded.fetched_at,
            # Preserve successful extraction; retry incomplete/failed rows.
            "extract_status": case(
                (Post.extract_status == "done", Post.extract_status),
                else_="pending",
            ),
            "extract_error": case(
                (Post.extract_status == "done", Post.extract_error),
                else_=None,
            ),
        },
    ).returning(Post.id)
    post_id = (await session.execute(stmt)).scalar_one()
    post = await session.get(Post, post_id)
    if post is None:  # pragma: no cover - RETURNING/PK invariant
        raise RuntimeError(f"upserted post {post_id} could not be reloaded")
    return post


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


async def set_interview_date(
    session: AsyncSession,
    post_id: int,
    value: str | None,
) -> None:
    """Persist ExtractedPost's YYYY-MM value as the first day of that month."""
    interview_date: date | None = None
    if value and len(value) == 7 and value[4] == "-":
        try:
            interview_date = date.fromisoformat(f"{value}-01")
        except ValueError:
            # ExtractedPost validation normally removes invalid values; keep
            # this repository boundary defensive for direct callers.
            interview_date = None
    await session.execute(
        update(Post)
        .where(Post.id == post_id)
        .values(interview_date=interview_date)
    )


async def set_content_score(
    session: AsyncSession,
    post_id: int,
    score: int,
    *,
    version: int = 1,
) -> None:
    await session.execute(
        update(Post)
        .where(Post.id == post_id)
        .values(
            content_score=score,
            content_score_version=version,
            content_scored_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
    )


async def replace_questions(
    session: AsyncSession,
    post_id: int,
    rounds: list[dict],
) -> int:
    """Sync questions for a post, preserving existing embeddings and AI answers when content matches.

    Instead of blindly dropping all rows, this:
    1. Reuses matching existing questions by content (updating round_no, round_type,
       category, answer_brief, while PRESERVING embedding and answer_ai).
    2. Adds new questions that didn't exist before.
    3. Removes orphaned questions that no longer appear in the extracted rounds.
    """
    existing_result = await session.execute(
        select(Question).where(Question.post_id == post_id)
    )
    existing_rows = list(existing_result.scalars().all())

    # Map content -> queue of existing questions (handling potential duplicate questions within same post)
    existing_by_content: dict[str, list[Question]] = {}
    for eq in existing_rows:
        key = " ".join(eq.content.split())
        existing_by_content.setdefault(key, []).append(eq)

    retained_ids: set[int] = set()
    total_active = 0

    for r in rounds:
        round_no = int(r.get("round_no") or 1)
        round_type = r.get("round_type")
        for q in r.get("questions") or []:
            content = (q.get("content") or "").strip()
            if not content:
                continue

            key = " ".join(content.split())
            matched_pool = existing_by_content.get(key)

            if matched_pool:
                # Reuse existing question, preserving id, embedding, and answer_ai!
                matched_q = matched_pool.pop(0)
                matched_q.round_no = round_no
                matched_q.round_type = round_type
                matched_q.category = q.get("category")
                matched_q.answer_brief = q.get("answer_brief")
                if matched_q.id is not None:
                    retained_ids.add(matched_q.id)
                total_active += 1
            else:
                # Brand new question
                new_q = Question(
                    post_id=post_id,
                    round_no=round_no,
                    round_type=round_type,
                    content=content,
                    category=q.get("category"),
                    answer_brief=q.get("answer_brief"),
                )
                session.add(new_q)
                total_active += 1

    # Clean up orphaned questions that are no longer present
    orphaned_ids = [eq.id for eq in existing_rows if eq.id is not None and eq.id not in retained_ids]
    if orphaned_ids:
        await session.execute(
            delete(Question).where(Question.id.in_(orphaned_ids))
        )

    await session.flush()
    return total_active


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
