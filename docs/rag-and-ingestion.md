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
7. Record the file in `<QDRANT_PATH>/manifest.json` (title, corpus, licence,
   hash, chunk count, time).

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

Search filters use these fields, for example
`retriever.retrieve(q, filters={"content_type": "exercise"})`.

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

### Query building and fusion

`build_query(message, features, concepts)` in `rag/query.py` makes the search text: the learner
message, then for each detected bug pattern its concept and plain search terms (`search_terms` on
`BugPattern`, for example "range len index off-by-one"), "syntax error" when the code does not
parse, the names of up to 6 built-ins and container methods the code calls (`range`, `len`,
`remove`, from the AST), and any classifier concepts. Repeated terms are dropped and the result is
capped at 300 characters, with at most half for the extra terms. The learner's code itself never
goes into the query: only names on a fixed list of built-ins and `list`, `dict`, `str`, `set`
methods, so the learner's own identifiers stay out.

`retrieve` searches with `build_query(message, features)` while the classifier runs. Then
`refine_retrieval` builds a second query from the classifier's standalone `search_query` (which
resolves "it" and "that" from the last two history entries) and its concepts. When the second
query differs from the first after normalizing, it retrieves again and merges both lists with
reciprocal rank fusion (`rrf_merge`, k=60): chunks are deduplicated by content hash, a chunk found
by both queries ranks higher, each keeps its best rerank score, the list is cut to `RERANK_TOP`,
and `grounded` is recomputed from the best score. Foreign turns (a session bound to another
learner) skip the second query, and the classifier sees no history for them. If the second
retrieval fails or finds nothing, the first result stands.

Latency: the second retrieval runs after `classify`, which is already on the critical path before
`policy`, so it adds one search (and one query embedding unless L3 has it) to most live turns. L3
and L4 caches apply to it as to the first. It has a budget of `REFINE_TIMEOUT_S` (default 0.3 s,
`asyncio.wait_for`): on a timeout the first result is used unchanged, a debug line is logged (no
learner text), and the `refine_timeouts` counter in `/v1/metrics` rises. Nothing has been measured
live. Offline, with the heuristic classifier, the second query equals the first and is skipped.

The offline eval's `retrieval_recall` uses the same path: `build_query` with the case's `code`,
and fusion for cases that carry a scripted `search_query` (standing in for the classifier) and
`history`.

### Rerankers

| Reranker | Use | Scores |
|---|---|---|
| `NoopReranker` (default) | Keeps Qdrant order | All 1.0, so any hit counts as grounded |
| `CrossEncoderReranker` | `CODEBUDDY_USE_CROSS_ENCODER=true` and `--extra rerank` | Sigmoid of the model score, 0 to 1; threshold is meaningful |

## Adding a corpus or document

1. Put the file in `data/raw/` and add a row to
   [corpus-manifest.md](corpus-manifest.md) (licence first).
2. Ingest it with the command above.
3. For a new learner-facing corpus, add its name to `LEARNER_CORPORA` in `api/wiring.py`.
4. Add a query to `eval/golden/retrieval.jsonl` for the new material and run the offline eval.
