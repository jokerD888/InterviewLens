"""/companies and /positions routes."""
from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..config import settings
from ..db import Company, Position
from ..observability import incr_cache
from .cache import cache_json_get, cache_json_set
from .deps import get_session
from .schemas import CompanyOut, CompanyPositionStat, PositionOut

router = APIRouter(tags=["taxonomy"])

# Taxonomy data changes only on crawl/normalize — a long TTL is safe.
_TAXONOMY_TTL = 3600


def _key(name: str, params: dict) -> str:
    canonical = json.dumps(params, sort_keys=True, ensure_ascii=False)
    return f"il:api:{name}:{hashlib.sha256(canonical.encode()).hexdigest()}"


@router.get("/companies", response_model=list[CompanyOut])
async def list_companies(
    limit: int = 100,
    offset: int = 0,
    with_counts: bool = True,
    session: AsyncSession = Depends(get_session),
) -> list[CompanyOut]:
    if settings.search_cache_enabled:
        key = _key("companies", {"limit": limit, "offset": offset, "with_counts": with_counts})
        cached = await cache_json_get(key)
        if cached is not None:
            await incr_cache(True)
            return [CompanyOut(**r) for r in cached]
        await incr_cache(False)

    if with_counts:
        sql = """
        SELECT c.id, c.canonical, c.industry, COUNT(DISTINCT pcp.post_id) AS n
        FROM companies c
        LEFT JOIN post_company_position pcp ON pcp.company_id = c.id
        GROUP BY c.id, c.canonical, c.industry
        ORDER BY n DESC, c.canonical
        LIMIT :limit OFFSET :offset
        """
        rows = (await session.execute(sa_text(sql), {"limit": limit, "offset": offset})).all()
        out = [
            CompanyOut(id=r[0], canonical=r[1], industry=r[2], post_count=int(r[3]))
            for r in rows
        ]
    else:
        rows = (
            await session.execute(
                select(Company).order_by(Company.canonical).limit(limit).offset(offset)
            )
        ).scalars().all()
        out = [CompanyOut(id=c.id, canonical=c.canonical, industry=c.industry) for c in rows]

    if settings.search_cache_enabled:
        await cache_json_set(key, [o.model_dump() for o in out], ttl_seconds=_TAXONOMY_TTL)
    return out


@router.get("/companies/{company_id}/positions", response_model=list[CompanyPositionStat])
async def list_company_positions(
    company_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[CompanyPositionStat]:
    if settings.search_cache_enabled:
        key = _key("company_positions", {"company_id": company_id})
        cached = await cache_json_get(key)
        if cached is not None:
            await incr_cache(True)
            return [CompanyPositionStat(**r) for r in cached]
        await incr_cache(False)

    sql = """
    SELECT * FROM v_company_position_stats
    WHERE company_id = :cid
    ORDER BY post_count DESC, position_name
    """
    rows = (await session.execute(sa_text(sql), {"cid": company_id})).mappings().all()
    if not rows:
        # Distinguish "no data" from "no such company" — this 404 path is NOT cached.
        existing = (
            await session.execute(select(Company).where(Company.id == company_id))
        ).scalar_one_or_none()
        if existing is None:
            raise HTTPException(404, "company not found")
    out = [CompanyPositionStat(**dict(r)) for r in rows]

    if settings.search_cache_enabled:
        await cache_json_set(key, [o.model_dump() for o in out], ttl_seconds=_TAXONOMY_TTL)
    return out


@router.get("/positions", response_model=list[PositionOut])
async def list_positions(
    limit: int = 100,
    offset: int = 0,
    with_counts: bool = True,
    session: AsyncSession = Depends(get_session),
) -> list[PositionOut]:
    if settings.search_cache_enabled:
        key = _key("positions", {"limit": limit, "offset": offset, "with_counts": with_counts})
        cached = await cache_json_get(key)
        if cached is not None:
            await incr_cache(True)
            return [PositionOut(**r) for r in cached]
        await incr_cache(False)

    if with_counts:
        sql = """
        SELECT p.id, p.canonical, p.category, COUNT(DISTINCT pcp.post_id) AS n
        FROM positions p
        LEFT JOIN post_company_position pcp ON p.position_id = p.id
        GROUP BY p.id, p.canonical, p.category
        ORDER BY n DESC, p.canonical
        LIMIT :limit OFFSET :offset
        """
        rows = (await session.execute(sa_text(sql), {"limit": limit, "offset": offset})).all()
        out = [
            PositionOut(id=r[0], canonical=r[1], category=r[2], post_count=int(r[3]))
            for r in rows
        ]
    else:
        rows = (
            await session.execute(
                select(Position).order_by(Position.canonical).limit(limit).offset(offset)
            )
        ).scalars().all()
        out = [PositionOut(id=p.id, canonical=p.canonical, category=p.category) for p in rows]

    if settings.search_cache_enabled:
        await cache_json_set(key, [o.model_dump() for o in out], ttl_seconds=_TAXONOMY_TTL)
    return out
