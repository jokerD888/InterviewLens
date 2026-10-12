"""Backfill embeddings for questions and canonical entity tables.

Each question's content is encoded with bge-m3 and written to
``questions.embedding``. Rows are skipped only when their vector already uses
the current model/version; ``force=True`` recomputes everything.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_, update
from sqlmodel import select

from ..config import settings
from ..db import Company, Position, Question, session_scope
from ..logging import log
from .bge_m3 import EMBEDDING_VERSION, embed_texts


@dataclass(slots=True)
class BackfillStats:
    scanned: int = 0
    embedded: int = 0
    skipped: int = 0


@dataclass(slots=True)
class CanonicalBackfillStats:
    scanned: int = 0
    embedded: int = 0
    skipped: int = 0


async def backfill_embeddings(
    *,
    batch_size: int = 64,
    limit: int | None = None,
    force: bool = False,
    post_ids: list[int] | None = None,
    processing_owner: str | None = None,
) -> BackfillStats:
    """Encode missing question embeddings in batches.

    bge-m3 prefers batch encoding for throughput, so we hit the model with up
    to ``batch_size`` strings at a time. The DB write is a single UPDATE per row
    keyed by id; pgvector's ``Vector`` type accepts a numpy array.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    stats = BackfillStats()

    async with session_scope() as session:
        stmt = select(Question)
        if post_ids is not None:
            if not post_ids:
                return stats
            stmt = stmt.where(Question.post_id.in_(post_ids))
        if not force:
            stmt = stmt.where(
                or_(
                    Question.embedding.is_(None),  # type: ignore[union-attr]
                    Question.embedding_model.is_(None),
                    Question.embedding_model != settings.embedding_model,
                    Question.embedding_version.is_(None),
                    Question.embedding_version != EMBEDDING_VERSION,
                )
            )
        stmt = stmt.order_by(Question.id)
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).scalars().all()

    stats.scanned = len(rows)
    if not rows:
        return stats

    log.info("embed.backfill_start", n=stats.scanned, batch_size=batch_size)
    for i in range(0, len(rows), batch_size):
        chunk = rows[i : i + batch_size]
        texts = [q.content for q in chunk]
        vecs = await embed_texts(texts)

        async with session_scope() as session:
            for q, v in zip(chunk, vecs, strict=True):
                if processing_owner:
                    from ..agent.processing import fence

                    await fence(session, q.post_id, processing_owner)
                # pgvector accepts list/np array for the Vector column
                await session.execute(
                    update(Question)
                    .where(Question.id == q.id, Question.content == q.content)
                    .values(
                        embedding=v.tolist(),
                        embedding_model=settings.embedding_model,
                        embedding_version=EMBEDDING_VERSION,
                    )
                )
        stats.embedded += len(chunk)
        log.info("embed.backfill_progress", done=stats.embedded, total=stats.scanned)

    return stats


async def backfill_canonical_embeddings(
    *,
    entity_type: str | None = None,
    batch_size: int = 64,
    limit: int | None = None,
    force: bool = False,
) -> CanonicalBackfillStats:
    """Persist embeddings for companies and/or positions.

    Existing canonical rows are intentionally backfilled separately from
    question embeddings: canonical vectors are consumed by the normalizer's
    pgvector nearest-neighbour query and must be available before tier 2 can
    match aliases. New canonical rows are embedded during creation; this
    command repairs old or temporarily failed rows.
    """
    if entity_type not in (None, "company", "position"):
        raise ValueError("entity_type must be 'company', 'position', or None")

    models = (
        [(entity_type, Company if entity_type == "company" else Position)]
        if entity_type is not None
        else [("company", Company), ("position", Position)]
    )
    stats = CanonicalBackfillStats()

    for current_type, Model in models:
        async with session_scope() as session:
            stmt = select(Model)
            if not force:
                stmt = stmt.where(
                    or_(
                        Model.embedding.is_(None),  # type: ignore[union-attr]
                        Model.embedding_model.is_(None),
                        Model.embedding_model != settings.embedding_model,
                        Model.embedding_version.is_(None),
                        Model.embedding_version != EMBEDDING_VERSION,
                    )
                )
            stmt = stmt.order_by(Model.id)
            if limit is not None:
                remaining = max(limit - stats.scanned, 0)
                stmt = stmt.limit(remaining)
            rows = (await session.execute(stmt)).scalars().all()

        stats.scanned += len(rows)
        if not rows:
            continue

        log.info(
            "embed.canonical_backfill_start",
            entity_type=current_type,
            n=len(rows),
            batch_size=batch_size,
        )
        for i in range(0, len(rows), batch_size):
            chunk = rows[i : i + batch_size]
            vecs = await embed_texts([row.canonical for row in chunk])

            async with session_scope() as session:
                for row, vector in zip(chunk, vecs, strict=True):
                    await session.execute(
                        update(Model)
                        .where(Model.id == row.id)
                        .values(
                            embedding=vector.tolist(),
                            embedding_model=settings.embedding_model,
                            embedding_version=EMBEDDING_VERSION,
                        )
                    )
            stats.embedded += len(chunk)
            log.info(
                "embed.canonical_backfill_progress",
                entity_type=current_type,
                done=stats.embedded,
                total=stats.scanned,
            )

    return stats
