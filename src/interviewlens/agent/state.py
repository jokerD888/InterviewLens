"""Pipeline state shared across all LangGraph nodes.

The state is a TypedDict with `total=False` so partial updates from each node
get merged into the running state. Convention: nodes only WRITE the keys they
own and only READ the keys produced by upstream nodes.
"""
from __future__ import annotations

from typing import Any, TypedDict


class PipelineState(TypedDict, total=False):
    # ---- input ---------------------------------------------------------
    url: str
    post_id: int | None

    # ---- crawler -------------------------------------------------------
    raw_html: str | None
    final_url: str | None
    title: str | None

    # ---- cleaner -------------------------------------------------------
    cleaned_text: str | None
    char_count: int | None

    # ---- extractor -----------------------------------------------------
    extracted: dict[str, Any] | None
    extract_usage: dict[str, Any] | None
    extract_cache_hit: bool | None

    # ---- normalizer (D6) ----------------------------------------------
    company_ids: list[int]
    position_ids: list[int]

    # ---- scorer (D7) --------------------------------------------------
    quality_score: int | None
    score_breakdown: dict[str, int] | None

    # ---- control flow --------------------------------------------------
    skip_reason: str | None
    errors: list[str]
    # current_node lets observability tooling know where we are mid-stream.
    current_node: str | None


def make_initial_state(url: str, *, post_id: int | None = None) -> PipelineState:
    return PipelineState(
        url=url,
        post_id=post_id,
        errors=[],
        current_node=None,
        skip_reason=None,
    )
