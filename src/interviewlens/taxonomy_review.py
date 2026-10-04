"""Explicit offline review import; no unauthenticated approval API."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from .crawler.cleaner import strip_nowcoder_noise
from .db.position_profiles import save_profiles
from .db.session import session_scope
from .position_taxonomy import PositionProfile, validate_evidence


async def import_reviews(path: Path):
    records = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    seen = set()
    accepted = 0
    async with session_scope() as session:
        for record in records:
            if record.get("approve") is not True:
                continue
            post_id = int(record["post_id"])
            if post_id in seen:
                raise ValueError(f"duplicate review for post {post_id}")
            seen.add(post_id)
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:post_id)"), {"post_id": post_id}
            )
            row = (
                (
                    await session.execute(
                        text("SELECT title,cleaned_text FROM posts WHERE id=:post_id FOR UPDATE"),
                        {"post_id": post_id},
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ValueError(f"post {post_id} no longer exists")
            author_text = (
                (row["title"] or "") + "\n" + strip_nowcoder_noise(row["cleaned_text"] or "")
            )
            if record["input_hash"] != hashlib.sha256(author_text.encode()).hexdigest():
                raise ValueError(f"post {post_id} changed since the reviewed preview")
            profiles = []
            for payload in record.get("profiles", [record.get("profile")]):
                proposed = PositionProfile.model_validate(payload)
                checked = validate_evidence(proposed, author_text)
                if any(
                    getattr(proposed, field) != getattr(checked, field)
                    for field in ("category", "raw_title", "skills", "domains", "specializations")
                ):
                    raise ValueError(f"post {post_id} has unsupported evidence")
                profiles.append(
                    PositionProfile.model_validate(
                        {
                            **checked.model_dump(mode="json"),
                            "human_reviewed": True,
                            "needs_review": False,
                        }
                    )
                )
            if not profiles:
                raise ValueError("a review must contain at least one profile")
            await save_profiles(session, post_id, profiles, author_text, overwrite_reviewed=True)
            accepted += 1
    print(json.dumps({"reviewed_posts": accepted}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    asyncio.run(import_reviews(parser.parse_args().input))
