"""Pydantic response schemas for the public API."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator
from .public_data import protect_question


class CompanyOut(BaseModel):
    id: int
    canonical: str
    industry: str | None = None
    post_count: int | None = None


class PositionOut(BaseModel):
    id: int
    canonical: str
    category: str | None = None
    post_count: int | None = None


class CompanyPositionStat(BaseModel):
    company_id: int
    company_name: str
    position_id: int
    position_name: str
    post_count: int
    avg_quality: int | None = None
    latest_posted_at: datetime | None = None


class QuestionOut(BaseModel):
    id: int
    post_id: int
    round_no: int | None = None
    round_type: str | None = None
    content: str
    category: str | None = None
    answer_brief: str | None = None
    answer_ai: str | None = None
    content_score: int | None = None
    freshness_score: int | None = None
    ranking_score: int | None = None
    # Deprecated response alias for clients that still expect the old name.
    quality_score: int | None = None
    source_url: str | None = None
    similarity: float | None = None

    @model_validator(mode="after")
    def public_boundary(self):
        return protect_question(self)


class PostBrief(BaseModel):
    id: int
    title: str | None = None
    source_url: str
    posted_at: datetime | None = None
    interview_date: date | None = None
    content_score: int | None = None
    freshness_score: int | None = None
    ranking_score: int | None = None
    # Deprecated response alias for clients that still expect the old name.
    quality_score: int | None = None
    companies: list[str] = Field(default_factory=list)
    positions: list[str] = Field(default_factory=list)


class SummaryOut(BaseModel):
    id: int
    company: str
    position: str
    period: str
    sample_count: int
    content_md: str
    updated_at: datetime | None = None


class JobsOut(BaseModel):
    queues: dict[str, int]
    dlq: dict[str, int]
    workers: list[str]


class HealthOut(BaseModel):
    status: str
    pg: bool
    redis: bool
    pgvector: bool


# ---------------------------------------------------------------- Bridge


class BridgeGenerateRequest(BaseModel):
    question_ids: list[int] = Field(min_length=1, max_length=50)
    regenerate: bool = False


class BridgeGeneratedAnswer(BaseModel):
    question_id: int
    content: str
    category: str | None = None
    generated_answer: str | None = None
    importance_score: int = 3
    error: str | None = None


class BridgeGenerateResponse(BaseModel):
    answers: list[BridgeGeneratedAnswer]


class BridgeExportItem(BaseModel):
    question: str
    answer: str
    importance_score: int = 3
    source_url: str | None = None


class BridgeExportRequest(BaseModel):
    cards: list[BridgeExportItem] = Field(min_length=1, max_length=50)


class BridgeExportResponse(BaseModel):
    imported: int
    skipped: int
    skipped_reasons: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- Feed


class FeedQuestionOut(BaseModel):
    id: int
    round_no: int | None = None
    round_type: str | None = None
    content: str
    answer_brief: str | None = None
    answer_ai: str | None = None

    @model_validator(mode="after")
    def public_boundary(self):
        return protect_question(self)


class PositionProfileOut(BaseModel):
    category: str | None = None
    specializations: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    status: str
    source: str
    taxonomy_version: int


class PostFeedItem(BaseModel):
    id: int
    title: str | None = None
    source_url: str
    posted_at: datetime | None = None
    interview_date: date | None = None
    content_score: int | None = None
    freshness_score: int | None = None
    ranking_score: int | None = None
    companies: list[str] = Field(default_factory=list)
    positions: list[str] = Field(default_factory=list)
    position_profiles: list[PositionProfileOut] = Field(default_factory=list)
    excerpt: str | None = None
    round_types: list[str] = Field(default_factory=list)
    question_count: int = 0
    questions: list[FeedQuestionOut] = Field(default_factory=list)
