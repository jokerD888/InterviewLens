"""Entity normalisation: alias table → pgvector → LLM.

API: ``resolve_entity(entity_type, alias) -> (canonical_id, confidence, source)``

source is one of: "alias" | "embedding" | "llm" | "new".
The function self-learns at the data layer: embedding/LLM matches and new
canonicals write an alias mapping back to the entity-specific alias table so
later calls can short-circuit. This does not update model parameters.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import openai
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select

from ..config import settings
from ..db import Company, CompanyAlias, Position, PositionAlias, session_scope
from ..embedding import EMBEDDING_VERSION, embed_texts
from ..llm.deepseek import call_tool
from ..llm.prompts import NORMALIZE_FUNCTION_SCHEMA, build_normalizer_messages
from ..logging import log
from .rules import has_lexical_anchor, is_entity_incompatible

EMBED_THRESHOLD_AUTO_MATCH: float = 0.92  # >= this AND lexical anchor AND not incompatible → auto-match
EMBED_THRESHOLD_HIGH: float = EMBED_THRESHOLD_AUTO_MATCH  # backward-compatible alias
EMBED_THRESHOLD_LOW: float = 0.55         # below this → no candidate sent to LLM
LLM_MIN_CONFIDENCE: float = 0.70          # below this → fall back to new canonical
REVIEW_CONFIDENCE_THRESHOLD: float = 0.85 # between 0.70 and 0.85 or weak lexical anchor → flagged for review
TOP_K: int = 5


@dataclass(slots=True)
class ResolveResult:
    canonical_id: int
    confidence: float
    source: str  # alias | embedding | llm | new
    needs_review: bool = False
    review_reason: str = ""


# --------------------------------------------------------------- helpers

def _model_for(entity_type: str):
    if entity_type == "company":
        return Company
    if entity_type == "position":
        return Position
    raise ValueError(f"unknown entity_type: {entity_type}")


def _alias_spec(entity_type: str):
    if entity_type == "company":
        return CompanyAlias, "company_id"
    if entity_type == "position":
        return PositionAlias, "position_id"
    raise ValueError(f"unknown entity_type: {entity_type}")


async def _lookup_alias(entity_type: str, alias: str) -> int | None:
    AliasModel, canonical_field = _alias_spec(entity_type)
    async with session_scope() as session:
        row = (
            await session.execute(
                select(getattr(AliasModel, canonical_field)).where(AliasModel.alias == alias)
            )
        ).scalar_one_or_none()
    return int(row) if row is not None else None


async def _search_canonicals(entity_type: str, alias: str) -> list[dict[str, float | int | str]]:
    """Return the nearest canonical rows using the database vector index.

    Canonical embeddings are persisted on ``companies``/``positions``. The
    old implementation encoded every canonical on every alias miss, which
    made each lookup O(number of canonicals) in both model work and memory.
    """
    if entity_type not in ("company", "position"):
        raise ValueError(f"unknown entity_type: {entity_type}")
    table = "companies" if entity_type == "company" else "positions"
    query_vector = (await embed_texts([alias]))[0].tolist()
    vec_str = "[" + ",".join(f"{value:.6f}" for value in query_vector) + "]"
    sql = f"""
        SELECT id, canonical,
               1 - (embedding <=> CAST(:vec AS vector)) AS similarity
        FROM {table}
        WHERE embedding IS NOT NULL
          AND embedding_model = :embedding_model
          AND embedding_version = :embedding_version
        ORDER BY embedding <=> CAST(:vec AS vector)
        LIMIT :limit
    """
    async with session_scope() as session:
        rows = (
            await session.execute(
                sa_text(sql),
                {
                    "vec": vec_str,
                    "limit": TOP_K,
                    "embedding_model": settings.embedding_model,
                    "embedding_version": EMBEDDING_VERSION,
                },
            )
        ).all()
    return [
        {
            "id": int(row[0]),
            "canonical": row[1],
            "similarity": max(-1.0, min(1.0, float(row[2]))),
        }
        for row in rows
    ]


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
    AliasModel, canonical_field = _alias_spec(entity_type)
    stmt = pg_insert(AliasModel).values(
        alias=alias,
        **{canonical_field: canonical_id},
        confidence=confidence,
    )
    stmt = (
        stmt.on_conflict_do_nothing(index_elements=["alias"])
        .returning(getattr(AliasModel, canonical_field), AliasModel.confidence)
    )
    row = (await session.execute(stmt)).first()
    if row is not None:
        return int(row[0]), float(row[1]), True

    existing = (
        await session.execute(
            select(getattr(AliasModel, canonical_field), AliasModel.confidence).where(
                AliasModel.alias == alias
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
    embedding: list[float] | None = None,
) -> tuple[int, bool]:
    """Atomically get or create a canonical row.

    Returns ``(id, created_here)``.  The insert conflict is resolved by the
    database unique constraint, then the already committed row is read back.
    """
    Model = _model_for(entity_type)
    values: dict[str, object] = {"canonical": name}
    if embedding is not None:
        values["embedding"] = embedding
        values["embedding_model"] = settings.embedding_model
        values["embedding_version"] = EMBEDDING_VERSION
    stmt = (
        pg_insert(Model)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["canonical"])
        .returning(Model.id)
    )
    row = (await session.execute(stmt)).first()
    if row is not None:
        return int(row[0]), True

    existing = (
        await session.execute(select(Model).where(Model.canonical == name))
    ).scalar_one()
    if embedding is not None and (
        existing.embedding is None
        or existing.embedding_model != settings.embedding_model
        or existing.embedding_version != EMBEDDING_VERSION
    ):
        existing.embedding = embedding
        existing.embedding_model = settings.embedding_model
        existing.embedding_version = EMBEDDING_VERSION
    return int(existing.id), False


async def _canonical_exists(entity_type: str, canonical_id: int) -> bool:
    """Validate an LLM-selected id against the requested entity table."""
    Model = _model_for(entity_type)
    async with session_scope() as session:
        row = (
            await session.execute(select(Model.id).where(Model.id == canonical_id))
        ).scalar_one_or_none()
    return row is not None


async def _get_canonical_name(entity_type: str, canonical_id: int) -> str | None:
    """Retrieve canonical name for post-validation checks."""
    Model = _model_for(entity_type)
    async with session_scope() as session:
        row = (
            await session.execute(select(Model.canonical).where(Model.id == canonical_id))
        ).scalar_one_or_none()
    return str(row) if row is not None else None



async def _persist_new_canonical(
    entity_type: str,
    alias: str,
    new_name: str,
) -> ResolveResult:
    """Create/claim tier-4 data without leaving a losing canonical orphan."""
    confidence = 0.5
    Model = _model_for(entity_type)
    embedding: list[float] | None = None
    try:
        embedding = (await embed_texts([new_name]))[0].tolist()
    except (ImportError, OSError, RuntimeError):
        # A model/runtime failure leaves the vector NULL; the backfill command
        # can repair it without losing the canonical or alias mapping.
        log.warning("normalize.canonical_embedding_failed", name=new_name, exc_info=True)
    async with session_scope() as session:
        new_id, created_here = await _get_or_create_canonical(
            session, entity_type, new_name, embedding
        )
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
                source="alias",
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
      1. entity-specific alias table direct lookup
      2. pgvector nearest-neighbour search over canonical embeddings
      3. LLM tool call with top-5 candidates
      4. new canonical (LLM said "new" or no candidates)
    """
    alias = alias.strip()
    if not alias:
        raise ValueError("alias cannot be empty")

    # --- tier 1: dictionary
    canonical_id = await _lookup_alias(entity_type, alias)
    if canonical_id is not None:
        log.info("normalize.tier1_hit", entity_type=entity_type, alias=alias, id=canonical_id)
        return ResolveResult(canonical_id=canonical_id, confidence=1.0, source="alias")

    # --- tier 2: embedding
    top = await _search_canonicals(entity_type, alias)
    # Pre-filtering: exclude candidates that violate domain/language incompatibility rules
    valid_candidates: list[dict[str, float | int | str]] = []
    candidates_name_map: dict[int, str] = {}
    for c in top:
        c_id = int(c["id"])
        c_name = str(c["canonical"])
        candidates_name_map[c_id] = c_name
        is_bad, reason = is_entity_incompatible(entity_type, alias, c_name)
        if is_bad:
            log.warning(
                "normalize.candidate_excluded_incompatible",
                entity_type=entity_type,
                alias=alias,
                candidate=c_name,
                similarity=c["similarity"],
                reason=reason,
            )
            continue
        valid_candidates.append(c)

    if valid_candidates:
        best = valid_candidates[0]
        # Dual-gating for Tier-2 auto match:
        # 1. High cosine similarity (>= EMBED_THRESHOLD_AUTO_MATCH)
        # 2. Strict lexical anchor (common stem / substring / character overlap)
        # 3. Passed incompatibility check above
        has_anchor = has_lexical_anchor(alias, str(best["canonical"]))
        if float(best["similarity"]) >= EMBED_THRESHOLD_AUTO_MATCH and has_anchor:
            winner_id, winner_confidence, claimed = await _write_alias(
                entity_type,
                alias,
                int(best["id"]),
                confidence=float(best["similarity"]),
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
                source="embedding" if claimed else "alias",
                needs_review=False,
            )

        # Candidates eligible for LLM evaluation
        candidates_for_llm = [c for c in valid_candidates if c["similarity"] >= EMBED_THRESHOLD_LOW]
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
            # Post-Validation Gate: inspect chosen canonical name
            chosen_name = candidates_name_map.get(cid)
            if not chosen_name:
                chosen_name = await _get_canonical_name(entity_type, cid)

            is_bad, bad_reason = (
                is_entity_incompatible(entity_type, alias, chosen_name)
                if chosen_name
                else (False, "")
            )
            if is_bad:
                log.warning(
                    "normalize.llm_match_rejected_incompatible",
                    entity_type=entity_type,
                    alias=alias,
                    chosen_id=cid,
                    chosen_name=chosen_name,
                    reason=bad_reason,
                )
                # LLM hallucinated an incompatible merge; refuse and proceed to tier 4
            else:
                has_anchor = has_lexical_anchor(alias, chosen_name) if chosen_name else False
                needs_review = (conf < REVIEW_CONFIDENCE_THRESHOLD) or (not has_anchor)
                review_reason = (
                    "llm_low_confidence_or_weak_lexical_anchor" if needs_review else ""
                )

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
                    needs_review=needs_review,
                )
                return ResolveResult(
                    canonical_id=winner_id,
                    confidence=winner_confidence,
                    source="llm" if claimed else "alias",
                    needs_review=needs_review,
                    review_reason=review_reason,
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
