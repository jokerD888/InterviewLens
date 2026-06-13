"""Backfill embeddings for questions table.

Each question's content is encoded with bge-m3 and written to
``questions.embedding``. Idempotent: rows with non-null embedding are skipped
unless ``force=True``.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import update
from sqlmodel import select

from ..db import Question, session_scope
from .bge_m3 import embed_texts
from ..logging import log


@dataclass(slots=True)
class BackfillStats:
    scanned: int = 0
    embedded: int = 0
    skipped: int = 0


async def backfill_embeddings(
    *,
    batch_size: int = 64,
    limit: int | None = None,
    force: bool = False,
) -> BackfillStats:
    """Encode missing question embeddings in batches.

    bge-m3 prefers batch encoding for throughput, so we hit the model with up
    to ``batch_size`` strings at a time. The DB write is a single UPDATE per row
    keyed by id; pgvector's ``Vector`` type accepts a numpy array.
    """
    stats = BackfillStats()

    async with session_scope() as session:
        stmt = select(Question)
        if not force:
            stmt = stmt.where(Question.embedding.is_(None))  # type: ignore[union-attr]
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
                # pgvector accepts list/np array for the Vector column
                await session.execute(
                    update(Question)
                    .where(Question.id == q.id)
                    .values(embedding=v.tolist())
                )
        stats.embedded += len(chunk)
        log.info("embed.backfill_progress", done=stats.embedded, total=stats.scanned)

    return stats
