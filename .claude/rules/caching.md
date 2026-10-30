---
paths:
  - "**/cache*/**"
---

# Caching (Upstash Redis)

Source: PROJECT_SPEC.md Section 10. Target: p95 time-to-first-token under 1 s, cache hits under 300 ms.

## Layers

| Layer | Key ingredients |
|---|---|
| L1 exact answer | normalized query, learner level, mode, hint level, index version |
| L2 semantic | query embedding, similarity at or above about 0.95, scoped by concept and language |
| L3 embedding | text hash, embedding model version |
| L4 retrieval | rewritten query, filters, index version |
| L5 tool result | tool name, args. Idempotent read-only tools only |
| L6 session state | session ID. Mirrored to Postgres |

## Rules

- Keys must include hint level and mode. The right reply to the same question differs by hint level.
- Cache knowledge (explanations, retrieval, bug patterns, tool output). Generate the personalized Socratic question fresh.
- Never cache Level 4 reveals across different learner code.
- Invalidate on index, prompt, or model version change by including all three in the key.
- Use a single-flight lock (`SET NX`) so concurrent identical misses trigger one generation.
- Track hit rate per layer and the semantic-cache false-positive rate.
