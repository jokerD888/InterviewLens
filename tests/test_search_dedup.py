"""Unit tests for /posts/search many-to-many deduplication via EXISTS subqueries."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from interviewlens.api.routes_search import search


@pytest.mark.asyncio
async def test_search_uses_exists_and_avoids_cartesian_join(monkeypatch):
    """Verify company/position filters generate EXISTS subqueries instead of JOINs."""
    captured_sqls: list[str] = []
    captured_params: list[dict] = []

    mock_session = AsyncMock()

    def fake_execute(statement, params):
        sql_str = str(statement)
        captured_sqls.append(sql_str)
        captured_params.append(dict(params))
        m = MagicMock()
        m.mappings.return_value.all.return_value = []
        return m

    mock_session.execute = AsyncMock(side_effect=fake_execute)

    # Mock embed_texts to return dummy 384-dim vector
    fake_vec = np.ones((1, 384), dtype=np.float32)
    monkeypatch.setattr(
        "interviewlens.api.routes_search.embed_texts", AsyncMock(return_value=fake_vec)
    )
    monkeypatch.setattr(
        "interviewlens.api.routes_search._result_cache_get", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        "interviewlens.api.routes_search._embed_cache_get", AsyncMock(return_value=None)
    )
    monkeypatch.setattr("interviewlens.api.routes_search._result_cache_set", AsyncMock())
    monkeypatch.setattr("interviewlens.api.routes_search._embed_cache_set", AsyncMock())
    monkeypatch.setattr("interviewlens.api.routes_search.incr_cache", AsyncMock())

    # Case 1: Search with company
    await search(q="分布式锁", company="字节跳动", session=mock_session)
    sql1 = captured_sqls[-1]
    # Must use EXISTS subquery
    assert "EXISTS" in sql1
    assert "qi.question_id=q.id" in sql1
    assert "pcp.post_id=q.post_id" in sql1
    # Must NOT have outer JOIN on post_company_position
    assert "FROM questions q\n    JOIN posts po ON po.id = q.post_id\n    WHERE" in sql1
    assert captured_params[-1]["company"] == "字节跳动"

    # Case 2: Search with position
    await search(q="分布式锁", position="后端开发", session=mock_session)
    sql2 = captured_sqls[-1]
    assert "EXISTS" in sql2
    assert "qi.question_id=q.id" in sql2
    assert "pcp.post_id=q.post_id" in sql2
    assert "FROM questions q\n    JOIN posts po ON po.id = q.post_id\n    WHERE" in sql2
    assert captured_params[-1]["position"] == "后端开发"

    # Case 3: Search with both company and position
    await search(q="分布式锁", company="字节跳动", position="后端开发", session=mock_session)
    sql3 = captured_sqls[-1]
    assert "post_attribution" in sql3
    assert "c.canonical = :company" in sql3
    assert "pos.canonical = :position" in sql3
    # Main FROM clause remains purely 1-to-1 between questions and posts
    assert "FROM questions q\n    JOIN posts po ON po.id = q.post_id\n    WHERE" in sql3


@pytest.mark.asyncio
async def test_search_results_unique_per_question(monkeypatch):
    """Verify search returns distinct questions and does not replicate rows."""
    fake_rows = [
        {
            "id": 101,
            "post_id": 1,
            "round_no": 1,
            "round_type": "tech",
            "content": "什么是分布式锁？",
            "category": "架构",
            "answer_brief": "Redis 或 ZK",
            "answer_ai": "深度题解",
            "content_score": 85,
            "quality_score": 85,
            "source_url": "https://nowcoder.com/1",
            "freshness_score": 25,
            "ranking_score": 110,
            "similarity": 0.95,
        },
        {
            "id": 102,
            "post_id": 1,
            "round_no": 1,
            "round_type": "tech",
            "content": "MySQL 事务隔离级别",
            "category": "数据库",
            "answer_brief": "RC, RR",
            "answer_ai": "深度题解2",
            "content_score": 85,
            "quality_score": 85,
            "source_url": "https://nowcoder.com/1",
            "freshness_score": 25,
            "ranking_score": 110,
            "similarity": 0.88,
        },
    ]

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = fake_rows
    mock_session.execute = AsyncMock(return_value=mock_result)

    fake_vec = np.ones((1, 384), dtype=np.float32)
    monkeypatch.setattr(
        "interviewlens.api.routes_search.embed_texts", AsyncMock(return_value=fake_vec)
    )
    monkeypatch.setattr(
        "interviewlens.api.routes_search._result_cache_get", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        "interviewlens.api.routes_search._embed_cache_get", AsyncMock(return_value=None)
    )
    monkeypatch.setattr("interviewlens.api.routes_search._result_cache_set", AsyncMock())
    monkeypatch.setattr("interviewlens.api.routes_search._embed_cache_set", AsyncMock())
    monkeypatch.setattr("interviewlens.api.routes_search.incr_cache", AsyncMock())

    results = await search(q="分布式锁", company="字节跳动", limit=10, session=mock_session)
    assert len(results) == 2
    question_ids = [q.id for q in results]
    assert len(question_ids) == len(set(question_ids)), "Every question must be distinct"
    assert question_ids == [101, 102]
    # Verify similarity ordering
    assert results[0].similarity > results[1].similarity
