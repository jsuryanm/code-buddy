# 0009. Logs with loguru, traces with Langfuse, RAG scores with RAGAS

Status: accepted. Logs and Langfuse tracing are built; the RAGAS runner is planned in this change
set and not built yet. Date: 2026-11-02.

## Context
No logging was configured: the `codebuddy.*` stdlib loggers had no handler, so INFO lines (the
per-turn `done` line included) were dropped, and that line held the raw session id. Nobody could
follow a turn through the graph. The spec (17.4) asks for traces, dashboards and TTFT
percentiles, and section 16 for RAG quality checks beyond the offline substring recall. The tutor
handles learner text and code, which must not leave the process through logs or traces.

## Decision
- **Logs (built).** loguru, configured once per process by `setup_logging(settings, app)` in
  `observability/logs.py`. Each start writes `logs/YYYY-MM-DD/<app>_HH-MM-SS.log` and
  `.errors.log` (optional `.jsonl`), local time; files older than `CODEBUDDY_LOG_RETENTION_DAYS`
  (5) are pruned at start by our own `prune_logs`, because loguru's `retention` with a dated path
  leaves empty day folders and only runs when a sink closes or rotates. Existing stdlib loggers stay
  and are bridged by an `InterceptHandler`, so `caplog` tests keep working; tests install no
  sinks. One wrapper around every graph node logs its duration and a summary from a per-node
  whitelist; unknown keys are dropped, never stringified. Session ids are hashed (8 hex of
  SHA-256). Sinks use `enqueue=True` and `diagnose=False`.
- **Traces (built).** Langfuse cloud, SDK v4 (4.18, optional extra `trace`), behind our own small
  `Tracer` protocol (`observability/tracing.py`) fed by the same whitelisted summaries: span names,
  durations, mode, level, tier, token usage, cache hits, source titles, scores. **No LangChain
  `CallbackHandler` on the tutor graph**, because it records prompts and completions, and
  Langfuse's `mask` does not cover third-party spans. No observation gets an input or output; the
  session id is the 8-char hash; the client exports only Langfuse's own spans
  (`should_export_span=is_langfuse_span`). Child observations are created from their parent
  (`start_observation`), not from the OpenTelemetry current context, because `run_turn` is an
  async generator and LangGraph runs nodes in separate tasks. Off without keys, with
  `CODEBUDDY_TRACING_ENABLED=false`, or without the extra; every tracer call is wrapped so
  failures never break a turn.
- **RAG evaluation (planned).** A separate, manual, paid runner (`eval/ragas_run.py`) scores the
  real graph on a golden set with RAGAS (faithfulness, response relevancy, context precision and
  recall) and pushes scores to Langfuse. Golden questions are not learner data, so those traces may
  carry content. It is never part of `pytest` or CI.

## Alternatives not taken
- stdlib `logging.config` only: workable, but rotation, JSON output, per-record context
  (`turn=`, `sess=`) and safe tracebacks take more code than loguru's sink options.
- Moving every existing `log.*` call to loguru: churn, and it breaks the `caplog` tests that pin
  exact records.
- Langfuse's LangChain callback with masking: easiest to wire, but it sends prompts, code and
  replies by default, and masking third-party spans is not guaranteed.
- OpenTelemetry directly: more setup for the same metadata; Langfuse v4 is OTel-based anyway.

## Consequences
- A turn can be followed line by line with `grep turn=<id>`; see `docs/observability.md`.
- With the real SDK, tracing adds about 2 ms per turn (measured offline); off, under 15
  microseconds. Not yet run against the live Langfuse cloud.
- Each log record costs about 90 microseconds on the calling thread with enqueued sinks (measured;
  10 microseconds without `enqueue`), so roughly 1 to 2 ms per turn before the first token.
- Exception messages from libraries in `.errors.log` tracebacks can still echo request details.
  The leak judge logs only the flag, hashed session and level; never its reason text.
