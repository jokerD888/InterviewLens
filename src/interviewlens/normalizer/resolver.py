"""Three-tier entity normalisation: alias_dict → embedding → LLM.

API: ``resolve_entity(entity_type, alias) -> (canonical_id, confidence, source)``

source is one of: "alias_dict" | "embedding" | "llm" | "new".
The function self-learns: if embedding or LLM produces a high-confidence match,
the alias is written back to ``alias_dict`` so the next call short-circuits.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select

from ..db import AliasDict, Company, Position, session_scope
from ..embedding import cosine_matrix, embed_texts
from ..llm.deepseek import call_tool
from ..llm.prompts import NORMALIZE_FUNCTION_SCHEMA, build_normalizer_messages
from ..logging import log

EMBED_THRESHOLD_HIGH: float = 0.85   # >= this → auto-match (no LLM)
EMBED_THRESHOLD_LOW: float = 0.55    # below this → no candidate sent to LLM
LLM_MIN_CONFIDENCE: float = 0.7      # below this → fall back to new canonical
TOP_K: int = 5


@dataclass(slots=True)
class ResolveResult:
    canonical_id: int
    confidence: float
    source: str  # alias_dict | embedding | llm | new


# --------------------------------------------------------------- helpers

def _model_for(entity_type: str):
    if entity_type == "company":
        return Company
    if entity_type == "position":
        return Position
    raise ValueError(f"unknown entity_type: {entity_type}")


async def _lookup_alias_dict(entity_type: str, alias: str) -> int | None:
    async with session_scope() as session:
        row = (
            await session.execute(
                select(AliasDict).where(
                    AliasDict.entity_type == entity_type,
                    AliasDict.alias == alias,
                )
            )
        ).scalar_one_or_none()
    return row.canonical_id if row is not None else None


async def _list_canonicals(entity_type: str) -> list[tuple[int, str]]:
    Model = _model_for(entity_type)
    async with session_scope() as session:
        rows = (await session.execute(select(Model.id, Model.canonical))).all()
    return [(r[0], r[1]) for r in rows]


async def _write_alias(
    entity_type: str,
    alias: str,
    canonical_id: int,
    confidence: float,
) -> None:
    """Idempotent alias_dict insert. Skip silently on duplicate."""
    async with session_scope() as session:
        stmt = pg_insert(AliasDict).values(
            entity_type=entity_type,
            alias=alias,
            canonical_id=canonical_id,
            confidence=confidence,
        )
        # Postgres ON CONFLICT DO NOTHING via the unique (entity_type, alias)
        stmt = stmt.on_conflict_do_nothing(index_elements=["entity_type", "alias"])
        await session.execute(stmt)


async def _create_canonical(entity_type: str, name: str) -> int:
    """Insert a new canonical row and return its id (idempotent on canonical)."""
    Model = _model_for(entity_type)
    async with session_scope() as session:
        existing = (
            await session.execute(select(Model).where(Model.canonical == name))
        ).scalar_one_or_none()
        if existing is not None:
            return existing.id  # type: ignore[return-value]
        row = Model(canonical=name)
        session.add(row)
        await session.flush()
        new_id = row.id
    return int(new_id)


# ---------------------------------------------------------------- main

async def resolve_entity(
    entity_type: str,
    alias: str,
    *,
    trace=None,
) -> ResolveResult:
    """Three-tier resolve. Returns canonical_id and how we got there.

    Order:
      1. alias_dict direct lookup
      2. embedding similarity vs all canonicals
      3. LLM tool call with top-5 candidates
      4. new canonical (LLM said "new" or no candidates)
    """
    alias = alias.strip()
    if not alias:
        raise ValueError("alias cannot be empty")

    # --- tier 1: dictionary
    canonical_id = await _lookup_alias_dict(entity_type, alias)
    if canonical_id is not None:
        log.info("normalize.tier1_hit", entity_type=entity_type, alias=alias, id=canonical_id)
        return ResolveResult(canonical_id=canonical_id, confidence=1.0, source="alias_dict")

    # --- tier 2: embedding
    canonicals = await _list_canonicals(entity_type)
    if canonicals:
        names = [c[1] for c in canonicals]
        embeddings = await embed_texts([alias, *names])
        sims = cosine_matrix(embeddings[:1], embeddings[1:])[0]
        order = np.argsort(-sims)
        top_idx = order[:TOP_K]
        top = [
            {"id": canonicals[i][0], "canonical": canonicals[i][1], "similarity": float(sims[i])}
            for i in top_idx
        ]
        best = top[0]
        if best["similarity"] >= EMBED_THRESHOLD_HIGH:
            await _write_alias(entity_type, alias, best["id"], confidence=best["similarity"])
            log.info(
                "normalize.tier2_hit",
                entity_type=entity_type,
                alias=alias,
                id=best["id"],
                sim=best["similarity"],
            )
            return ResolveResult(
                canonical_id=best["id"],
                confidence=float(best["similarity"]),
                source="embedding",
            )
        # filter out very low-similarity candidates before sending to LLM
        candidates_for_llm = [c for c in top if c["similarity"] >= EMBED_THRESHOLD_LOW]
    else:
        candidates_for_llm = []

    # --- tier 3: LLM tool call
    messages = build_normalizer_messages(
        entity_type=entity_type, alias=alias, candidates=candidates_for_llm
    )
    try:
        result = await call_tool(
            messages=messages,
            tools=[NORMALIZE_FUNCTION_SCHEMA],
            tool_choice={
                "type": "function",
                "function": {"name": "decide_canonical"},
            },
            trace_name="normalizer",
            trace_metadata={"entity_type": entity_type, "alias": alias},
            trace=trace,
            temperature=0.0,
            max_tokens=512,
        )
        decision = result.arguments
    except Exception as exc:  # noqa: BLE001
        log.warning("normalize.llm_failed", alias=alias, err=str(exc))
        decision = None

    if decision and decision.get("decision") == "match" and decision.get("canonical_id"):
        cid = int(decision["canonical_id"])
        conf = float(decision.get("confidence") or 0.5)
        if conf >= LLM_MIN_CONFIDENCE:
            await _write_alias(entity_type, alias, cid, confidence=conf)
            log.info(
                "normalize.tier3_match",
                entity_type=entity_type,
                alias=alias,
                id=cid,
                confidence=conf,
            )
            return ResolveResult(canonical_id=cid, confidence=conf, source="llm")

    # --- tier 4: create a new canonical
    new_name = (decision or {}).get("canonical_name") or alias
    new_id = await _create_canonical(entity_type, new_name)
    await _write_alias(entity_type, alias, new_id, confidence=1.0)
    if new_name != alias:
        await _write_alias(entity_type, new_name, new_id, confidence=1.0)
    log.info(
        "normalize.tier4_new",
        entity_type=entity_type,
        alias=alias,
        new_canonical=new_name,
        id=new_id,
    )
    return ResolveResult(canonical_id=new_id, confidence=0.5, source="new")
