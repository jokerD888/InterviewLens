"""Visible, paginated post metadata; questions are loaded on expansion."""
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.processing_reads import VISIBLE_POST_SQL
from ..position_taxonomy import TAXONOMY_VERSION, PositionCategory
from ..scoring import freshness_case_sql
from .deps import get_session
from .position_filters import profile_predicate
from .schemas import FeedQuestionOut, PostFeedItem
from .public_data import public_profile

router = APIRouter(tags=["feed"])


@router.get("/posts", response_model=list[PostFeedItem])
async def feed(
    company: str | None = None, position: str | None = None, category: str | None = None,
    position_category: PositionCategory | None = None,
    specializations: Annotated[list[str] | None, Query()] = None,
    domains: Annotated[list[str] | None, Query()] = None,
    skills: Annotated[list[str] | None, Query()] = None,
    include_unreviewed: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
    session: AsyncSession = Depends(get_session),
) -> list[PostFeedItem]:
    clauses = [VISIBLE_POST_SQL]
    params = {"limit": limit, "offset": offset, "as_of": datetime.now(timezone.utc)}
    if company:
        clauses.append("EXISTS(SELECT 1 FROM post_companies pc JOIN companies c ON c.id=pc.company_id WHERE pc.post_id=po.id AND c.canonical=:company)")
        params["company"] = company
    if position or category:
        conditions = ["pcp.post_id=po.id"]
        if position:
            conditions.append("p.canonical=:position")
            params["position"] = position
        if category:
            conditions.append("p.category=:category")
            params["category"] = category
        clauses.append("EXISTS(SELECT 1 FROM post_company_position pcp JOIN positions p ON p.id=pcp.position_id WHERE " + " AND ".join(conditions) + ")")
    predicate = profile_predicate(position_category, specializations, domains, skills, include_unreviewed, params)
    if predicate:
        clauses.append(predicate)
    freshness = freshness_case_sql()
    sql = f"""
    WITH page AS MATERIALIZED (
        SELECT po.id,po.title,po.source_url,po.posted_at,po.interview_date,po.content_score
        FROM posts po WHERE {' AND '.join(clauses)}
        ORDER BY po.posted_at DESC NULLS LAST,po.id DESC LIMIT :limit OFFSET :offset
    )
    SELECT po.id,po.title,po.source_url,po.posted_at,po.interview_date,po.content_score,
           {freshness} AS freshness_score,
           CASE WHEN po.content_score IS NULL THEN NULL ELSE po.content_score+{freshness} END AS ranking_score,
           co.companies,ps.positions,qs.round_types,qs.question_count,preview.content AS excerpt
    FROM page po
    LEFT JOIN LATERAL (SELECT array_agg(DISTINCT c.canonical) AS companies FROM post_companies pc JOIN companies c ON c.id=pc.company_id WHERE pc.post_id=po.id) co ON true
    LEFT JOIN LATERAL (SELECT array_agg(DISTINCT p.canonical) AS positions FROM post_company_position pcp JOIN positions p ON p.id=pcp.position_id WHERE pcp.post_id=po.id) ps ON true
    LEFT JOIN LATERAL (SELECT count(*) AS question_count,array_agg(DISTINCT q.round_type) FILTER(WHERE q.round_type IS NOT NULL) AS round_types FROM questions q WHERE q.post_id=po.id) qs ON true
    LEFT JOIN LATERAL (SELECT q.content FROM questions q WHERE q.post_id=po.id ORDER BY q.round_no NULLS LAST,q.id LIMIT 1) preview ON true
    ORDER BY po.posted_at DESC NULLS LAST,po.id DESC
    """
    rows = (await session.execute(text(sql), params)).mappings().all()
    if not rows:
        return []
    profiles = (await session.execute(text("""
        SELECT post_id,payload FROM post_position_profiles
        WHERE post_id=ANY(:ids) AND taxonomy_version=:version ORDER BY ordinal
    """), {"ids": [row["id"] for row in rows], "version": TAXONOMY_VERSION})).mappings().all()
    profile_map = {}
    for profile in profiles:
        profile_map.setdefault(profile["post_id"], []).append(public_profile(profile["payload"]))
    result = []
    for row in rows:
        item = dict(row)
        item["companies"] = item["companies"] or []
        item["positions"] = item["positions"] or []
        item["round_types"] = item["round_types"] or []
        preview = FeedQuestionOut(id=0, content=item.get("excerpt") or "").content
        item["excerpt"] = preview[:200] + ("…" if len(preview) > 200 else "") if preview else None
        result.append(PostFeedItem(**item, position_profiles=profile_map.get(row["id"], [])))
    return result


@router.get("/posts/{post_id}/questions", response_model=list[FeedQuestionOut])
async def post_questions(
    post_id: Annotated[int, Path(ge=1, le=9223372036854775807)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
    session: AsyncSession = Depends(get_session),
):
    visible = (await session.execute(text(f"SELECT 1 FROM posts po WHERE po.id=:id AND {VISIBLE_POST_SQL}"), {"id": post_id})).first()
    if not visible:
        raise HTTPException(404, "post not found")
    rows = (await session.execute(text("""
        SELECT id,round_no,round_type,content,answer_brief,answer_ai FROM questions
        WHERE post_id=:id ORDER BY round_no NULLS LAST,id LIMIT :limit OFFSET :offset
    """), {"id": post_id, "limit": limit, "offset": offset})).mappings().all()
    return [FeedQuestionOut(**dict(row)) for row in rows]
