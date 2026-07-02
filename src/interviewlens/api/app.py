"""FastAPI application entrypoint.

Run via:
  uv run uvicorn interviewlens.api.app:app --reload --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..logging import log
from .routes_admin import router as admin_router
from .routes_bridge import router as bridge_router
from .routes_feed import router as feed_router
from .routes_search import router as search_router
from .routes_summary import router as summary_router
from .routes_taxonomy import router as taxonomy_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm bge-m3 in the background so first /posts/search isn't slow
    try:
        from ..embedding import get_model

        await get_model()
        log.info("api.embedding_warmed")
    except Exception:  # noqa: BLE001  # ponytail: startup must not abort on model load; broad catch intentional
        log.warning("api.embedding_warm_failed", exc_info=True)
    yield


app = FastAPI(
    title="InterviewLens API",
    version="0.1.0",
    description="Aggregate Nowcoder interview experiences. See docs/ for design.",
    lifespan=lifespan,
)

# Local-dev CORS — allow any origin so Next.js dev server (3000) can call.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(feed_router)
app.include_router(taxonomy_router)
app.include_router(search_router)
app.include_router(summary_router)
app.include_router(bridge_router)
app.include_router(admin_router)


@app.get("/", tags=["meta"])
async def root() -> dict:
    return {
        "name": "InterviewLens",
        "version": "0.1.0",
        "docs": "/docs",
        "endpoints": [
            "/companies",
            "/companies/{id}/positions",
            "/positions",
            "/posts",
            "/posts/search",
            "/posts/{id}",
            "/summaries",
            "/summaries/{company}/{position}",
            "/admin/health",
            "/admin/jobs",
            "/admin/metrics",
        ],
    }
