"""/posts — time-sorted post feed with company/position/category filters."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from .deps import get_session
from .schemas import FeedQuestionOut, PostFeedItem

router = APIRouter(tags=["feed"])


@router.get("/posts", response_model=list[PostFeedItem])
async def feed(
    company: str | None = None,
    position: str | None = None,
    category: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[PostFeedItem]:
    """Time-sorted post feed with optional company/position/category filters.

    Returns posts ordered by ``posted_at DESC NULLS LAST``.
    Only posts with ``extract_status = 'done'`` are included.
    Each post includes its associated questions (questions are fetched
    in a second query and merged in Python).
    """
    clauses = ["po.extract_status = 'done'"]
    params: dict[str, object] = {"limit": limit, "offset": offset}

    if company:
        clauses.append("c.canonical = :company")
        params["company"] = company
    if position:
        clauses.append("p.canonical = :position")
        params["position"] = position
    if category:
        clauses.append("p.category = :category")
        params["category"] = category

    where = " AND ".join(clauses)

    sql = f"""
    SELECT po.id, po.title, po.source_url, po.posted_at, po.cleaned_text,
           array_agg(DISTINCT c.canonical) FILTER (WHERE c.canonical IS NOT NULL) AS companies,
           array_agg(DISTINCT p.canonical) FILTER (WHERE p.canonical IS NOT NULL) AS positions,
           array_agg(DISTINCT q.round_type) FILTER (WHERE q.round_type IS NOT NULL) AS round_types,
           COUNT(DISTINCT q.id) FILTER (WHERE q.id IS NOT NULL) AS question_count
    FROM posts po
    JOIN post_company_position pcp ON pcp.post_id = po.id
    JOIN companies c ON c.id = pcp.company_id
    JOIN positions p ON p.id = pcp.position_id
    LEFT JOIN questions q ON q.post_id = po.id
    WHERE {where}
    GROUP BY po.id
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

    def _excerpt(text: str | None, max_chars: int = 200) -> str | None:
        if not text:
            return None
        return text[:max_chars] + "…" if len(text) > max_chars else text

    return [
        PostFeedItem(
            id=r["id"],
            title=r["title"],
            source_url=r["source_url"],
            posted_at=r["posted_at"],
            companies=list(r["companies"] or []),
            positions=list(r["positions"] or []),
            cleaned_text=r["cleaned_text"],
            excerpt=_excerpt(r["cleaned_text"]),
            round_types=list(r["round_types"] or []),
            question_count=r["question_count"],
            questions=q_map.get(r["id"], []),
        )
        for r in rows
    ]
