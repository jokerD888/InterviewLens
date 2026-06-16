# ============================================================
# InterviewLens · Backend image (FastAPI + Celery Worker)
# ============================================================
FROM python:3.13-slim

WORKDIR /app

# ---- uv package manager ----
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# ---- System deps (cache stable — before source) ----
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# ---- Layer 1: Python deps (cached unless pyproject/uv.lock change) ----
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ---- Layer 2: Playwright Chromium (kept close to deps to maximise cache) ----
RUN uv run playwright install --with-deps chromium

# ---- Layer 3: source + project install (lightweight: uv sync only does "pip install -e .") ----
COPY src/ ./src/
COPY data/ ./data/
COPY sql/ ./sql/
COPY README.md ./
RUN uv sync --frozen --no-dev

# ---- HuggingFace cache volume mount point ----
ENV HF_HOME=/app/.cache/huggingface

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "interviewlens.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
