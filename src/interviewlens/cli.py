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


# --------------------------------------------------------------- extract
@app.command()
def extract(
    post_id: int = typer.Argument(..., help="Post id to extract structured data from"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass Redis LLM result cache"),
) -> None:
    """Run Extractor (DeepSeek Function Calling) on a post's cleaned_text."""
    from .llm import extract_post

    async def _run() -> None:
        outcome = await extract_post(post_id, use_cache=not no_cache)
        if not outcome.success:
            console.print(Panel(outcome.error or "unknown error", title="extract failed", border_style="red"))
            raise typer.Exit(code=1)

        parsed = outcome.parsed
        assert parsed is not None
        meta = Table(title=f"extract#{post_id}", show_header=False)
        meta.add_column("k", style="cyan")
        meta.add_column("v")
        meta.add_row("companies", ", ".join(parsed.companies) or "(none)")
        meta.add_row("positions", ", ".join(parsed.positions) or "(none)")
        meta.add_row("level", parsed.level.value)
        meta.add_row("interview_date", parsed.interview_date or "(unknown)")
        meta.add_row("rounds", str(len(parsed.rounds)))
        meta.add_row("questions inserted", str(outcome.questions_inserted))
        meta.add_row("cache_hit", "yes" if outcome.cache_hit else "no")
        if outcome.usage:
            usage_str = (
                f"in={outcome.usage.get('prompt_tokens')} "
                f"out={outcome.usage.get('completion_tokens')} "
                f"total={outcome.usage.get('total_tokens')}"
            )
            meta.add_row("tokens", usage_str)
        meta.add_row("model", outcome.model or "")
        console.print(meta)

        for r in parsed.rounds:
            preview_lines = []
            for i, q in enumerate(r.questions, 1):
                cat = f"[{q.category.value}]" if q.category else ""
                preview_lines.append(f"{i:2}. {cat} {q.content[:120]}")
            body = "\n".join(preview_lines) or "(no questions)"
            console.print(
                Panel(
                    body,
                    title=f"round {r.round_no} · {r.round_type.value if r.round_type else '?'}",
                    border_style="cyan",
                )
            )

    asyncio.run(_run())


# ------------------------------------------------------------ run-pipeline
@app.command(name="run-pipeline")
def run_pipeline_cmd(
    url: str = typer.Argument(..., help="Nowcoder URL to crawl + extract"),
    headless: bool = typer.Option(True, "--headless/--no-headless"),
    no_cache: bool = typer.Option(False, "--no-cache"),
) -> None:
    """[Legacy] Linear crawl + extract pipeline. Prefer `il graph` (D4)."""
    from .crawler import NowcoderFetcher, crawl_one
    from .llm import extract_post

    async def _run() -> None:
        fetcher = NowcoderFetcher(headless=headless)
        await fetcher.start()
        try:
            crawl_outcome = await crawl_one(url, fetcher=fetcher)
        finally:
            await fetcher.stop()

        if crawl_outcome.skipped:
            console.print(
                Panel(
                    f"crawl skipped: {crawl_outcome.skip_reason}",
                    title="pipeline halted",
                    border_style="yellow",
                )
            )
            raise typer.Exit(code=2)

        extract_outcome = await extract_post(crawl_outcome.post_id, use_cache=not no_cache)
        if not extract_outcome.success:
            console.print(
                Panel(
                    extract_outcome.error or "unknown error",
                    title="extract failed",
                    border_style="red",
                )
            )
            raise typer.Exit(code=3)

        console.print(
            Panel(
                f"post_id      : {crawl_outcome.post_id}\n"
                f"crawl chars  : {crawl_outcome.char_count}\n"
                f"questions    : {extract_outcome.questions_inserted}\n"
                f"cache_hit    : {extract_outcome.cache_hit}\n"
                f"model        : {extract_outcome.model}\n"
                f"tokens       : {extract_outcome.usage}",
                title="pipeline ok",
                border_style="green",
            )
        )

    asyncio.run(_run())


# ------------------------------------------------------------------ graph
@app.command()
def graph(
    url: str = typer.Argument(..., help="Nowcoder URL to run through the LangGraph pipeline"),
    headless: bool = typer.Option(True, "--headless/--no-headless"),
    no_cache: bool = typer.Option(False, "--no-cache"),
    no_reuse: bool = typer.Option(False, "--no-reuse", help="Force refetch even if URL already crawled"),
    min_chars: int = typer.Option(200),
) -> None:
    """Run the LangGraph state-machine pipeline (D4)."""
    from .agent import run_pipeline
    from .crawler import NowcoderFetcher

    async def _run() -> None:
        fetcher = NowcoderFetcher(headless=headless)
        await fetcher.start()
        try:
            final = await run_pipeline(
                url,
                fetcher=fetcher,
                use_cache=not no_cache,
                min_chars=min_chars,
                reuse_existing=not no_reuse,
            )
        finally:
            await fetcher.stop()

        meta = Table(title="graph result", show_header=False)
        meta.add_column("k", style="cyan")
        meta.add_column("v")
        meta.add_row("post_id", str(final.get("post_id")))
        meta.add_row("title", final.get("title") or "")
        meta.add_row("chars", str(final.get("char_count")))
        meta.add_row("skip_reason", final.get("skip_reason") or "(none)")
        meta.add_row("cache_hit", "yes" if final.get("extract_cache_hit") else "no")
        meta.add_row("errors", "; ".join(final.get("errors") or []) or "(none)")
        if final.get("extract_usage"):
            usage = final["extract_usage"]
            meta.add_row(
                "tokens",
                f"in={usage.get('prompt_tokens')} out={usage.get('completion_tokens')} total={usage.get('total_tokens')}",
            )
        console.print(meta)

        if final.get("skip_reason"):
            console.print(Panel(final.get("skip_reason"), title="halted", border_style="yellow"))
            raise typer.Exit(code=2)
        if final.get("errors"):
            raise typer.Exit(code=3)
        console.print(Panel("ok", title="graph", border_style="green"))

    asyncio.run(_run())


# ----------------------------------------------------------------- resume
@app.command()
def resume(
    statuses: str = typer.Option(
        "failed,pending",
        help="Comma-separated extract_status values to retry",
    ),
    limit: int = typer.Option(50, help="Max posts to retry in this run"),
    no_cache: bool = typer.Option(False, "--no-cache"),
    headless: bool = typer.Option(True, "--headless/--no-headless"),
) -> None:
    """Re-run the LangGraph pipeline for posts whose extract_status is failed/pending."""
    from .agent import resume_failed
    from .crawler import NowcoderFetcher

    async def _run() -> None:
        statuses_tuple = tuple(s.strip() for s in statuses.split(",") if s.strip())
        fetcher = NowcoderFetcher(headless=headless)
        await fetcher.start()
        try:
            summaries = await resume_failed(
                statuses=statuses_tuple,
                limit=limit,
                use_cache=not no_cache,
                fetcher=fetcher,
            )
        finally:
            await fetcher.stop()

        if not summaries:
            console.print(Panel(f"no posts matching {statuses_tuple}", title="resume", border_style="yellow"))
            return

        table = Table(title=f"resumed {len(summaries)} posts")
        table.add_column("id")
        table.add_column("status")
        table.add_column("notes")
        for s in summaries:
            ok = bool(s.get("extracted")) and not s.get("skip_reason") and not s.get("errors")
            status = "[green]ok[/green]" if ok else "[red]err[/red]"
            note = s.get("skip_reason") or "; ".join(s.get("errors", [])) or "extracted"
            table.add_row(str(s["post_id"]), status, note)
        console.print(table)

    asyncio.run(_run())


# ---------------------------------------------------------------- metrics
@app.command()
def metrics(
    price_in: float = typer.Option(1.0, "--price-in", help="DeepSeek price per million prompt tokens, CNY"),
    price_out: float = typer.Option(2.0, "--price-out", help="DeepSeek price per million completion tokens, CNY"),
) -> None:
    """Show Redis-tracked metrics: cache hit rate, token totals, per-node latency."""
    from .observability import fetch_metrics

    async def _run() -> None:
        snap = await fetch_metrics()

        cache_table = Table(title="LLM cache")
        cache_table.add_column("k", style="cyan")
        cache_table.add_column("v")
        cache_table.add_row("hits", str(snap.cache_hit))
        cache_table.add_row("misses", str(snap.cache_miss))
        cache_table.add_row("total", str(snap.cache_total))
        cache_table.add_row("hit_rate", f"{snap.cache_hit_rate:.1%}")
        console.print(cache_table)

        tok_table = Table(title="Tokens & cost")
        tok_table.add_column("k", style="cyan")
        tok_table.add_column("v")
        tok_table.add_row("prompt_tokens", f"{snap.tokens_prompt:,}")
        tok_table.add_row("completion_tokens", f"{snap.tokens_completion:,}")
        tok_table.add_row("total_tokens", f"{snap.tokens_total:,}")
        cost = snap.estimated_cost_cny(
            price_in_per_million=price_in,
            price_out_per_million=price_out,
        )
        tok_table.add_row("estimated_cost", f"¥{cost:.4f}")
        console.print(tok_table)

        if snap.node_runs:
            node_table = Table(title="Per-node latency")
            node_table.add_column("node", style="cyan")
            node_table.add_column("runs")
            node_table.add_column("avg_ms")
            for node, runs in sorted(snap.node_runs.items()):
                node_table.add_row(
                    node,
                    str(runs),
                    f"{snap.node_avg_ms.get(node, 0):.1f}",
                )
            console.print(node_table)
        else:
            console.print("[yellow]no node runs recorded yet[/yellow]")

    asyncio.run(_run())


@app.command(name="metrics-reset")
def metrics_reset() -> None:
    """Wipe all Redis metric counters (cache hits, tokens, node latency)."""
    from .observability import reset_metrics

    async def _run() -> None:
        await reset_metrics()
        console.print("[green]metrics reset[/green]")

    asyncio.run(_run())


if __name__ == "__main__":
    app()
