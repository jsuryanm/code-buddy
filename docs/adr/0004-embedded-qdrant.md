# 0004. Embedded Qdrant for development

Status: accepted. Date: 2026-10-29.

## Context
Docker was not working in the development shell, and the corpus is small (a few books).

## Decision
Use `QdrantClient(path=...)` (files under `data/index/`) by default. Set `CODEBUDDY_QDRANT_URL`
to use a server. Hybrid search (dense plus BM25 with reciprocal rank fusion) works in both modes.
One collection per corpus and index version.

## Consequences
No services to run. Embedded mode allows one process and no payload indexes, so ingestion and the
API cannot run at the same time, and production should use a server. Retrieval calls run in a
worker thread because the embedded client is synchronous.
