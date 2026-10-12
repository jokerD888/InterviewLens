"""Normalizer node — runs after Extractor.

Maps each raw company / position string into a canonical id via the
three-tier resolver, then writes the post_company_position links.
"""

from __future__ import annotations

import asyncio
from typing import Any

import openai

from ...db import replace_post_links, session_scope
from ...db.position_profiles import save_post_companies
from ...logging import log
from ...normalizer import resolve_entity
from ...observability import node_span
from ..processing import fence_state
from ..state import PipelineState

NODE_NAME = "normalizer"


async def run(state: PipelineState, *, trace: Any | None = None) -> PipelineState:
    post_id = state.get("post_id")
    extracted = state.get("extracted") or {}
    log.info("node.start", node=NODE_NAME, post_id=post_id)

    async with node_span(
        node_name=NODE_NAME,
        trace=trace,
        input_payload={
            "post_id": post_id,
            "companies": extracted.get("companies"),
            "positions": extracted.get("positions"),
        },
    ):
        if state.get("skip_reason"):
            return {"current_node": NODE_NAME}
        if post_id is None or not extracted:
            return {"current_node": NODE_NAME}

        company_names: list[str] = list(dict.fromkeys(extracted.get("companies") or []))
        position_names: list[str] = list(dict.fromkeys(extracted.get("positions") or []))

        company_ids: list[int] = []
        company_map = {}
        position_map = {}
        for name in company_names:
            try:
                r = await resolve_entity("company", name, trace=trace)
                company_ids.append(r.canonical_id)
                company_map[name] = r.canonical_id
            except (openai.APIError, asyncio.TimeoutError, RuntimeError):  # noqa: BLE001
                # Never replace old associations with a partial resolution.
                log.warning("normalize.company_failed", alias=name, exc_info=True)
                raise

        position_ids: list[int] = []
        for name in position_names:
            try:
                r = await resolve_entity("position", name, trace=trace)
                position_ids.append(r.canonical_id)
                position_map[name] = r.canonical_id
            except (openai.APIError, asyncio.TimeoutError, RuntimeError):  # noqa: BLE001
                log.warning("normalize.position_failed", alias=name, exc_info=True)
                raise

        # Deduplicate while preserving order
        company_ids = list(dict.fromkeys(company_ids))
        position_ids = list(dict.fromkeys(position_ids))

        async with session_scope() as session:
            await fence_state(session, state)
            await save_post_companies(session, post_id, company_ids)
            from ...db.attribution import save_attribution

            author = (state.get("title") or "") + "\n" + (state.get("cleaned_text") or "")
            pairs, mode = await save_attribution(
                session, post_id, extracted, company_map, position_map, author
            )
            n_links = await replace_post_links(
                session,
                post_id,
                company_ids=company_ids,
                position_ids=position_ids,
                explicit_pairs=pairs if mode != "ambiguous" else None,
            )

        log.info(
            "node.done",
            node=NODE_NAME,
            post_id=post_id,
            company_ids=company_ids,
            position_ids=position_ids,
            links=n_links,
        )
        return {
            "current_node": NODE_NAME,
            "company_ids": company_ids,
            "position_ids": position_ids,
        }
