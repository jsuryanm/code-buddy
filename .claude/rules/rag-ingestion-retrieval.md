---
paths:
  - "**/ingest*/**"
  - "**/retriev*/**"
  - "docs/corpus-manifest.md"
---

# RAG ingestion and retrieval

Source: PROJECT_SPEC.md Sections 9 and 19.5.

## Ingestion

- Convert PDFs to Markdown (Docling) before chunking. A plain-text PDF dump loses headings and code blocks.
- Chunk 200 to 500 tokens, 10 to 15% overlap. Never split a code block from its explanation. Index small chunks, return the parent section (small-to-big).
- Required metadata: `concept`, `language`, `difficulty`, `pcdit_stage`, `content_type` (explanation, example, common-bug, exercise), `source`, `license`, `version`, `updated_at`.
- Prepend a one-line context to each chunk before embedding. Index synthetic learner questions alongside chunks.
- Upsert idempotently with the content hash as ID. Record `embedding_model_version`.
- Promote a new index only after the golden-set retrieval eval passes, then swap the collection alias and bump the cache `index_version`.
- Every document needs a `docs/corpus-manifest.md` entry: title, edition, URL, retrieval date, SHA-256, licence, corpus, owner.

## Corpus access

- Learner turns search `fundamentals` only.
- `pedagogy` (PCDIT paper and page) is searched only by policy and prompt-building nodes. Cite it by method name, never a verbatim passage.
- Instructor uploads live in `tenant_<id>`, enforced by filter.

## Retrieval

Rewrite, metadata filter, hybrid dense+sparse search, RRF fusion, local cross-encoder rerank to the top 4 to 6, parent expansion, relevance threshold. Below the threshold, say the answer is not grounded instead of guessing.
