# 0002. Rule-based streaming leak guard

Status: accepted. Date: 2026-10-29.

## Context
The spec wanted a rule check plus an LLM judge before any reply could show corrected code at hint
levels 0 to 3. A blocking judge needs the full reply, which makes the learner wait for the whole
generation and breaks the "first token in under one second" target.

## Decision
Only the rule-based `StreamGuard` blocks, and it works on the token stream. Prose streams
immediately; lines that start like code are held until the line ends. A violation stops the reply
and appends a safe stage question. The LLM judge is for evals and sampled monitoring (not built).

## Consequences
Low latency and deterministic, testable behavior. The guard misses leaks phrased in prose or
unfenced indented code, so the judge-based sampling is still needed to measure the real leak rate.
