# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

InterviewLens is a personal interview-experience (面经) aggregation tool. It crawls Nowcoder (牛客) posts, extracts structured data via LLM, normalizes company/position names, scores quality, and generates RAG summaries. Python backend + Next.js 15 frontend.

## Essential commands

```bash
# Infrastructure (first time)
cp .env.example .env          # Fill in DeepSeek key, Nowcoder cookie, Langfuse secrets
docker compose up -d          # postgres:5433, redis:6380, langfuse:3001
uv sync                       # Install Python deps (torch pinned to CPU-only wheel index, see pyproject [tool.uv.sources])
uv run playwright install chromium
uv run il seed-aliases        # Load seed company/position aliases
uv run pytest                 # Run all tests

# Backend
uv run il doctor              # Health check (pg + redis + pgvector)
uv run il serve               # FastAPI at :8000
uv run il serve --reload      # Dev mode with auto-reload

# Frontend (separate terminal)
cd web && pnpm install && pnpm dev   # Next.js at :3000

# Key CLI commands
uv run il info                # Show config (keys masked)
uv run il crawl <url>         # Fetch + clean one URL
uv run il extract <post_id>   # Run LLM extraction on a post
uv run il graph <url>         # Full LangGraph pipeline (crawl→clean→extract→normalize→score)
uv run il resume              # Retry failed/pending posts
uv run il normalize "字节" --type company  # Test alias resolution
uv run il rescore <post_id>   # Recompute quality score
uv run il top-posts           # List highest-quality posts
uv run il aggregate           # Generate RAG summaries
uv run il answer              # Generate difficulty-adaptive AI answers (offline)
uv run il backfill-embeddings # Encode questions with bge-m3
uv run il batch --pages 3     # Discover + enqueue URLs via Celery
uv run il dlq list            # Inspect dead-letter queue
uv run il metrics             # Cache hit rate, token usage, per-node latency
uv run il seed-demo           # Insert demo data for UI development
uv run il bench-search        # Benchmark pgvector search latency
uv run il reset               # Wipe DB tables (dev reset)
uv run il show-post <id>      # Dump one post's cleaned text + extraction
uv run il aliases             # List alias_dict entries
uv run il task-status <id>    # Check a Celery task's status

# Lint / typecheck
uv run ruff check src/ tests/
uv run mypy src/
cd web && pnpm typecheck && pnpm lint
```

## Architecture

### Data pipeline (LangGraph state machine)

```
URL → Crawler → Cleaner → Extractor → Normalizer → Scorer
       (Playwright)  (trafilatura)  (DeepSeek FC)  (3-tier)  (rule-based)
```

- **State**: `PipelineState` (TypedDict) flows through nodes. Each node reads upstream keys, writes its own. Conditional edges skip on `skip_reason`.
- **Crawler**: Playwright fetches HTML; skips if `source_url` already in DB (`reuse_existing`).
- **Cleaner**: trafilatura extracts body text; skips if < 200 chars.
- **Extractor**: DeepSeek Function Calling with strict JSON schema → `ExtractedPost`. Redis-cached by `sha256(text) + prompt_version`.
- **Normalizer**: Three-tier resolution — alias_dict lookup → bge-m3 cosine similarity (≥0.85 auto-match) → LLM tool call → create new canonical. Self-learns by writing back matches to alias_dict.
- **Scorer**: Pure function, no I/O. `quantity(30) + answers(20) + rounds(20) + recency(30)` = 0–100.
- **Aggregator** (offline): Groups questions by (company, position, period), retrieves top-100 via pgvector, generates markdown summary via DeepSeek.

### Key modules

| Module | Role |
|---|---|
| `src/interviewlens/config.py` | pydantic-settings from `.env`, singleton via `get_settings()` |
| `src/interviewlens/db/` | SQLModel ORM (7 tables), async session factory with `session_scope()` context manager |
| `src/interviewlens/agent/` | LangGraph nodes + graph assembly + `run_pipeline()` / `resume_failed()` entry points |
| `src/interviewlens/llm/` | DeepSeek client (`call_tool`), extractor, Redis cache, prompts, JSON schema |
| `src/interviewlens/crawler/` | Playwright browser management, listing discovery, trafilatura cleaning |
| `src/interviewlens/normalizer/` | Three-tier `resolve_entity()` — the core normalization logic |
| `src/interviewlens/scoring/` | `score_extracted()` pure function with configurable `ScorerWeights` |
| `src/interviewlens/embedding/` | bge-m3 via sentence-transformers, `embed_texts()`, `cosine_matrix()`, backfill |
| `src/interviewlens/aggregator/` | `aggregate_one()` / `aggregate_all()` — RAG summary generation |
| `src/interviewlens/answerer/` | `run_answers()` / `generate_one()` — difficulty-adaptive AI answer generation |
| `src/interviewlens/tasks/` | Celery tasks (`crawl_url`, `enqueue_listing`, `aggregate_pair`), DLQ management |
| `src/interviewlens/api/` | FastAPI app: taxonomy routes, semantic search, summaries, admin |
| `src/interviewlens/observability.py` | Langfuse tracing + Redis metric counters (cache hits, tokens, node latency) |
| `src/interviewlens/cli.py` | Typer CLI — all `il *` commands defined here |

### Database

PostgreSQL 16 + pgvector. Seven tables: `companies`, `positions`, `posts`, `questions` (with `vector(1024)` column + HNSW index), `post_company_position` (M:N join), `summaries` (pre-computed by company×position×period), `alias_dict` (self-learning normalization dictionary).

Key design decisions:
- `extract_version` on posts allows prompt-version gated re-extraction
- Embeddings live on `questions` (not `posts`) — search granularity is individual questions
- `summaries` is pre-computed offline, not generated on read
- `alias_dict` has a `confidence` column; manual seeds get 1.0, LLM-learned gets lower

### Frontend (Next.js 15 App Router)

Three pages: `/` (3-column browser: companies → positions → summary), `/search` (semantic search with pgvector), `/admin` (health + Celery queue status + metrics). Uses SWR for data fetching, shadcn/ui + Tailwind, react-markdown for summary rendering. API calls proxied through Next.js rewrites to avoid CORS.

### Infrastructure (Docker Compose)

- `postgres:16` via `pgvector/pgvector:pg16` image, port 5433
- `redis:7-alpine`, port 6380
- `langfuse/langfuse:2` + its own postgres, port 3001
- Celery worker started separately: `uv run celery -A interviewlens.tasks.celery_app worker --loglevel=info`

### Observability

- Langfuse traces every pipeline run and LLM call (node-level spans)
- Redis counters track cache hits/misses, token totals, per-node latency
- `il metrics` shows the dashboard; `il metrics-reset` wipes it

## Testing

Tests live in `tests/`, use `pytest` with `pytest-asyncio` (auto mode). Run all: `uv run pytest`. Single file: `uv run pytest tests/test_scorer.py`. The test suite covers: scorer logic, embedding utilities, API endpoints, cache key generation, cookie parsing, graph routing logic, cleaner output, listing discovery, metrics, and smoke tests.

## Configuration

All config via `.env` (see `.env.example`). `pydantic-settings` with `extra="ignore"` — unknown env vars are silently dropped. The `EXTRACT_PROMPT_VERSION` int gates cache invalidation: bump it when changing extraction prompts to force re-extraction.

## Legal constraint

**Never commit the `.env` file.** Cookie values in `.env` must stay local. Scraped content must not be republished to any public site — this is a personal-use-only tool.
