"""Opt-in integration: real JSONB facets, same-profile semantics and rollback."""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from interviewlens.api.routes_feed import feed
from interviewlens.config import settings
from interviewlens.db.position_profiles import save_profiles
from interviewlens.position_taxonomy import preview_title


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("IL_TEST_TAXONOMY_DB") != "1", reason="requires migrated local database"
)
async def test_real_facets_and_manual_correction(monkeypatch):
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                session = AsyncSession(bind=connection)
                row = (
                    await session.execute(
                        text("""
                    SELECT po.id,pcp.position_id FROM posts po JOIN post_company_position pcp ON pcp.post_id=po.id
                    WHERE po.extract_status='done' AND EXISTS (SELECT 1 FROM questions q WHERE q.post_id=po.id)
                    LIMIT 1
                """)
                    )
                ).first()
                company_id = (
                    await session.execute(
                        text("""
                    INSERT INTO companies(canonical) VALUES ('__taxonomy_integration__') RETURNING id
                """)
                    )
                ).scalar_one()
                await session.execute(
                    text("""
                    INSERT INTO post_company_position(post_id,company_id,position_id) VALUES (:post,:company,:position)
                """),
                    {"post": row[0], "company": company_id, "position": row[1]},
                )
                await session.execute(
                    text("INSERT INTO post_companies(post_id,company_id) VALUES (:post,:company)"),
                    {"post": row[0], "company": company_id},
                )
                profiles = [preview_title("Java后端开发"), preview_title("Python算法工程师")]
                await save_profiles(session, row[0], profiles, "Java后端开发;Python算法工程师")

                async def search(category, skill, unreviewed):
                    return await feed(
                        company="__taxonomy_integration__",
                        position_category=category,
                        specializations=[],
                        domains=[],
                        skills=[skill],
                        include_unreviewed=unreviewed,
                        limit=100,
                        offset=0,
                        session=session,
                    )

                from interviewlens.position_taxonomy import PositionCategory

                assert [p.id for p in await search(PositionCategory.BACKEND, "Java", True)] == [
                    row[0]
                ]
                assert await search(PositionCategory.BACKEND, "Python", True) == []
                assert len(await search(PositionCategory.BACKEND, "Java", False)) == 1
                result = await search(PositionCategory.AI, "Python", True)
                assert len(result) == 1
                assert len(result[0].position_profiles) == 2
                # Multiselect OR within a facet; no duplicate post despite multiple profiles.
                both = await feed(
                    company="__taxonomy_integration__",
                    skills=["Python", "Java"],
                    specializations=[],
                    domains=[],
                    include_unreviewed=True,
                    limit=100,
                    offset=0,
                    session=session,
                )
                assert len(both) == 1
                # Semantic search shares the same predicate and preserves unique question rows.
                from unittest.mock import AsyncMock

                import numpy as np

                from interviewlens.api import routes_search

                monkeypatch.setattr(
                    routes_search, "embed_texts", AsyncMock(return_value=np.ones((1, 1024)))
                )
                monkeypatch.setattr(routes_search.settings, "search_cache_enabled", False)
                matched = await routes_search.search(
                    q="后端",
                    company="__taxonomy_integration__",
                    position_category=PositionCategory.BACKEND,
                    skills=["Java"],
                    include_unreviewed=True,
                    limit=2,
                    session=session,
                )
                assert matched and all(q.post_id == row[0] for q in matched)
                assert len({q.id for q in matched}) == len(matched)
                assert (
                    await routes_search.search(
                        q="后端",
                        company="__taxonomy_integration__",
                        position_category=PositionCategory.BACKEND,
                        skills=["Python"],
                        include_unreviewed=True,
                        limit=2,
                        session=session,
                    )
                    == []
                )
                # Human review survives a subsequent automatic extraction.
                reviewed = profiles[0].model_copy(
                    update={"human_reviewed": True, "needs_review": False}
                )
                await save_profiles(
                    session, row[0], [reviewed], "Java后端开发", overwrite_reviewed=True
                )
                await save_profiles(session, row[0], [profiles[1]], "Java后端开发")
                reviewed_result = await search(PositionCategory.BACKEND, "Java", False)
                assert len(reviewed_result) == 1
                assert reviewed_result[0].position_profiles[0].human_reviewed
                await save_profiles(session, row[0], [profiles[1]], "Python算法工程师")
                assert len(await search(PositionCategory.BACKEND, "Java", False)) == 1
                stale = await search(PositionCategory.BACKEND, "Java", True)
                assert stale[0].position_profiles[0].source_changed
                # Unknown legacy job must not hide a post or its company mentions.
                await session.execute(
                    text("DELETE FROM post_company_position WHERE post_id=:post"), {"post": row[0]}
                )
                unknown_job = await feed(
                    company="__taxonomy_integration__", session=session, limit=100
                )
                assert len(unknown_job) == 1
                assert unknown_job[0].positions == []
                assert "__taxonomy_integration__" in unknown_job[0].companies
                # Admin correction persists, invalidates old facets and rejects stale edits.
                from fastapi import HTTPException

                from interviewlens.api.routes_position_editor import (
                    Correction,
                    correct_positions,
                    editor_state,
                )

                _, author, editor = await editor_state(session, row[0])
                body = Correction(
                    revision=editor["revision"], profiles=[{"category": "前端", "skills": ["Vue"]}]
                )
                updated = await correct_positions(row[0], body, session)
                assert updated["profiles"][0]["human_reviewed"]
                assert updated["profiles"][0]["category"] == "前端"
                assert await search(PositionCategory.BACKEND, "Java", False) == []
                assert len(await search(PositionCategory.FRONTEND, "Vue", False)) == 1
                with pytest.raises(HTTPException) as stale_edit:
                    await correct_positions(row[0], body, session)
                assert stale_edit.value.status_code == 409
                bad = Correction(
                    revision=updated["revision"],
                    profiles=[{"category": "前端", "skills": ["基础架构"]}],
                )
                with pytest.raises(HTTPException) as invalid:
                    await correct_positions(row[0], bad, session)
                assert invalid.value.status_code == 422
                await save_profiles(session, row[0], profiles, author)
                assert (await editor_state(session, row[0]))[2]["profiles"][0]["category"] == "前端"
            finally:
                await transaction.rollback()
                await session.close()
    finally:
        await engine.dispose()
