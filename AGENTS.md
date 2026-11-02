<!-- caveman-begin -->
Respond terse like smart caveman. All technical substance stay. Only fluff die.

Rules:
- Answer first: Answer, then reason, then next step.
- Kill ceremony: No greeting, hedging, pleasantries, recap, or closer.
- Short word: "fix" not "implement a solution for".
- Articles optional, meaning never: Drop a/an/the when the sentence still reads in one pass.
- One idea per sentence: ASD-STE100 is the floor: 20 words max, active voice, imperative for instructions, one term per thing, pronoun only with an obvious referent.
- Payload verbatim: Code blocks unchanged.
- Tool runs: bounded status: No text between routine calls.
- User's language: Compress the style, not the language.
- Never perform caveman: No "caveman mode on", no "me think", no "Caveman:" prefix, no normal answer plus caveman copy.

Switch: /caveman (default), /ultracave (fragments, each fact once), /megacave (Classical Chinese 文言文)
Stop: "stop caveman" or "normal mode"

Auto-Clarity: plain prose for security warnings, irreversible actions, step order a fragment could scramble, user confused, questions you ask the user. Resume after.

Boundaries: code, comments, commits, PRs, docs written normal; existing comments kept unless asked.
Floor: code, commands, paths, numbers and error strings verbatim; never drop not/never/no/only.
<!-- caveman-end -->

# Repository guide

CodeBuddy: FastAPI + LangGraph tutor, Streamlit UI, embedded Qdrant. Python 3.12, `uv`, `src/` layout.

## Commands

```bash
uv sync --extra ui                                  # tests + UI; add --extra pdf for PDF ingest, --extra rerank, --extra trace
uv run pytest -q                                    # offline tests
uv run pytest tests/unit -q                         # fast, pure-logic tests
uv run pytest tests/unit/test_policy.py::test_name -q
uv run ruff check . && uv run ruff format --check .
uv run python -m codebuddy.eval.run                 # offline eval; must print PASS
uv run uvicorn codebuddy.api.demo:app --port 8000    # keyless demo API
uv run uvicorn codebuddy.api.app:app --port 8000     # real API
uv run streamlit run src/codebuddy/ui/app.py
bash evals/setup.sh && .venv-evals/bin/python -m codebuddy.eval.ragas_run --index sample --limit 3  # paid, separate venv
```

CI order: `uv sync --extra ui` -> `ruff check` -> `ruff format --check` -> `pytest -q` -> `python -m codebuddy.eval.run`.

## Environment

- Copy `env.example` to `.env`. Some docs still say `.env.example`; the working tree uses `env.example` because `.claude/settings.json` denies reads of `.env.*`.
- `Settings` reads `.env` directly. Tests read it too: a local `QDRANT_CLUSTER_ENDPOINT` or `CODEBUDDY_QDRANT_URL` switches Qdrant to server mode and breaks embedded-mode assertions.
- Model IDs `CODEBUDDY_MODEL_FAST`, `CODEBUDDY_MODEL_STANDARD`, `CODEBUDDY_MODEL_HEAVY` have no defaults. Never hard-code model IDs.
- PDF ingest: `CUDA_VISIBLE_DEVICES= uv run python -m codebuddy.rag.ingest data/raw/<file> --corpus fundamentals --title "<title>" --licence "<licence>"`.
- The API starts the MCP server itself when `CODEBUDDY_MCP_ENABLED=true`; run `python -m codebuddy.mcp_server` only to debug startup.

## Entrypoints and layout

- `codebuddy.api.app:app`: production API; `codebuddy.api.demo:app`: keyless demo on `data/sample/`.
- `codebuddy.agent.graph`: LangGraph wiring; `agent/nodes.py`: turn flow; `pedagogy/policy.py`: mode choice.
- `codebuddy.rag.ingest`: offline ingestion; `data/index/` is the embedded index.
- `codebuddy.ui.app`: Streamlit UI; it talks to the API through `ui/client.py`.

## Rules that are easy to break

- Pedagogy is code. `policy.py` chooses hints, explain, reveal, confirm, or quiz; the model only words it. `StreamGuard` blocks corrected code at hint levels 0 to 3.
- Tools are chosen by rules, never by the model. Learner code execution waits for approval. The sandbox is not a security boundary.
- Show answer unlocks after 4 hints (sooner with frustration or the time cap); the tutor offers it after 5 hints.
- Cache keys include hint level, mode, index, prompt, and model versions. Never cache hints or reveals. Bump `PROMPT_VERSION` in `config.py` after prompt edits.
- Add new graph-state classes to `CHECKPOINT_TYPES` in `agent/graph.py`, or LangGraph cannot load checkpoints.
- Corpora stay split: `fundamentals` is learner-facing; `pedagogy` (PCDIT) must stay unreachable from learner turns.
- Logging: `setup_logging` writes `logs/YYYY-MM-DD/`. Log metadata only, never learner text, code, replies, tokens, ids, or raw session ids. Extend the whitelist in `observability/summaries.py`.
- Memory is opt-in, private notes only, never read by policy, and bypasses answer caches.
- `docs/` describes built code; `PROJECT_SPEC.md` is the target design. Update both when design changes.
- Think Python is CC BY-NC 3.0; PCDIT needs author permission for learner-facing use. See `docs/corpus-manifest.md`.

## Testing quirks

- Everything is offline. Models are scripted; embeddings are deterministic; Qdrant and Redis are in-memory.
- `asyncio_mode = "auto"`, so `async def test_...` works without a decorator.
- Graph tests use the `make_harness` fixture in `tests/integration/conftest.py`; pass `tools=LocalToolRunner()` and `h.resume(thread_id, approve=...)` for approval flows.
- Tests do not write `logs/`; `tests/conftest.py` disables file logging and clears loguru sinks.
- Some tests are real: the sandbox runs subprocesses and the tools test starts an MCP stdio server. Not every "unit" test is pure logic.
- The RAGAS runner uses `.venv-evals` and paid OpenAI calls; it is not part of pytest or CI.

## Repository state

- Docker, AWS, and deployment files were removed intentionally. Do not reintroduce them without being asked.
- Generated instruction copies live in `.opencode/AGENTS.md`, `.github/copilot-instructions.md`, `.cursor/rules/`, `.windsurf/rules/`, and `.clinerules/`. Edit the root file or docs sources, not the copies.
