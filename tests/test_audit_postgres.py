"""Real SQL, recovery, leases and attribution in a disposable test schema."""

from __future__ import annotations

import os
import asyncio
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import asyncpg
import numpy as np
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from interviewlens.agent import graph, processing
from interviewlens.agent.nodes import extractor, normalizer, scorer
from interviewlens.aggregator import aggregator
from interviewlens.config import settings
from interviewlens.db import repositories
from interviewlens.db import session as db_session
from interviewlens.db.attribution import question_scope_sql, save_attribution
from interviewlens.embedding import backfill
from interviewlens.llm.schema import ExtractedPost

pytestmark = pytest.mark.skipif(
    not os.environ.get("IL_TEST_BACKFILL_DSN"), reason="isolated PostgreSQL DSN required"
)


@pytest_asyncio.fixture
async def database(monkeypatch):
    dsn = os.environ["IL_TEST_BACKFILL_DSN"]
    schema = "test_audit_" + uuid.uuid4().hex
    connection = await asyncpg.connect(dsn.replace("postgresql+asyncpg://", "postgresql://"))
    await connection.execute(f'CREATE SCHEMA "{schema}"')
    try:
        await connection.execute(f'SET search_path TO "{schema}",public')
        sql = Path(__file__).resolve().parents[1] / "sql"
        for name in (
            "001_init.sql",
            "008_position_profiles.sql",
            "011_pipeline_recovery.sql",
            "012_site_request_guard.sql",
            "013_interview_attribution.sql",
        ):
            await connection.execute((sql / name).read_text(encoding="utf-8"))
        engine = create_async_engine(
            dsn, connect_args={"server_settings": {"search_path": schema + ",public"}}
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)

        @asynccontextmanager
        async def scope():
            async with factory() as session:
                try:
                    yield session
                    await session.commit()
                except BaseException:
                    await session.rollback()
                    raise

        for module in (processing, extractor, normalizer, scorer, backfill, aggregator):
            monkeypatch.setattr(module, "session_scope", scope)
        monkeypatch.setattr(db_session, "get_session_factory", lambda: factory)
        # No external services or model calls in these integration tests.
        monkeypatch.setattr(graph, "get_langfuse", lambda: None)
        monkeypatch.setattr(graph, "langfuse_flush", lambda: None)
        from interviewlens.api import cache

        monkeypatch.setattr(cache, "invalidate_read_caches", AsyncMock())
        try:
            yield scope, engine
        finally:
            await engine.dispose()
    finally:
        await connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await connection.close()


async def seed(scope, *, count=1):
    vector = "[" + ",".join(["1"] + ["0"] * 1023) + "]"
    async with scope() as session:
        await session.execute(text("INSERT INTO companies(id,canonical) VALUES(1,'A'),(2,'B')"))
        await session.execute(
            text("INSERT INTO positions(id,canonical) VALUES(1,'后端'),(2,'客户端')")
        )
        await session.execute(
            text("""
            INSERT INTO posts(id,source_url,title,cleaned_text,extract_status,content_score)
            VALUES(1,'https://www.nowcoder.com/discuss/123','A 后端面经',
                'A 后端面经：Redis问题，B 客户端面经：Android问题','done',50)
        """)
        )
        await session.execute(text("INSERT INTO post_company_position VALUES(1,1,1)"))
        for i in range(1, count + 1):
            await session.execute(
                text("""
                INSERT INTO questions(id,post_id,content,category,answer_brief,embedding,embedding_model,embedding_version)
                VALUES(:id,1,:content,'数据库','文本要点',CAST(:vec AS vector),:model,2)
            """),
                {"id": i, "content": f"问题 {i}", "vec": vector, "model": settings.embedding_model},
            )
        # Explicit seed IDs must advance sequences before ORM INSERTs.
        for table in ("posts", "questions"):
            await session.execute(
                text(
                    f"SELECT setval(pg_get_serial_sequence('{table}','id'),(SELECT MAX(id) FROM {table}))"
                )
            )


async def test_named_sql_mapping_and_keyset_pages_feed_real_cluster_counts(database):
    scope, _ = database
    await seed(scope, count=5)
    rows = await aggregator._fetch_candidate_questions(
        company_id=1, position_id=1, period=None, top_n=None, min_quality=30, page_size=2
    )
    assert [row["id"] for row in rows] == [5, 4, 3, 2, 1]
    assert all(
        row["post_id"] == 1
        and row["content"].startswith("问题")
        and row["content_score"] == 50
        and row["source_url"].endswith("/123")
        and row["answer_brief"] == "文本要点"
        for row in rows
    )
    vectors = await aggregator._fetch_embeddings([r["id"] for r in rows], batch_size=2)
    clusters = aggregator._cluster_questions(rows, vectors, threshold=0.92)
    assert (
        len(clusters) == 1 and clusters[0]["question_count"] == 5 and clusters[0]["post_count"] == 1
    )


async def test_lease_content_change_and_expired_owner_fencing(database):
    scope, _ = database
    await seed(scope)
    assert await processing.claim(1, "first", "source") is not None
    assert await processing.claim(1, "second", "source") is None
    async with scope() as session:
        await processing.save_extraction(session, 1, "first", {"rounds": []})
        await session.execute(
            text("UPDATE post_processing SET lease_until=NOW()-INTERVAL '1 second'")
        )
    saved = await processing.claim(1, "second", "source")
    assert saved["payload"] == {"rounds": []}
    async with scope() as session:
        with pytest.raises(processing.ProcessingLeaseLost):
            await processing.fence(session, 1, "first")
    await processing.release("first")
    async with scope() as session:
        assert (
            await session.execute(text("SELECT owner FROM post_processing"))
        ).scalar_one() == "second"
    await processing.release("second")
    assert (await processing.claim(1, "third", "changed"))["payload"] is None


async def test_failed_normalization_resumes_without_reextract_and_indexes(database, monkeypatch):
    scope, _ = database
    await seed(scope)
    parsed = ExtractedPost.model_validate(
        {
            "companies": ["A"],
            "positions": ["后端"],
            "rounds": [
                {"round_no": 1, "questions": [{"content": "问题 1"}, {"content": "新增问题"}]}
            ],
        }
    )
    extract = AsyncMock(return_value=(parsed, {"cache_hit": False}))
    monkeypatch.setattr(extractor, "extract_from_text", extract)
    resolve = AsyncMock(side_effect=RuntimeError("provider temporarily down"))
    monkeypatch.setattr(normalizer, "resolve_entity", resolve)
    monkeypatch.setattr(
        backfill,
        "embed_texts",
        AsyncMock(return_value=np.array([[1] + [0] * 1023], dtype=np.float32)),
    )
    with pytest.raises(RuntimeError, match="temporarily"):
        await graph.run_pipeline("https://www.nowcoder.com/discuss/123")
    async with scope() as session:
        state = (
            await session.execute(text("SELECT stages,failed_stage,owner FROM post_processing"))
        ).first()
        assert state[0]["extract"] == "done" and state[1] == "normalize" and state[2] is None
        assert (
            await session.execute(text("SELECT COUNT(*) FROM post_company_position"))
        ).scalar_one() == 1
    assert await aggregator._fetch_candidate_questions(company_id=1,position_id=1,
        period=None,top_n=None,min_quality=0)==[]
    from interviewlens.normalizer.resolver import ResolveResult

    monkeypatch.setattr(
        normalizer, "resolve_entity", AsyncMock(return_value=ResolveResult(1, 1, "alias"))
    )
    final = await graph.run_pipeline("https://www.nowcoder.com/discuss/123")
    assert not final.get("skip_reason")
    assert extract.await_count == 1
    async with scope() as session:
        stages = (await session.execute(text("SELECT stages FROM post_processing"))).scalar_one()
        assert all(
            stages.get(stage) == "done" for stage in ("extract", "normalize", "score", "index")
        )
        assert (
            await session.execute(text("SELECT COUNT(*) FROM questions WHERE embedding IS NULL"))
        ).scalar_one() == 0


async def test_explicit_experiences_prevent_false_company_position_pairings(database):
    scope, _ = database
    await seed(scope, count=2)
    async with scope() as session:
        await session.execute(text("INSERT INTO post_question_refs VALUES(1,0,0,1),(1,0,1,2)"))
        extracted = {
            "interviews": [
                {
                    "company": "A",
                    "position": "后端",
                    "evidence": "A 后端面经",
                    "questions": [{"round_index": 0, "question_index": 0}],
                },
                {
                    "company": "B",
                    "position": "客户端",
                    "evidence": "B 客户端面经",
                    "questions": [{"round_index": 0, "question_index": 1}],
                },
            ]
        }
        pairs, mode = await save_attribution(
            session,
            1,
            extracted,
            {"A": 1, "B": 2},
            {"后端": 1, "客户端": 2},
            "A 后端面经：Redis问题，B 客户端面经：Android问题",
        )
        assert mode == "explicit" and pairs == [(1, 1), (2, 2)]
        await repositories.replace_post_links(
            session, 1, company_ids=[1, 2], position_ids=[1, 2], explicit_pairs=pairs
        )
    async with scope() as session:
        sql = text("SELECT q.id FROM questions q WHERE " + question_scope_sql())
        assert (
            await session.execute(sql, {"company": "A", "position": "后端"})
        ).scalars().all() == [1]
        assert (
            await session.execute(sql, {"company": "A", "position": "客户端"})
        ).scalars().all() == []
        assert (
            await session.execute(sql, {"company": "B", "position": "客户端"})
        ).scalars().all() == [2]


async def test_concurrent_pipeline_claims_only_one_extraction(database, monkeypatch):
    scope, _ = database
    await seed(scope)
    parsed = ExtractedPost.model_validate(
        {
            "companies": ["A"],
            "positions": ["后端"],
            "rounds": [{"round_no": 1, "questions": [{"content": "问题 1"}]}],
        }
    )

    async def slow_extract(*args, **kwargs):
        await asyncio.sleep(0.1)
        return parsed, {"cache_hit": False}

    extract = AsyncMock(side_effect=slow_extract)
    monkeypatch.setattr(extractor, "extract_from_text", extract)
    from interviewlens.normalizer.resolver import ResolveResult

    monkeypatch.setattr(
        normalizer, "resolve_entity", AsyncMock(return_value=ResolveResult(1, 1, "alias"))
    )
    results = await asyncio.gather(
        *(graph.run_pipeline("https://www.nowcoder.com/discuss/123") for _ in range(2))
    )
    assert extract.await_count == 1
    assert sum(r.get("skip_reason") == "processing_locked" for r in results) == 1
    async with scope() as session:
        assert (await session.execute(text("SELECT COUNT(*) FROM questions"))).scalar_one() == 1


async def test_changed_author_text_rejects_stale_extraction(database, monkeypatch):
    scope, _ = database
    await seed(scope)

    async def change_then_extract(*args, **kwargs):
        async with scope() as session:
            await session.execute(text("UPDATE posts SET cleaned_text='作者已修改正文' WHERE id=1"))
        return ExtractedPost.model_validate(
            {"rounds": [{"round_no": 1, "questions": [{"content": "旧内容抽取"}]}]}
        ), {}

    monkeypatch.setattr(extractor, "extract_from_text", AsyncMock(side_effect=change_then_extract))
    with pytest.raises(processing.ProcessingLeaseLost, match="content changed"):
        await graph.run_pipeline("https://www.nowcoder.com/discuss/123")
    async with scope() as session:
        assert (
            await session.execute(text("SELECT content FROM questions"))
        ).scalar_one() == "问题 1"
