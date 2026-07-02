"""/posts/search and /posts/{id} — semantic question search via pgvector."""
from __future__ import annotations

import base64
import hashlib
import json

import numpy as np
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..config import settings
from ..db import Post
from ..embedding import embed_texts
from ..logging import log
from ..observability import get_redis, incr_cache
from .deps import get_session
from .schemas import PostBrief, QuestionOut

router = APIRouter(tags=["search"])


# --------------------------------------------------------------- cache keys


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _emb_version() -> str:
    """Stable version tag from the embedding model id; bump invalidates keys."""
    return _sha(settings.embedding_model)[:16]


def _embed_key(q: str) -> str:
    return f"il:search:embed:v{_emb_version()}:{_sha(q)}"


def _result_key(q: str, filters: dict) -> str:
    canonical = json.dumps({"q": q, **filters}, sort_keys=True, ensure_ascii=False)
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
        return np.frombuffer(base64.b64decode(blob), dtype=np.float32)
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
    try:
        r = get_redis()
        raw = await r.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except (aioredis.RedisError, json.JSONDecodeError):
        log.warning("search.result_cache_get_failed", exc_info=True)
        return None


async def _result_cache_set(key: str, rows: list[dict]) -> None:
    try:
        r = get_redis()
        await r.set(
            key,
            json.dumps(rows, ensure_ascii=False),
            ex=settings.search_result_ttl_seconds,
        )
    except aioredis.RedisError:
        log.warning("search.result_cache_set_failed", exc_info=True)


# ----------------------------------------------------------------- routes


@router.get("/posts/search", response_model=list[QuestionOut])
async def search(
    q: str = Query(..., min_length=2, description="Free-text query"),
    company: str | None = None,
    position: str | None = None,
    min_quality: int = 0,
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[QuestionOut]:
    """pgvector cosine top-K with optional company/position filters.

    Two Redis cache layers (both TTL-driven, miss-through on Redis failure):
      1. query embedding  — 24h, shared across filters
      2. full result      — 30min, keyed on query + filters
    """
    filters = {
        "company": company,
        "position": position,
        "min_quality": min_quality,
        "limit": limit,
    }

    if settings.search_cache_enabled:
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
            qvec = await embed_texts([q])
            await _embed_cache_set(ekey, qvec[0])
    else:
        qvec = await embed_texts([q])

    if qvec.size == 0:
        return []
    vec_str = "[" + ",".join(f"{v:.6f}" for v in qvec[0].tolist()) + "]"

    clauses = ["q.embedding IS NOT NULL"]
    params: dict[str, object] = {
        "limit": limit,
        "vec": vec_str,
        "min_q": min_quality,
    }
    joins = "JOIN posts po ON po.id = q.post_id"
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
    if min_quality > 0:
        clauses.append("COALESCE(po.quality_score, 0) >= :min_q")

    sql = f"""
    SELECT q.id, q.post_id, q.round_no, q.round_type, q.content, q.category,
           q.answer_brief, q.answer_ai, po.quality_score, po.source_url,
           1 - (q.embedding <=> CAST(:vec AS vector)) AS similarity
    FROM questions q
    {joins}
    WHERE {' AND '.join(clauses)}
    ORDER BY q.embedding <=> CAST(:vec AS vector)
    LIMIT :limit
    """
    rows = (await session.execute(sa_text(sql), params)).mappings().all()
    out = [QuestionOut(**dict(r)) for r in rows]

    if settings.search_cache_enabled:
        await _result_cache_set(rkey, [o.model_dump() for o in out])

    return out


@router.get("/posts/{post_id}", response_model=PostBrief)
async def get_post(
    post_id: int,
    session: AsyncSession = Depends(get_session),
) -> PostBrief:
    post = (await session.execute(select(Post).where(Post.id == post_id))).scalar_one_or_none()
    if post is None:
        raise HTTPException(404, "post not found")

    sql = """
    SELECT array_agg(DISTINCT c.canonical) AS companies,
           array_agg(DISTINCT p.canonical) AS positions
    FROM post_company_position pcp
    JOIN companies c ON c.id = pcp.company_id
    JOIN positions p ON p.id = pcp.position_id
    WHERE pcp.post_id = :pid
    """
    row = (await session.execute(sa_text(sql), {"pid": post_id})).mappings().first()
    return PostBrief(
        id=post.id,
        title=post.title,
        source_url=post.source_url,
        posted_at=post.posted_at,
        quality_score=post.quality_score,
        companies=list(row["companies"] or []) if row else [],
        positions=list(row["positions"] or []) if row else [],
    )
