# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync --extra ui                                  # install (extras: pdf, rerank)
uv run pytest -q                                    # all tests, offline
uv run pytest tests/unit/test_policy.py::test_name  # one test
uv run ruff check . && uv run ruff format --check .
uv run python -m codebuddy.eval.run                 # offline eval, must PASS
uv run uvicorn codebuddy.api.demo:app --port 8000   # keyless demo API
uv run streamlit run src/codebuddy/ui/app.py
```

Live use needs `.env` (template: `env.example`). See [docs/](docs/README.md).

## State and docs

Built: API, tutor graph, RAG, caches, Streamlit UI, Groq voice, MCP tools with learner approval, API keys and rate limits, opt-in learner memory. Not built: instructor features, accounts, Langfuse, container-grade sandbox. Docker files and live OpenAI, Groq, Upstash runs are untested. [PROJECT_SPEC.md](PROJECT_SPEC.md) is the target design; `docs/` describes the code as built. Update both in the same change as any design decision. `AGENTS.md`, `.cursor/`, `.windsurf/`, `.clinerules/`, `.github/copilot-instructions.md`, `.opencode/` are generated terse-style rules; don't hand-edit.

## Architecture rules

- **Pedagogy is code, not prompt.** `pedagogy/policy.py` picks the mode (hint ladder 0 to 3, explain, reveal); the LLM only verbalizes. `StreamGuard` blocks corrected code at levels 0 to 3 on the token stream. Don't move this into prompts.
- **Anti-frustration:** Show answer is available after the first hint; the answer is offered after 3 hints, a time cap, or frustration signals; an explicit request always reveals.
- **Tools:** rules choose them, never the model. Anything that executes learner code must pause for approval (`approve_run`). The sandbox (behind the `SandboxBackend` seam) is not a security boundary.
- **LLM:** OpenAI only, no gateway. Task class, then tier (fast, standard, heavy) from env model IDs, then fallback down the tiers, then a degraded reply. Never hard-code model IDs.
- **Memory:** opt-in, private notes only, never read by policy, bypasses answer caches.
- **Latency target:** p95 time-to-first-token under 1 s.
- **Caching:** keys include hint level, mode, index, prompt, and model versions. Hints and reveals are never cached. Bump `PROMPT_VERSION` after prompt edits.
- **Corpora split by collection:** `fundamentals` is learner-facing; `pedagogy` (PCDIT) is never reachable from learner turns.
- **Checkpoints:** new classes in graph state must be added to `CHECKPOINT_TYPES` in `agent/graph.py`.
- **LangChain packages:** no `langchain-classic` without an ADR in `docs/adr/`.

## Licences

Think Python is CC BY-NC 3.0 (non-commercial); PCDIT material needs author permission before learner-facing use. See `docs/corpus-manifest.md`.
