from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from interviewlens.llm import extractor
from interviewlens.llm.deepseek import ToolCallResult
from interviewlens.position_taxonomy import PositionProfile


def payload():
    return {
        "companies": ["字节"],
        "positions": ["后端开发"],
        "rounds": [{"round_no": 1, "questions": [{"content": "Redis 与 Elasticsearch 的区别?"}]}],
        "position_profiles": [
            {
                "category": "后端",
                "status": "classified",
                "source": "declared",
                "raw_title": "后端开发",
                "skills": ["Redis", "Elasticsearch", "Golang"],
                "specializations": ["数据库", "任意新方向"],
                "domains": ["电商", "新领域"],
                "evidence": [
                    {
                        "field": "category",
                        "value": "后端",
                        "quote": "后端开发",
                        "source": "declared",
                    },
                    {
                        "field": "skills",
                        "value": "Redis",
                        "quote": "Redis 与 Elasticsearch",
                        "source": "interview",
                    },
                    {
                        "field": "skills",
                        "value": "Elasticsearch",
                        "quote": "Redis 与 Elasticsearch",
                        "source": "interview",
                    },
                    {
                        "field": "skills",
                        "value": "Golang",
                        "quote": "Golang",
                        "source": "interview",
                    },
                    {
                        "field": "specializations",
                        "value": "数据库",
                        "quote": "数据库",
                        "source": "declared",
                    },
                    {"field": "domains", "value": "电商", "quote": "电商", "source": "declared"},
                ],
            }
        ],
    }


BODY = "字节后端开发,电商数据库。Redis 与 Elasticsearch 的区别?Golang"


@pytest.mark.asyncio
@pytest.mark.parametrize("cache_hit", [False, True])
async def test_optional_unknown_facets_do_not_discard_questions(monkeypatch, cache_hit):
    args = payload()
    args["rounds"][0]["questions"].extend([{"content": "锁"}, {"content": " "}])
    original = deepcopy(args)
    cached = {"arguments": args, "model": "test"} if cache_hit else None
    monkeypatch.setattr(extractor, "cache_get", AsyncMock(return_value=cached))
    cache_set = AsyncMock()
    monkeypatch.setattr(extractor, "cache_set", cache_set)
    monkeypatch.setattr(extractor, "incr_cache", AsyncMock())
    tool = AsyncMock(return_value=ToolCallResult("extract_interview_post", args, {}, None, "test"))
    monkeypatch.setattr(extractor, "call_tool", tool)
    parsed, info = await extractor.extract_from_text(BODY)
    assert parsed.total_questions == 1
    assert parsed.rounds[0].questions[0].content == original["rounds"][0]["questions"][0]["content"]
    profile = parsed.position_profiles[0]
    assert profile.skills == ["Redis", "Go"]
    assert profile.specializations == ["数据库"]
    assert profile.domains == ["电商"]
    assert not any(e.value == "Elasticsearch" for e in profile.evidence)
    assert info["cache_hit"] == cache_hit
    assert args == original
    if cache_hit:
        tool.assert_not_awaited()
    else:
        assert cache_set.await_args.args[1]["arguments"]["position_profiles"][0]["skills"] == [
            "Redis",
            "Go",
        ]


def test_admin_validation_and_primary_category_remain_strict():
    with pytest.raises(ValidationError):
        PositionProfile(skills=["Elasticsearch"])
    args = payload()
    args["position_profiles"][0]["category"] = "Java研发"
    with pytest.raises(ValidationError):
        extractor._parse_extraction(args, BODY)


def test_malformed_optional_facet_is_still_invalid():
    args = payload()
    args["position_profiles"][0]["skills"] = {"Redis": True}
    with pytest.raises(ValidationError):
        extractor._parse_extraction(args, BODY)


@pytest.mark.parametrize("status,category", [("uncertain", "后端"), ("classified", None)])
def test_contradictory_classification_downgrades_without_losing_questions(status, category):
    args = payload()
    args["position_profiles"][0].update(status=status, category=category)
    parsed = extractor._parse_extraction(args, BODY)
    assert parsed.total_questions == 1
    assert parsed.position_profiles[0].status == "uncertain"
    assert parsed.position_profiles[0].category is None
