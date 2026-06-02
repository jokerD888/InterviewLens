"""Typer CLI entrypoint."""
from __future__ import annotations

import asyncio
import json

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlalchemy import text
from sqlmodel import select

from .config import PROJECT_ROOT, settings
from .db import AliasDict, Company, Position, Post, session_scope
from .logging import log

app = typer.Typer(no_args_is_help=True, add_completion=False, help="InterviewLens CLI")
console = Console()


def _mask(value: str) -> str:
    if not value or len(value) < 8:
        return "***"
    return value[:4] + "***" + value[-4:]


# --------------------------------------------------------------------- info
@app.command()
def info() -> None:
    """Print effective configuration (sensitive values masked)."""
    table = Table(title="InterviewLens settings", show_lines=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="white")
    table.add_row("app_env", settings.app_env)
    table.add_row("database_url", settings.database_url)
    table.add_row("redis_url", settings.redis_url)
    table.add_row("deepseek_model_chat", settings.deepseek_model_chat)
    table.add_row("deepseek_api_key", _mask(settings.deepseek_api_key))
    table.add_row("embedding_model", settings.embedding_model)
    table.add_row("nowcoder_cookie", "set" if settings.nowcoder_cookie else "MISSING")
    table.add_row("crawler_rate_per_sec", str(settings.crawler_rate_per_sec))
    table.add_row("extract_prompt_version", str(settings.extract_prompt_version))
    console.print(table)


# ------------------------------------------------------------------ doctor
@app.command()
def doctor() -> None:
    """Probe Postgres / Redis / pgvector availability."""

    async def _check_pg() -> tuple[bool, str]:
        try:
            async with session_scope() as s:
                row = await s.execute(
                    text("SELECT extname FROM pg_extension WHERE extname='vector'")
                )
                vec = row.fetchone()
            return True, "ok (pgvector loaded)" if vec else "WARN: pgvector not enabled"
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
        table.add_column("Status")
        table.add_column("Detail")
        table.add_row(
            "PostgreSQL",
            "[green]OK[/green]" if pg_ok else "[red]FAIL[/red]",
            pg_msg,
        )
        table.add_row(
            "Redis",
            "[green]OK[/green]" if redis_ok else "[red]FAIL[/red]",
            redis_msg,
        )
        console.print(table)

    asyncio.run(_run())


# ----------------------------------------------------------- seed-aliases
@app.command(name="seed-aliases")
def seed_aliases() -> None:
    """Load data/seed_aliases.yaml into companies/positions/alias_dict."""
    import yaml

    yaml_path = PROJECT_ROOT / "data" / "seed_aliases.yaml"
    if not yaml_path.exists():
        console.print(f"[red]Missing[/red] {yaml_path}")
        raise typer.Exit(code=1)

    seeds = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))

    async def _run() -> None:
        added = {"company": 0, "position": 0, "alias": 0}
        async with session_scope() as s:
            for entity_type, entries in seeds.items():
                Model = Company if entity_type == "company" else Position
                for entry in entries:
                    canonical = entry["canonical"]
                    aliases = entry.get("aliases", [])

                    existing = (
                        await s.execute(select(Model).where(Model.canonical == canonical))
                    ).scalar_one_or_none()
                    if existing is None:
                        existing = Model(canonical=canonical)
                        s.add(existing)
                        await s.flush()
                        added[entity_type] += 1

                    for alias in {canonical, *aliases}:
                        already = (
                            await s.execute(
                                select(AliasDict).where(
                                    AliasDict.entity_type == entity_type,
                                    AliasDict.alias == alias,
                                )
                            )
                        ).scalar_one_or_none()
                        if already is None:
                            s.add(
                                AliasDict(
                                    entity_type=entity_type,
                                    alias=alias,
                                    canonical_id=existing.id,
                                    confidence=1.0,
                                )
                            )
                            added["alias"] += 1
        log.info("seed_aliases.done", **added)
        console.print(f"[green]Seeded[/green] {json.dumps(added)}")

    asyncio.run(_run())


# ----------------------------------------------------------------- crawl
@app.command()
def crawl(
    url: str = typer.Argument(..., help="Nowcoder discussion / experience URL"),
    headless: bool = typer.Option(True, "--headless/--no-headless", help="Run browser headless"),
    min_chars: int = typer.Option(200, help="Skip if cleaned text shorter than this"),
) -> None:
    """Fetch a single URL, clean it, and persist to posts table."""
    from .crawler import crawl_one, NowcoderFetcher

    async def _run() -> None:
        fetcher = NowcoderFetcher(headless=headless)
        await fetcher.start()
        try:
            outcome = await crawl_one(url, fetcher=fetcher, min_chars=min_chars)
        finally:
            await fetcher.stop()

        body = (
            f"post_id: {outcome.post_id}\n"
            f"title:   {outcome.title}\n"
            f"final:   {outcome.final_url}\n"
            f"chars:   {outcome.char_count}\n"
            f"skipped: {outcome.skipped} ({outcome.skip_reason})"
        )
        style = "yellow" if outcome.skipped else "green"
        console.print(Panel(body, title="crawl result", border_style=style))

    asyncio.run(_run())


# ------------------------------------------------------------- show-post
@app.command(name="show-post")
def show_post(
    post_id: int = typer.Argument(..., help="Post id to inspect"),
    chars: int = typer.Option(800, help="How many cleaned chars to preview"),
) -> None:
    """Pretty-print a Post row including a snippet of cleaned_text."""

    async def _run() -> None:
        async with session_scope() as s:
            row = (await s.execute(select(Post).where(Post.id == post_id))).scalar_one_or_none()
        if row is None:
            console.print(f"[red]No post with id={post_id}[/red]")
            raise typer.Exit(code=1)

        meta = Table(title=f"posts#{row.id}", show_header=False)
        meta.add_column("k", style="cyan")
        meta.add_column("v")
        meta.add_row("source_url", row.source_url)
        meta.add_row("title", row.title or "")
        meta.add_row("posted_at", str(row.posted_at))
        meta.add_row("fetched_at", str(row.fetched_at))
        meta.add_row("extract_status", row.extract_status)
        meta.add_row("extract_version", str(row.extract_version))
        meta.add_row("cleaned_chars", str(len(row.cleaned_text or "")))
        console.print(meta)

        snippet = (row.cleaned_text or "")[:chars]
        console.print(Panel(snippet or "(empty)", title="cleaned_text preview", border_style="cyan"))

    asyncio.run(_run())


if __name__ == "__main__":
    app()
