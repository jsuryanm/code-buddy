# 0009. Logs with loguru, traces with Langfuse, RAG scores with RAGAS

Status: accepted for logs (built); Langfuse tracing and the RAGAS runner are planned in this change
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
- **Traces (planned).** Langfuse cloud, SDK v4, behind our own small `Tracer` protocol fed by the
  same whitelisted summaries: span names, durations, mode, level, tier, token usage, cache hits,
  source titles, scores. **No LangChain `CallbackHandler` on the tutor graph**, because it records
  prompts and completions, and Langfuse's `mask` does not cover third-party spans. Off without
  keys; failures never break a turn.
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
- Each log record costs about 90 microseconds on the calling thread with enqueued sinks (measured;
  10 microseconds without `enqueue`), so roughly 1 to 2 ms per turn before the first token.
- Exception messages from libraries in `.errors.log` tracebacks can still echo request details;
  the leak judge's reason text remains the documented exception.
