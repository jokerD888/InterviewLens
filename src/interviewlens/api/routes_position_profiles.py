"""Controlled vocabularies, coverage, and read-only per-post evidence."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..position_taxonomy import DOMAINS, SKILLS, SPECIALIZATIONS, TAXONOMY_VERSION, PositionCategory
from .deps import get_session

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
async def post_profiles(post_id: int, session: Annotated[AsyncSession, Depends(get_session)]):
    rows = (
        (
            await session.execute(
                text("""
        SELECT payload, origin, input_hash FROM post_position_profiles
        WHERE post_id=:post_id AND taxonomy_version=:version ORDER BY ordinal
    """),
                {"post_id": post_id, "version": TAXONOMY_VERSION},
            )
        )
        .mappings()
        .all()
    )
    return [
        {**row["payload"], "origin": row["origin"], "input_hash": row["input_hash"]} for row in rows
    ]
