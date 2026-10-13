"""Local admin correction of position facets, with optimistic concurrency."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..crawler.cleaner import strip_nowcoder_noise
from ..db.position_profiles import save_profiles
from ..position_taxonomy import PositionCategory, PositionProfile
from .deps import get_session
from .security import require_admin

# Kept as an import alias for callers; all admin routes use the same guard.
local_editor = require_admin

router = APIRouter(prefix="/admin", tags=["position-editor"], dependencies=[Depends(local_editor)])
Session = Annotated[AsyncSession, Depends(get_session)]


class PositionEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: PositionCategory | None
    specializations: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


class Correction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str
    profiles: list[PositionEdit] = Field(min_length=1, max_length=20)


async def editor_state(session, post_id):
    post = (
        (
            await session.execute(
                text("SELECT id,title,cleaned_text FROM posts WHERE id=:id"), {"id": post_id}
            )
        )
        .mappings()
        .first()
    )
    if not post:
        raise HTTPException(404, "Post not found")
    rows = (
        (
            await session.execute(
                text(
                    "SELECT payload,input_hash FROM post_position_profiles WHERE post_id=:id ORDER BY ordinal"
                ),
                {"id": post_id},
            )
        )
        .mappings()
        .all()
    )
    raw = [dict(row) for row in rows]
    author = (post["title"] or "") + "\n" + strip_nowcoder_noise(post["cleaned_text"] or "")
    revision = hashlib.sha256(
        json.dumps([author, raw], ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()
    return (
        post,
        author,
        {
            "post_id": post_id,
            "title": post["title"],
            "revision": revision,
            "profiles": [r["payload"] for r in rows],
        },
    )


@router.get("/position-posts")
async def find_posts(session: Session, q: str = ""):
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id,title FROM posts WHERE title ILIKE :q OR CAST(id AS text)=:id ORDER BY id DESC LIMIT 20"
                ),
                {"q": "%" + q + "%", "id": q},
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


@router.get("/posts/{post_id}/position-profiles")
async def load_editor(post_id: int, session: Session):
    return (await editor_state(session, post_id))[2]


@router.put("/posts/{post_id}/position-profiles")
async def correct_positions(post_id: int, body: Correction, session: Session):
    from ..db.write_lock import lock_write_generation

    await lock_write_generation(session)
    await session.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": post_id})
    await session.execute(text("SELECT id FROM posts WHERE id=:id FOR UPDATE"), {"id": post_id})
    _, author, state = await editor_state(session, post_id)
    if body.revision != state["revision"]:
        raise HTTPException(409, "Classification changed; reload before saving")
    profiles = []
    for index, edit in enumerate(body.profiles):
        previous = state["profiles"][index] if index < len(state["profiles"]) else {}
        values = edit.model_dump(mode="json")
        evidence = [
            e
            for e in previous.get("evidence", [])
            if e["field"] in {"raw_title", "normalized_title"}
            or (e["field"] == "category" and e["value"] == values["category"])
            or (isinstance(values.get(e["field"]), list) and e["value"] in values[e["field"]])
        ]
        try:
            profile = PositionProfile.model_validate(
                {
                    **previous,
                    **values,
                    "evidence": evidence,
                    "status": "classified" if edit.category else "uncertain",
                    "human_reviewed": True,
                    "source_changed": False,
                    "needs_review": False,
                }
            )
        except ValueError as exc:
            raise HTTPException(422, "Unsupported position facets") from exc
        profiles.append(profile)
    await save_profiles(session, post_id, profiles, author, overwrite_reviewed=True)
    result = (await editor_state(session, post_id))[2]
    await session.commit()
    from .cache import invalidate_read_caches

    await invalidate_read_caches()
    return result
