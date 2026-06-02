"""SQLModel ORM definitions, mirrored against sql/001_init.sql."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Index
from sqlmodel import Field, SQLModel


class Company(SQLModel, table=True):
    __tablename__ = "companies"

    id: int | None = Field(default=None, primary_key=True)
    canonical: str = Field(unique=True, index=True)
    industry: str | None = None
    created_at: datetime | None = Field(default=None)


class Position(SQLModel, table=True):
    __tablename__ = "positions"

    id: int | None = Field(default=None, primary_key=True)
    canonical: str = Field(unique=True, index=True)
    category: str | None = None
    level: str | None = None
    created_at: datetime | None = Field(default=None)


class Post(SQLModel, table=True):
    __tablename__ = "posts"

    id: int | None = Field(default=None, primary_key=True)
    source_url: str = Field(unique=True, index=True)
    title: str | None = None
    raw_html: str | None = None
    cleaned_text: str | None = None
    posted_at: datetime | None = None
    fetched_at: datetime | None = None
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
    embedding: Any | None = Field(
        default=None,
        sa_column=Column(Vector(1024), nullable=True),
    )
    created_at: datetime | None = None


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
    sample_count: int = 0
    updated_at: datetime | None = None


class AliasDict(SQLModel, table=True):
    __tablename__ = "alias_dict"
    __table_args__ = (
        Index("ux_alias_lookup", "entity_type", "alias", unique=True),
    )

    id: int | None = Field(default=None, primary_key=True)
    entity_type: str  # 'company' | 'position'
    alias: str
    canonical_id: int
    confidence: float = 1.0
    learned_at: datetime | None = None
