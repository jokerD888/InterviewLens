"""Tests for the graph routing function (no I/O)."""
from __future__ import annotations

from interviewlens.agent.graph import _route_after_cleaner
from interviewlens.agent.state import PipelineState, make_initial_state


def test_route_proceeds_when_no_skip() -> None:
    state: PipelineState = make_initial_state("https://x")
    state["cleaned_text"] = "x" * 500
    state["char_count"] = 500
    assert _route_after_cleaner(state) == "extract"


def test_route_ends_on_skip() -> None:
    state: PipelineState = make_initial_state("https://x")
    state["skip_reason"] = "too_short"
    assert _route_after_cleaner(state) == "end"


def test_initial_state_defaults() -> None:
    s = make_initial_state("https://www.nowcoder.com/discuss/1")
    assert s["url"].endswith("/1")
    assert s["errors"] == []
    assert s["skip_reason"] is None
    assert s["current_node"] is None
