# RAG evaluation with RAGAS

`src/codebuddy/eval/ragas_run.py` scores the tutor's answers to concept questions with RAGAS.
It uses real models and costs OpenAI calls, so it is a manual runner. It never runs in `pytest`
or CI. The offline eval in `eval/run.py` ([testing.md](testing.md)) stays the CI gate.

Status: the runner, its dataset and its tests are built. The tests use fakes: an injected scoring
function, a fake graph run and a fake Langfuse client. The live path has not been run: no ragas
judge call against OpenAI and no push to Langfuse cloud. Treat the first live run as a test.

## What is scored

Each golden question goes through the real tutor graph, the same code the API runs:
`load_state`, `check_cache`, `classify`, `retrieve`, `refine_retrieval`, `policy`, `generate`.
For the evaluation the runner changes only this:

- Every question gets a fresh session and fresh in-process caches, so there is no answer-cache hit
  and nothing is written to the shared cache or the counters. There is no semantic cache, no
  memory, no tools and no metadata tracer.
- The classifier still runs and still writes the search query and concepts. Its intent is pinned
  to `concept_question`, so the policy picks an explanation (`explain`). Hints are made to hold
  answers back, so scoring them for faithfulness or recall would mean little.

Each item gets three things:

- `retrieved_contexts`: the passages the prompt actually got, each cut to its first
  `PASSAGE_CHARS` (1200) characters, the same constant `generate` uses (`agent/nodes.py`).
- `response`: the final reply.
- `reference`: the answer written in the dataset.

## Metrics

The judge is the standard-tier model (`CODEBUDDY_MODEL_STANDARD`). Answer relevancy also needs
embeddings, from `CODEBUDDY_EMBED_MODEL`. No model id is hard-coded. All scores run from 0 to 1.

| Name | RAGAS metric | What it means for the tutor |
|---|---|---|
| `faithfulness` | `Faithfulness` | Share of the claims in the reply that the passages support. Low means the tutor states things the course material does not say. This is the hallucination check |
| `answer_relevancy` | `AnswerRelevancy` | Whether the reply answers the question asked. The judge writes questions the reply would answer, and they are compared with the real one by embedding. A reply that drifts or stays vague scores low. A Socratic reply that ends in a question can score a little lower than a direct one |
| `context_precision` | `ContextPrecisionWithReference` | Whether the useful passages are ranked first, judged against the reference. Low means retrieval puts noise first |
| `context_recall` | `ContextRecall` | Share of the reference's claims found in the passages. Low means retrieval missed material the answer needs, so the tutor cannot ground it |

The report also has `section_hit` for each item: whether the item's `expected_section` is among the
sections of the passages. It is a free check that needs no judge call.

### Which ragas API is used

ragas 0.4.3 offers two paths. In the legacy path, `evaluate()` takes metrics from `ragas.metrics`
with `LangchainLLMWrapper` and `LangchainEmbeddingsWrapper`. It works with our langchain-openai,
but every one of those names raises a `DeprecationWarning` (they will be removed in ragas 1.0).
The runner uses the current path instead. It builds the metrics from `ragas.metrics.collections`,
with `llm_factory(<standard model>, client=AsyncOpenAI())` as the judge and
`ragas.embeddings.OpenAIEmbeddings`. It scores one sample at a time with `ascore`. This path
raises no deprecation warning. For reasoning models (gpt-5, o-series) the runner passes
`max_tokens=4096`, which ragas sends as `max_completion_tokens`. A metric that fails on an item
is recorded as missing (`-`), and the run goes on.

## Setup: a separate environment

ragas cannot join the main lock. ragas needs `instructor`, which caps `jiter` below 0.15. The
openai version we use (3.41) needs `jiter` 0.16 or newer, so resolving ragas in `uv.lock` would
downgrade openai to 3.3.0. It would also downgrade `rich` and `fsspec`. The main project therefore
has no `evals` extra. The runner has its own virtual environment, `.venv-evals/` (git-ignored),
built from the versions in `uv.lock` plus ragas:

```bash
bash evals/setup.sh
```

The script runs `uv export --frozen` of the main lock as constraints, then installs the project
with the `trace` extra (Langfuse) and `evals/requirements.txt` (`ragas==0.4.3`,
`langchain-community==0.4.1`). It applies `evals/overrides.txt`, which lifts instructor's and
datasets' upper bounds on `jiter`, `rich` and `fsspec`. That keeps openai 3.41, langchain,
pydantic, langgraph and qdrant-client at the main lock's versions. langchain-community is pinned
because ragas 0.4.3 imports a module that 0.4.2 removed. langchain-community also brings in
`langchain-classic`, but only into this environment (ADR 0009). Lifting the caps was checked by
importing ragas, building all four metrics and running the scorer up to the network call. It has
not been checked in a live run.

Environment (`.env`, read at start):

| Variable | Needed for |
|---|---|
| `OPENAI_API_KEY` | Always. The runner refuses to start without it |
| `CODEBUDDY_MODEL_FAST`, `_STANDARD`, `_HEAVY` | Always. The graph uses the tiers, and the judge is the standard tier |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` | Optional. Without them the run skips Langfuse |
| Qdrant variables (`QDRANT_CLUSTER_ENDPOINT`, ...) | `--index real` with a server; see [configuration.md](configuration.md) |

## Running

```bash
.venv-evals/bin/python -m codebuddy.eval.ragas_run --index sample --limit 3     # a cheap first try
.venv-evals/bin/python -m codebuddy.eval.ragas_run --index sample               # all 20 items
.venv-evals/bin/python -m codebuddy.eval.ragas_run --index real --fail-under faithfulness=0.8
.venv-evals/bin/python -m codebuddy.eval.ragas_run --metrics faithfulness,context_recall --no-langfuse
```

| Option | Default | Meaning |
|---|---|---|
| `--index sample\|real` | `sample` | `sample` builds a temporary embedded index from `data/sample/python_basics.md` with the real embeddings (index version `sample`). `real` uses the configured index (embedded folder or Qdrant server) |
| `--dataset PATH` | `eval/golden/ragas.jsonl` | Golden items |
| `--limit N` | all | Only the first N items |
| `--metrics a,b` | all four | Any of `faithfulness,answer_relevancy,context_precision,context_recall` |
| `--no-langfuse` | off | Skip the Langfuse push |
| `--out PATH` | `data/eval/ragas-<UTC time>.json` | Report file (`data/eval/` is git-ignored) |
| `--fail-under metric=value` | none | Exit code 2 when that metric's mean is below the value, or missing. Repeat for more gates |
| `--generate-draft N` | | Draft N items from the real index instead of scoring (below) |

Exit codes: 0 done, 1 refused (missing key, model ids or ragas) or failed (including a run where
every score is missing), 2 a `--fail-under` gate missed.

The logs follow the other entrypoints ([observability.md](observability.md)), in
`logs/YYYY-MM-DD/ragas_HH-MM-SS.log`. They hold a start line, a config summary without secrets,
one line per item with its duration and one per item with its scores, a finish line with the
means, and a hint on failure.

### Cost

Count calls, not money. For each item:

- Pipeline: 1 classifier call (fast tier), 1 reply (standard tier) and 1 or 2 query embeddings.
- Judge: `faithfulness` 2, `answer_relevancy` 3 (one per generated question, plus about 4
  embeddings), `context_precision` 1 per passage (up to `CODEBUDDY_RERANK_TOP`, default 5),
  `context_recall` 1.

Judge calls = items x (6 + passages), with all four metrics. The full golden set of 20 items with
5 passages is about 20 x 11 = 220 judge calls, plus 40 pipeline calls. `--index sample` also
embeds the 6 sample chunks once. `--generate-draft N` makes N heavy-tier calls.

## Reading the results

The console prints one row per item and a `mean` row. The JSON report holds:

- `config`: index and index version, prompt version, the model ids including judge and
  embeddings, `retrieve_k`, `rerank_top`, relevance threshold, `passage_chars`, git sha, start time.
- `means`: the mean of each metric.
- `items`: for each item the question, reference, passages, sources, reply, mode, timings and
  scores.

In Langfuse (when keys are set):

- **Datasets, `codebuddy-ragas`**: one dataset item per golden question, with input `question`,
  expected output `reference` and metadata `expected_section`. The item id is a hash of the
  question, so a rerun updates the item instead of adding a copy.
- **Runs**: each run is named `<prompt_version>-<index_version>-<UTC time>`, for example
  `p5-sample-20261102T081500Z`. Open the dataset's runs and compare two of them to see the
  per-metric means side by side, for example before and after a prompt or index change.
- **Traces**: one `ragas-item` trace per item, with a `retrieve` observation (passages and their
  sources) and a `generate` observation (the passages in, the reply out). Each metric is a
  numeric score on the trace. Filter traces by score to find the weakest items.

These traces carry content: questions, passages and replies. That is allowed only because golden
questions are written for testing and are not learner data. A learner turn is never traced this
way. The tutor's own traces stay metadata only ([observability.md](observability.md)).

## Growing the golden set

`eval/golden/ragas.jsonl` has one JSON object per line:

```json
{"question": "What is an accumulator?", "reference": "An accumulator is a variable ...", "expected_section": "Accumulators"}
```

The keys are `question` and `reference` (required), `expected_section` (the last heading of the
passage that answers it), and `source` and `auto_generated` (set by drafts). The loader rejects
unknown keys, empty fields and duplicate questions. The 20 starting items were written from
`data/sample/python_basics.md`, and every reference is stated in that file. Use them with
`--index sample`.

For the real corpus:

```bash
.venv-evals/bin/python -m codebuddy.eval.ragas_run --generate-draft 20 --seed 1
```

This samples 20 chunks of the configured `fundamentals` collection. For each one it asks the heavy
model for a question and a reference grounded only in that chunk. It writes them to
`data/eval/ragas-draft-<time>.jsonl` with `"auto_generated": true` and prints a warning. **A human
must review every draft.** Check each reference against its passage, fix or delete what is wrong,
then remove `auto_generated` or keep it to track where the item came from. Then copy the items
into a dataset file and pass it with `--dataset`. Do not invent facts about the source book when
editing. A reference must be stated in the material.

## How this differs from `retrieval_recall`

`retrieval_recall` in `eval/run.py` checks whether an expected substring is in the top passages,
using fake embeddings and the sample corpus. It is deterministic, free and runs in CI. It catches
wiring regressions in the query path. It cannot tell whether the passages are the best ones or
whether the reply is grounded.

RAGAS answers those questions with a judge LLM. It measures whether the retrieved passages hold
what the answer needs (context recall and precision) and whether the reply is supported and on
topic (faithfulness, answer relevancy). It measures this with the real embeddings and models. Its
scores vary a little between runs and cost money, so it gates manually (`--fail-under`), not in
CI.
