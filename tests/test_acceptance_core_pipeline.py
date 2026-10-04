"""Master acceptance test suite covering core pipeline fixes.

Validates the 5 essential acceptance criteria:
1. Consecutive DB / async tasks running in the same process without loop death.
2. Celery deadlock prevention when called from worker loop.
3. Coroutine timeout, future cancellation, and resource cleanup.
4. Re-extraction data retention (embedding & answer_ai preserved) + question additions/deletions.
5. Cleaner protection for system design questions mentioning '点赞/收藏'.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from interviewlens.crawler.cleaner import strip_nowcoder_noise
from interviewlens.db.models import Question
from interviewlens.db.repositories import replace_questions
from interviewlens.db.session import session_scope
from interviewlens.tasks.pipeline import BackgroundLoopWorker, _run_async


# =========================================================================
# 1. Celery Worker Event Loop & Database Concurrency Acceptance
# =========================================================================

def test_acceptance_consecutive_tasks_same_process() -> None:
    """Verify that multiple tasks execute sequentially in the same process on a single loop."""
    loop1 = BackgroundLoopWorker.get_loop()
    assert loop1.is_running(), "Background loop must be actively running"

    call_log: list[str] = []

    async def task_one() -> str:
        call_log.append("task_one_start")
        await asyncio.sleep(0.02)
        call_log.append("task_one_end")
        return "res1"

    async def task_two() -> str:
        call_log.append("task_two_start")
        await asyncio.sleep(0.02)
        call_log.append("task_two_end")
        return "res2"

    res1 = _run_async(task_one(), timeout=5.0)
    res2 = _run_async(task_two(), timeout=5.0)

    loop2 = BackgroundLoopWorker.get_loop()
    assert loop1 is loop2, "Loop must be preserved across tasks in the same process"
    assert res1 == "res1"
    assert res2 == "res2"
    assert call_log == ["task_one_start", "task_one_end", "task_two_start", "task_two_end"]


def test_acceptance_consecutive_db_session_tasks_in_worker_loop() -> None:
    """Verify session_scope can be entered/exited across multiple consecutive tasks."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_factory = MagicMock(return_value=mock_session)
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None

    with patch("interviewlens.db.session.get_session_factory", return_value=mock_factory):
        async def db_task_1() -> int:
            async with session_scope() as session:
                assert session is mock_session
            return 101

        async def db_task_2() -> int:
            async with session_scope() as session:
                assert session is mock_session
            return 202

        r1 = _run_async(db_task_1())
        r2 = _run_async(db_task_2())

        assert r1 == 101
        assert r2 == 202
        # Both tasks committed their transactions
        assert mock_session.commit.await_count == 2
        # Both sessions closed via context manager exit
        assert mock_session.__aexit__.await_count == 2


def test_acceptance_celery_loop_deadlock_detection() -> None:
    """Verify run_coroutine raises RuntimeError if invoked from inside the worker loop."""
    async def invoke_from_inside() -> None:
        BackgroundLoopWorker.run_coroutine(asyncio.sleep(0.01))

    # Schedule the coroutine directly on the loop
    loop = BackgroundLoopWorker.get_loop()
    fut = asyncio.run_coroutine_threadsafe(invoke_from_inside(), loop)
    
    with pytest.raises(RuntimeError, match="Cannot invoke _run_async from inside the worker event loop thread"):
        fut.result(timeout=2.0)


def test_acceptance_timeout_cancels_background_task_and_frees_resources() -> None:
    """Verify timeout cancels the running task, triggers CancelledError cleanup, and does not block."""
    cleanup_flag = {"cleaned_up": False, "task_finished": False}

    async def long_running_task() -> str:
        try:
            await asyncio.sleep(2.0)
            cleanup_flag["task_finished"] = True
            return "done"
        except asyncio.CancelledError:
            cleanup_flag["cleaned_up"] = True
            raise

    with pytest.raises(TimeoutError, match="timed out after 0.1 seconds and was cancelled"):
        BackgroundLoopWorker.run_coroutine(long_running_task(), timeout=0.1)

    # Allow cancellation callback to complete on the loop
    time.sleep(0.1)
    assert cleanup_flag["cleaned_up"] is True, "CancelledError must be propagated to clean up resources"
    assert cleanup_flag["task_finished"] is False, "Task must not continue to completion after timeout"

    # Verify loop is still completely healthy for subsequent tasks
    async def fast_task() -> str:
        return "immediate_recovery"

    recovery_res = BackgroundLoopWorker.run_coroutine(fast_task(), timeout=2.0)
    assert recovery_res == "immediate_recovery"


# =========================================================================
# 2. Re-extraction Data Retention & Question Management Acceptance
# =========================================================================

@pytest.mark.asyncio
async def test_acceptance_replace_questions_retention_and_mutations() -> None:
    """Verify replace_questions preserves existing embedding/answer_ai, adds new questions, and removes orphans."""
    q_existing_1 = Question(
        id=1,
        post_id=99,
        round_no=1,
        round_type="tech_1",
        content="什么是分库分表与读写分离？",
        category="Database",
        answer_brief="旧版极简题解",
        answer_ai="这是耗费大模型算力生成的高价值深度题解，绝对不能丢失！",
        embedding=[0.11, 0.22, 0.33, 0.44],
    )
    q_orphaned_2 = Question(
        id=2,
        post_id=99,
        round_no=1,
        round_type="tech_1",
        content="已不再被提及的旧问题",
        category="Other",
        answer_brief="旧题解",
        answer_ai=None,
        embedding=None,
    )

    existing_rows = [q_existing_1, q_orphaned_2]

    mock_session = AsyncMock(spec=AsyncSession)
    # mock session.add to be a synchronous MagicMock so no unawaited coroutine warnings
    mock_session.add = MagicMock()
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = existing_rows
    mock_result.scalars.return_value = mock_scalars
    mock_session.execute.return_value = mock_result

    # New extraction payload:
    # 1. q_existing_1 reappears in round 2 with whitespace padding and updated answer_brief
    # 2. q_new_3 is a newly discovered question
    # 3. q_orphaned_2 is omitted
    new_rounds = [
        {
            "round_no": 2,
            "round_type": "tech_2",
            "questions": [
                {
                    "content": "   什么是分库分表与读写分离？   ",  # Content match with whitespace
                    "category": "数据库高可用",
                    "answer_brief": "更新后的新版题解",
                },
                {
                    "content": "请介绍 Raft 协议的选主逻辑",
                    "category": "分布式系统",
                    "answer_brief": "Leader 选举过程",
                },
            ],
        }
    ]

    total_active = await replace_questions(mock_session, post_id=99, rounds=new_rounds)

    assert total_active == 2

    # Verification 1: Existing question in-place reuse & data preservation
    assert q_existing_1.id == 1, "Question ID must be preserved"
    assert q_existing_1.embedding == [0.11, 0.22, 0.33, 0.44], "Existing vector embedding must not be wiped!"
    assert q_existing_1.answer_ai == "这是耗费大模型算力生成的高价值深度题解，绝对不能丢失！", "Existing AI answer must be retained!"
    assert q_existing_1.round_no == 2, "Round number must be updated"
    assert q_existing_1.round_type == "tech_2", "Round type must be updated"
    assert q_existing_1.category == "数据库高可用", "Category must be updated"
    assert q_existing_1.answer_brief == "更新后的新版题解", "Answer brief must be updated"

    # Verification 2: New question addition
    mock_session.add.assert_called_once()
    new_q_instance: Question = mock_session.add.call_args[0][0]
    assert new_q_instance.content == "请介绍 Raft 协议的选主逻辑"
    assert new_q_instance.post_id == 99
    assert new_q_instance.category == "分布式系统"
    assert new_q_instance.round_no == 2

    # Verification 3: Orphan deletion & flush
    assert mock_session.execute.await_count >= 2  # 1 select + 1 delete
    mock_session.flush.assert_awaited_once()


# =========================================================================
# 3. Cleaner Noise Truncation & System Design Question Protection Acceptance
# =========================================================================

def test_acceptance_cleaner_preserves_system_design_questions_and_truncates_noise() -> None:
    """Verify cleaner does not truncate questions about '点赞/收藏' systems and properly drops noise."""
    raw_forum_post = """
1. 自我介绍
2. 解释一下 TCP TIME_WAIT 状态的作用
3. 请设计一个高并发点赞和收藏系统，QPS 10 万如何抗住？
4. 点赞和收藏计数的数据一致性与缓存穿透如何解决？
5. 分库分表后，用户历史点赞列表如何高效查询？
6. 反问环节
点赞 88 收藏 66 分享
全部评论 (25)
用户张三：感谢楼主分享，已拿字节 Offer！
    """.strip()

    cleaned = strip_nowcoder_noise(raw_forum_post)

    # Retained questions
    assert "请设计一个高并发点赞和收藏系统，QPS 10 万如何抗住？" in cleaned
    assert "点赞和收藏计数的数据一致性与缓存穿透如何解决？" in cleaned
    assert "分库分表后，用户历史点赞列表如何高效查询？" in cleaned
    assert "反问环节" in cleaned

    # Truncated action bar & noise
    assert "点赞 88 收藏 66 分享" not in cleaned
    assert "全部评论" not in cleaned
    assert "用户张三" not in cleaned
