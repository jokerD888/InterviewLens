"""//posts — time-sorted post feed with company/position/category filters."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from ..crawler.cleaner import strip_nowcoder_noise
from ..position_taxonomy import TAXONOMY_VERSION, PositionCategory
from ..scoring import freshness_case_sql
from .deps import get_session
from .position_filters import profile_predicate
from .schemas import FeedQuestionOut, PostFeedItem

router = APIRouter(tags=["feed"])


@router.get("/posts", response_model=list[PostFeedItem])
async def feed(
    company: str | None = None,
    position: str | None = None,
    category: str | None = None,
    position_category: PositionCategory | None = None,
    specializations: Annotated[list[str] | None, Query()] = None,
    domains: Annotated[list[str] | None, Query()] = None,
    skills: Annotated[list[str] | None, Query()] = None,
    include_unreviewed: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    session: AsyncSession = Depends(get_session),
) -> list[PostFeedItem]:
    """Time-sorted post feed with optional company/position/category filters.

    Returns posts ordered by ``posted_at DESC NULLS LAST``.
    Only posts with ``extract_status = 'done'`` **and at least one extracted
    question** are included — posts without questions are noise for the feed.
    Each post includes its associated questions (questions are fetched
    in a second query and merged in Python).
    """
    clauses = ["po.extract_status = 'done'"]
    params: dict[str, object] = {
        "limit": limit,
        "offset": offset,
        "as_of": datetime.now(timezone.utc),
    }

    if company:
        clauses.append("c.canonical = :company")
        params["company"] = company
    if position:
        clauses.append("p.canonical = :position")
        params["position"] = position
    if category:
        clauses.append("p.category = :category")
        params["category"] = category

    predicate = profile_predicate(position_category, specializations, domains, skills, include_unreviewed, params)
    if predicate:
        clauses.append(predicate)

    where = " AND ".join(clauses)

    freshness = freshness_case_sql()
    sql = f"""
    SELECT po.id, po.title, po.source_url, po.posted_at, po.interview_date, po.cleaned_text,
           po.content_score,
           {freshness} AS freshness_score,
           CASE WHEN po.content_score IS NULL THEN NULL
                ELSE po.content_score + {freshness}
           END AS ranking_score,
           array_agg(DISTINCT c.canonical) FILTER (WHERE c.canonical IS NOT NULL) AS companies,
           array_agg(DISTINCT p.canonical) FILTER (WHERE p.canonical IS NOT NULL) AS positions,
           array_agg(DISTINCT q.round_type) FILTER (WHERE q.round_type IS NOT NULL) AS round_types,
           COUNT(DISTINCT q.id) FILTER (WHERE q.id IS NOT NULL) AS question_count
    FROM posts po
    LEFT JOIN post_companies pc ON pc.post_id = po.id
    LEFT JOIN companies c ON c.id = pc.company_id
    LEFT JOIN post_company_position pcp ON pcp.post_id = po.id
    LEFT JOIN positions p ON p.id = pcp.position_id
    LEFT JOIN questions q ON q.post_id = po.id
    WHERE {where}
    GROUP BY po.id
    HAVING COUNT(DISTINCT q.id) FILTER (WHERE q.id IS NOT NULL) > 0
    ORDER BY po.posted_at DESC NULLS LAST
    LIMIT :limit OFFSET :offset
    """
    rows = (await session.execute(sa_text(sql), params)).mappings().all()

    if not rows:
        return []

    post_ids = [r["id"] for r in rows]

    q_sql = """
    SELECT q.id, q.post_id, q.round_no, q.round_type, q.content, q.answer_brief, q.answer_ai
    FROM questions q
    WHERE q.post_id = ANY(:post_ids)
    ORDER BY q.round_no NULLS LAST, q.id
    """
    q_rows = (await session.execute(sa_text(q_sql), {"post_ids": post_ids})).mappings().all()

    q_map: dict[int, list[FeedQuestionOut]] = {pid: [] for pid in post_ids}
    for qr in q_rows:
        q_map[qr["post_id"]].append(FeedQuestionOut(**dict(qr)))

    profile_rows = (await session.execute(sa_text("""
        SELECT post_id,payload,origin FROM post_position_profiles
        WHERE post_id = ANY(:post_ids) AND taxonomy_version=:version ORDER BY ordinal
    """), {"post_ids": post_ids, "version": TAXONOMY_VERSION})).mappings().all()
    profile_map: dict[int, list[dict]] = {pid: [] for pid in post_ids}
    for profile_row in profile_rows:
        profile_map[profile_row["post_id"]].append({**profile_row["payload"], "origin": profile_row["origin"]})

    def _excerpt(questions: list[FeedQuestionOut], cleaned: str | None, max_chars: int = 200) -> str | None:
        """Build excerpt from the first question, falling back to cleaned text."""
        if questions:
            q = questions[0].content
            return q[:max_chars] + "…" if len(q) > max_chars else q
        if not cleaned:
            return None
        return cleaned[:max_chars] + "…" if len(cleaned) > max_chars else cleaned

    return [
        PostFeedItem(
            id=r["id"],
            position_profiles=profile_map[r["id"]],
            title=r["title"],
            source_url=r["source_url"],
            posted_at=r["posted_at"],
            interview_date=r["interview_date"],
            content_score=r["content_score"],
            freshness_score=r["freshness_score"],
            ranking_score=r["ranking_score"],
            companies=list(r["companies"] or []),
            positions=list(r["positions"] or []),
            cleaned_text=strip_nowcoder_noise(r["cleaned_text"]) if r["cleaned_text"] else None,
            excerpt=_excerpt(q_map.get(r["id"], []), r["cleaned_text"]),
            round_types=list(r["round_types"] or []),
            question_count=r["question_count"],
            questions=q_map.get(r["id"], []),
        )
        for r in rows
    ]
