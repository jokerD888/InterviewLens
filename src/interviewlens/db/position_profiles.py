"""Persist per-post profiles without modifying legacy canonical identities."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import text

from ..position_taxonomy import PositionProfile


async def save_post_companies(session, post_id: int, company_ids: list[int]) -> None:
    await session.execute(
        text("DELETE FROM post_companies WHERE post_id=:post_id"), {"post_id": post_id}
    )
    for company_id in set(company_ids):
        await session.execute(
            text("""
            INSERT INTO post_companies(post_id,company_id) VALUES (:post_id,:company_id)
            ON CONFLICT DO NOTHING
        """),
            {"post_id": post_id, "company_id": company_id},
        )


async def save_profiles(
    session,
    post_id: int,
    profiles: list[PositionProfile],
    author_text: str,
    *,
    origin: str = "extractor",
    overwrite_reviewed: bool = False,
    refresh_preview: bool = False,
) -> None:
    # Serialize competing extractions, previews and manual reviews for this post.
    await session.execute(text("SELECT pg_advisory_xact_lock(:post_id)"), {"post_id": post_id})
    # New extraction replaces only this derived profile set, in the caller's transaction.
    # A historical preview must never overwrite profiles produced by extraction.
    if origin == "historical_preview":
        existing = await session.execute(
            text(
                "SELECT 1 FROM post_position_profiles WHERE post_id=:post_id "
                "AND (NOT :refresh OR origin <> 'historical_preview' OR NOT needs_review) LIMIT 1"
            ),
            {"post_id": post_id, "refresh": refresh_preview},
        )
        if existing.first():
            return
    elif not overwrite_reviewed:
        reviewed = await session.execute(
            text("""
            SELECT input_hash FROM post_position_profiles WHERE post_id=:post_id
            AND payload @> CAST(:reviewed AS jsonb) LIMIT 1
        """),
            {"post_id": post_id, "reviewed": json.dumps({"human_reviewed": True})},
        )
        reviewed_row = reviewed.first()
        if reviewed_row:
            if reviewed_row[0] != hashlib.sha256(author_text.encode()).hexdigest():
                await session.execute(
                    text("""
                    UPDATE post_position_profiles SET needs_review=TRUE,
                    payload=payload || CAST(:stale AS jsonb) WHERE post_id=:post_id
                """),
                    {
                        "post_id": post_id,
                        "stale": json.dumps({"source_changed": True, "needs_review": True}),
                    },
                )
            return
    await session.execute(
        text("DELETE FROM post_position_profiles WHERE post_id=:post_id"), {"post_id": post_id}
    )
    for ordinal, profile in enumerate(profiles):
        await session.execute(
            text("""
            INSERT INTO post_position_profiles
                (post_id,ordinal,category,status,needs_review,taxonomy_version,input_hash,origin,payload)
            VALUES (:post_id,:ordinal,:category,:status,:needs_review,:version,:hash,:origin,CAST(:payload AS jsonb))
        """),
            {
                "post_id": post_id,
                "ordinal": ordinal,
                "category": profile.category,
                "status": profile.status,
                "needs_review": profile.needs_review,
                "version": profile.taxonomy_version,
                "hash": hashlib.sha256(author_text.encode()).hexdigest(),
                "origin": origin,
                "payload": json.dumps(profile.model_dump(mode="json"), ensure_ascii=False),
            },
        )
