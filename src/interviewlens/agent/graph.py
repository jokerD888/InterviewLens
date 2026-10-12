"""LangGraph StateGraph: Crawler → Cleaner → Extractor → Normalizer → Scorer.

Routing rules:
- After cleaner: skip_reason set → END.
- After extractor: skip_reason set → END; otherwise → normalize.
- After normalizer: → score.
- After scorer: → END.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import suppress
from typing import Any

from langgraph.graph import END, START, StateGraph

from ..crawler import NowcoderFetcher
from ..errors import swallow
from ..logging import log
from ..observability import get_langfuse, langfuse_flush
from . import processing
from .nodes import cleaner as cleaner_node
from .nodes import crawler as crawler_node
from .nodes import extractor as extractor_node
from .nodes import indexer as indexer_node
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
):
    """Compile a StateGraph parameterised on the runtime knobs."""

    def _route_after_extract(state: PipelineState) -> str:
        if state.get("skip_reason"):
            log.info(
                "graph.route", from_="extractor", decision="end", reason=state.get("skip_reason")
            )
            return "end"
        return "normalize"

    async def _crawl(state: PipelineState) -> dict[str, Any]:
        return await crawler_node.run(state, fetcher=fetcher, reuse=reuse_existing, trace=trace)

    async def _clean(state: PipelineState) -> dict[str, Any]:
        return await cleaner_node.run(state, min_chars=min_chars, trace=trace)

    async def _extract(state: PipelineState) -> dict[str, Any]:
        owner = state.get("processing_owner")
        if not owner:
            return await extractor_node.run(state, use_cache=use_cache, trace=trace)
        from ..llm import get_extractor_prompt_version
        from ..config import settings

        source = (
            f"{get_extractor_prompt_version()}:{settings.deepseek_model_chat}:"
            + (state.get("title") or "")
            + "\n"
            + (state.get("cleaned_text") or "")
        )
        saved = await processing.claim(state["post_id"], owner, source)
        if saved is None:
            return {"skip_reason": "processing_locked", "current_node": "extractor"}
        if not use_cache or saved["stages"].get("index") != "done":
            from ..api.cache import invalidate_read_caches
            await invalidate_read_caches()
        if use_cache and saved["payload"] and saved["stages"].get("extract") == "done":
            return {
                "extracted": saved["payload"],
                "completed_stages": saved["stages"],
                "current_node": "extractor",
                "extract_cache_hit": True,
            }
        return await _stage(
            "extract", state, lambda: extractor_node.run(state, use_cache=use_cache, trace=trace)
        )

    async def _stage(name, state, call):
        owner = state.get("processing_owner")
        if state.get("skip_reason"):
            return {}
        if owner and state.get("completed_stages", {}).get(name) == "done":
            return {"current_node": name}
        try:
            result = await call()
            if owner:
                error = result.get("skip_reason")
                await processing.checkpoint(state["post_id"], owner, name, error=error)
            return result
        except BaseException as exc:
            if owner:
                with suppress(processing.ProcessingLeaseLost):
                    await processing.checkpoint(
                        state["post_id"], owner, name, error=f"{type(exc).__name__}: {exc}"[:2000]
                    )
            raise

    async def _normalize(state: PipelineState) -> dict[str, Any]:
        return await _stage("normalize", state, lambda: normalizer_node.run(state, trace=trace))

    async def _score(state: PipelineState) -> dict[str, Any]:
        return await _stage("score", state, lambda: scorer_node.run(state, trace=trace))

    async def _index(state):
        result = await _stage("index", state, lambda: indexer_node.run(state, trace=trace))
        if not state.get("skip_reason"):
            from ..api.cache import invalidate_read_caches

            await invalidate_read_caches()
        return result

    graph: StateGraph = StateGraph(PipelineState)
    graph.add_node("crawl", _crawl)
    graph.add_node("clean", _clean)
    graph.add_node("extract", _extract)
    graph.add_node("normalize", _normalize)
    graph.add_node("score", _score)
    graph.add_node("index", _index)

    graph.add_edge(START, "crawl")
    graph.add_edge("crawl", "clean")
    graph.add_conditional_edges(
        "clean",
        _route_after_cleaner,
        {"extract": "extract", "end": END},
    )

    graph.add_conditional_edges(
        "extract",
        _route_after_extract,
        {"normalize": "normalize", "end": END},
    )
    graph.add_edge("normalize", "score")
    graph.add_edge("score", "index")
    graph.add_edge("index", END)

    return graph.compile()


async def run_pipeline(
    url: str,
    *,
    fetcher: NowcoderFetcher | None = None,
    use_cache: bool = True,
    min_chars: int = 200,
    reuse_existing: bool = True,
) -> PipelineState:
    """Build + invoke + return final state for one URL."""
    lf = get_langfuse()
    trace = None
    if lf is not None:
        with swallow("graph.trace_create_failed", url=url):  # Layer A
            trace = lf.trace(
                name="il.pipeline",
                metadata={
                    "url": url,
                    "use_cache": use_cache,
                    "min_chars": min_chars,
                    "reuse_existing": reuse_existing,
                },
            )

    app = build_graph(
        fetcher=fetcher,
        use_cache=use_cache,
        min_chars=min_chars,
        reuse_existing=reuse_existing,
        trace=trace,
    )
    initial = make_initial_state(url)
    owner = uuid.uuid4().hex
    initial["processing_owner"] = owner

    async def heartbeat():
        while True:
            await asyncio.sleep(30)
            await processing.renew(owner)

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        final: PipelineState = await app.ainvoke(initial)
        if trace is not None:
            with swallow("graph.trace_update_failed", url=url):  # Layer A
                trace.update(
                    output={
                        "post_id": final.get("post_id"),
                        "skip_reason": final.get("skip_reason"),
                        "errors": final.get("errors"),
                        "company_ids": final.get("company_ids"),
                        "position_ids": final.get("position_ids"),
                        "content_score": final.get("content_score"),
                    }
                )
        return final
    finally:
        heartbeat_task.cancel()
        try:
            with suppress(asyncio.CancelledError):
                await heartbeat_task
        finally:
            try:
                await processing.release(owner)
            finally:
                await asyncio.to_thread(langfuse_flush)
