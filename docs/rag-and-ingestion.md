# RAG and ingestion

Code: `src/codebuddy/rag/`. Design rationale: [../PROJECT_SPEC.md](../PROJECT_SPEC.md) Section 9.

## Corpora

| Corpus | Collection | Who may read it | Typical content |
|---|---|---|---|
| `fundamentals` | `cb_fundamentals_<index_version>` | Learner turns (cited to the learner) | Think Python (338 chunks ingested), Python docs |
| `pedagogy` | `cb_pedagogy_<index_version>` | Only code that builds a `Retriever` with `allowed={"pedagogy"}`. The production API does not, and no node uses it yet | PCDIT paper (29 chunks ingested) and page |
| any other name, e.g. `tenant_42` | `cb_tenant_42_<index_version>` | Not wired into the API yet | Instructor uploads |

Separation is by collection, not by prompt. `Retriever.retrieve()` raises `PermissionError` for a
corpus it was not built to read (tested in `tests/unit/test_rag.py`). Ingesting into `pedagogy`
today only stores the material for later use by policy and prompt-building nodes.

## Ingesting

```bash
uv run python -m codebuddy.rag.ingest PATH --corpus NAME [options]
```

| Option | Default | Meaning |
|---|---|---|
| `PATH` | | A file, or a folder (all supported files below it) |
| `--corpus` | `fundamentals` | Target corpus |
| `--title` | filename | Display and citation name (applies when `PATH` is a single file) |
| `--licence` | `unverified` | Recorded in chunk metadata and the manifest |
| `--language` | `python` | Metadata and retrieval filter |
| `--difficulty` | `beginner` | Metadata |
| `--pcdit-stage` | none | Tags every chunk with a PCDIT stage |
| `--force` | off | Re-ingest even if the file hash is unchanged |

Supported files: `.md`, `.markdown`, `.txt`, `.html`, `.htm`, `.pdf`.

| Format | Handling |
|---|---|
| Markdown, text | Read as Markdown |
| HTML | Small built-in converter: headings, paragraphs, lists, and `<pre>` blocks to Markdown. Scripts and styles skipped. Not a general-purpose scraper |
| PDF | Docling converts to Markdown (needs `uv sync --extra pdf`). `tidy_docling_markdown` then indents any line that starts with a single `#`: Docling writes every real heading as `##`, so a single `#` is a comment from a code listing and must not become a heading. Run on the two real PDFs; inspect the output of any new PDF before trusting it |

The CLI loads `.env` into the process environment, so `OPENAI_API_KEY` there is found. A `PATH` that
does not exist is an error. Docling can segfault on WSL while probing for a GPU; run ingestion with
`CUDA_VISIBLE_DEVICES=` set to empty (see [setup.md](setup.md)). The 240-page book took several
minutes on CPU.

Embedding uses `OpenAIEmbeddings` (needs `OPENAI_API_KEY`) plus BM25 sparse vectors from
`fastembed`. Embedded Qdrant allows one process at a time, so stop the API during ingestion.

## What ingestion does

1. Hash the file (SHA-256). Skip it if the manifest already has the same hash for this corpus.
2. Convert to Markdown.
3. Split into sections at headings (levels 1 to 4), never at a heading inside a code fence.
4. Pack paragraphs and whole code blocks into chunks of 800 to 2000 characters (about 200 to 500
   tokens). A tiny tail folds into the previous chunk. A code block is never split.
5. Prefix each chunk with `From <title>, <section path>:` before embedding, so retrieval sees
   where it came from.
6. Upsert with a deterministic ID (UUID derived from the SHA-256 of source plus chunk text).
   Re-ingesting identical text overwrites instead of duplicating.
7. Record the file in `<QDRANT_PATH>/manifest.json` (title, corpus, licence, hash, chunk count, time).

### Chunk metadata

| Field | Value |
|---|---|
| `source`, `title` | File name, display title |
| `corpus`, `license` | Target corpus, licence string |
| `language`, `difficulty`, `pcdit_stage` | From options (`pcdit_stage` only if given) |
| `chapter`, `section`, `concept` | First heading, full heading path, last heading lowercased |
| `content_type` | `exercise` (heading mentions "exercise"), `common-bug` (debug, common error, pitfall, mistake), `example` (contains a code fence), else `explanation` |
| `parent` | The whole section text (capped), kept for small-to-big context |
| `version`, `updated_at`, `content_hash` | Index version, ingest time, chunk hash |

Search filters use these fields, for example `retriever.retrieve(q, filters={"content_type": "exercise"})`.

### Known limitations

- **Edited documents leave stale chunks.** IDs derive from chunk text, so a changed chunk gets a
  new ID and the old one stays. `--force` re-adds but does not delete. To rebuild cleanly, bump
  `CODEBUDDY_INDEX_VERSION` (new collections, old ones remain on disk) or delete `data/index/`.
- Content-type and concept tags are heading heuristics, not classification.
- Synthetic question generation and contextual summaries from the spec are not implemented.
- No near-duplicate detection across documents.

## Retrieval

`Retriever.retrieve(query, corpus="fundamentals", filters=None)`:

1. Check the L4 cache (key: query, corpus, filters, index version).
2. Warm the query embedding (L3 cache), then run Qdrant hybrid search (dense plus BM25, fused by
   reciprocal rank) for `RETRIEVE_K` candidates, in a worker thread.
3. Rerank to `RERANK_TOP` with the configured reranker.
4. Report `grounded` when the best score reaches `RELEVANCE_THRESHOLD`.

The agent builds the query from the learner message plus the concept of each detected bug pattern.

### Rerankers

| Reranker | Use | Scores |
|---|---|---|
| `NoopReranker` (default) | Keeps Qdrant order | All 1.0, so any hit counts as grounded |
| `CrossEncoderReranker` | `CODEBUDDY_USE_CROSS_ENCODER=true` and `--extra rerank` | Sigmoid of the model score, 0 to 1; threshold is meaningful |

## Adding a corpus or document

1. Put the file in `data/raw/` and add a row to [corpus-manifest.md](corpus-manifest.md) (licence first).
2. Ingest it with the command above.
3. For a new learner-facing corpus, add its name to `LEARNER_CORPORA` in `api/wiring.py`.
4. Add a query to `eval/golden/retrieval.jsonl` for the new material and run the offline eval.
