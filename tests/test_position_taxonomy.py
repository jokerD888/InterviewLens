from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from interviewlens.crawler.cleaner import strip_nowcoder_noise
from interviewlens.db.position_profiles import save_profiles
from interviewlens.position_taxonomy import (
    Evidence,
    PositionProfile,
    preview_title,
    profile_tool_schema,
    validate_evidence,
)


@pytest.mark.parametrize(
    ("title", "category"),
    [
        ("Java后端开发", "后端"),
        ("Android开发", "客户端"),
        ("推荐算法工程师", "算法/AI"),
        ("大数据开发", "数据"),
        ("Unity客户端开发", "游戏"),
        ("游戏测试开发", "测试"),
        ("安全平台前端", "前端"),
        ("安全研发工程师", "安全"),
        ("AI Infra训推系统实习", "后端"),
        ("CSIG日常实习", None),
        ("Java实习生", None),
        ("笔试算法题回忆", None),
    ],
)
def test_title_preview_is_unreviewed(title, category):
    profile = preview_title(title)
    assert profile.category == category
    assert profile.needs_review


def test_reject_invented_category_and_tag():
    with pytest.raises(ValidationError):
        PositionProfile(category="Java", status="classified")
    with pytest.raises(ValidationError):
        PositionProfile(skills=["基础架构"])
    with pytest.raises(ValidationError):
        PositionProfile(specializations=["C++"])


def test_inference_cannot_bypass_review():
    profile = PositionProfile(category="后端", status="classified", needs_review=False)
    assert profile.needs_review


def test_missing_and_fabricated_evidence_downgrades_category():
    profile = PositionProfile(
        category="后端",
        status="classified",
        source="declared",
        raw_title="Java后端",
        needs_review=False,
        skills=["Java", "Linux"],
        evidence=[
            Evidence(field="category", value="后端", quote="Java后端", source="declared"),
            Evidence(field="skills", value="Java", quote="Java后端", source="declared"),
            Evidence(field="skills", value="Linux", quote="Java后端", source="declared"),
        ],
    )
    validated = validate_evidence(profile, "面试Java后端")
    assert validated.skills == ["Java"]
    assert not validated.needs_review
    rejected = validate_evidence(profile, "CSIG笔试")
    assert rejected.category is None
    assert rejected.status == "uncertain"
    assert rejected.skills == []
    assert rejected.needs_review


def test_preserve_skill_provenance_and_dimensions():
    profile = preview_title("快手直播转码 C++ 后端开发")
    assert profile.category == "后端"
    assert profile.specializations == ["音视频"]
    assert profile.domains == ["直播"]
    assert profile.skills == ["C++"]
    profile.evidence.append(
        Evidence(field="skills", value="Redis", quote="面试问Redis", source="interview")
    )
    profile.skills.append("Redis")
    result = validate_evidence(profile, "快手直播转码 C++ 后端开发。面试问Redis")
    assert result.evidence[-1].source == "interview"


def test_flattened_footer_does_not_import_recommended_roles():
    text = "韶音笔试。请设计推荐系统\n题目:删除vector元素。    一键发评 \n推荐:校招Java开发"
    assert "Java" not in strip_nowcoder_noise(text)
    assert "设计推荐系统" in strip_nowcoder_noise(text)
    text = "设计一个点赞收藏系统\n快捷表情  \ufeff 首次评论必得10牛币 推荐Java开发"
    assert strip_nowcoder_noise(text) == "设计一个点赞收藏系统"


@pytest.mark.asyncio
async def test_historical_preview_never_overwrites_existing_profiles():
    session = MagicMock()
    result = MagicMock()
    result.first.return_value = (1,)
    session.execute = AsyncMock(return_value=result)
    await save_profiles(
        session, 1, [preview_title("后端开发")], "后端开发", origin="historical_preview"
    )
    assert session.execute.await_count == 2
    assert all("DELETE" not in str(call.args[0]) for call in session.execute.await_args_list)


def test_model_cannot_claim_human_approval():
    profile = PositionProfile(category="后端", status="classified", human_reviewed=True)
    assert not profile.needs_review
    result = validate_evidence(profile, "后端开发")
    assert not result.human_reviewed
    assert result.needs_review


def test_tool_schema_exposes_controlled_tags_but_not_human_approval():
    schema = profile_tool_schema()
    assert "human_reviewed" not in schema["properties"]
    assert "C++" in schema["properties"]["skills"]["items"]["enum"]
    assert "基础架构" not in schema["properties"]["skills"]["items"]["enum"]
    assert "基础架构" in schema["properties"]["specializations"]["items"]["enum"]


def test_department_cannot_be_other_research_role():
    profile = PositionProfile(
        raw_title="CSIG",
        category="其他",
        status="classified",
        source="declared",
        needs_review=False,
        evidence=[
            Evidence(field="category", value="其他", quote="CSIG日常实习", source="declared")
        ],
    )
    checked = validate_evidence(profile, "CSIG日常实习")
    assert checked.category is None
    assert checked.status == "uncertain"


def test_standalone_comment_action_cuts_following_profiles():
    assert (
        strip_nowcoder_noise("系统设计:推荐算法如何实现\n一键发评\n某用户 Java后端")
        == "系统设计:推荐算法如何实现"
    )
