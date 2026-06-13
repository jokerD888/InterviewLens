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
from .db import AliasDict, Company, Position, Post, Summary, session_scope
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
    skip_normalize: bool = typer.Option(False, "--skip-normalize", help="Bypass Normalizer node (faster cold start)"),
) -> None:
    """Run the LangGraph state-machine pipeline (D4+D6)."""
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
                skip_normalize=skip_normalize,
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
        meta.add_row("company_ids", ", ".join(map(str, final.get("company_ids") or [])) or "(none)")
        meta.add_row("position_ids", ", ".join(map(str, final.get("position_ids") or [])) or "(none)")
        meta.add_row("quality_score", str(final.get("quality_score")) if final.get("quality_score") is not None else "(none)")
        if final.get("score_breakdown"):
            br = final["score_breakdown"]
            meta.add_row(
                "score_breakdown",
                f"q={br.get('quantity')} a={br.get('answers')} r={br.get('rounds')} t={br.get('recency')}",
            )
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


# -------------------------------------------------------------- normalize
@app.command()
def normalize(
    alias: str = typer.Argument(..., help='Alias to resolve, e.g. "字节" or "服务端"'),
    entity_type: str = typer.Option(
        "company", "--type", help='"company" or "position"'
    ),
) -> None:
    """Resolve a single alias through the three-tier normalizer."""
    from .normalizer import resolve_entity

    async def _run() -> None:
        result = await resolve_entity(entity_type, alias)
        meta = Table(title=f"normalize · {entity_type}", show_header=False)
        meta.add_column("k", style="cyan")
        meta.add_column("v")
        meta.add_row("alias", alias)
        meta.add_row("canonical_id", str(result.canonical_id))
        meta.add_row("source", result.source)
        meta.add_row("confidence", f"{result.confidence:.3f}")
        console.print(meta)

    asyncio.run(_run())


@app.command()
def aliases(
    entity_type: str = typer.Option("company", "--type", help='"company" or "position"'),
    limit: int = typer.Option(50),
) -> None:
    """List alias_dict entries for sanity-checking the dictionary."""

    async def _run() -> None:
        async with session_scope() as s:
            rows = (
                await s.execute(
                    select(AliasDict)
                    .where(AliasDict.entity_type == entity_type)
                    .order_by(AliasDict.canonical_id, AliasDict.alias)
                    .limit(limit)
                )
            ).scalars().all()
        if not rows:
            console.print(f"[yellow]no aliases for {entity_type}[/yellow]")
            return
        table = Table(title=f"alias_dict · {entity_type} · {len(rows)} rows")
        table.add_column("alias", style="cyan")
        table.add_column("canonical_id")
        table.add_column("conf")
        for r in rows:
            table.add_row(r.alias, str(r.canonical_id), f"{r.confidence:.2f}")
        console.print(table)

    asyncio.run(_run())


# ---------------------------------------------------------------- rescore
@app.command()
def rescore(
    post_id: int = typer.Argument(..., help="Post id to recompute quality_score for"),
    rescore_all: bool = typer.Option(False, "--all", help="Ignore post_id, rescore every post with extracted data"),
) -> None:
    """Recompute Scorer output from existing questions table (no LLM call)."""
    from sqlalchemy import update as sa_update

    from .db import Question
    from .scoring import score_extracted

    async def _build_extracted(s, pid: int) -> dict | None:
        rows = (
            await s.execute(
                select(Question).where(Question.post_id == pid).order_by(Question.round_no, Question.id)
            )
        ).scalars().all()
        if not rows:
            return None
        rounds: dict[int, dict] = {}
        for q in rows:
            r = rounds.setdefault(q.round_no or 1, {"round_no": q.round_no or 1, "round_type": q.round_type, "questions": []})
            r["questions"].append(
                {
                    "content": q.content,
                    "category": q.category,
                    "answer_brief": q.answer_brief,
                }
            )
        return {"rounds": list(rounds.values())}

    async def _do_one(pid: int) -> tuple[int, int, dict[str, int] | None]:
        async with session_scope() as s:
            post = (await s.execute(select(Post).where(Post.id == pid))).scalar_one_or_none()
            if post is None:
                return pid, -1, None
            extracted = await _build_extracted(s, pid)
            br = score_extracted(extracted, posted_at=post.posted_at)
            await s.execute(sa_update(Post).where(Post.id == pid).values(quality_score=br.total))
        return pid, br.total, br.as_dict()

    async def _run() -> None:
        if rescore_all:
            async with session_scope() as s:
                ids = [
                    pid for (pid,) in (
                        await s.execute(
                            select(Post.id)
                            .where(Post.extract_status == "done")
                            .order_by(Post.id)
                        )
                    ).all()
                ]
            if not ids:
                console.print("[yellow]no posts with extract_status='done'[/yellow]")
                return
            table = Table(title=f"rescored {len(ids)} posts")
            table.add_column("post_id")
            table.add_column("score")
            table.add_column("breakdown")
            for pid in ids:
                _, total, br = await _do_one(pid)
                table.add_row(
                    str(pid),
                    str(total),
                    f"q={br['quantity']} a={br['answers']} r={br['rounds']} t={br['recency']}" if br else "(no data)",
                )
            console.print(table)
            return

        pid, total, br = await _do_one(post_id)
        if total == -1:
            console.print(f"[red]post {post_id} not found[/red]")
            raise typer.Exit(code=1)
        meta = Table(title=f"rescore post#{pid}", show_header=False)
        meta.add_column("k", style="cyan")
        meta.add_column("v")
        meta.add_row("total", str(total))
        if br:
            meta.add_row("quantity", str(br["quantity"]))
            meta.add_row("answers", str(br["answers"]))
            meta.add_row("rounds", str(br["rounds"]))
            meta.add_row("recency", str(br["recency"]))
        console.print(meta)

    asyncio.run(_run())


# ------------------------------------------------------------- top-posts
@app.command(name="top-posts")
def top_posts(
    limit: int = typer.Option(20),
    company: str | None = typer.Option(None, help="Filter by canonical company name"),
    position: str | None = typer.Option(None, help="Filter by canonical position name"),
) -> None:
    """List highest-quality posts, optionally filtered by company/position."""
    from sqlalchemy import text as sa_text

    async def _run() -> None:
        params: dict[str, object] = {"limit": limit}
        clauses = ["po.quality_score IS NOT NULL"]
        joins = ""
        if company:
            joins += (
                " JOIN post_company_position pcp_c ON pcp_c.post_id = po.id"
                " JOIN companies c ON c.id = pcp_c.company_id"
            )
            clauses.append("c.canonical = :company")
            params["company"] = company
        if position:
            joins += (
                " JOIN post_company_position pcp_p ON pcp_p.post_id = po.id"
                " JOIN positions p ON p.id = pcp_p.position_id"
            )
            clauses.append("p.canonical = :position")
            params["position"] = position
        sql = (
            "SELECT po.id, po.title, po.quality_score, po.posted_at, po.source_url"
            f" FROM posts po{joins}"
            f" WHERE {' AND '.join(clauses)}"
            " ORDER BY po.quality_score DESC, po.posted_at DESC NULLS LAST"
            " LIMIT :limit"
        )
        async with session_scope() as s:
            rows = (await s.execute(sa_text(sql), params)).all()
        if not rows:
            console.print("[yellow]no rows[/yellow]")
            return
        table = Table(title=f"top {len(rows)} posts" + (f" · {company}" if company else "") + (f" · {position}" if position else ""))
        table.add_column("id")
        table.add_column("score")
        table.add_column("title")
        table.add_column("url")
        for r in rows:
            table.add_row(
                str(r[0]),
                str(r[2]),
                (r[1] or "")[:60],
                str(r[4] or ""),
            )
        console.print(table)

    asyncio.run(_run())


# ---------------------------------------------------------- backfill-embeddings
@app.command(name="backfill-embeddings")
def backfill_embeddings_cmd(
    batch_size: int = typer.Option(64),
    limit: int | None = typer.Option(None, help="Process at most N rows"),
    force: bool = typer.Option(False, "--force", help="Re-embed rows that already have embedding"),
) -> None:
    """Encode questions.content with bge-m3 and write to questions.embedding."""
    from .embedding import backfill_embeddings

    async def _run() -> None:
        stats = await backfill_embeddings(batch_size=batch_size, limit=limit, force=force)
        meta = Table(title="backfill embeddings", show_header=False)
        meta.add_column("k", style="cyan")
        meta.add_column("v")
        meta.add_row("scanned", str(stats.scanned))
        meta.add_row("embedded", str(stats.embedded))
        meta.add_row("skipped", str(stats.skipped))
        console.print(meta)

    asyncio.run(_run())


# ------------------------------------------------------------ aggregate
@app.command()
def aggregate(
    company: str | None = typer.Option(None, help="Canonical company name; omit to aggregate all pairs"),
    position: str | None = typer.Option(None, help="Canonical position name; required when company is given"),
    period: str | None = typer.Option(None, help='e.g. "2025Q2"; omit for "all"'),
    top_n: int = typer.Option(100),
    min_quality: int = typer.Option(30),
    no_write: bool = typer.Option(False, "--no-write", help="Print summary, don't persist"),
) -> None:
    """Run RAG-based summarisation per (company × position × period) bucket."""
    from .aggregator import aggregate_all, aggregate_one

    async def _run() -> None:
        if company and position:
            outcome = await aggregate_one(
                company=company,
                position=position,
                period=period,
                top_n=top_n,
                min_quality=min_quality,
                write=not no_write,
            )
            meta = Table(title="aggregate one", show_header=False)
            meta.add_column("k", style="cyan")
            meta.add_column("v")
            meta.add_row("company_id", str(outcome.company_id))
            meta.add_row("position_id", str(outcome.position_id))
            meta.add_row("period", outcome.period)
            meta.add_row("sample_count", str(outcome.sample_count))
            meta.add_row("summary_chars", str(outcome.summary_chars))
            meta.add_row("written", str(outcome.written))
            meta.add_row("skip_reason", outcome.skip_reason or "(none)")
            console.print(meta)
            return

        if company or position:
            console.print("[red]--company and --position must be set together[/red]")
            raise typer.Exit(code=1)

        results = await aggregate_all(
            top_n=top_n,
            min_quality=min_quality,
            period=period,
            write=not no_write,
        )
        if not results:
            console.print("[yellow]no buckets matched[/yellow]")
            return
        table = Table(title=f"aggregate all · {len(results)} buckets")
        table.add_column("c_id")
        table.add_column("p_id")
        table.add_column("period")
        table.add_column("samples")
        table.add_column("chars")
        table.add_column("status")
        for r in results:
            table.add_row(
                str(r.company_id),
                str(r.position_id),
                r.period,
                str(r.sample_count),
                str(r.summary_chars),
                r.skip_reason or "ok",
            )
        console.print(table)

    asyncio.run(_run())


# ---------------------------------------------------------- show-summary
@app.command(name="show-summary")
def show_summary(
    company: str = typer.Argument(..., help="Canonical company name"),
    position: str = typer.Argument(..., help="Canonical position name"),
    period: str = typer.Option("all", help='e.g. "2025Q2"'),
) -> None:
    """Print a stored summary as markdown."""

    async def _run() -> None:
        async with session_scope() as s:
            row = (
                await s.execute(
                    select(Summary, Company, Position)
                    .join(Company, Company.id == Summary.company_id)
                    .join(Position, Position.id == Summary.position_id)
                    .where(
                        Company.canonical == company,
                        Position.canonical == position,
                        Summary.period == period,
                    )
                )
            ).first()
        if row is None:
            console.print(f"[red]no summary for {company} / {position} / {period}[/red]")
            raise typer.Exit(code=1)
        summary, c, p = row
        console.print(
            Panel(
                summary.content_md,
                title=f"{c.canonical} · {p.canonical} · {summary.period} · {summary.sample_count} samples",
                border_style="cyan",
            )
        )

    asyncio.run(_run())


# ------------------------------------------------------------------- batch
@app.command()
def batch(
    pages: int = typer.Option(1, help="How many listing pages to scan"),
    source: str = typer.Option("interview", help="experience | interview"),
    skip_normalize: bool = typer.Option(False, "--skip-normalize"),
    inline: bool = typer.Option(False, "--inline", help="Run synchronously without Celery (debug)"),
) -> None:
    """Discover URLs from Nowcoder listings and enqueue Celery tasks."""

    async def _inline() -> None:
        from .crawler import NowcoderFetcher, discover_from_listing
        from .agent import run_pipeline

        fetcher = NowcoderFetcher()
        await fetcher.start()
        try:
            urls = await discover_from_listing(source=source, pages=pages, fetcher=fetcher)
            log.info("inline.discovered", n=len(urls))
            for u in urls:
                try:
                    final = await run_pipeline(u, fetcher=fetcher, skip_normalize=skip_normalize)
                    console.print(f"[green]ok[/green] {u} → post_id={final.get('post_id')} score={final.get('quality_score')}")
                except Exception as exc:  # noqa: BLE001
                    console.print(f"[red]err[/red] {u} {exc}")
        finally:
            await fetcher.stop()

    if inline:
        asyncio.run(_inline())
        return

    from .tasks import enqueue_listing

    result = enqueue_listing.delay(pages, source, skip_normalize)
    console.print(
        Panel(
            f"task_id: {result.id}\nuse `il task-status {result.id}` or watch worker logs",
            title="enqueued",
            border_style="green",
        )
    )


# --------------------------------------------------------------- task-status
@app.command(name="task-status")
def task_status(task_id: str = typer.Argument(...)) -> None:
    """Show Celery task state by id."""
    from celery.result import AsyncResult

    from .tasks import celery_app

    res = AsyncResult(task_id, app=celery_app)
    meta = Table(title=f"task {task_id}", show_header=False)
    meta.add_column("k", style="cyan")
    meta.add_column("v")
    meta.add_row("state", res.state)
    meta.add_row("ready", str(res.ready()))
    meta.add_row("successful", str(res.successful()) if res.ready() else "(pending)")
    if res.ready():
        try:
            meta.add_row("result", str(res.result)[:300])
        except Exception as exc:  # noqa: BLE001
            meta.add_row("result_err", str(exc))
    console.print(meta)


# ----------------------------------------------------------------- dlq
@app.command()
def dlq(
    action: str = typer.Argument("list", help="list | drain | clear"),
    task_name: str = typer.Option("il.crawl_url", help="il.crawl_url | il.aggregate_pair"),
    limit: int = typer.Option(50),
) -> None:
    """Inspect or drain the dead-letter queue."""
    from .tasks import dlq_clear, dlq_drain, dlq_list

    if action == "list":
        items = dlq_list(task_name, limit)
        if not items:
            console.print(f"[yellow]DLQ {task_name} is empty[/yellow]")
            return
        table = Table(title=f"DLQ {task_name} · {len(items)} items")
        table.add_column("payload")
        for it in items:
            table.add_row(json.dumps(it, ensure_ascii=False)[:200])
        console.print(table)
    elif action == "drain":
        n = dlq_drain(task_name, limit)
        console.print(f"[green]drained {n} items back into queue[/green]")
    elif action == "clear":
        n = dlq_clear(task_name)
        console.print(f"[green]cleared {n} keys[/green]")
    else:
        console.print(f"[red]unknown action: {action}[/red]")
        raise typer.Exit(code=1)


# ----------------------------------------------------------------- seed-demo
@app.command(name="seed-demo")
def seed_demo_cmd() -> None:
    """Insert deterministic demo data so the UI is demoable without crawling."""
    from .seed_demo import seed_demo

    async def _run() -> None:
        counts = await seed_demo()
        meta = Table(title="demo seed", show_header=False)
        meta.add_column("k", style="cyan")
        meta.add_column("v")
        for k, v in counts.items():
            meta.add_row(k, str(v))
        console.print(meta)
        console.print(
            Panel(
                "Demo data inserted. Try:\n  uv run il serve  &\n  cd web && pnpm dev\n  open http://localhost:3000",
                title="next",
                border_style="green",
            )
        )

    asyncio.run(_run())


# --------------------------------------------------------------- bench-search
@app.command(name="bench-search")
def bench_search(
    queries: str = typer.Option(
        "分布式锁,Redis 持久化,JVM GC,TCP 三次握手,Transformer attention",
        help="comma-separated queries",
    ),
    limit: int = typer.Option(10),
    repeat: int = typer.Option(3),
) -> None:
    """Time pgvector search across a list of queries (embed + retrieval p50)."""
    import time

    from .embedding import embed_texts

    async def _run() -> None:
        from sqlalchemy import text as sa_text

        qs = [q.strip() for q in queries.split(",") if q.strip()]
        table = Table(title=f"bench-search · {len(qs)} queries × {repeat} runs")
        table.add_column("query", style="cyan")
        table.add_column("emb ms")
        table.add_column("p50 ms")
        table.add_column("hits")

        for q in qs:
            t0 = time.perf_counter()
            qvec = await embed_texts([q])
            emb_ms = (time.perf_counter() - t0) * 1000
            vec_str = "[" + ",".join(f"{v:.6f}" for v in qvec[0].tolist()) + "]"

            sample_times: list[float] = []
            hits = 0
            async with session_scope() as s:
                for _ in range(repeat):
                    t0 = time.perf_counter()
                    res = (
                        await s.execute(
                            sa_text(
                                "SELECT q.id FROM questions q "
                                "WHERE q.embedding IS NOT NULL "
                                "ORDER BY q.embedding <=> CAST(:vec AS vector) LIMIT :lim"
                            ),
                            {"vec": vec_str, "lim": limit},
                        )
                    ).all()
                    sample_times.append((time.perf_counter() - t0) * 1000)
                    hits = len(res)

            sample_times.sort()
            p50 = sample_times[len(sample_times) // 2]
            table.add_row(q, f"{emb_ms:.1f}", f"{p50:.1f}", str(hits))

        console.print(table)

    asyncio.run(_run())


# ----------------------------------------------------------------- serve
@app.command()
def serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    """Run the FastAPI dev server (uvicorn)."""
    import uvicorn

    uvicorn.run(
        "interviewlens.api.app:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    app()
