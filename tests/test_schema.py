"""Unit tests for ExtractedPost validation."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from interviewlens.llm.schema import ExtractedPost, Level


def test_minimal_valid() -> None:
    obj = ExtractedPost.model_validate({
        "companies": ["字节跳动"],
        "positions": ["后端开发"],
        "rounds": [
            {
                "round_no": 1,
                "round_type": "技术一面",
                "questions": [
                    {"content": "Redis 分布式锁怎么实现", "category": "数据库"},
                    {"content": "讲项目里最难的部分", "category": "项目"},
                ],
            }
        ],
    })
    assert obj.level is Level.UNKNOWN
    assert obj.total_questions == 2
    assert obj.rounds[0].questions[0].content.startswith("Redis")


def test_interview_date_normalised() -> None:
    obj = ExtractedPost.model_validate({
        "companies": [],
        "positions": [],
        "interview_date": "2025-10-15",
        "rounds": [],
    })
    assert obj.interview_date == "2025-10"

    obj2 = ExtractedPost.model_validate({
        "companies": [],
        "positions": [],
        "interview_date": "garbage",
        "rounds": [],
    })
    assert obj2.interview_date is None


def test_round_no_bounds() -> None:
    with pytest.raises(ValidationError):
        ExtractedPost.model_validate({
            "companies": [],
            "positions": [],
            "rounds": [{"round_no": 99, "questions": []}],
        })


def test_short_content_rejected() -> None:
    with pytest.raises(ValidationError):
        ExtractedPost.model_validate({
            "companies": [],
            "positions": [],
            "rounds": [
                {
                    "round_no": 1,
                    "questions": [{"content": "?"}],
                }
            ],
        })
