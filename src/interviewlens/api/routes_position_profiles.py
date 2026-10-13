"""Controlled vocabularies, coverage, and read-only per-post evidence."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..position_taxonomy import DOMAINS, SKILLS, SPECIALIZATIONS, TAXONOMY_VERSION, PositionCategory
from .deps import get_session
from .public_data import public_profile

router = APIRouter(tags=["position-taxonomy"])


@router.get("/position-taxonomy")
async def position_taxonomy(session: Annotated[AsyncSession, Depends(get_session)]):
    counts = (
        (
            await session.execute(
                text("""
        SELECT category, COUNT(DISTINCT post_id) AS posts,
               COUNT(DISTINCT post_id) FILTER (WHERE NOT needs_review) AS accepted_posts
        FROM post_position_profiles WHERE taxonomy_version=:version
        GROUP BY category ORDER BY category
    """),
                {"version": TAXONOMY_VERSION},
            )
        )
        .mappings()
        .all()
    )
    return {
        "version": TAXONOMY_VERSION,
        "categories": list(PositionCategory),
        "specializations": SPECIALIZATIONS,
        "domains": DOMAINS,
        "skills": SKILLS,
        "counts": [dict(row) for row in counts],
    }


@router.get("/posts/{post_id}/position-profiles")
async def post_profiles(post_id: Annotated[int, Path(ge=1, le=9223372036854775807)], session: Annotated[AsyncSession, Depends(get_session)]):
    rows = (
        (
            await session.execute(
                text("""
        SELECT payload FROM post_position_profiles
        WHERE post_id=:post_id AND taxonomy_version=:version ORDER BY ordinal
    """),
                {"post_id": post_id, "version": TAXONOMY_VERSION},
            )
        )
        .mappings()
        .all()
    )
    return [public_profile(row["payload"]) for row in rows]
