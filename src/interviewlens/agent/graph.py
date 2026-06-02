"""LangGraph StateGraph wiring Crawler → Cleaner → Extractor.

Routing rules:
- After cleaner: if ``skip_reason`` is set (e.g. "too_short"), END.
- After extractor: always END (extractor sets its own skip_reason on failure).

The compiled graph is built lazily and cached so repeated runs reuse it.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Awaitable, Callable

from langgraph.graph import END, START, StateGraph

from ..crawler import NowcoderFetcher
from ..logging import log
from .nodes import cleaner as cleaner_node
from .nodes import crawler as crawler_node
from .nodes import extractor as extractor_node
from .state import PipelineState, make_initial_state


def _route_after_cleaner(state: PipelineState) -> str:
    if state.get("skip_reason"):
        log.info("graph.route", from_="cleaner", decision="end", reason=state.get("skip_reason"))
        return "end"
    return "extract"


def build_graph(
    *,
    fetcher: NowcoderFetcher | None = None,
    use_cache: bool = True,
    min_chars: int = 200,
    reuse_existing: bool = True,
):
    """Compile a StateGraph parameterised on the runtime knobs.

    The returned object exposes ``ainvoke`` for one-shot async runs and
    ``astream`` for streaming intermediate states.
    """

    async def _crawl(state: PipelineState) -> dict[str, Any]:
        return await crawler_node.run(state, fetcher=fetcher, reuse=reuse_existing)

    async def _clean(state: PipelineState) -> dict[str, Any]:
        return await cleaner_node.run(state, min_chars=min_chars)

    async def _extract(state: PipelineState) -> dict[str, Any]:
        return await extractor_node.run(state, use_cache=use_cache)

    graph: StateGraph = StateGraph(PipelineState)
    graph.add_node("crawl", _crawl)
    graph.add_node("clean", _clean)
    graph.add_node("extract", _extract)

    graph.add_edge(START, "crawl")
    graph.add_edge("crawl", "clean")
    graph.add_conditional_edges(
        "clean",
        _route_after_cleaner,
        {"extract": "extract", "end": END},
    )
    graph.add_edge("extract", END)

    return graph.compile()


async def run_pipeline(
    url: str,
    *,
    fetcher: NowcoderFetcher | None = None,
    use_cache: bool = True,
    min_chars: int = 200,
    reuse_existing: bool = True,
) -> PipelineState:
    """Convenience: build + invoke + return final state for one URL."""
    app = build_graph(
        fetcher=fetcher,
        use_cache=use_cache,
        min_chars=min_chars,
        reuse_existing=reuse_existing,
    )
    initial = make_initial_state(url)
    final: PipelineState = await app.ainvoke(initial)
    return final
