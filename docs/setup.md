# Setup

## Prerequisites

- Python 3.12 (`.python-version` pins it) and [uv](https://docs.astral.sh/uv/)
- An OpenAI API key (for live tutoring and embeddings)
- A Groq API key (optional, for voice input)
- An Upstash Redis database (optional; without it the API uses an in-process cache)
- Network access on first run: the BM25 sparse model (`Qdrant/bm25`) is downloaded by `fastembed`
- No Docker needed. Qdrant runs embedded, as files under `data/index/`

## Install

```bash
uv sync --extra ui          # API + Streamlit UI + dev tools
# optional extras
uv sync --extra ui --extra pdf      # Docling, to ingest PDFs
uv sync --extra ui --extra rerank   # sentence-transformers, for the cross-encoder reranker
```

## Configure

```bash
cp env.example .env     # then edit .env
```

The template is named `env.example` (no leading dot) because `.claude/settings.json` denies
Claude Code from reading `.env.*` files. `.env` itself is gitignored. Minimum for live use:

```dotenv
OPENAI_API_KEY=sk-...
CODEBUDDY_MODEL_FAST=<small, low-latency model id>
CODEBUDDY_MODEL_STANDARD=<mid-tier model id>
CODEBUDDY_MODEL_HEAVY=<most capable model id>
UPSTASH_REDIS_REST_URL=https://...        # optional
UPSTASH_REDIS_REST_TOKEN=...              # optional
GROQ_API_KEY=...                          # optional, enables the microphone
```

The API and the ingest CLI load `.env` into the process environment themselves, so you do not
need to `export` anything.

Model IDs have no defaults on purpose; look up the current IDs in OpenAI's model list.
See [configuration.md](configuration.md) for everything else.

## Try it without any keys (demo mode)

The demo server replays canned tutor replies over the sample corpus, so you can see the UI work:

```bash
uv run uvicorn codebuddy.api.demo:app --port 8000
# in a second terminal
uv run streamlit run src/codebuddy/ui/app.py
```

Open http://localhost:8501, paste buggy code, and ask a question. The replies are scripted
(see `src/codebuddy/api/demo.py`), not generated. Everything around them is real: the hint
ladder, the leak guard, the permission prompt before your code runs (the sandbox genuinely
executes it), and the microphone widget (which returns a canned transcript).

## Add your documents

Put files in `data/raw/` (gitignored), then ingest each into a corpus:

```bash
CUDA_VISIBLE_DEVICES= uv run python -m codebuddy.rag.ingest data/raw/thinkpython.pdf \
    --corpus fundamentals --title "Think Python: How to Think Like a Computer Scientist (v2.0.17)" \
    --licence "CC BY-NC 3.0 Unported (stated on p4 of the PDF)"

CUDA_VISIBLE_DEVICES= uv run python -m codebuddy.rag.ingest data/raw/pcdit_paper.pdf \
    --corpus pedagogy --title "Steps Before Syntax: PCDIT (arXiv:2109.08896)" \
    --licence "arXiv preprint; licence not stated in the PDF; author permission needed for learner-facing use"
```

The empty `CUDA_VISIBLE_DEVICES=` is needed on WSL: Docling's PyTorch crashes (segfault) while
probing for a GPU. On CPU the 240-page book took several minutes. A path that does not exist is an
error, not a silent no-op. With these files the index holds 338 `fundamentals` chunks (Think
Python) and 29 `pedagogy` chunks (the PCDIT paper).

PDFs need `--extra pdf`. Markdown, text, and HTML work out of the box. Re-running is safe: files
whose SHA-256 has not changed are skipped, and changed files overwrite their own chunks. Details
and licence notes are in [rag-and-ingestion.md](rag-and-ingestion.md).

Check [../PROJECT_SPEC.md](../PROJECT_SPEC.md) Section 19.5 before ingesting: Think Python is
licensed CC BY-NC 3.0 Unported (non-commercial, stated on page 4 of the PDF), and the PCDIT paper and page need the authors'
permission before any learner-facing use.

## Turn on learner memory (optional)

Memory keeps private notes about a learner across sessions, only for learners who tick the box in
the UI. It calls OpenAI on writes and stores personal data under `data/memory`. Add to `.env`:

```dotenv
CODEBUDDY_MEMORY_ENABLED=true
CODEBUDDY_MEMORY_SECRET=<output of: python -c "import secrets; print(secrets.token_urlsafe(32))">
```

Restart the API and check `curl localhost:8000/healthz` shows `"memory_enabled": true`. Without
`CODEBUDDY_MEMORY_SECRET` tokens stop working after every restart. Read [memory.md](memory.md)
first.

## Run for real

```bash
uv run uvicorn codebuddy.api.app:app --port 8000      # terminal 1
uv run streamlit run src/codebuddy/ui/app.py           # terminal 2
```

Check it is alive: `curl localhost:8000/healthz` returns the cache type and whether the three
model IDs are set. If `CODEBUDDY_API_URL` points elsewhere, set it before starting Streamlit.

## Verify the install

```bash
uv run pytest -q                      # 205 tests, no network or keys needed
uv run ruff check . && uv run ruff format --check .
uv run python -m codebuddy.eval.run   # offline eval, prints PASS
```

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `RuntimeError: Set model IDs in the environment` at API startup | One of `CODEBUDDY_MODEL_FAST/STANDARD/HEAVY` is empty. Set all three in `.env`. |
| `/healthz` shows `"cache": "memory"` | Upstash variables are missing, so caching is per-process and lost on restart. Set both. |
| Qdrant error about the storage folder being locked | Embedded Qdrant allows one process. Stop the API before running ingestion, or set `CODEBUDDY_QDRANT_URL` to use a server. |
| Replies say "I can't reach the tutor model" | The model call failed (bad key, wrong model ID, network). The API logs the cause at WARNING level; the reply falls back to course material. |
| Replies cite nothing and say the context is missing | The corpus is empty. Ingest documents (see above) and check `data/index/manifest.json`. |
| `PDF ingestion needs the extra` | Run `uv sync --extra pdf`. |
| Microphone widget missing, or "Voice input is off" | The server has no speech provider. Set `GROQ_API_KEY` and restart the API (`/healthz` shows `stt_configured`) |
| `Voice input failed (502)` | Groq (and the fallback, if set) rejected or failed the request. Type the question instead; the API log has the cause |
| The tutor never asks to run my code | Tools are off (`CODEBUDDY_TOOLS_ENABLED=false`), the code has a syntax error, the learner already answered "remember" for this session, or the message was a concept question without code |
| `401 Missing or invalid API key` | `CODEBUDDY_API_KEYS` is set on the server. Put a matching key in the UI sidebar or `CODEBUDDY_API_KEY` |
| `429 Too many requests` | Rate limit hit. Wait for `Retry-After` seconds or raise `CODEBUDDY_RATE_LIMIT_PER_MINUTE` |
| MCP warning "calling tools in-process" in the API log | The MCP subprocess did not start; tools still work in-process. Check that `python -m codebuddy.mcp_server` runs |
| Docling segfaults during PDF ingestion (WSL) | PyTorch crashes in its CUDA probe. Run ingestion with `CUDA_VISIBLE_DEVICES=` set to empty, for example `CUDA_VISIBLE_DEVICES= uv run python -m codebuddy.rag.ingest ...` |
| `/healthz` shows `"memory_enabled": false` after setting `CODEBUDDY_MEMORY_ENABLED=true` | The memory store failed to start (the API log says why, often a locked `data/memory` or a missing `CODEBUDDY_MODEL_FAST`). The API runs without memory |
| `403 Invalid learner token` | The token was minted under another `CODEBUDDY_MEMORY_SECRET`, another API key, or a restart with no secret set. Tick the box again to get a new one |
| `409 This session belongs to another learner` | That session ID was first used with memory by someone else. Use **New session** |
| First start is slow | `fastembed` downloads the BM25 model once. |
| Streamlit shows "API not reachable" | Start the API first, or fix the API URL in the sidebar. |
