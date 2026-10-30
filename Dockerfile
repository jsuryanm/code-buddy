# CodeBuddy API (and, with another command, the Streamlit UI).
# Not built or run during development: Docker was unavailable in the dev shell.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first so this layer is cached until pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --extra ui

COPY src ./src
COPY data/sample ./data/sample
RUN uv sync --frozen --no-dev --extra ui

# Run as a non-root user; only data/ is writable (index, checkpoints, manifest).
RUN useradd --create-home --uid 10001 app && mkdir -p /app/data && chown -R app /app/data
USER app

EXPOSE 8000 8501
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"

CMD ["uvicorn", "codebuddy.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
