"""Typer CLI entrypoint — extended in later days."""
from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import text

from .config import settings
from .db import session_scope
from .logging import log

app = typer.Typer(no_args_is_help=True, add_completion=False, help="InterviewLens CLI")
console = Console()


@app.command()
def info() -> None:
    """Print effective configuration (sensitive values masked)."""

    def mask(value: str) -> str:
        if not value or len(value) < 8:
            return "***"
        return value[:4] + "***" + value[-4:]

    table = Table(title="InterviewLens settings", show_lines=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="white")
    table.add_row("app_env", settings.app_env)
    table.add_row("database_url", settings.database_url)
    table.add_row("redis_url", settings.redis_url)
    table.add_row("deepseek_model_chat", settings.deepseek_model_chat)
    table.add_row("deepseek_api_key", mask(settings.deepseek_api_key))
    table.add_row("embedding_model", settings.embedding_model)
    table.add_row("nowcoder_cookie", "set" if settings.nowcoder_cookie else "MISSING")
    table.add_row("extract_prompt_version", str(settings.extract_prompt_version))
    console.print(table)


@app.command()
def doctor() -> None:
    """Probe Postgres / Redis / pgvector availability."""

    async def _check_pg() -> tuple[bool, str]:
        try:
            async with session_scope() as s:
                row = await s.execute(text("SELECT version(), extname FROM pg_extension WHERE extname='vector'"))
                _ = row.fetchone()
            return True, "ok (pgvector loaded)"
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"

    async def _check_redis() -> tuple[bool, str]:
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(settings.redis_url)
            pong = await client.ping()
            await client.aclose()
            return True, f"ok ({pong})"
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"

    async def _run() -> None:
        pg_ok, pg_msg = await _check_pg()
        redis_ok, redis_msg = await _check_redis()
        table = Table(title="Health check")
        table.add_column("Component")
        table.add_column("Status", style="green" if pg_ok and redis_ok else "red")
        table.add_column("Detail")
        table.add_row("PostgreSQL", "OK" if pg_ok else "FAIL", pg_msg)
        table.add_row("Redis", "OK" if redis_ok else "FAIL", redis_msg)
        console.print(table)

    asyncio.run(_run())


@app.command()
def seed_aliases() -> None:
    """Load data/seed_aliases.yaml into companies/positions/alias_dict."""
    import yaml

    from .config import PROJECT_ROOT
    from .db import AliasDict, Company, Position

    yaml_path = PROJECT_ROOT / "data" / "seed_aliases.yaml"
    if not yaml_path.exists():
        console.print(f"[red]Missing[/red] {yaml_path}")
        raise typer.Exit(code=1)

    seeds = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))

    async def _run() -> None:
        from sqlmodel import select

        added = {"company": 0, "position": 0, "alias": 0}
        async with session_scope() as s:
            for entity_type, entries in seeds.items():
                Model = Company if entity_type == "company" else Position
                for entry in entries:
                    canonical = entry["canonical"]
                    aliases = entry.get("aliases", [])

                    existing = (await s.execute(
                        select(Model).where(Model.canonical == canonical)
                    )).scalar_one_or_none()
                    if existing is None:
                        existing = Model(canonical=canonical)
                        s.add(existing)
                        await s.flush()
                        added[entity_type] += 1

                    for alias in {canonical, *aliases}:
                        already = (await s.execute(
                            select(AliasDict).where(
                                AliasDict.entity_type == entity_type,
                                AliasDict.alias == alias,
                            )
                        )).scalar_one_or_none()
                        if already is None:
                            s.add(AliasDict(
                                entity_type=entity_type,
                                alias=alias,
                                canonical_id=existing.id,
                                confidence=1.0,
                            ))
                            added["alias"] += 1
        log.info("seed_aliases.done", **added)
        console.print(f"[green]Seeded[/green] {added}")

    asyncio.run(_run())


if __name__ == "__main__":
    app()
