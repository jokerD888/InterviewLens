"""Pipeline state shared across all LangGraph nodes."""
from __future__ import annotations

from typing import Any, TypedDict


class PipelineState(TypedDict, total=False):
    """Mutable state passed between nodes.

    Each node should only read what it needs and write its own outputs.
    Empty / None values mean "node hasn't run yet".
    """

    # input
    url: str
    post_id: int | None

    # crawler
    raw_html: str | None

    # cleaner
    cleaned_text: str | None

    # extractor
    extracted: dict[str, Any] | None

    # normalizer
    company_ids: list[int]
    position_ids: list[int]

    # scorer
    quality_score: int | None

    # control flow
    skip_reason: str | None
    errors: list[str]
