"""/summaries — query persisted Aggregator output."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..db import Company, Position, Summary
from .deps import get_session
from .schemas import QuestionOut, SummaryOut

router = APIRouter(tags=["summary"])


@router.get("/summaries", response_model=list[SummaryOut])
async def list_summaries(
    company: str | None = None,
    position: str | None = None,
    period: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> list[SummaryOut]:
    stmt = (
        select(Summary, Company.canonical, Position.canonical)
        .join(Company, Company.id == Summary.company_id)
        .join(Position, Position.id == Summary.position_id)
        .order_by(Summary.updated_at.desc())
        .limit(limit)
    )
    if company:
        stmt = stmt.where(Company.canonical == company)
    if position:
        stmt = stmt.where(Position.canonical == position)
    if period:
        stmt = stmt.where(Summary.period == period)

    rows = (await session.execute(stmt)).all()
    return [
        SummaryOut(
            id=s.id,
            company=c_name,
            position=p_name,
            period=s.period,
            sample_count=s.sample_count,
            content_md=s.content_md,
            updated_at=s.updated_at,
        )
        for s, c_name, p_name in rows
    ]


@router.get("/summaries/{company}/{position}", response_model=SummaryOut)
async def get_summary(
    company: str,
    position: str,
    period: str = "all",
    session: AsyncSession = Depends(get_session),
) -> SummaryOut:
    stmt = (
        select(Summary, Company.canonical, Position.canonical)
        .join(Company, Company.id == Summary.company_id)
        .join(Position, Position.id == Summary.position_id)
        .where(
            Company.canonical == company,
            Position.canonical == position,
            Summary.period == period,
        )
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise HTTPException(404, f"no summary for {company}/{position}/{period}")
    s, c_name, p_name = row
    return SummaryOut(
        id=s.id,
        company=c_name,
        position=p_name,
        period=s.period,
        sample_count=s.sample_count,
        content_md=s.content_md,
        updated_at=s.updated_at,
    )


@router.get("/summaries/{company}/{position}/questions", response_model=list[QuestionOut])
async def list_raw_questions(
    company: str,
    position: str,
    period: str = "all",
    session: AsyncSession = Depends(get_session),
) -> list[QuestionOut]:
    """Return every question (no dedup, no LLM) for this company+position."""
    from sqlalchemy import text as sa_text

    sql = sa_text("""
        SELECT q.id, q.post_id, q.round_no, q.round_type,
               q.content, q.category, q.answer_brief,
               COALESCE(po.quality_score, 0) AS quality_score,
               po.source_url
        FROM questions q
        JOIN posts po ON po.id = q.post_id
        JOIN post_company_position pcp ON pcp.post_id = po.id
        JOIN companies c ON c.id = pcp.company_id
        JOIN positions p ON p.id = pcp.position_id
        WHERE c.canonical = :company
          AND p.canonical = :position
          AND po.extract_status = 'done'
          AND (
              CAST(:period AS TEXT) IS NULL
              OR CAST(:period AS TEXT) = 'all'
              OR to_char(po.posted_at, 'YYYY"Q"Q') = :period
          )
        ORDER BY q.category NULLS LAST, po.quality_score DESC NULLS LAST
    """)
    rows = (
        await session.execute(
            sql,
            {
                "company": company,
                "position": position,
                "period": period,
            },
        )
    ).all()
    return [
        QuestionOut(
            id=r[0],
            post_id=r[1],
            round_no=r[2],
            round_type=r[3],
            content=r[4],
            category=r[5],
            answer_brief=r[6],
            quality_score=r[7],
            source_url=r[8],
        )
        for r in rows
    ]
