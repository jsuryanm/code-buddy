# syntax=docker/dockerfile:1.7
# CodeBuddy image: one image for the API, the Streamlit UI and one-off ingestion.
# Authored and statically checked only (tests/unit/test_deploy_files.py); never built or run
# here because the dev shell had no Docker daemon. See docs/deployment.md.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="CodeBuddy" \
      org.opencontainers.image.description="Socratic Python tutor: API, Streamlit UI, ingestion" \
      org.opencontainers.image.source="https://github.com/jayasuryan-mutyala/code-buddy" \
      org.opencontainers.image.licenses="NOASSERTION"

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    FASTEMBED_CACHE_PATH=/app/.cache/fastembed \
    CODEBUDDY_LOG_DIR=/app/logs \
    CODEBUDDY_QDRANT_PATH=/app/data/index \
    CODEBUDDY_CHECKPOINT_PATH=/app/data/checkpoints.sqlite \
    CODEBUDDY_MEMORY_PATH=/app/data/memory

WORKDIR /app

# Extras to install. `trace` is the light Langfuse client (tracing stays off without keys).
# PDF ingestion is opt-in because docling pulls in PyTorch (several GB):
#   --build-arg EXTRAS="--extra ui --extra trace --extra pdf"
# RAGAS and the evals environment are never part of the image.
ARG EXTRAS="--extra ui --extra trace"

# Dependencies first: this layer is reused until pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project $EXTRAS

COPY src ./src
COPY data/sample ./data/sample
COPY .streamlit ./.streamlit
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev $EXTRAS

# Non-root user. Writable: logs, data (index, checkpoints, manifest, memory), model cache.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app/logs /app/data /app/.cache/fastembed \
    && chown -R app /app/logs /app/data /app/.cache
USER app

# Bake the BM25 sparse model so the first start needs no download. Best effort: a failed
# download only means the container fetches it at first use (it needs network then).
RUN python -c "from fastembed import SparseTextEmbedding as S; S('Qdrant/bm25'); print('bm25 model cached')" \
    || echo "WARNING: could not pre-download Qdrant/bm25; it will download at first use"

EXPOSE 8000 8501
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"

CMD ["uvicorn", "codebuddy.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
