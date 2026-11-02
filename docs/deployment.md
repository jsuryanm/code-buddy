# Deployment

## AWS free tier

Planned: see `docs/aws-free-tier.md` (written in a later task, not present yet).

## Local Docker

The Docker files below were **authored and checked statically only** (YAML parsing and
`tests/unit/test_deploy_files.py`). Nothing was built or run: the development shell had no Docker
daemon. Expect to fix small things on your first run.

### Files

| File | Purpose |
|---|---|
| `Dockerfile` | One image for the API, the UI and ingestion. Python 3.12 slim, `uv sync --frozen` with build arg `EXTRAS` (default `--extra ui --extra trace`), BuildKit cache for uv, BM25 model baked in (best effort), non-root user (uid 10001), `/healthz` health check |
| `docker-compose.yml` | The services below. Secrets come from `.env` |
| `.dockerignore` | Keeps `.env`, logs, data, tests, docs, evals, and tooling out of the image. `.streamlit/` is kept |
| `.github/workflows/ci.yml` | Ruff, format check, pytest, and the offline eval on every push and pull request |

### What each service does

| Service | Starts with | What it is |
|---|---|---|
| `qdrant` | `docker compose up` | Local vector database, pinned image, volume `qdrant-data`. Always on; with Qdrant Cloud use `--no-deps` (below) |
| `api` | `docker compose up` | The tutor API on `127.0.0.1:8000`. Waits for Qdrant to be healthy. Logs go to `./logs` |
| `ui` | `docker compose up` | Streamlit on `127.0.0.1:8501`, talks to `http://api:8000` |
| `api-demo` | profile `demo` | Keyless demo server (canned replies, no keys, no Qdrant). Takes the network name `api` |
| `ingest` | profile `ingest` | One-off ingestion into the corpus; run, then it exits |

Ports bind to 127.0.0.1, so only your own machine can reach them. Memory and process limits are
set per service (`mem_limit`, `pids_limit`).

### First run

```bash
cp env.example .env               # fill in OPENAI_API_KEY, CODEBUDDY_MODEL_* ; see configuration.md
mkdir -p logs && chmod a+rwx logs # the container user (uid 10001) must be able to write here
docker compose up --build -d
curl localhost:8000/healthz       # then open http://localhost:8501
```

`.env` is optional in Compose 2.24+ (`required: false`), but without it there are no model keys
and the real API cannot answer. To only look at the UI, run the demo instead (do not run it
together with `api`, both want port 8000):

```bash
docker compose up --build api-demo ui
```

### Ingesting documents

Put files in `./data/raw` (mounted read-only), then:

```bash
docker compose --profile ingest run --rm ingest data/raw/x.pdf --corpus fundamentals --title "X"
```

Arguments are those of `python -m codebuddy.rag.ingest`. Markdown, text, and HTML work with the
default image. PDFs need Docling (PyTorch, several GB), so build with the `pdf` extra first:
`docker compose build --build-arg EXTRAS="--extra ui --extra trace --extra pdf" ingest`, then
rebuild without it for everyday use. Add `-e CUDA_VISIBLE_DEVICES=` to the run if Docling hits
the GPU probe crash on WSL (see [setup.md](setup.md)).

### Logs, stopping, resetting

- Logs: `./logs/YYYY-MM-DD/` on your machine (metadata only; see [observability.md](observability.md)).
  Langfuse tracing needs `LANGFUSE_*` keys in `.env`; the `trace` extra is already in the image.
- Stop: `docker compose down`. Data stays in the volumes.
- Reset everything, including the index and checkpoints: `docker compose down -v`, then ingest again.

### Common errors

- **Port already in use**: something else uses 8000 or 8501 (a local `uvicorn`, or `api` and
  `api-demo` together). Stop it.
- **`docker: command not found` or "cannot connect to the daemon" in WSL**: turn on Docker
  Desktop's WSL integration for your distro.
- **`.env` missing**: the API starts but replies with a degraded answer or `/healthz` shows models
  missing. Create `.env`.
- **Qdrant unreachable**: check `docker compose ps` (qdrant should be healthy) and the `api` log
  line naming the Qdrant host. If you set `QDRANT_CLUSTER_ENDPOINT` the cloud cluster is used
  instead of the local one.
- **Out of memory (container killed, exit 137)**: raise `mem_limit` for that service, or give
  Docker Desktop more RAM.
- **No log files**: `./logs` is not writable by uid 10001; `chmod a+rwx logs`.

### What was not tested

The image build, the BM25 pre-download step (it is allowed to fail and then downloads at first
use), the Qdrant health check (a bash TCP probe, assuming the image has bash), `required: false`
on `env_file`, the demo's `api` network alias, the Streamlit health check, bind-mount permissions,
and the whole compose flow with live OpenAI, Qdrant, Groq, Upstash, or Langfuse.

## Qdrant Cloud or a managed server

To use a hosted cluster instead of the compose Qdrant, set `QDRANT_CLUSTER_ENDPOINT`,
`QDRANT_API_KEY` and `QDRANT_COLLECTION_NAME` (collection prefix, default `cb`) in the API's
environment, in `.env` (Compose maps `QDRANT_CLUSTER_ENDPOINT` into `CODEBUDDY_QDRANT_URL`) and start with
`docker compose up -d --no-deps api ui` so the local Qdrant is skipped. Run ingestion once
against the cluster, for example
`docker compose --profile ingest run --rm ingest data/raw/thinkpython.pdf --corpus fundamentals`;
the log lines name the target host and collection. Check `/healthz` for `"qdrant": "server"`.
Learner memory still uses embedded files under `MEMORY_PATH`.

## Production checklist

- Set `CODEBUDDY_API_KEYS`, and put TLS in front (a proxy or platform load balancer).
- Set Upstash credentials. Without them caches, rate limits, sessions, and metrics are per process.
- Run one API replica per embedded Qdrant folder, or use the Qdrant server and scale replicas.
- Pin the Qdrant server image to the version you tested, matching the `qdrant-client` major/minor.
- Persist `/app/data` (checkpoints, manifest). Back up the Qdrant volume or re-ingest from source.
- If learner memory is on, `/app/data/memory` holds personal data and must persist and be backed up
  (or learners lose their notes). Set `CODEBUDDY_MEMORY_SECRET` from a secret store, or tokens die
  on restart. Memory uses embedded Qdrant, so run one API worker.
- Run the sandbox without network access (see [security.md](security.md)). In a default Docker
  container `unshare -rn` usually fails, so `/healthz` will report
  `sandbox_network_isolated: false`.
- Watch `/v1/metrics`: `degraded` and `rate_limited` rising, `guard_stops` and `judge_flagged`
  for answer-leak trends, `approvals_*` for how learners react to the permission prompt.
- Set `CODEBUDDY_JUDGE_SAMPLE_RATE` (for example 0.05) to sample hint replies for leaks.
- Latency: read `ttft_ms` from the `turn end` and `api done` log lines or the `done` event; the
  target is p95 under 1 s.
- Logs: the API writes `/app/logs/YYYY-MM-DD/api_HH-MM-SS.log` (and `.errors.log`). Mount
  `/app/logs` as a volume (for example `./logs:/app/logs` on the `api` and `ui` services) to keep
  them across restarts, and make it writable by the container's non-root user; otherwise the app
  logs one warning and falls back to stderr only. Files older than
  `CODEBUDDY_LOG_RETENTION_DAYS` (5) are deleted at start. Set `CODEBUDDY_LOG_JSON=true` if a log
  shipper reads the files. See [observability.md](observability.md).

## Known gaps

No Helm or Terraform, no migrations (there is no relational database), no log shipping, no
Langfuse dashboards or alerts, no autoscaling guidance. The checkpoint database grows with every turn.
