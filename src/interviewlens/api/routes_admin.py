"""/admin — health probe + jobs panel + manual ingest."""
from __future__ import annotations

import json

import redis
from fastapi import APIRouter, Body, Depends
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..errors import swallow
from ..observability import fetch_metrics
from .deps import get_session
from .schemas import HealthOut, JobsOut

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/health", response_model=HealthOut)
async def health(session: AsyncSession = Depends(get_session)) -> HealthOut:
    pg_ok = False
    pgvector_ok = False
    try:
        row = (
            await session.execute(
                sa_text("SELECT extname FROM pg_extension WHERE extname='vector'")
            )
        ).first()
        pg_ok = True
        pgvector_ok = row is not None
    except Exception:  # noqa: BLE001  # ponytail: health probe — broad catch by design
        pg_ok = False

    redis_ok = False
    try:
        r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        redis_ok = bool(r.ping())
    except Exception:  # noqa: BLE001  # ponytail: health probe — broad catch by design
        redis_ok = False

    status = "ok" if pg_ok and redis_ok and pgvector_ok else "degraded"
    return HealthOut(status=status, pg=pg_ok, redis=redis_ok, pgvector=pgvector_ok)


@router.get("/jobs", response_model=JobsOut)
def jobs() -> JobsOut:
    """Snapshot of Celery queue length + DLQ counts + active workers.

    Sync endpoint on purpose — Celery's ``inspect`` API is blocking.
    """
    from celery.app.control import Inspect

    from ..tasks import celery_app

    r = redis.Redis.from_url(settings.redis_url, decode_responses=True)

    queues: dict[str, int] = {}
    with swallow("admin.jobs.queue_len_failed"):  # Layer D
        # Default Celery queue name when no routing is configured
        queues["celery"] = int(r.llen("celery") or 0)

    dlq: dict[str, int] = {}
    with swallow("admin.jobs.dlq_scan_failed"):  # Layer D
        for key in r.scan_iter(match="il:dlq:*"):
            dlq[key] = int(r.llen(key) or 0)

    workers: list[str] = []
    with swallow("admin.jobs.workers_failed"):  # Layer D — Celery inspect may timeout
        insp: Inspect = celery_app.control.inspect(timeout=1.0)
        active = insp.active() or {}
        workers = list(active.keys())

    return JobsOut(queues=queues, dlq=dlq, workers=workers)


@router.get("/metrics")
async def metrics_endpoint() -> dict:
    snap = await fetch_metrics()
    return {
        "cache": {
            "hits": snap.cache_hit,
            "misses": snap.cache_miss,
            "hit_rate": snap.cache_hit_rate,
        },
        "tokens": {
            "prompt": snap.tokens_prompt,
            "completion": snap.tokens_completion,
            "total": snap.tokens_total,
            "estimated_cost_cny": snap.estimated_cost_cny(),
        },
        "node_runs": snap.node_runs,
        "node_avg_ms": snap.node_avg_ms,
    }


@router.post("/ingest")
def ingest(payload: dict = Body(..., examples=[{"url": "https://www.nowcoder.com/discuss/123"}])) -> dict:
    """Enqueue one URL via Celery. Self-only convenience for the dashboard."""
    from ..tasks import crawl_url

    url = payload.get("url")
    if not url:
        return {"ok": False, "error": "missing url"}
    skip_normalize = bool(payload.get("skip_normalize", False))
    res = crawl_url.delay(url, skip_normalize=skip_normalize)
    return {"ok": True, "task_id": res.id, "url": url}


@router.delete("/dlq/{task_name}")
def clear_dlq(task_name: str) -> dict:
    r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    n = int(r.delete(f"il:dlq:{task_name}"))
    return {"cleared": n, "task_name": task_name}


@router.get("/dlq/{task_name}")
def list_dlq(task_name: str, limit: int = 50) -> dict:
    r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    raw = r.lrange(f"il:dlq:{task_name}", 0, limit - 1) or []
    items = []
    for x in raw:
        try:
            items.append(json.loads(x))
        except json.JSONDecodeError:
            items.append({"raw": x})
    return {"task_name": task_name, "count": len(items), "items": items}
