"""Ordered, checksum-verified SQL migrations with a PostgreSQL advisory lock.

Existing databases without a ledger require explicit baseline after restore
verification; startup never silently treats an unknown schema as up to date.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re

import psycopg

from ..config import PROJECT_ROOT, settings

LOCK_ID = 479830714
LEDGER = """CREATE TABLE IF NOT EXISTS il_schema_migrations (
    version INTEGER PRIMARY KEY, filename TEXT NOT NULL, sha256 TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(), baseline BOOLEAN NOT NULL DEFAULT false
)"""


def migrations(directory: Path):
    files = sorted(directory.glob("[0-9][0-9][0-9]_*.sql"))
    if not files:
        raise RuntimeError("No migration files found")
    versions = [int(path.name[:3]) for path in files]
    if versions != list(range(1, max(versions) + 1)):
        raise RuntimeError("Migration numbering must be contiguous")
    return files


def transaction_body(source: str) -> str:
    # Only standalone top-level transaction wrappers used in these SQL files.
    # PL/pgSQL BEGIN/END (without semicolon after BEGIN) remain unchanged.
    return re.sub(r"(?im)^\s*(?:BEGIN|COMMIT);\s*$", "", source)


def verify_current(conn):
    tables = ("posts", "questions", "companies", "positions", "company_aliases", "position_aliases",
              "summaries", "post_company_position", "post_companies", "post_position_profiles",
              "crawl_progress", "crawl_queue", "crawl_daily_budget", "crawl_scan_pages",
              "crawl_date_repairs", "crawl_date_unavailable", "post_processing", "site_request_state",
              "post_attribution", "post_question_refs", "interview_experiences", "question_interviews")
    for table in tables:
        if conn.execute("SELECT to_regclass(%s)", (f"public.{table}",)).fetchone()[0] is None:
            raise RuntimeError(f"Baseline refused: missing {table}")
    for table, column in (("summaries", "input_fingerprint"), ("questions", "embedding_model"),
                          ("questions", "embedding_version"), ("posts", "content_score"),
                          ("post_processing", "lease_until")):
        if not conn.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name=%s AND column_name=%s", (table, column)).fetchone():
            raise RuntimeError(f"Baseline refused: missing {table}.{column}")
    if not conn.execute("SELECT 1 FROM pg_extension WHERE extname='vector'").fetchone():
        raise RuntimeError("Baseline refused: pgvector missing")


def run(action: str, directory: Path = PROJECT_ROOT / "sql", *, dsn: str | None = None):
    files = migrations(directory)
    url = (dsn or settings.database_url_sync).replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))
        try:
            conn.execute(LEDGER)
            rows = conn.execute("SELECT version, sha256 FROM il_schema_migrations ORDER BY version").fetchall()
            applied = dict(rows)
            for path in files:
                version = int(path.name[:3])
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if version in applied and applied[version] != digest:
                    raise RuntimeError(f"Migration checksum changed: {path.name}")
            if set(applied) - {int(path.name[:3]) for path in files}:
                raise RuntimeError("Database is newer than this release; do not run older migrations")
            if list(applied) != list(range(1, len(applied) + 1)):
                raise RuntimeError("Migration ledger contains a gap")
            if action == "status":
                print(f"Applied {len(applied)}/{len(files)} migrations")
                return
            if action == "baseline":
                if applied:
                    raise RuntimeError("Baseline refused: ledger is not empty")
                if len(files) != 13:
                    raise RuntimeError("Legacy baseline supports schema 013 only; migrate newer versions normally")
                verify_current(conn)
                with conn.transaction():
                    for path in files:
                        conn.execute("INSERT INTO il_schema_migrations(version,filename,sha256,baseline) VALUES (%s,%s,%s,true)", (int(path.name[:3]), path.name, hashlib.sha256(path.read_bytes()).hexdigest()))
                print("Recorded explicitly verified legacy schema 013 baseline")
                return
            if not applied and conn.execute("SELECT to_regclass('public.posts')").fetchone()[0]:
                raise RuntimeError("Existing database has no migration ledger: verify a backup restore, then run baseline explicitly")
            for path in files:
                version = int(path.name[:3])
                if version in applied:
                    continue
                with conn.transaction():
                    conn.execute(transaction_body(path.read_text(encoding="utf-8")), prepare=False)
                    conn.execute("INSERT INTO il_schema_migrations(version,filename,sha256) VALUES (%s,%s,%s)", (version, path.name, hashlib.sha256(path.read_bytes()).hexdigest()))
                print(f"Applied {path.name}")
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("apply", "status", "baseline"))
    args = parser.parse_args()
    try:
        run(args.action)
    except Exception as error:
        # Connection strings / server exception text can include credentials.
        print(f"Migration stopped ({type(error).__name__}). No credentials printed.")
        if isinstance(error, RuntimeError):
            print(str(error))
        raise SystemExit(1) from None
