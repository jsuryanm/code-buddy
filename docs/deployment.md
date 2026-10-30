# Deployment

Everything here was written but **not run**: Docker was unavailable in the development shell, and
no cloud credentials were used. Treat the files as a starting point and test them.

## Files

| File | Purpose |
|---|---|
| `Dockerfile` | One image, API by default. Python 3.12 slim, dependencies via `uv sync --frozen`, non-root user, `/healthz` health check |
| `docker-compose.yml` | Qdrant server, API, and Streamlit UI. Secrets come from `.env` |
| `.dockerignore` | Keeps `.env`, data, tests, docs, and tooling out of the image |
| `.github/workflows/ci.yml` | Ruff, format check, pytest, and the offline eval on every push and pull request |

## Steps

```bash
cp env.example .env           # fill in keys and model IDs
docker compose up --build -d
# one-off ingestion against the Qdrant server (stop nothing; server mode allows concurrent access)
docker compose run --rm api python -m codebuddy.rag.ingest /app/data/raw/think_python.md --corpus fundamentals
curl localhost:8000/healthz
```

Mount your documents (for example add `./data/raw:/app/data/raw:ro` to the `api` service) before
ingesting. Compose sets `CODEBUDDY_QDRANT_URL`, which turns on the server code path (payload
indexes) that the embedded mode cannot exercise, so test it.

## Production checklist

- Set `CODEBUDDY_API_KEYS`, and put TLS in front (a proxy or platform load balancer).
- Set Upstash credentials. Without them caches, rate limits, sessions, and metrics are per process.
- Run one API replica per embedded Qdrant folder, or use the Qdrant server and scale replicas.
- Pin the Qdrant server image to the version you tested, matching the `qdrant-client` major/minor.
- Persist `/app/data` (checkpoints, manifest). Back up the Qdrant volume or re-ingest from source.
- Run the sandbox without network access (see [security.md](security.md)). In a default Docker
  container `unshare -rn` usually fails, so `/healthz` will report `sandbox_network_isolated: false`.
- Watch `/v1/metrics`: `degraded` and `rate_limited` rising, `guard_stops` and `judge_flagged`
  for answer-leak trends, `approvals_*` for how learners react to the permission prompt.
- Set `CODEBUDDY_JUDGE_SAMPLE_RATE` (for example 0.05) to sample hint replies for leaks.
- Latency: read `ttft_ms` from the API logs or the `done` event; the target is p95 under 1 s.

## Known gaps

No Helm or Terraform, no migrations (there is no relational database), no log shipping, no
Langfuse tracing, no autoscaling guidance. The checkpoint database grows with every turn.
