"""Separate process liveness from dependency readiness, without public details."""
import asyncio

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse
from sqlalchemy import text

from ..db.session import get_engine
from ..db.migrate import migrations
from ..config import PROJECT_ROOT
from ..observability import get_redis
from ..logging import log
from .resource_guard import inference_healthy

router = APIRouter(tags=["meta"])


@router.get("/health/live")
async def live():
    return {"status": "alive"}


async def database_ready():
    expected = int(migrations(PROJECT_ROOT / "sql")[-1].name[:3])
    async with get_engine().connect() as conn:
        row = (await conn.execute(text("SELECT count(*),max(version) FROM il_schema_migrations"))).one()
        revision = (await conn.execute(text("SELECT revision FROM il_read_revision WHERE id=1"))).scalar_one()
        version = (await conn.execute(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))).scalar_one()
        return row[0] == expected and row[1] == expected and revision >= 0 and tuple(int(part) for part in version.split('.')[:2]) >= (0,8)


@router.get("/health/ready")
async def ready(request: Request):
    async def dependencies():
        results = await asyncio.gather(database_ready(), get_redis().ping())
        return all(results)
    healthy = False
    if getattr(request.app.state, "embedding_ready", False) and inference_healthy():
        try:
            healthy = await asyncio.wait_for(dependencies(), timeout=2)
        except Exception as error:
            # Readiness is a failure boundary; no credentials/details in response.
            log.warning("api.not_ready", error_type=type(error).__name__)
    return JSONResponse({"status": "ready" if healthy else "not_ready"},
                        status_code=200 if healthy else 503,
                        headers={"Cache-Control": "no-store"})
