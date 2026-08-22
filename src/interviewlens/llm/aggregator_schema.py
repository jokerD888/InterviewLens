"""Runtime schema for Aggregator output.

The model is deliberately kept separate from the Extractor schema.  The
Extractor returns data that is persisted, while the Aggregator returns a
short-lived presentation model that is rendered to Markdown.
"""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


NonEmptyString = Annotated[str, Field(min_length=1)]


class AggregatorTopic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    topic: str = Field(min_length=1)
    frequency: int = Field(ge=1)
    sample_questions: list[NonEmptyString] = Field(min_length=1)


class AggregatorEdgeCase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    topic: str = Field(min_length=1)
    questions: list[NonEmptyString] = Field(min_length=1)


class AggregatorResult(BaseModel):
    """Validated JSON returned by the Aggregator model."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    high_frequency_topics: list[AggregatorTopic] = Field(min_length=1)
    focus_areas: list[NonEmptyString] = Field(min_length=1)
    edge_cases: list[AggregatorEdgeCase] = Field(min_length=1)
    prep_advice: list[NonEmptyString] = Field(min_length=1)
