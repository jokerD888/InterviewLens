"""Pydantic response schemas for the public API."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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
    quality_score: int | None = None
    source_url: str | None = None
    similarity: float | None = None


class PostBrief(BaseModel):
    id: int
    title: str | None = None
    source_url: str
    posted_at: datetime | None = None
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
