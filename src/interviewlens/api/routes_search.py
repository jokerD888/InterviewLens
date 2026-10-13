"""/posts/search and /posts/{id} — semantic question search via pgvector."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from typing import Annotated

import numpy as np
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..db.processing_reads import READY_POST_SQL
from ..config import settings
from ..db import Post
from ..db.attribution import question_scope_sql
from ..embedding import EMBEDDING_VERSION, embed_texts
from ..logging import log
from ..observability import get_cache_redis as get_redis, incr_cache
from ..position_taxonomy import TAXONOMY_VERSION, PositionCategory
from ..scoring import FRESHNESS_POLICY_VERSION, freshness_case_sql, ranking_score, score_freshness
from .deps import get_session
from .position_filters import profile_predicate
from .schemas import PostBrief, QuestionOut
from .resource_guard import bounded_search_embed

router = APIRouter(tags=["search"])


# --------------------------------------------------------------- cache keys


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _emb_version() -> str:
    """Stable tag from model id and contract version; bump invalidates keys."""
    return _sha(f"{settings.embedding_model}:v{EMBEDDING_VERSION}")[:16]


def _embed_key(q: str) -> str:
    return f"il:search:embed:v{_emb_version()}:{_sha(q)}"


def _result_key(q: str, filters: dict) -> str:
    facet_defaults = {
        "position_category": None,
        "specializations": [],
        "domains": [],
        "skills": [],
        "include_unreviewed": False,
        "taxonomy_version": TAXONOMY_VERSION,
    }
    canonical = json.dumps(
        {"q": q, "freshness_policy": FRESHNESS_POLICY_VERSION, "data_policy": 2, **facet_defaults, **filters},
        sort_keys=True,
        ensure_ascii=False,
    )
    return f"il:search:result:v{_emb_version()}:{_sha(canonical)}"


# ----------------------------------------------------------- cache helpers
# Layer B (infra client): Redis failures miss-through to the original path;
# see openspec/changes/exception-handling-layering/.


async def _embed_cache_get(key: str) -> np.ndarray | None:
    try:
        r = get_redis()
        blob = await r.get(key)
        if blob is None:
            return None
        vector = np.frombuffer(base64.b64decode(blob, validate=True), dtype=np.float32)
        with np.errstate(over="ignore", invalid="ignore"):
            norm = float(np.linalg.norm(vector))
        if vector.shape != (settings.embedding_dim,) or not np.isfinite(vector).all() or not np.isfinite(norm) or abs(norm - 1) > .01:
            # Treat corrupted/obsolete cache as a miss; delete only this key.
            await r.delete(key)
            log.warning("search.embed_cache_invalid")
            return None
        return vector
    except (aioredis.RedisError, ValueError):
        log.warning("search.embed_cache_get_failed", exc_info=True)
        return None


async def _embed_cache_set(key: str, vec: np.ndarray) -> None:
    try:
        r = get_redis()
        blob = base64.b64encode(vec.astype(np.float32).tobytes()).decode("ascii")
        await r.set(key, blob, ex=settings.search_embed_ttl_seconds)
    except aioredis.RedisError:
        log.warning("search.embed_cache_set_failed", exc_info=True)


async def _result_cache_get(key: str) -> list[dict] | None:
    from .cache import cache_json_get
    return await cache_json_get(key, redis_client=get_redis())


async def _result_cache_set(key: str, rows: list[dict]) -> None:
    from .cache import cache_json_set
    await cache_json_set(key, rows, ttl_seconds=settings.search_result_ttl_seconds,
                         redis_client=get_redis())


@router.get("/posts/search", response_model=list[QuestionOut])
async def search(
    q: str = Query(..., min_length=2, max_length=1000, description="Free-text query"),
    company: str | None = None,
    position: str | None = None,
    position_category: PositionCategory | None = None,
    specializations: Annotated[list[str] | None, Query()] = None,
    domains: Annotated[list[str] | None, Query()] = None,
    skills: Annotated[list[str] | None, Query()] = None,
    include_unreviewed: bool = False,
    min_quality: Annotated[int, Query(ge=0, le=100)] = 0,
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[QuestionOut]:
    """pgvector cosine top-K with optional company/position filters.

    Two Redis cache layers (both TTL-driven, miss-through on Redis failure):
      1. query embedding  — 24h, shared across filters
      2. full result      — 30min, keyed on query + filters
    """
    limit_val = getattr(limit, "default", 20) if not isinstance(limit, int) else int(limit)
    filters = {
        "company": company,
        "position": position,
        "min_quality": min_quality,
        "limit": limit_val,
        "position_category": position_category,
        "specializations": sorted(set(specializations or [])),
        "domains": sorted(set(domains or [])),
        "skills": sorted(set(skills or [])),
        "include_unreviewed": include_unreviewed,
        "taxonomy_version": TAXONOMY_VERSION,
    }
    facet_params: dict[str, object] = {}
    predicate = profile_predicate(
        position_category,
        specializations,
        domains,
        skills,
        include_unreviewed,
        facet_params,
        question_scope=True,
    )

    if settings.search_cache_enabled and not predicate:
        # Layer 2: full result cache
        rkey = _result_key(q, filters)
        cached_rows = await _result_cache_get(rkey)
        if cached_rows is not None:
            await incr_cache(True)
            return [QuestionOut(**row) for row in cached_rows]
        await incr_cache(False)

    # Layer 1: query embedding cache
    if settings.search_cache_enabled:
        ekey = _embed_key(q)
        qvec_arr = await _embed_cache_get(ekey)
        if qvec_arr is not None:
            await incr_cache(True)
            qvec = qvec_arr.reshape(1, -1)
        else:
            await incr_cache(False)
            qvec = await bounded_search_embed(lambda: embed_texts([q]))
            await _embed_cache_set(ekey, qvec[0])
    else:
        qvec = await bounded_search_embed(lambda: embed_texts([q]))

    if qvec.size == 0:
        return []
    vec_str = "[" + ",".join(f"{v:.6f}" for v in qvec[0].tolist()) + "]"

    clauses = [
        READY_POST_SQL, "po.extract_status = 'done'",
        "q.embedding IS NOT NULL",
        "q.embedding_model = :embedding_model",
        "q.embedding_version = :embedding_version",
    ]
    params: dict[str, object] = {
        "limit": limit_val,
        "vec": vec_str,
        "min_q": min_quality,
        "as_of": datetime.now(timezone.utc),
        "embedding_model": settings.embedding_model,
        "embedding_version": EMBEDDING_VERSION,
    }
    joins = "JOIN posts po ON po.id = q.post_id"
    if predicate:
        clauses.append(predicate)
        params.update(facet_params)
    if company or position:
        clauses.append(
            question_scope_sql(
                company=":company" if company else None, position=":position" if position else None
            )
        )
        params.update({"company": company, "position": position})
    if min_quality > 0:
        clauses.append("COALESCE(po.content_score, 0) >= :min_q")

    freshness = freshness_case_sql()

    sql = f"""
    SELECT q.id, q.post_id, q.round_no, q.round_type, q.content, q.category,
           q.answer_brief, q.answer_ai, po.content_score, po.content_score AS quality_score,
           po.source_url,
           {freshness} AS freshness_score,
           CASE WHEN po.content_score IS NULL THEN NULL
                ELSE po.content_score + {freshness}
           END AS ranking_score,
           1 - (q.embedding <=> CAST(:vec AS vector)) AS similarity
    FROM questions q
    {joins}
    WHERE {" AND ".join(clauses)}
    ORDER BY q.embedding <=> CAST(:vec AS vector)
    LIMIT :limit
    """
    rows = (await session.execute(sa_text(sql), params)).mappings().all()
    out = [QuestionOut(**dict(r)) for r in rows]

    if settings.search_cache_enabled and not predicate:
        await _result_cache_set(rkey, [o.model_dump() for o in out])

    return out


@router.get("/posts/{post_id}", response_model=PostBrief)
async def get_post(
    post_id: Annotated[int, Path(ge=1, le=9223372036854775807)],
    session: AsyncSession = Depends(get_session),
) -> PostBrief:
    post = (await session.execute(select(Post).where(Post.id == post_id))).scalar_one_or_none()
    if post is None:
        raise HTTPException(404, "post not found")

    sql = """
    SELECT array_agg(DISTINCT c.canonical) FILTER (WHERE c.canonical IS NOT NULL) AS companies,
           array_agg(DISTINCT p.canonical) FILTER (WHERE p.canonical IS NOT NULL) AS positions
    FROM posts po
    LEFT JOIN post_companies pc ON pc.post_id = po.id
    LEFT JOIN companies c ON c.id = pc.company_id
    LEFT JOIN post_company_position pcp ON pcp.post_id = po.id
    LEFT JOIN positions p ON p.id = pcp.position_id
    WHERE po.id = :pid
    """
    row = (await session.execute(sa_text(sql), {"pid": post_id})).mappings().first()
    as_of = datetime.now(timezone.utc)
    freshness = score_freshness(post.posted_at, as_of=as_of)
    return PostBrief(
        id=post.id,
        title=post.title,
        source_url=post.source_url,
        posted_at=post.posted_at,
        interview_date=post.interview_date,
        content_score=post.content_score,
        freshness_score=freshness,
        ranking_score=ranking_score(
            post.content_score or 0,
            freshness,
        )
        if post.content_score is not None
        else None,
        quality_score=post.content_score,
        companies=list(row["companies"] or []) if row else [],
        positions=list(row["positions"] or []) if row else [],
    )
