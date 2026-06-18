"""/posts/search and /posts/{id} — semantic question search via pgvector."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..db import Post
from ..embedding import embed_texts
from .deps import get_session
from .schemas import PostBrief, QuestionOut

router = APIRouter(tags=["search"])


@router.get("/posts/search", response_model=list[QuestionOut])
async def search(
    q: str = Query(..., min_length=2, description="Free-text query"),
    company: str | None = None,
    position: str | None = None,
    min_quality: int = 0,
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[QuestionOut]:
    """pgvector cosine top-K with optional company/position filters.

    The query is embedded with bge-m3 server-side; the resulting vector is
    handed to Postgres via the ``<#>`` (cosine distance) operator. Lower
    distance = more similar; we convert to ``similarity = 1 - distance``.
    """
    qvec = await embed_texts([q])
    if qvec.size == 0:
        return []
    vec_str = "[" + ",".join(f"{v:.6f}" for v in qvec[0].tolist()) + "]"

    clauses = ["q.embedding IS NOT NULL"]
    params: dict[str, object] = {
        "limit": limit,
        "vec": vec_str,
        "min_q": min_quality,
    }
    joins = "JOIN posts po ON po.id = q.post_id"
    if company:
        joins += (
            " JOIN post_company_position pcp_c ON pcp_c.post_id = po.id"
            " JOIN companies c ON c.id = pcp_c.company_id"
        )
        clauses.append("c.canonical = :company")
        params["company"] = company
    if position:
        joins += (
            " JOIN post_company_position pcp_p ON pcp_p.post_id = po.id"
            " JOIN positions p ON p.id = pcp_p.position_id"
        )
        clauses.append("p.canonical = :position")
        params["position"] = position
    if min_quality > 0:
        clauses.append("COALESCE(po.quality_score, 0) >= :min_q")

    sql = f"""
    SELECT q.id, q.post_id, q.round_no, q.round_type, q.content, q.category,
           q.answer_brief, q.answer_ai, po.quality_score, po.source_url,
           1 - (q.embedding <=> CAST(:vec AS vector)) AS similarity
    FROM questions q
    {joins}
    WHERE {' AND '.join(clauses)}
    ORDER BY q.embedding <=> CAST(:vec AS vector)
    LIMIT :limit
    """
    rows = (await session.execute(sa_text(sql), params)).mappings().all()
    return [QuestionOut(**dict(r)) for r in rows]


@router.get("/posts/{post_id}", response_model=PostBrief)
async def get_post(
    post_id: int,
    session: AsyncSession = Depends(get_session),
) -> PostBrief:
    post = (await session.execute(select(Post).where(Post.id == post_id))).scalar_one_or_none()
    if post is None:
        raise HTTPException(404, "post not found")

    sql = """
    SELECT array_agg(DISTINCT c.canonical) AS companies,
           array_agg(DISTINCT p.canonical) AS positions
    FROM post_company_position pcp
    JOIN companies c ON c.id = pcp.company_id
    JOIN positions p ON p.id = pcp.position_id
    WHERE pcp.post_id = :pid
    """
    row = (await session.execute(sa_text(sql), {"pid": post_id})).mappings().first()
    return PostBrief(
        id=post.id,
        title=post.title,
        source_url=post.source_url,
        posted_at=post.posted_at,
        quality_score=post.quality_score,
        companies=list(row["companies"] or []) if row else [],
        positions=list(row["positions"] or []) if row else [],
    )
