"""LangGraph StateGraph: Crawler → Cleaner → Extractor → Normalizer → Scorer.

Routing rules:
- After cleaner: skip_reason set → END.
- After extractor: skip_reason set → END; otherwise → normalize (or score when skip_normalize).
- After normalizer: → score.
- After scorer: → END.
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
from .nodes import normalizer as normalizer_node
from .nodes import scorer as scorer_node
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
    trace: Any | None = None,
    skip_normalize: bool = False,
):
    """Compile a StateGraph parameterised on the runtime knobs."""

    next_after_extract = "score" if skip_normalize else "normalize"

    def _route_after_extract(state: PipelineState) -> str:
        if state.get("skip_reason"):
            log.info("graph.route", from_="extractor", decision="end", reason=state.get("skip_reason"))
            return "end"
        return next_after_extract

    async def _crawl(state: PipelineState) -> dict[str, Any]:
        return await crawler_node.run(state, fetcher=fetcher, reuse=reuse_existing, trace=trace)

    async def _clean(state: PipelineState) -> dict[str, Any]:
        return await cleaner_node.run(state, min_chars=min_chars, trace=trace)

    async def _extract(state: PipelineState) -> dict[str, Any]:
        return await extractor_node.run(state, use_cache=use_cache, trace=trace)

    async def _normalize(state: PipelineState) -> dict[str, Any]:
        return await normalizer_node.run(state, trace=trace)

    async def _score(state: PipelineState) -> dict[str, Any]:
        return await scorer_node.run(state, trace=trace)

    graph: StateGraph = StateGraph(PipelineState)
    graph.add_node("crawl", _crawl)
    graph.add_node("clean", _clean)
    graph.add_node("extract", _extract)
    if not skip_normalize:
        graph.add_node("normalize", _normalize)
    graph.add_node("score", _score)

    graph.add_edge(START, "crawl")
    graph.add_edge("crawl", "clean")
    graph.add_conditional_edges(
        "clean",
        _route_after_cleaner,
        {"extract": "extract", "end": END},
    )

    if skip_normalize:
        graph.add_conditional_edges(
            "extract",
            _route_after_extract,
            {"score": "score", "end": END},
        )
    else:
        graph.add_conditional_edges(
            "extract",
            _route_after_extract,
            {"normalize": "normalize", "end": END},
        )
        graph.add_edge("normalize", "score")
    graph.add_edge("score", END)

    return graph.compile()


async def run_pipeline(
    url: str,
    *,
    fetcher: NowcoderFetcher | None = None,
    use_cache: bool = True,
    min_chars: int = 200,
    reuse_existing: bool = True,
    skip_normalize: bool = False,
) -> PipelineState:
    """Build + invoke + return final state for one URL."""
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
                    "skip_normalize": skip_normalize,
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
        skip_normalize=skip_normalize,
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
                        "company_ids": final.get("company_ids"),
                        "position_ids": final.get("position_ids"),
                        "quality_score": final.get("quality_score"),
                    }
                )
            except Exception:  # noqa: BLE001
                pass
        return final
    finally:
        langfuse_flush()
