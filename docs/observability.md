# Logs and observability

Every runnable part of CodeBuddy writes a plain-language log with loguru
(`src/codebuddy/observability/`). The log lets you follow one turn from the request to the reply:
which nodes ran, how long each took, what the policy decided, which model tier answered, and
whether a cache or a fallback was involved. It never contains learner text (see
[Privacy](#privacy)).

With Langfuse keys set, each turn is also sent to Langfuse as a trace of metadata only (see
[Langfuse tracing](#langfuse-tracing)). RAGAS evaluation is built: run it with
`uv run python -m codebuddy.eval.ragas_run` (ADR 0009).

## Where the files are

Each process start gets its own files in a folder for the day (local time). The name says which
program wrote it and when it started:

```
logs/
  2026-11-02/
    api_09-14-03.log            flow log of the API started at 09:14:03 (INFO and up)
    api_09-14-03.errors.log     WARNING and up, with tracebacks
    api_09-14-03.jsonl          only with CODEBUDDY_LOG_JSON=true
    ui_09-14-10.log
    mcp_09-14-04.log            the MCP tool server the API starts
    eval_10-02-55.log
  2026-11-01/
    ingest_16-40-12.log
```

| App name | Written by |
|---|---|
| `api` | `uvicorn codebuddy.api.app:app` |
| `demo` | `uvicorn codebuddy.api.demo:app` (keyless demo) |
| `ui` | `streamlit run src/codebuddy/ui/app.py` (set up once per process, not on every rerun) |
| `ingest` | `python -m codebuddy.rag.ingest` |
| `eval` | `python -m codebuddy.eval.run` |
| `mcp` | `python -m codebuddy.mcp_server` (stdout is the MCP protocol, so it logs to the file and stderr only) |
| `ragas` | `python -m codebuddy.eval.ragas_run` |

The same lines also go to stderr. To find the log of the run you just started, read the first
line on the terminal: it prints the path.

```
starting the keyless demo API (app=demo version=0.1.0 git=94c9df0 python=3.12.12) log=logs/2026-11-02/demo_07-21-28.log
```

The folder is created on demand. If it cannot be created (permissions, a file in the way), the
program logs one warning and keeps going with stderr only; logging never stops the app.

## Retention

At start, `setup_logging` deletes `*.log`, `*.jsonl` and `*.zip` files under the log folder whose
modification time is older than `CODEBUDDY_LOG_RETENTION_DAYS` (default 5), then removes day
folders that became empty. It never follows symlinks and never touches other files. The start
lines report how many files went. Within one run a file is rotated only if it passes 50 MB (a
safety net for a runaway process).

loguru's own `retention` is not used: with a dated path it deletes old files of the same program
only when a sink closes or rotates, and it leaves the empty day folders behind (checked with
loguru 0.7.3).

## Reading one turn

This is a real turn from the keyless demo (`uv run uvicorn codebuddy.api.demo:app`): a learner
sends buggy code, the tutor asks to run it, the learner approves. Lines are copied from
`logs/2026-11-02/demo_07-21-28.log`; only the date and the level (all INFO) are cut from each line.

```
07:21:29.226 | uvicorn.protocols.http.h11_impl | turn=- sess=- | 127.0.0.1:45020 - "POST /v1/turn HTTP/1.1" 200
07:21:29.227 | agent.graph    | turn=d071e09d sess=5166ff00 | turn start route=turn
07:21:29.229 | agent.graph    | turn=d071e09d sess=5166ff00 | <- load_state 0.1 ms has_code=True code_changed=True
07:21:29.232 | agent.graph    | turn=d071e09d sess=5166ff00 | <- analyze_code 0.3 ms patterns=['off_by_one_range'] parse_error=False
07:21:29.234 | agent.graph    | turn=d071e09d sess=5166ff00 | <- check_cache 0.0 ms cacheable=False
07:21:29.237 | agent.graph    | turn=d071e09d sess=5166ff00 | <- classify 0.1 ms intent=debug_help stage=T concepts=0
07:21:29.238 | agent.graph    | turn=d071e09d sess=5166ff00 | <- recall_memory 0.0 ms memories=0
07:21:29.241 | rag.retrieve   | turn=d071e09d sess=5166ff00 | retrieve corpus=fundamentals query_chars=68 cache_hit=False k=30 candidates=6 rerank=NoopReranker top=5 chunks=5
07:21:29.241 | agent.graph    | turn=d071e09d sess=5166ff00 | <- retrieve 3.3 ms chunks=5 grounded=True cache_hit=False sources=['Sample Python Basics']
07:21:29.243 | agent.graph    | turn=d071e09d sess=5166ff00 | <- refine_retrieval 0.0 ms refined=False
07:21:29.244 | agent.graph    | turn=d071e09d sess=5166ff00 | <- policy 0.1 ms mode=hint level=0 can_show=False offer=False offer_quiz=False reasons=['hints given: 0'] tools=['trace_python']
07:21:29.245 | agent.graph    | turn=d071e09d sess=5166ff00 | <- approve_run 0.0 ms paused
07:21:29.246 | agent.graph    | turn=d071e09d sess=5166ff00 | turn end ttft_ms=None total_ms=19 mode=hint level=0 cache_hit=False degraded=False guarded=False paused=True
07:21:29.247 | api.app        | turn=d071e09d sess=5166ff00 | api done ttft_ms=19 total_ms=19 awaiting_approval=True citations=0 degraded=False guarded=False cache_hit=False stage=P hints_given=0 learner=no
07:21:29.247 | api.app        | turn=d071e09d sess=5166ff00 | approval requested tool=trace_python
07:21:36.123 | api.app        | turn=d071e09d sess=5166ff00 | approval granted remember=True
07:21:36.125 | agent.graph    | turn=d071e09d sess=- | turn start route=approve
07:21:36.127 | agent.graph    | turn=d071e09d sess=5166ff00 | <- approve_run 0.1 ms approved=True
07:21:36.145 | tools.runner   | turn=d071e09d sess=5166ff00 | tool trace_python via=inprocess 16.3 ms ok=True
07:21:36.145 | agent.graph    | turn=d071e09d sess=5166ff00 | <- run_tools 16.8 ms traced=True
07:21:36.148 | agent.nodes    | turn=d071e09d sess=5166ff00 | generate tier=standard cap=250 -> ok
07:21:36.148 | agent.graph    | turn=d071e09d sess=5166ff00 | <- generate 2.0 ms reply_chars=219 guarded=False degraded=False
07:21:36.151 | agent.graph    | turn=d071e09d sess=5166ff00 | <- update_state 0.2 ms hints_given=1 stage=T reveals=0 quiz_index=None
07:21:36.153 | agent.graph    | turn=d071e09d sess=5166ff00 | turn end ttft_ms=24 total_ms=28 mode=hint level=0 cache_hit=False degraded=False guarded=False paused=False
07:21:36.153 | api.app        | turn=d071e09d sess=5166ff00 | api done ttft_ms=25 total_ms=28 awaiting_approval=False citations=5 degraded=False guarded=False cache_hit=False stage=T hints_given=1 learner=no
```

How to read it:

- Every line of a turn carries `turn=` (the first 8 characters of the `turn_id` the API returns in
  the `done` event) and `sess=` (the first 8 hex characters of the SHA-256 of the session id).
  `grep turn=d071e09d` gives the whole turn, including the resumed half after the approval.
  The resumed `turn start` has `sess=-` because the resume command carries no session id; the
  node lines after it have the hash again.
- `<- node  N ms  summary` is written when a graph node returns: its duration and a whitelisted
  summary of what it changed. With `CODEBUDDY_LOG_LEVEL=DEBUG` a `-> node` line marks each start,
  and the cache layers log `cache L1 hit|miss` and `cache L2 hit|miss`.
- `classify`, `retrieve` and `recall_memory` run in parallel, so their lines can interleave.
- `policy` shows the decision made by code: mode, hint level, whether Show answer is allowed,
  whether the answer is offered, and the policy's reasons.
- `generate tier=... cap=... -> ok|empty|error <type>` is one line per model attempt. A fallback
  adds `generate falling back to tier=...`, and a stopped reply says `stopped by the leak guard`.
- `turn end` is the graph's view (time to the first token streamed by the graph, total time);
  `api done` is the HTTP side, as sent to the client in the `done` event. `learner=yes|no` says
  whether a memory token was used, never which learner.
- Refused requests appear as `request refused status=401|403|409|429 route=...` (the route
  template, not the path).

Other programs write the same kind of lines: a start line, a `config ...` summary without secrets
(model ids, Qdrant mode with the host only, index and prompt versions, memory, tools; the API also
reports `tracing=on|off`),
progress with counts and durations, a finish line with the outcome and elapsed time, and on a
failure the exception type with a hint such as `OPENAI_API_KEY is not set: add it to .env` or
`the Qdrant folder is locked: stop the API (or the other process) first`. The traceback goes to
the `.errors.log` file.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `CODEBUDDY_LOG_LEVEL` | `INFO` | Level for stderr, the flow log and the JSON file. `DEBUG` adds node starts and cache layer lines |
| `CODEBUDDY_LOG_DIR` | `logs` | Root folder for the day folders |
| `CODEBUDDY_LOG_TO_FILE` | `true` | `false`: stderr only (the test suite sets this) |
| `CODEBUDDY_LOG_JSON` | `false` | Also write a `.jsonl` file (one JSON object per record, loguru's `serialize`) for log shippers |
| `CODEBUDDY_LOG_RETENTION_DAYS` | `5` | Files older than this are deleted at start (minimum 1) |

## How it is wired

- `setup_logging(settings, app=...)` in `observability/logs.py` installs the sinks. Every
  entrypoint calls it first. `create_app(deps)` with injected dependencies (tests) does not, so
  tests never write `logs/`; `tests/conftest.py` also removes all loguru sinks around each test.
- Existing modules keep their stdlib loggers (`codebuddy.api`, `.agent`, `.memory`, `.tools`,
  `.stt`, `.judge`). An `InterceptHandler` on the root logger forwards their records, and
  uvicorn's, into loguru. Third-party libraries stay at WARNING, so their INFO lines (HTTP request
  lines with URLs, for example) do not reach the files.
- The node lines come from one wrapper around every node in `build_graph` (`agent/graph.py`), so a
  new node is logged without extra code. Its summary comes from a per-node whitelist in
  `observability/summaries.py`.
- File and stderr sinks use `enqueue=True` (a background thread writes them) and
  `backtrace=False, diagnose=False`, so tracebacks never print local variable values.
- The MCP child process receives the `CODEBUDDY_LOG_*` variables from the API (the MCP client
  passes only a minimal environment otherwise).

## Privacy

Logs hold metadata only: names, durations, counts, booleans, modes and levels, tier names, tool
names, pattern ids, policy reasons and source titles. They never hold the learner's message, code,
the reply, a prompt, a learner id or token, or the raw session id.

- Node summaries come from a whitelist; unknown keys are dropped, never stringified.
- Session ids are hashed (the same hash as the leak judge's log line). The uvicorn access log has
  `/v1/session/<id>` instead of the real path.
- The leak guard's log line names the kind of stop (`code statement`) and no longer quotes the
  model's text.
- A test runs a full graph turn and API turns with sentinel strings in the message, the code, the
  replies, the learner token and the session id, with every sink on at DEBUG, and checks that none
  of them appear (`tests/integration/test_logging_flow.py`).

What remains outside that guarantee: exception messages in `.errors.log` tracebacks come from
libraries (OpenAI, Qdrant, mem0) and could in principle echo request details; the leak judge's
`reason` text is never logged (only the flag, hashed session and level); and
the access log records client IP addresses.

## Cost on the hot path

Without sinks (tests) the node wrapper costs about 2 microseconds per node. With the default
enqueued file sinks, each log record costs roughly 90 microseconds on the calling thread (loguru
pickles the record for its queue; measured on the development machine), so a turn spends on the
order of 1 to 2 ms on logging before its first token. That is well under the 1 s p95 target but
not free; writing the files without `enqueue` costs about 10 microseconds per record instead.

## Langfuse tracing

The API can send one trace per turn to a Langfuse cloud project
(`src/codebuddy/observability/tracing.py`). Traces hold the same kind of metadata as the log
lines, so Langfuse can chart time to first token, fallbacks, reveals and degraded replies across
many turns. Tracing is off unless both Langfuse keys are set and the `trace` extra is installed.
Nothing in this repository has been run against the real Langfuse cloud yet: the adapter is tested
against a fake `langfuse` module, and the SDK calls were checked against the installed
langfuse 4.18 source.

### Setup

1. Create a project in Langfuse cloud (Settings, API keys) and copy the public and secret keys.
2. Add them to `.env`:
   ```
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_SECRET_KEY=sk-lf-...
   LANGFUSE_BASE_URL=https://cloud.langfuse.com      # or https://us.cloud.langfuse.com
   ```
   `LANGFUSE_HOST` (the old name) is still read when `LANGFUSE_BASE_URL` is not set. Without
   either, the SDK uses the EU cloud.
3. Install the extra: `uv sync --extra ui --extra trace`.
4. Restart the API. The start lines say `tracing on: Langfuse host=... sample_rate=...` and the
   `config ...` line ends with `tracing=on`; `/healthz` returns `"tracing_enabled": true`.
   Otherwise one line says why it is off (switch off, a key missing, the package missing, or the
   client failed to start).
5. Send a turn and open Tracing in the Langfuse project. Traces are exported in the background in
   batches, so they appear after a few seconds; the API flushes what is left when it shuts down.

The keyless demo, the UI process, ingestion and the offline eval never trace.

### What a trace contains

| Observation | Kind | Attributes |
|---|---|---|
| `tutor-turn` | root span, one per `run_turn` call | `route` (turn, show-answer, approve; a quiz start is a `turn`), and at the end `mode`, `level`, `paused`, or `error` (exception type). Trace fields: name `tutor-turn`, session id = the 8-char session hash, tag = the route, metadata `prompt_version`, `index_version`, the three tier model ids, and `turn` (first 8 characters of the turn id) |
| `load_state`, `analyze_code`, `check_cache`, `classify`, `retrieve`, `recall_memory`, `refine_retrieval`, `policy`, `approve_run`, `run_tools`, `generate`, `update_state`, `emit_cached` | span per node that ran, child of the root | the node's whitelisted summary, the same fields as its log line (for example `mode`, `level`, `reasons` on `policy`; `chunks`, `grounded`, `sources` on `retrieve`); `paused` or `error` when it did not return |
| `classifier` | generation, under `classify` | model id, tier `fast`, `outcome` ok or error. Only the LLM classifier makes one; the rule shortcut for "show me the answer" makes no call |
| `generate` | generation per model attempt, under the `generate` node | model id, tier, `cap` (also as `max_completion_tokens`), token usage (input, output) and `finish_reason` when the stream reports them, `outcome` ok, empty, error (with the type) or guarded |
| `tool:trace_python`, `tool:suggest_cases` | span per tool call, under `run_tools` | `ok`, `error` type |

Scores on each trace:

| Score | Type | Meaning |
|---|---|---|
| `ttft_ms` | numeric | Time from the start of the graph run to its first streamed token (absent when no token was sent, for example a turn paused for approval) |
| `total_ms` | numeric | Whole graph run |
| `cache_hit` | boolean | Reply came from the answer cache |
| `guarded` | boolean | The leak guard stopped the model's reply |
| `degraded` | boolean | Every tier failed and the learner got the degraded text |
| `quiz` | boolean | The turn started or answered a quiz |

A turn paused for approval gives two traces: the first part (route `turn`, `paused`) and the
resumed part (route `approve`). They share the `turn` metadata value. The resumed part has no
session id, because the resume command carries none.

### Dashboard recipe

In Langfuse, Dashboards, new dashboard, filter traces by name `tutor-turn` (and by environment if
you set `LANGFUSE_TRACING_ENVIRONMENT`):

- **TTFT p50 and p95**: a chart on scores, score name `ttft_ms`, aggregation p50 and p95, by day.
  The spec target is p95 under 1000 ms.
- **Total time**: the same with `total_ms`.
- **Degraded rate and guarded rate**: scores `degraded` and `guarded`, aggregation average (the
  share of turns where the value is 1).
- **Cache hit rate**: score `cache_hit`, average.
- **Fallback rate**: observations of type generation named `generate`, grouped by `outcome`; the
  share of `error` and `empty` attempts is the share that moved down a tier. Group by `tier` or
  model to see which model fails.
- **Reveal rate**: traces grouped by the `mode` attribute of the root; `reveal` divided by all.
- **Token use by model**: the generation usage charts, grouped by model.

### Privacy

Langfuse cloud is a third party: whatever the tracer sends is stored on Langfuse's servers under
their terms and data region (EU or US, chosen by the base URL). The tracer therefore sends metadata
only:

- Sent: observation names, start and end times, node summaries from the logging whitelist (modes,
  levels, counts, booleans, policy reasons, pattern ids, tool names, corpus source titles), model
  ids, tier names, token caps and counts, finish reasons, outcomes, exception type names, the
  prompt and index versions, the first 8 characters of the turn id, and the 8-char SHA-256 hash
  of the session id.
- Never sent: the learner's message or code, the reply, prompts, retrieved chunk text, memory
  notes, learner ids or tokens, the raw session id. No observation is given an input or output
  field, and no user id is set.
- There is no LangChain `CallbackHandler` on the graph (it would record prompts and completions;
  ADR 0009). The client is created with `should_export_span` set to Langfuse's own spans only, so
  OpenTelemetry spans from other libraries are not exported through it.
- A test records every observation of graph and API turns with sentinel strings in the message,
  code, replies, learner token and session id and checks that none appear
  (`tests/integration/test_tracing_flow.py`); another checks the adapter never passes `input` or
  `output` (`tests/unit/test_tracing.py`).

### Turning it off

Set `CODEBUDDY_TRACING_ENABLED=false`, or remove the two keys, and restart. Without the `trace`
extra installed it is off as well. `CODEBUDDY_TRACE_SAMPLE_RATE` (0 to 1, default 1) keeps only
that share of traces (the SDK's sampler).

### Failure and cost

Every tracer call is wrapped: an error is logged at DEBUG with its type name and the turn goes on
unchanged (tested). The SDK sends batches from a background thread; the hot path never waits on
the network. Measured on the development machine with the offline graph: the tracing hooks cost
under 1 microsecond per node with tracing off (about 10 to 15 microseconds per turn), and the real
Langfuse SDK adds about 2 ms per turn (span creation for about 15 observations and 6 scores; most
of it before the first token). Export failures are logged by the SDK's own `langfuse` logger and
reach `.errors.log`. At shutdown the API drains background tasks, then flushes and shuts down the
tracer; with an unreachable host the SDK's retries can make that take a few seconds.
