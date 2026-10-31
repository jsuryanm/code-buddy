# Testing and evaluation

Everything below runs offline: no API keys, no network, no Docker.

## Commands

```bash
uv run pytest -q                                   # all tests
uv run pytest tests/unit -q                        # fast, pure-logic tests
uv run pytest tests/unit/test_policy.py::test_name -q       # one test
uv run pytest tests/integration/test_graph.py -q   # agent graph with scripted models
uv run ruff check .                                # lint
uv run ruff format --check .                       # formatting (drop --check to apply)
uv run python -m codebuddy.eval.run                # offline eval; exit code 1 on failure
uv run python -m codebuddy.eval.run --json
```

`pyproject.toml` sets `asyncio_mode = "auto"`, so `async def test_...` just works.

## Layout

| Path | Covers |
|---|---|
| `tests/unit/test_policy.py` | Hint ladder, escalation, show-answer, frustration signals, fix detection (`fixed_it`, the code fingerprint, deleted or unrelated code, the moved-bug gap as an expected failure), the `confirm` decision, the persistent quiz offer and the reply after a fix |
| `tests/unit/test_quiz.py` | Quiz bank: 2/2/1 difficulty split per pattern, each snippet has exactly its bug and each solution none, every snippet fails and every solution prints its `expect` when run in the sandbox, every solution counts as close to its question; grading, different code not graded, one hint then the solution, a question about unchanged code, skip and stop only as whole messages or an explicit action, summary |
| `tests/unit/test_guard.py` | Leak guard: prose passes, code and fences blocked, streaming behavior |
| `tests/unit/test_code_analysis.py` | The five bug patterns and false positives; an `if` without a stopping `return` is no base case; statement counting |
| `tests/unit/test_cache.py` | Key ingredients, TTL, single-flight, layers, session bind (first learner wins), cacheability rule |
| `tests/unit/test_query.py` | `build_query` terms per pattern and for parse errors, no code lines or learner identifiers, length cap; reciprocal rank fusion keeps and dedupes; classifier sees the last two history entries, with `<history>` tags stripped from them |
| `tests/unit/test_rag.py` | Chunking, ingestion idempotence, hybrid retrieval, corpus access, filters |
| `tests/unit/test_ui_client.py` | SSE parser, client errors, API key header, transcription upload, approval request, the quiz `action` field |
| `tests/unit/test_sandbox.py` | Real subprocess runs: traces, errors with line numbers, infinite loops, recursion, output cap, thirteen refused code patterns |
| `tests/unit/test_tools.py` | Tool functions, permission rules, and a **real MCP stdio server** called through `langchain.mcp` |
| `tests/unit/test_sandbox_backend.py` | The `SandboxBackend` seam: default `local` backend and its result keys, unknown names, `trace_python` uses the configured backend, allowlist runs before it |
| `tests/unit/test_memory.py` | Memory kinds in the fake and in `Mem0LearnerMemory` (against a recording stub), exact mem0 call arguments, recall shapes, exact forget count past the 1000-row list limit, and `build_config` accepted by mem0's `MemoryConfig` |
| `tests/unit/test_learner_tokens.py` | Token issue and verify: round trip, tampering, binding to the minting API key, `MEMORY_WRITE_EVERY` must be at least 1, and the secret hidden from `repr` |
| `tests/unit/test_wiring_memory.py` | `build_memory`: builds nothing when disabled, returns a warmed mem0 store, and logs and continues without memory when warm-up fails |
| `tests/unit/test_judge.py` | Sampled leak judge: counting, rate, never judging reveals, failures ignored |
| `tests/integration/test_graph.py` | Full graph: ladder (Show answer after 4 hints, the offer after 5), guard, reveal, outage and empty replies, caching, history, citations |
| `tests/integration/test_api.py` | HTTP endpoints and SSE framing |
| `tests/integration/test_api_hardening.py` | API keys, rate limits, the approval flow over HTTP (including another session being refused), speech upload limits and fallback, metrics, background judge |
| `tests/integration/test_tools_hitl.py` | Pause and resume around running code: approve, decline, remember, syntax errors, reveals, refused code |
| `tests/integration/test_cache_and_rewrite.py` | Semantic cache hit and no false positive; fusion of the classifier query, no history or second query on foreign turns; a timed-out second retrieval finishes in the background |
| `tests/integration/test_ui_smoke.py` | Streamlit page with a stub client |
| `tests/integration/test_ui_voice_approval.py` | Permission prompt (approve, decline) and editing a transcript before sending |
| `tests/integration/test_memory.py` | Memory through the graph and API: recall and `<memory>` prompt block, timeout, background writes on reveal and every Nth hint, cache bypass and no shared storing, tag stripping, client-chosen ids (422) and forged tokens (403), tokens bound to an API key, the secret surviving a restart, session binding (409, concurrent first turns, and the graph backstop), the session status route on a bound session, list and forget endpoints |
| `tests/integration/test_ui_memory.py` | Opt-in box, token minting, **Use this profile** for links, Forget me, mint failures |
| `tests/integration/test_quiz_flow.py` | Fix confirmation and ladder reset through the graph; deleted, replaced, or revealed code is not a fix; the quiz offer persists, the reflection is acknowledged, new buggy code or a new problem withdraws it; `/v1/quiz` (404 before a fix, no model call, API key, resends the running question), correct answers, the nudge for unchanged code, different code, the guarded quiz hint, a degraded hint keeps the try, no classifier or retrieval on quiz answers, skip, stop, the `action` field, and the summary |
| `tests/integration/test_ui_quiz.py` | Try a quiz only after a confirmed fix, the snippet in the code box, the quiz caption, Skip question and Stop quiz with their actions, the learner's code restored after Stop and after the summary, Show answer from the server's flag only |
| `tests/integration/test_eval.py` | The offline eval meets its thresholds |

## Fakes (no real models)

| Fake | Where | Replaces |
|---|---|---|
| `ScriptedChat(replies, fail=False)` | `rag/fakes.py`, re-exported by `tests/helpers.py` | Chat models. Replays scripted replies token by token and records every prompt in `.calls` |
| `DeterministicFakeEmbedding` | `langchain_core` | Dense embeddings |
| `HashSparse` | `rag/fakes.py` | BM25 sparse embeddings (no model download) |
| `QdrantClient(":memory:")` | `qdrant-client` | Qdrant |
| `InMemoryCache` | `cache/memory.py` | Upstash Redis (accepts an injected clock for TTL tests) |
| `HeuristicClassifier` | `agent/deps.py` | The LLM classifier |
| `LocalToolRunner` | `tools/runner.py` | The MCP session (the sandbox itself is real) |
| `InMemoryLearnerMemory` | `memory/store.py` | mem0 and its OpenAI calls. Ranks by word overlap, isolates learners |
| Recording stub for `mem0.Memory` | `tests/unit/test_memory.py` | The mem0 client, to check the exact calls our store makes |
| Fake transcribers | `tests/integration/test_api_hardening.py` | Groq and OpenAI speech |
| `Stub` client | `tests/integration/test_ui_voice_approval.py` | The HTTP API, for UI tests |

Fake embeddings carry no meaning, so retrieval tests rely on the BM25 half of the hybrid search.

## Writing a graph test

Use the `make_harness` fixture (`tests/integration/conftest.py`). It builds the graph over the
sample corpus with scripted tiers:

```python
async def test_example(make_harness):
    model = ScriptedChat(["What is i on the last pass?"])
    h = make_harness(standard=model)  # also: fast=, heavy=
    out = await h.turn("my sum crashes", code=BUGGY)
    assert out["meta"]["level"] == 0  # meta event
    assert out["text"].startswith("What is i")  # tokens the learner saw
    assert out["state"]["progress"].hints_given == 1
    assert "off_by_one_range" in model.calls[0][1][1]  # the user prompt the model got
```

`out["state"]` is the final graph state. Pass `session="other"` to `turn()` for a separate learner.
Use different `code` per turn when you want to avoid the repeated-submission frustration signal.

For tools, pass `tools=LocalToolRunner()` to `make_harness`. A turn that needs permission returns
`out["interrupt"]` (the approval payload) and `out["thread_id"]`; continue it with
`await h.resume(out["thread_id"], approve=True)`.

## Offline eval (`eval/run.py`)

Data: `src/codebuddy/eval/golden/cases.jsonl` (buggy programs, each with a scripted "leaky" reply)
and `retrieval.jsonl` (queries with expected text).

| Metric | Meaning | Threshold |
|---|---|---|
| `leak_rate` | Hint replies still containing code after the guard | at most 0.02 |
| `guard_trigger_rate` | Scripted leaky replies the guard stopped | 1.0 |
| `pattern_recall` | Labeled bugs found by static analysis | 1.0 |
| `escalation_ok` | Show answer after four hints, the offer after five, never a reveal unasked | 1.0 |
| `fix_detection` | Per pattern: "I fixed it" with unchanged code is a hint, the bank solution is a `confirm` | 1.0 |
| `retrieval_recall` | Queries whose expected text is in the top results (sample corpus) | at least 0.75 |

These measure the machinery with fake models. They do not rate the quality of a real model's
questions. For that, run real conversations and have an instructor score them (spec Section 16.3).

## Not tested

- Live OpenAI, Groq, Upstash, and Qdrant-server behavior (needs your credentials). This includes
  real mem0 extraction: the offline tests check the calls we make, not what mem0 stores
- The Docker files and CI workflow
- The sandbox against a determined attacker (see [security.md](security.md))
- The cross-encoder reranker (optional extra). Docling PDF ingestion was run by hand on the two
  real PDFs; the tests cover only the markdown clean-up (`tidy_docling_markdown`)
- The Streamlit page in a real browser, and recording audio from a real microphone
- Load and latency under concurrency

A good first live check: set `.env`, ingest one document, ask a question through the UI, and read
`ttft_ms` in the API log. Ask the same concept question twice and confirm `cache_hit` is true.
