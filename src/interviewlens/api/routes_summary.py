"""/summaries — query persisted Aggregator output."""
from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..config import settings
from ..db import Company, Position, Summary
from ..observability import incr_cache
from .cache import cache_json_get, cache_json_set
from .deps import get_session
from .schemas import QuestionOut, SummaryOut

router = APIRouter(tags=["summary"])

# Summaries are pre-computed offline; only change on re-aggregation.
_SUMMARY_TTL = 3600


def _key(name: str, params: dict) -> str:
    canonical = json.dumps(params, sort_keys=True, ensure_ascii=False)
    return f"il:api:{name}:{hashlib.sha256(canonical.encode()).hexdigest()}"


def _summary_out(s, c_name, p_name) -> SummaryOut:
    return SummaryOut(
        id=s.id,
        company=c_name,
        position=p_name,
        period=s.period,
        sample_count=s.sample_count,
        content_md=s.content_md,
        updated_at=s.updated_at,
    )


@router.get("/summaries", response_model=list[SummaryOut])
async def list_summaries(
    company: str | None = None,
    position: str | None = None,
    period: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> list[SummaryOut]:
    if settings.search_cache_enabled:
        key = _key("summaries", {
            "company": company, "position": position, "period": period, "limit": limit
        })
        cached = await cache_json_get(key)
        if cached is not None:
            await incr_cache(True)
            return [SummaryOut(**r) for r in cached]
        await incr_cache(False)

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
    out = [_summary_out(s, c_name, p_name) for s, c_name, p_name in rows]

    if settings.search_cache_enabled:
        await cache_json_set(key, [o.model_dump(mode="json") for o in out], ttl_seconds=_SUMMARY_TTL)
    return out


@router.get("/summaries/{company}/{position}", response_model=SummaryOut)
async def get_summary(
    company: str,
    position: str,
    period: str = "all",
    session: AsyncSession = Depends(get_session),
) -> SummaryOut:
    if settings.search_cache_enabled:
        key = _key("summary", {"company": company, "position": position, "period": period})
        cached = await cache_json_get(key)
        if cached is not None:
            await incr_cache(True)
            return SummaryOut(**cached)
        await incr_cache(False)

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
        # 404 path is NOT cached — a later aggregation may create it.
        raise HTTPException(404, f"no summary for {company}/{position}/{period}")
    s, c_name, p_name = row
    out = _summary_out(s, c_name, p_name)

    if settings.search_cache_enabled:
        await cache_json_set(key, out.model_dump(mode="json"), ttl_seconds=_SUMMARY_TTL)
    return out


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
               q.content, q.category, q.answer_brief, q.answer_ai,
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
            answer_ai=r[7],
            quality_score=r[8],
            source_url=r[9],
        )
        for r in rows
    ]


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
               q.content, q.category, q.answer_brief, q.answer_ai,
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
            answer_ai=r[7],
            quality_score=r[8],
            source_url=r[9],
        )
        for r in rows
    ]
