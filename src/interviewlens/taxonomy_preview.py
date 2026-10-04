"""Offline historical proposals. Default is a read-only JSONL export, no LLM cost."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from .config import PROJECT_ROOT
from .crawler.cleaner import strip_nowcoder_noise
from .db.position_profiles import save_profiles
from .db.session import get_engine, session_scope
from .position_taxonomy import preview_title


async def run(
    output: Path, *, initialize: bool = False, store: bool = False, refresh_preview: bool = False
):
    if initialize:
        migration = (PROJECT_ROOT / "sql/008_position_profiles.sql").read_text(encoding="utf-8")
        async with get_engine().begin() as connection:
            for statement in migration.split(";"):
                if statement.strip() and statement.strip() not in {"BEGIN", "COMMIT"}:
                    # BEGIN is preceded by a comment in this fixed migration.
                    if statement.rstrip().endswith("BEGIN"):
                        continue
                    await connection.execute(text(statement))
    records = []
    async with session_scope() as session:
        rows = (
            (await session.execute(text("SELECT id,title,cleaned_text FROM posts ORDER BY id")))
            .mappings()
            .all()
        )
        for row in rows:
            title = row["title"] or ""
            author_text = title + "\n" + strip_nowcoder_noise(row["cleaned_text"] or "")
            profile = preview_title(title)
            records.append(
                {
                    "post_id": row["id"],
                    "title": title,
                    "origin": "historical_preview",
                    "input_hash": hashlib.sha256(author_text.encode()).hexdigest(),
                    "profile": profile.model_dump(mode="json"),
                }
            )
            if store:
                await save_profiles(
                    session,
                    row["id"],
                    [profile],
                    author_text,
                    origin="historical_preview",
                    refresh_preview=refresh_preview,
                )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )
    counts = {}
    for record in records:
        key = record["profile"]["category"] or record["profile"]["status"]
        counts[key] = counts.get(key, 0) + 1
    print(
        json.dumps(
            {"posts": len(records), "stored_as_unreviewed": store, "counts": counts},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--init", action="store_true", help="Apply additive migration 008")
    parser.add_argument(
        "--store",
        action="store_true",
        help="Save unreviewed proposals; never overwrite existing profiles",
    )
    parser.add_argument(
        "--refresh-preview",
        action="store_true",
        help="Refresh only unreviewed historical proposals",
    )
    arguments = parser.parse_args()
    asyncio.run(
        run(
            arguments.output,
            initialize=arguments.init,
            store=arguments.store,
            refresh_preview=arguments.refresh_preview,
        )
    )
