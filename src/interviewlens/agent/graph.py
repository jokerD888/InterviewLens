"""LangGraph StateGraph wiring Crawler → Cleaner → Extractor.

Routing rules:
- After cleaner: if ``skip_reason`` is set (e.g. "too_short"), END.
- After extractor: always END (extractor sets its own skip_reason on failure).

A Langfuse trace is created per ``run_pipeline`` invocation; each node attaches
its own span beneath it. Without Langfuse credentials, all observability calls
become no-ops.
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from ..crawler import NowcoderFetcher
from ..logging import log
from ..observability import get_langfuse, langfuse_flush
from .nodes import cleaner as cleaner_node
from .nodes import crawler as crawler_node
from .nodes import extractor as extractor_node
from .state import PipelineState, make_initial_state


def _route_after_cleaner(state: PipelineState) -> str:
    if state.get("skip_reason"):
        log.info(
            "graph.route",
            from_="cleaner",
            decision="end",
            reason=state.get("skip_reason"),
        )
        return "end"
    return "extract"


def build_graph(
    *,
    fetcher: NowcoderFetcher | None = None,
    use_cache: bool = True,
    min_chars: int = 200,
    reuse_existing: bool = True,
    trace: Any | None = None,
):
    """Compile a StateGraph parameterised on the runtime knobs."""

    async def _crawl(state: PipelineState) -> dict[str, Any]:
        return await crawler_node.run(
            state, fetcher=fetcher, reuse=reuse_existing, trace=trace
        )

    async def _clean(state: PipelineState) -> dict[str, Any]:
        return await cleaner_node.run(state, min_chars=min_chars, trace=trace)

    async def _extract(state: PipelineState) -> dict[str, Any]:
        return await extractor_node.run(state, use_cache=use_cache, trace=trace)

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
    """Build + invoke + return final state for one URL.

    A Langfuse trace named ``il.pipeline`` is created per call (if configured).
    """
    lf = get_langfuse()
    trace = None
    if lf is not None:
        try:
            trace = lf.trace(
                name="il.pipeline",
                metadata={
                    "url": url,
                    "use_cache": use_cache,
                    "min_chars": min_chars,
                    "reuse_existing": reuse_existing,
                },
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("graph.trace_create_failed", err=str(exc))
            trace = None

    app = build_graph(
        fetcher=fetcher,
        use_cache=use_cache,
        min_chars=min_chars,
        reuse_existing=reuse_existing,
        trace=trace,
    )
    initial = make_initial_state(url)
    try:
        final: PipelineState = await app.ainvoke(initial)
        if trace is not None:
            try:
                trace.update(
                    output={
                        "post_id": final.get("post_id"),
                        "skip_reason": final.get("skip_reason"),
                        "errors": final.get("errors"),
                    }
                )
            except Exception:  # noqa: BLE001
                pass
        return final
    finally:
        langfuse_flush()
