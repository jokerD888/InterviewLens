# ============================================================
# InterviewLens · Backend image (FastAPI + Celery Worker)
# ============================================================
FROM python:3.13-slim AS dependencies

WORKDIR /app

# ---- uv package manager ----
COPY --from=ghcr.io/astral-sh/uv:0.10.12 /uv /uvx /bin/

# ---- System deps (cache stable — before source) ----
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# ---- Layer 1: Python deps (cached unless pyproject/uv.lock change) ----
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache

# ---- HuggingFace cache volume mount point ----
ENV HF_HOME=/models \
    PATH="/app/.venv/bin:$PATH" \
    UV_NO_SYNC=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN useradd --uid 10001 --create-home app \
    && mkdir -p /models /app/.cache/huggingface \
    && chown -R app:app /models /app/.cache

# Cache browser/system packages before source changes. API never inherits them.
FROM dependencies AS browser_dependencies
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
RUN .venv/bin/playwright install --with-deps chromium \
    && chown -R app:app /opt/playwright

FROM dependencies AS runtime
COPY src/ ./src/
COPY data/ ./data/
COPY sql/ ./sql/
COPY README.md ./
RUN uv sync --frozen --no-dev --no-cache
USER app

EXPOSE 8000

CMD ["uvicorn", "interviewlens.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

FROM browser_dependencies AS worker
COPY src/ ./src/
COPY data/ ./data/
COPY sql/ ./sql/
COPY README.md ./
RUN uv sync --frozen --no-dev --no-cache
USER app
CMD ["uvicorn", "interviewlens.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS api
