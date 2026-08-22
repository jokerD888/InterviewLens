"""Three-tier entity normalisation: alias_dict → embedding → LLM.

API: ``resolve_entity(entity_type, alias) -> (canonical_id, confidence, source)``

source is one of: "alias_dict" | "embedding" | "llm" | "new".
The function self-learns at the data layer: embedding/LLM matches and tier-4
new canonicals write an alias mapping back to ``alias_dict`` so later calls can
short-circuit. This does not update model parameters.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import numpy as np
import openai
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


async def _claim_alias(
    session,
    entity_type: str,
    alias: str,
    canonical_id: int,
    confidence: float,
) -> tuple[int, float, bool]:
    """Insert an alias and return the database's winning mapping.

    ``DO NOTHING`` protects the unique key, but the caller must use the row
    already stored in the database when another resolver won the race.  The
    third return value tells the caller whether this invocation inserted the
    mapping.
    """
    stmt = pg_insert(AliasDict).values(
        entity_type=entity_type,
        alias=alias,
        canonical_id=canonical_id,
        confidence=confidence,
    )
    stmt = (
        stmt.on_conflict_do_nothing(index_elements=["entity_type", "alias"])
        .returning(AliasDict.canonical_id, AliasDict.confidence)
    )
    row = (await session.execute(stmt)).first()
    if row is not None:
        return int(row[0]), float(row[1]), True

    existing = (
        await session.execute(
            select(AliasDict.canonical_id, AliasDict.confidence).where(
                AliasDict.entity_type == entity_type,
                AliasDict.alias == alias,
            )
        )
    ).one()
    return int(existing[0]), float(existing[1]), False


async def _write_alias(
    entity_type: str,
    alias: str,
    canonical_id: int,
    confidence: float,
) -> tuple[int, float, bool]:
    """Persist an alias and return the database's winning mapping."""
    async with session_scope() as session:
        return await _claim_alias(session, entity_type, alias, canonical_id, confidence)


async def _get_or_create_canonical(
    session,
    entity_type: str,
    name: str,
) -> tuple[int, bool]:
    """Atomically get or create a canonical row.

    Returns ``(id, created_here)``.  The insert conflict is resolved by the
    database unique constraint, then the already committed row is read back.
    """
    Model = _model_for(entity_type)
    stmt = (
        pg_insert(Model)
        .values(canonical=name)
        .on_conflict_do_nothing(index_elements=["canonical"])
        .returning(Model.id)
    )
    row = (await session.execute(stmt)).first()
    if row is not None:
        return int(row[0]), True

    existing = (
        await session.execute(select(Model.id).where(Model.canonical == name))
    ).scalar_one()
    return int(existing), False


async def _canonical_exists(entity_type: str, canonical_id: int) -> bool:
    """Validate an LLM-selected id against the requested entity table."""
    Model = _model_for(entity_type)
    async with session_scope() as session:
        row = (
            await session.execute(select(Model.id).where(Model.id == canonical_id))
        ).scalar_one_or_none()
    return row is not None


async def _persist_new_canonical(
    entity_type: str,
    alias: str,
    new_name: str,
) -> ResolveResult:
    """Create/claim tier-4 data without leaving a losing canonical orphan."""
    confidence = 0.5
    Model = _model_for(entity_type)
    async with session_scope() as session:
        new_id, created_here = await _get_or_create_canonical(session, entity_type, new_name)
        winner_id, winner_confidence, claimed = await _claim_alias(
            session,
            entity_type,
            alias,
            new_id,
            confidence,
        )

        if not claimed:
            if created_here:
                row = await session.get(Model, new_id)
                if row is not None:
                    await session.delete(row)
            return ResolveResult(
                canonical_id=winner_id,
                confidence=winner_confidence,
                source="alias_dict",
            )

        if new_name != alias:
            await _claim_alias(session, entity_type, new_name, new_id, confidence)

    return ResolveResult(canonical_id=new_id, confidence=confidence, source="new")


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
            winner_id, winner_confidence, claimed = await _write_alias(
                entity_type,
                alias,
                best["id"],
                confidence=best["similarity"],
            )
            log.info(
                "normalize.tier2_hit",
                entity_type=entity_type,
                alias=alias,
                id=winner_id,
                sim=winner_confidence,
                alias_claimed=claimed,
            )
            return ResolveResult(
                canonical_id=winner_id,
                confidence=winner_confidence,
                source="embedding" if claimed else "alias_dict",
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
    except (openai.APIError, asyncio.TimeoutError, RuntimeError) as exc:
        # Layer C: only external/LLM failures degrade to tier4.
        # Logic bugs (TypeError/AttributeError/KeyError) bubble up to the DLQ —
        # ponytail: intentional narrowing, see exception-handling-layering spec.
        log.warning("normalize.llm_failed", alias=alias, exc_info=True)
        decision = None

    if decision and decision.get("decision") == "match" and decision.get("canonical_id"):
        try:
            cid = int(decision["canonical_id"])
            conf = float(decision.get("confidence") or 0.5)
        except (TypeError, ValueError):
            cid = 0
            conf = 0.0
        if cid and conf >= LLM_MIN_CONFIDENCE and await _canonical_exists(entity_type, cid):
            winner_id, winner_confidence, claimed = await _write_alias(
                entity_type,
                alias,
                cid,
                confidence=conf,
            )
            log.info(
                "normalize.tier3_match",
                entity_type=entity_type,
                alias=alias,
                id=winner_id,
                confidence=winner_confidence,
                alias_claimed=claimed,
            )
            return ResolveResult(
                canonical_id=winner_id,
                confidence=winner_confidence,
                source="llm" if claimed else "alias_dict",
            )

    # --- tier 4: create a new canonical
    new_name = (decision or {}).get("canonical_name") or alias
    result = await _persist_new_canonical(entity_type, alias, new_name)
    log.info(
        "normalize.tier4_new" if result.source == "new" else "normalize.alias_race_winner",
        entity_type=entity_type,
        alias=alias,
        new_canonical=new_name,
        id=result.canonical_id,
        source=result.source,
    )
    return result
