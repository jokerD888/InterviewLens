"""Unit tests for repositories module, specifically replace_questions data retention."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from interviewlens.db.models import Question
from interviewlens.db.repositories import replace_questions


@pytest.mark.asyncio
async def test_replace_questions_retains_embedding_and_ai_answer():
    """Verify that re-extracting questions preserves existing embeddings and AI answers."""
    # Pre-existing question in database
    existing_q1 = Question(
        id=101,
        post_id=1,
        round_no=1,
        round_type="tech",
        content="什么是 GIL？",
        category="Python",
        answer_brief="全局解释器锁",
        answer_ai="这是高价值的 AI 题解内容，必须保留！",
        embedding=[0.1, 0.2, 0.3],
    )
    # Question that will be dropped/orphaned
    existing_q2 = Question(
        id=102,
        post_id=1,
        round_no=1,
        round_type="tech",
        content="已过期的题目",
        category="Other",
    )

    existing_rows = [existing_q1, existing_q2]

    # Mock session
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = existing_rows
    mock_result.scalars.return_value = mock_scalars
    mock_session.execute.return_value = mock_result

    # Re-extracted payload: q1 has slightly different whitespace and updated answer_brief,
    # plus a new q3 is introduced.
    new_rounds = [
        {
            "round_no": 2,  # round changed
            "round_type": "tech_2",
            "questions": [
                {
                    "content": "  什么是 GIL？  ",  # same content with whitespace
                    "category": "Python高级",
                    "answer_brief": "更新后的极简题解",
                },
                {
                    "content": "分布式锁如何实现？",
                    "category": "架构",
                    "answer_brief": "Redis 或 ZK",
                },
            ],
        }
    ]

    total = await replace_questions(mock_session, post_id=1, rounds=new_rounds)

    assert total == 2
    # Verify q1 was updated in-place, retaining id, embedding, and answer_ai
    assert existing_q1.round_no == 2
    assert existing_q1.round_type == "tech_2"
    assert existing_q1.category == "Python高级"
    assert existing_q1.answer_brief == "更新后的极简题解"
    assert existing_q1.answer_ai == "这是高价值的 AI 题解内容，必须保留！"
    assert existing_q1.embedding == [0.1, 0.2, 0.3]

    # Verify session.add was called for the new question
    added_questions = [call.args[0] for call in mock_session.add.call_args_list]
    assert len(added_questions) == 1
    assert added_questions[0].content == "分布式锁如何实现？"
    assert added_questions[0].post_id == 1

    # Verify delete was called for orphaned q2 (id=102)
    assert mock_session.execute.call_count >= 2  # 1 select + 1 delete
    mock_session.flush.assert_awaited_once()
