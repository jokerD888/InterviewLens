"""Durable stage checkpoints and fenced, renewable post leases."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import text

from ..db import session_scope
from ..db.write_lock import lock_write_generation

LEASE_SECONDS = 300


class ProcessingLeaseLost(RuntimeError):
    pass


async def fence_state(session, state):
    await fence(session, state["post_id"], state.get("processing_owner"))
    if not state.get("processing_owner"):
        return
    current = (
        await session.execute(
            text("SELECT title,cleaned_text FROM posts WHERE id=:id FOR UPDATE"),
            {"id": state["post_id"]},
        )
    ).first()
    if not current or (current[0] or "", current[1] or "") != (
        state.get("title") or "",
        state.get("cleaned_text") or "",
    ):
        raise ProcessingLeaseLost("Post content changed during processing")


async def claim(post_id: int, owner: str, source: str) -> dict | None:
    digest = hashlib.sha256(source.encode()).hexdigest()
    async with session_scope() as session:
        await session.execute(
            text("""
            INSERT INTO post_processing(post_id) VALUES(:id)
            ON CONFLICT DO NOTHING
        """),
            {"id": post_id},
        )
        row = (
            (
                await session.execute(
                    text("""
            UPDATE post_processing SET owner=:owner,
                lease_until=NOW()+(:ttl * INTERVAL '1 second'),
                payload=CASE WHEN input_hash=:hash THEN payload ELSE NULL END,
                stages=CASE WHEN input_hash=:hash THEN stages ELSE '{}'::jsonb END,
                failed_stage=CASE WHEN input_hash=:hash THEN failed_stage ELSE NULL END,
                error=CASE WHEN input_hash=:hash THEN error ELSE NULL END,
                input_hash=:hash, updated_at=NOW()
            WHERE post_id=:id AND (owner IS NULL OR lease_until < NOW() OR owner=:owner)
            RETURNING payload,stages
        """),
                    {"id": post_id, "owner": owner, "ttl": LEASE_SECONDS, "hash": digest},
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None


async def fence(session, post_id: int, owner: str | None) -> None:
    if not owner:
        return
    await lock_write_generation(session)
    # Lock the lease row until the business transaction commits. A stale worker
    # cannot commit after a replacement owner has acquired the post.
    row = (
        await session.execute(
            text("""
        SELECT post_id FROM post_processing WHERE post_id=:id
          AND owner=:owner AND lease_until>NOW() FOR UPDATE
    """),
            {"id": post_id, "owner": owner},
        )
    ).first()
    if not row:
        raise ProcessingLeaseLost(f"post {post_id} processing lease expired")


async def save_extraction(session, post_id: int, owner: str | None, payload: dict) -> None:
    if not owner:
        return
    await fence(session, post_id, owner)
    await session.execute(
        text("""
        UPDATE post_processing SET payload=CAST(:payload AS JSONB),
            stages='{"extract":"done"}'::jsonb, updated_at=NOW()
        WHERE post_id=:id AND owner=:owner
    """),
        {"id": post_id, "owner": owner, "payload": json.dumps(payload, ensure_ascii=False)},
    )


async def checkpoint(post_id: int, owner: str, stage: str, *, error: str | None = None):
    async with session_scope() as session:
        await fence(session, post_id, owner)
        await session.execute(
            text("""
            UPDATE post_processing SET stages=stages || CAST(:status AS JSONB),
                failed_stage=:failed,error=:error,updated_at=NOW()
            WHERE post_id=:id AND owner=:owner
        """),
            {
                "id": post_id,
                "owner": owner,
                "status": json.dumps({stage: "failed" if error else "done"}),
                "failed": stage if error else None,
                "error": error,
            },
        )


async def renew(owner: str):
    async with session_scope() as session:
        await session.execute(
            text("""
            UPDATE post_processing SET lease_until=NOW()+(:ttl * INTERVAL '1 second')
            WHERE owner=:owner AND lease_until>NOW()
        """),
            {"owner": owner, "ttl": LEASE_SECONDS},
        )


async def release(owner: str):
    async with session_scope() as session:
        await session.execute(
            text("""
            UPDATE post_processing SET owner=NULL,lease_until=NULL WHERE owner=:owner
        """),
            {"owner": owner},
        )
