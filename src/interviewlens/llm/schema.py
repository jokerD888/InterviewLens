"""Pydantic schemas for Extractor output (mirrors PROMPT_LIBRARY.md §1.1)."""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class Level(StrEnum):
    INTERN = "实习"
    CAMPUS = "校招"
    SOCIAL = "社招"
    UNKNOWN = "未知"


class RoundType(StrEnum):
    R1 = "技术一面"
    R2 = "技术二面"
    R3 = "技术三面"
    HR = "HR面"
    CROSS = "交叉面"
    OTHER = "其他"


class Category(StrEnum):
    ALGO = "算法"
    DS = "数据结构"
    SYS = "系统设计"
    DB = "数据库"
    OS = "操作系统"
    NET = "网络"
    LANG = "语言基础"
    PROJECT = "项目"
    HR = "HR"
    OTHER = "其他"


class QuestionItem(BaseModel):
    content: str = Field(min_length=2)
    category: Category | None = None
    answer_brief: str | None = None


class RoundItem(BaseModel):
    round_no: int = Field(ge=1, le=20)
    round_type: RoundType | None = None
    questions: list[QuestionItem] = Field(default_factory=list)


class ExtractedPost(BaseModel):
    """Top-level Extractor output. Matches function call schema."""

    companies: list[str] = Field(default_factory=list)
    positions: list[str] = Field(default_factory=list)
    level: Level = Level.UNKNOWN
    interview_date: str | None = None  # YYYY-MM
    rounds: list[RoundItem] = Field(default_factory=list)

    @field_validator("interview_date")
    @classmethod
    def _validate_date(cls, v: str | None) -> str | None:
        if v in (None, "", "null"):
            return None
        if len(v) >= 7 and v[4] == "-":
            return v[:7]
        return None

    @property
    def total_questions(self) -> int:
        return sum(len(r.questions) for r in self.rounds)


# OpenAI / DeepSeek tool schema. Hand-rolled so we control nullability.
EXTRACT_FUNCTION_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": "extract_interview_post",
        "description": "从面经文本中抽取公司、岗位、面试题目等结构化信息",
        "parameters": {
            "type": "object",
            "required": ["companies", "positions", "rounds"],
            "properties": {
                "companies": {
                    "type": "array",
                    "description": "面经涉及的公司名（原文出现的形式，不要规范化）",
                    "items": {"type": "string"},
                },
                "positions": {
                    "type": "array",
                    "description": "面经涉及的岗位（原文形式）",
                    "items": {"type": "string"},
                },
                "level": {
                    "type": "string",
                    "enum": ["实习", "校招", "社招", "未知"],
                },
                "interview_date": {
                    "type": ["string", "null"],
                    "description": "面试时间，YYYY-MM 格式，无法判断填 null",
                },
                "rounds": {
                    "type": "array",
                    "description": "按面试轮次分组的题目",
                    "items": {
                        "type": "object",
                        "required": ["round_no", "questions"],
                        "properties": {
                            "round_no": {"type": "integer", "minimum": 1, "maximum": 20},
                            "round_type": {
                                "type": ["string", "null"],
                                "enum": [
                                    "技术一面",
                                    "技术二面",
                                    "技术三面",
                                    "HR面",
                                    "交叉面",
                                    "其他",
                                    None,
                                ],
                            },
                            "questions": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "required": ["content"],
                                    "properties": {
                                        "content": {"type": "string"},
                                        "category": {
                                            "type": ["string", "null"],
                                            "enum": [
                                                "算法",
                                                "数据结构",
                                                "系统设计",
                                                "数据库",
                                                "操作系统",
                                                "网络",
                                                "语言基础",
                                                "项目",
                                                "HR",
                                                "其他",
                                                None,
                                            ],
                                        },
                                        "answer_brief": {"type": ["string", "null"]},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}
