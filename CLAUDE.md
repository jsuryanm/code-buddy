# CLAUDE.md

## Commands

```bash
uv sync --extra ui                                  # extras: pdf, rerank
uv run pytest -q                                    # offline tests
uv run pytest tests/unit/test_policy.py::test_name  # one
uv run ruff check . && uv run ruff format --check .
uv run python -m codebuddy.eval.run                 # eval, must PASS
uv run uvicorn codebuddy.api.demo:app --port 8000   # keyless demo
uv run streamlit run src/codebuddy/ui/app.py
```

Live use needs `.env` (template `.env.example`). See [docs/](docs/README.md).

## State and docs

Built: API, tutor graph, RAG, caches, Streamlit UI, Groq voice, approved MCP tools, API keys, rate limits, opt-in memory. Not built: instructor features, accounts, Langfuse, container-grade sandbox. Docker and live OpenAI, Groq, Upstash runs untested. [PROJECT_SPEC.md](PROJECT_SPEC.md) is the target design; `docs/` describes the code as built. Update both with design changes. `AGENTS.md`, `.cursor/`, `.windsurf/`, `.clinerules/`, `.github/copilot-instructions.md`, `.opencode/` are generated; don't hand-edit.

## Architecture rules

- **Pedagogy is code, not prompt.** `pedagogy/policy.py` picks the mode (hint ladder 0 to 3, explain, reveal); the LLM only verbalizes. `StreamGuard` blocks corrected code at levels 0 to 3 on the token stream. Don't move this into prompts.
- **Anti-frustration:** Show answer works after the first hint; the answer is offered after 3 hints, a time cap, or frustration; an explicit request always reveals.
- **Tools:** rules choose them, never the model. Learner code execution pauses for approval (`approve_run`). The sandbox (`SandboxBackend` seam) is no security boundary.
- **LLM:** OpenAI only, no gateway. Task class, then tier (fast, standard, heavy) from env model IDs, then fallback down tiers, then a degraded reply. Never hard-code model IDs.
- **Memory:** opt-in, private notes only, never read by policy, bypasses answer caches.
- **Latency target:** p95 time-to-first-token under 1 s.
- **Caching:** keys include hint level, mode, index, prompt, model versions. Never cache hints or reveals. Bump `PROMPT_VERSION` after prompt edits.
- **Corpora split by collection:** `fundamentals` is learner-facing; `pedagogy` (PCDIT) is unreachable to learners.
- **Checkpoints:** add new graph-state classes to `CHECKPOINT_TYPES` in `agent/graph.py`.
- **LangChain packages:** no `langchain-classic` without an ADR (`docs/adr/`).

## Licences

Think Python is CC BY-NC 3.0 (non-commercial); PCDIT needs author permission for learner-facing use. See `docs/corpus-manifest.md`.
