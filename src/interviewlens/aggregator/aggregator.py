"""Aggregator: bucket questions by (company, position, period), dedup by
embedding similarity, then ask DeepSeek to summarise into markdown.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import text as sa_text
from sqlmodel import select

from ..config import settings
from ..db import (
    Company,
    Position,
    Post,
    Question,
    Summary,
    session_scope,
)
from ..embedding import cosine_matrix, embed_texts
from ..llm.deepseek import call_tool, get_client
from ..llm.prompts import (
    build_aggregator_messages,
    render_aggregator_md,
)
from ..logging import log
from ..observability import incr_tokens

DEFAULT_TOP_N = 100
DUP_SIM_THRESHOLD = 0.92  # questions with cosine >= this collapse into one cluster
MIN_QUALITY_SCORE = 30


@dataclass(slots=True)
class AggregateOutcome:
    company_id: int
    position_id: int
    period: str
    sample_count: int
    summary_chars: int
    cache_hit_questions: int
    written: bool
    skip_reason: str | None = None


def _period_for(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    quarter = (dt.month - 1) // 3 + 1
    return f"{dt.year}Q{quarter}"


async def _resolve_canonical_ids(
    *, company: str, position: str
) -> tuple[int | None, int | None]:
    async with session_scope() as session:
        c_id = (
            await session.execute(select(Company.id).where(Company.canonical == company))
        ).scalar_one_or_none()
        p_id = (
            await session.execute(select(Position.id).where(Position.canonical == position))
        ).scalar_one_or_none()
    return c_id, p_id


async def _fetch_candidate_questions(
    *,
    company_id: int,
    position_id: int,
    period: str,
    top_n: int,
    min_quality: int,
) -> list[dict]:
    """Pull candidate questions for a bucket. Falls back to "any time" when the
    period filter starves the bucket."""
    sql = """
    WITH bucket_posts AS (
        SELECT po.id, po.posted_at, po.quality_score
        FROM posts po
        JOIN post_company_position pcp ON pcp.post_id = po.id
        WHERE pcp.company_id = :c
          AND pcp.position_id = :p
          AND po.extract_status = 'done'
          AND COALESCE(po.quality_score, 0) >= :min_q
          AND (
              CAST(:period AS TEXT) IS NULL
              OR to_char(po.posted_at, 'YYYY"Q"Q') = :period
          )
    )
    SELECT q.id, q.content, q.category, q.answer_brief, bp.quality_score, p.source_url
    FROM questions q
    JOIN bucket_posts bp ON bp.id = q.post_id
    JOIN posts p ON p.id = bp.id
    WHERE q.embedding IS NOT NULL
    ORDER BY bp.quality_score DESC NULLS LAST, q.id DESC
    LIMIT :top_n
    """
    params = {
        "c": company_id,
        "p": position_id,
        "period": period,
        "min_q": min_quality,
        "top_n": top_n,
    }
    async with session_scope() as session:
        rows = (await session.execute(sa_text(sql), params)).all()
    return [
        {
            "id": r[0],
            "content": r[1],
            "category": r[2],
            "answer_brief": r[3],
            "quality_score": r[4],
            "source_url": r[5],
        }
        for r in rows
    ]


async def _fetch_embeddings(question_ids: list[int]) -> dict[int, np.ndarray]:
    if not question_ids:
        return {}
    sql = "SELECT id, embedding::text FROM questions WHERE id = ANY(:ids)"
    async with session_scope() as session:
        rows = (await session.execute(sa_text(sql), {"ids": question_ids})).all()

    out: dict[int, np.ndarray] = {}
    for qid, vec_str in rows:
        if vec_str is None:
            continue
        # pgvector text format: "[0.1,0.2,...]"
        cleaned = vec_str.strip().strip("[]")
        if not cleaned:
            continue
        out[qid] = np.fromstring(cleaned, sep=",", dtype=np.float32)
    return out


def _cluster_questions(
    questions: list[dict],
    embeddings: dict[int, np.ndarray],
    *,
    threshold: float,
) -> list[dict]:
    """Greedy clustering by cosine similarity.

    Returns one representative per cluster with a ``freq`` field counting how
    many duplicates collapsed in.
    """
    clusters: list[dict] = []
    centroids: list[np.ndarray] = []

    for q in questions:
        emb = embeddings.get(q["id"])
        if emb is None or emb.size == 0:
            # No embedding → treat as its own cluster.
            clusters.append({**q, "freq": 1})
            continue

        if not centroids:
            clusters.append({**q, "freq": 1})
            centroids.append(emb)
            continue

        gallery = np.stack(centroids)
        sims = cosine_matrix(emb[None, :], gallery)[0]
        best = int(np.argmax(sims))
        if sims[best] >= threshold:
            clusters[best]["freq"] = clusters[best].get("freq", 1) + 1
            continue

        clusters.append({**q, "freq": 1})
        centroids.append(emb)

    clusters.sort(key=lambda x: (-x.get("freq", 1), -(x.get("quality_score") or 0)))
    return clusters


async def _summarise(
    *,
    company: str,
    position: str,
    period: str,
    questions: list[dict],
    trace=None,
) -> tuple[str, dict | None]:
    """Generate structured JSON via DeepSeek, then render to consistent markdown.

    If JSON mode produces empty output, retries once without response_format
    (free-form markdown fallback).
    """
    messages = build_aggregator_messages(
        company=company, position=position, period=period, questions=questions
    )
    client = get_client()
    usage_total: dict | None = None

    # ---- Attempt 1: JSON mode ----
    resp = await client.chat.completions.create(
        model=settings.deepseek_model_chat,
        messages=messages,  # type: ignore[arg-type]
        temperature=0.3,
        max_tokens=8192,
        response_format={"type": "json_object"},  # type: ignore[arg-type]
    )
    raw_content = resp.choices[0].message.content or ""
    usage_total = resp.usage.model_dump() if resp.usage else None

    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError:
        from json_repair import repair_json
        data = json.loads(repair_json(raw_content))
    content_md = render_aggregator_md(data) if isinstance(data, dict) else str(data)

    if usage_total:
        await incr_tokens(
            prompt=int(usage_total.get("prompt_tokens") or 0),
            completion=int(usage_total.get("completion_tokens") or 0),
        )
    if trace is not None:
        try:
            trace.generation(
                name="aggregator.summary",
                model=settings.deepseek_model_chat,
                input=messages,
                output=content_md,
                usage=usage_total,
            ).end()
        except Exception:  # noqa: BLE001
            pass
    return content_md, usage_total


async def aggregate_one(
    *,
    company: str,
    position: str,
    period: str | None = None,
    top_n: int = DEFAULT_TOP_N,
    min_quality: int = MIN_QUALITY_SCORE,
    dedup_threshold: float = DUP_SIM_THRESHOLD,
    write: bool = True,
    trace=None,
) -> AggregateOutcome:
    """Run aggregation for one (company, position, period) bucket."""
    c_id, p_id = await _resolve_canonical_ids(company=company, position=position)
    if c_id is None or p_id is None:
        return AggregateOutcome(
            company_id=c_id or 0,
            position_id=p_id or 0,
            period=period or "",
            sample_count=0,
            summary_chars=0,
            cache_hit_questions=0,
            written=False,
            skip_reason="unknown_canonical",
        )

    period_label = period or "all"
    log.info(
        "aggregate.start",
        company=company,
        position=position,
        period=period_label,
        top_n=top_n,
    )

    raw = await _fetch_candidate_questions(
        company_id=c_id,
        position_id=p_id,
        period=period if period and period != "all" else None,
        top_n=top_n,
        min_quality=min_quality,
    )
    if not raw:
        return AggregateOutcome(
            company_id=c_id,
            position_id=p_id,
            period=period_label,
            sample_count=0,
            summary_chars=0,
            cache_hit_questions=0,
            written=False,
            skip_reason="no_questions",
        )

    # Skip if summary already exists and question count hasn't changed
    if write:
        async with session_scope() as session:
            existing = (
                await session.execute(
                    select(Summary).where(
                        Summary.company_id == c_id,
                        Summary.position_id == p_id,
                        Summary.period == period_label,
                    )
                )
            ).scalar_one_or_none()
        if existing is not None and existing.sample_count == len(raw):
            log.info("aggregate.cached", company=company, position=position, period=period_label, samples=len(raw))
            return AggregateOutcome(
                company_id=c_id,
                position_id=p_id,
                period=period_label,
                sample_count=len(raw),
                summary_chars=0,
                cache_hit_questions=0,
                written=False,
                skip_reason="cached",
            )

    embeddings = await _fetch_embeddings([q["id"] for q in raw])
    clusters = _cluster_questions(raw, embeddings, threshold=dedup_threshold)
    log.info(
        "aggregate.clustered",
        raw=len(raw),
        clusters=len(clusters),
    )

    summary_md, _usage = await _summarise(
        company=company,
        position=position,
        period=period_label,
        questions=clusters,
        trace=trace,
    )

    if write:
        async with session_scope() as session:
            existing = (
                await session.execute(
                    select(Summary).where(
                        Summary.company_id == c_id,
                        Summary.position_id == p_id,
                        Summary.period == period_label,
                    )
                )
            ).scalar_one_or_none()
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            if existing is None:
                session.add(
                    Summary(
                        company_id=c_id,
                        position_id=p_id,
                        period=period_label,
                        content_md=summary_md,
                        sample_count=len(clusters),
                        updated_at=now,
                    )
                )
            else:
                existing.content_md = summary_md
                existing.sample_count = len(clusters)
                existing.updated_at = now

    return AggregateOutcome(
        company_id=c_id,
        position_id=p_id,
        period=period_label,
        sample_count=len(clusters),
        summary_chars=len(summary_md),
        cache_hit_questions=0,
        written=write,
    )


async def aggregate_all(
    *,
    top_n: int = DEFAULT_TOP_N,
    min_quality: int = MIN_QUALITY_SCORE,
    period: str | None = None,
    write: bool = True,
) -> list[AggregateOutcome]:
    """Find every (company, position) pair with data and run aggregate_one."""
    sql = """
    SELECT DISTINCT c.canonical, p.canonical
    FROM post_company_position pcp
    JOIN companies c ON c.id = pcp.company_id
    JOIN positions p ON p.id = pcp.position_id
    JOIN posts po ON po.id = pcp.post_id
    WHERE po.extract_status = 'done' AND COALESCE(po.quality_score, 0) >= :min_q
    """
    async with session_scope() as session:
        pairs = (await session.execute(sa_text(sql), {"min_q": min_quality})).all()

    log.info("aggregate.all_pairs", n=len(pairs))
    results: list[AggregateOutcome] = []
    sem = asyncio.Semaphore(20)  # DeepSeek flash supports 2500 CCU

    async def _one(c_name: str, p_name: str) -> AggregateOutcome | None:
        async with sem:
            try:
                return await aggregate_one(
                    company=c_name,
                    position=p_name,
                    period=period,
                    top_n=top_n,
                    min_quality=min_quality,
                    write=write,
                )
            except Exception as exc:  # noqa: BLE001
                log.error("aggregate.pair_failed", company=c_name, position=p_name, err=str(exc))
                return None

    gathered = await asyncio.gather(*(_one(c, p) for c, p in pairs))
    results = [r for r in gathered if r is not None]
    return results
