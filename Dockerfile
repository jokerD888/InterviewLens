# ============================================================
# InterviewLens · Backend image (FastAPI + Celery Worker)
# ============================================================
FROM python:3.13-slim

WORKDIR /app

# ---- uv package manager ----
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# ---- Layer 1: dependencies (cached unless pyproject/uv.lock change) ----
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ---- Layer 2: source + project install ----
COPY src/ ./src/
COPY data/ ./data/
COPY sql/ ./sql/
RUN uv sync --frozen --no-dev

# ---- Layer 3: Playwright Chromium (heavy, cache this layer) ----
# curl needed for healthcheck; chromium needs system deps
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && uv run playwright install --with-deps chromium

# ---- HuggingFace cache volume mount point ----
ENV HF_HOME=/app/.cache/huggingface

EXPOSE 8000

# Default command: start FastAPI
CMD ["uv", "run", "uvicorn", "interviewlens.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
