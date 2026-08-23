"""SQLModel ORM definitions, mirrored against the SQL migrations."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Index, func
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Company(SQLModel, table=True):
    __tablename__ = "companies"

    id: int | None = Field(default=None, primary_key=True)
    canonical: str = Field(unique=True, index=True)
    industry: str | None = None
    embedding: Any | None = Field(
        default=None,
        sa_column=Column(Vector(1024), nullable=True),
    )
    embedding_model: str | None = None
    embedding_version: int | None = None
    created_at: datetime = Field(default_factory=_now, sa_column_kwargs={"server_default": func.now()})


class Position(SQLModel, table=True):
    __tablename__ = "positions"

    id: int | None = Field(default=None, primary_key=True)
    canonical: str = Field(unique=True, index=True)
    category: str | None = None
    embedding: Any | None = Field(
        default=None,
        sa_column=Column(Vector(1024), nullable=True),
    )
    embedding_model: str | None = None
    embedding_version: int | None = None
    created_at: datetime = Field(default_factory=_now, sa_column_kwargs={"server_default": func.now()})


class Post(SQLModel, table=True):
    __tablename__ = "posts"

    id: int | None = Field(default=None, primary_key=True)
    source_url: str = Field(unique=True, index=True)
    title: str | None = None
    raw_html: str | None = None
    cleaned_text: str | None = None
    posted_at: datetime | None = None
    # Extractor only returns YYYY-MM today; persisted as the first day of month.
    interview_date: date | None = None
    fetched_at: datetime = Field(default_factory=_now, sa_column_kwargs={"server_default": func.now()})
    # Stable, time-independent score used for content-quality gates.
    content_score: int | None = Field(default=None, index=True)
    content_score_version: int = Field(default=1, index=True)
    content_scored_at: datetime | None = None
    # Legacy field kept only so old databases/exports can be read during the
    # migration. New code must not use it for ranking or filtering.
    quality_score: int | None = None
    extract_status: str = Field(default="pending", index=True)
    extract_error: str | None = None
    extract_version: int = Field(default=0, index=True)


class PostCompanyPosition(SQLModel, table=True):
    __tablename__ = "post_company_position"

    post_id: int = Field(foreign_key="posts.id", primary_key=True)
    company_id: int = Field(foreign_key="companies.id", primary_key=True)
    position_id: int = Field(foreign_key="positions.id", primary_key=True)


class Question(SQLModel, table=True):
    __tablename__ = "questions"

    id: int | None = Field(default=None, primary_key=True)
    post_id: int = Field(foreign_key="posts.id", index=True)
    round_no: int | None = None
    round_type: str | None = None
    content: str
    category: str | None = Field(default=None, index=True)
    answer_brief: str | None = None
    answer_ai: str | None = None
    answer_ai_version: int = Field(default=0)
    embedding: Any | None = Field(
        default=None,
        sa_column=Column(Vector(1024), nullable=True),
    )
    embedding_model: str | None = None
    embedding_version: int | None = None
    created_at: datetime = Field(default_factory=_now, sa_column_kwargs={"server_default": func.now()})


class Summary(SQLModel, table=True):
    __tablename__ = "summaries"
    __table_args__ = (
        Index("ux_summaries_lookup", "company_id", "position_id", "period", unique=True),
    )

    id: int | None = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id")
    position_id: int = Field(foreign_key="positions.id")
    period: str
    content_md: str
    sample_count: int = 0  # number of source questions used by the summary
    input_fingerprint: str | None = None  # aggregation cache fingerprint
    updated_at: datetime = Field(default_factory=_now, sa_column_kwargs={"server_default": func.now()})


class CompanyAlias(SQLModel, table=True):
    __tablename__ = "company_aliases"
    __table_args__ = (
        Index("ux_company_alias_lookup", "alias", unique=True),
        Index("idx_company_alias_canonical", "company_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id")
    alias: str
    confidence: float = 1.0
    learned_at: datetime = Field(default_factory=_now, sa_column_kwargs={"server_default": func.now()})


class PositionAlias(SQLModel, table=True):
    __tablename__ = "position_aliases"
    __table_args__ = (
        Index("ux_position_alias_lookup", "alias", unique=True),
        Index("idx_position_alias_canonical", "position_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    position_id: int = Field(foreign_key="positions.id")
    alias: str
    confidence: float = 1.0
    learned_at: datetime = Field(default_factory=_now, sa_column_kwargs={"server_default": func.now()})
