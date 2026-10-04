"""Unit tests for backend aggregation frequency calculation and citation deduplication.

Verifies:
1. Backend recalculates and overrides LLM frequency hallucinations using true cluster counts.
2. Deduplication of cluster citations (multiple questions from same cluster are not double-counted).
3. Explicit distinction between question occurrence count (题次) and post coverage count (篇次).
4. Deterministic markdown rendering showing '×X题 / Y篇面经'.
5. Correct topic re-sorting by true verified frequency.
"""
from __future__ import annotations

import json
import pytest

from interviewlens.aggregator import aggregator
from interviewlens.llm.prompts import render_aggregator_md


def test_backend_frequency_overrides_llm_hallucination() -> None:
    """Verify backend replaces hallucinated LLM frequency with true cluster frequency."""
    cluster_1 = {
        "id": 1,
        "content": "Redis 分布式锁怎么实现？",
        "category": "数据库",
        "question_count": 8,
        "post_count": 5,
        "member_ids": [1, 2, 3, 4, 5, 6, 7, 8],
        "member_post_ids": [101, 102, 103, 104, 105],
        "member_contents": ["Redis 分布式锁怎么实现？", "Redis Redlock 原理"],
    }

    # LLM hallucinates frequency=999
    llm_payload = {
        "high_frequency_topics": [
            {
                "topic": "Redis 分布式锁",
                "frequency": 999,  # Hallucinated by LLM
                "sample_questions": ["Redis 分布式锁怎么实现？"],
            }
        ],
        "focus_areas": ["分布式锁实现与失效处理"],
        "edge_cases": [
            {"topic": "锁续期", "questions": ["Redis 分布式锁怎么实现？"]}
        ],
        "prep_advice": ["准备加锁、续期和故障恢复的完整回答"],
    }

    result = aggregator._parse_aggregator_output(
        json.dumps(llm_payload, ensure_ascii=False),
        questions=[cluster_1],
    )

    topic = result.high_frequency_topics[0]
    assert topic.frequency == 8, "Hallucinated frequency 999 must be overridden with true question_count 8"
    assert topic.question_count == 8
    assert topic.post_count == 5


def test_cluster_citation_deduplication() -> None:
    """Verify citing multiple questions from the SAME cluster does not double-count frequency."""
    cluster_1 = {
        "id": 1,
        "content": "MySQL 索引失效场景有哪些？",
        "category": "数据库",
        "question_count": 6,
        "post_count": 4,
        "member_ids": [10, 11, 12, 13, 14, 15],
        "member_post_ids": [201, 202, 203, 204],
        "member_contents": [
            "MySQL 索引失效场景有哪些？",
            "哪些情况会导致 MySQL 走全表扫描？",
        ],
    }

    # LLM includes two questions from the SAME cluster in sample_questions
    llm_payload = {
        "high_frequency_topics": [
            {
                "topic": "MySQL 索引失效",
                "frequency": 1,
                "sample_questions": [
                    "MySQL 索引失效场景有哪些？",
                    "哪些情况会导致 MySQL 走全表扫描？",
                ],
            }
        ],
        "focus_areas": ["索引优化"],
        "edge_cases": [
            {"topic": "like查询", "questions": ["MySQL 索引失效场景有哪些？"]}
        ],
        "prep_advice": ["深入掌握最左匹配原则"],
    }

    result = aggregator._parse_aggregator_output(
        json.dumps(llm_payload, ensure_ascii=False),
        questions=[cluster_1],
    )

    topic = result.high_frequency_topics[0]
    # Because both questions belong to cluster_1, it must be counted once: 6 questions across 4 posts
    assert topic.frequency == 6
    assert topic.question_count == 6
    assert topic.post_count == 4


def test_multi_cluster_aggregation_and_post_count_merging() -> None:
    """Verify combining distinct clusters sums question_count and unites post_count."""
    # Cluster A: 3 questions from post 1, 2
    cluster_a = {
        "id": 1,
        "content": "TCP 三次握手过程",
        "category": "网络",
        "question_count": 3,
        "post_count": 2,
        "member_ids": [1, 2, 3],
        "member_post_ids": [1, 2],
        "member_contents": ["TCP 三次握手过程"],
    }
    # Cluster B: 2 questions from post 2, 3 (post 2 overlaps!)
    cluster_b = {
        "id": 2,
        "content": "TCP 四次挥手与 TIME_WAIT",
        "category": "网络",
        "question_count": 2,
        "post_count": 2,
        "member_ids": [4, 5],
        "member_post_ids": [2, 3],
        "member_contents": ["TCP 四次挥手与 TIME_WAIT"],
    }

    llm_payload = {
        "high_frequency_topics": [
            {
                "topic": "TCP 连接与断开状态机",
                "frequency": 2,
                "sample_questions": [
                    "TCP 三次握手过程",
                    "TCP 四次挥手与 TIME_WAIT",
                ],
            }
        ],
        "focus_areas": ["传输层协议"],
        "edge_cases": [
            {"topic": "TIME_WAIT 调优", "questions": ["TCP 四次挥手与 TIME_WAIT"]}
        ],
        "prep_advice": ["背熟状态机流转"],
    }

    result = aggregator._parse_aggregator_output(
        json.dumps(llm_payload, ensure_ascii=False),
        questions=[cluster_a, cluster_b],
    )

    topic = result.high_frequency_topics[0]
    # Total questions = 3 + 2 = 5
    assert topic.question_count == 5
    assert topic.frequency == 5
    # Unique posts = {1, 2} | {2, 3} = {1, 2, 3} -> 3 posts
    assert topic.post_count == 3


def test_render_aggregator_md_distinguishes_questions_and_posts() -> None:
    """Verify render_aggregator_md formats explicit badges for questions and posts."""
    data = {
        "high_frequency_topics": [
            {
                "topic": "Redis 缓存穿透与雪崩",
                "frequency": 12,
                "question_count": 12,
                "post_count": 8,
                "sample_questions": ["如何防止缓存雪崩？"],
            },
            {
                "topic": "单个偶现题",
                "frequency": 1,
                "question_count": 1,
                "post_count": 1,
                "sample_questions": ["罕见算法题"],
            },
        ],
        "focus_areas": ["缓存设计"],
        "edge_cases": [],
        "prep_advice": ["熟记多级缓存"],
    }

    md = render_aggregator_md(data)
    assert "### Redis 缓存穿透与雪崩 <sub>×12题 / 8篇面经</sub>" in md
    assert "### 单个偶现题 <sub>×1题 / 1篇面经</sub>" in md


def test_backend_resorts_topics_by_verified_frequency() -> None:
    """Verify topics are re-sorted by true verified frequency instead of LLM order."""
    cluster_high = {
        "id": 1,
        "content": "高频分布式锁",
        "question_count": 20,
        "post_count": 15,
        "member_ids": list(range(20)),
        "member_post_ids": list(range(15)),
        "member_contents": ["高频分布式锁"],
    }
    cluster_low = {
        "id": 2,
        "content": "低频概念",
        "question_count": 2,
        "post_count": 2,
        "member_ids": [101, 102],
        "member_post_ids": [201, 202],
        "member_contents": ["低频概念"],
    }

    # LLM mistakenly puts low-frequency topic first
    llm_payload = {
        "high_frequency_topics": [
            {
                "topic": "低频概念专题",
                "frequency": 100,  # Hallucinated higher number
                "sample_questions": ["低频概念"],
            },
            {
                "topic": "高频分布式锁专题",
                "frequency": 5,    # Hallucinated lower number
                "sample_questions": ["高频分布式锁"],
            },
        ],
        "focus_areas": ["架构设计"],
        "edge_cases": [
            {"topic": "细节", "questions": ["低频概念"]}
        ],
        "prep_advice": ["全面备考"],
    }

    result = aggregator._parse_aggregator_output(
        json.dumps(llm_payload, ensure_ascii=False),
        questions=[cluster_high, cluster_low],
    )

    # After backend calculation, 高频分布式锁专题 (freq=20) must be first!
    assert result.high_frequency_topics[0].topic == "高频分布式锁专题"
    assert result.high_frequency_topics[0].frequency == 20
    assert result.high_frequency_topics[1].topic == "低频概念专题"
    assert result.high_frequency_topics[1].frequency == 2
