# Logs, tracing and evaluation

Three tools tell you what CodeBuddy is doing and how well. They answer different questions:

| Tool | Question it answers | Where it lives | Needs |
|---|---|---|---|
| **Logs** (loguru) | What happened in this turn, step by step? Why did it fail? | Text files in `logs/` on your computer | Nothing; always on |
| **Tracing** (Langfuse) | Across many turns, how fast is it, how often does it fall back or degrade? | Charts on the Langfuse website | A Langfuse account and the `trace` extra |
| **Evaluation** (RAGAS) | Are the answers grounded in the book and on topic? Is the search finding the right pages? | A report file and Langfuse | An OpenAI key; costs money per run |

Think of it this way: logs are a diary, tracing is a dashboard, and evaluation is an exam.

The reference pages are [../observability.md](../observability.md) (logs and tracing) and
[../evaluation.md](../evaluation.md) (RAGAS).

## 1. Logs: what the program wrote down

A **log** is a text file where a program writes one line for each thing it does.
CodeBuddy uses a library called [loguru](06-glossary.md#loguru) for this.

### Where the files are

Each time a program starts, it gets new files in a folder for the day:

```text
logs/
  <YYYY-MM-DD>/
    api_<HH-MM-SS>.log           the normal log: INFO and up
    api_<HH-MM-SS>.errors.log    only warnings and errors, with full error details
```

The first part of the name says which program wrote it: `api`, `demo`, `ui`, `ingest`,
`eval`, `mcp`, or `ragas`. The time is when it started, in local time.

To find the log of something you just started, read the first line it prints. It ends with
`log=logs/<DATE>/<APP>_<TIME>.log`.

The same lines are also printed in the terminal. Set `CODEBUDDY_LOG_JSON=true` to also get a
`.jsonl` file (one JSON object per line) for log tools.

### Cleanup

At start, files older than **5 days** are deleted, and empty day folders removed
(`CODEBUDDY_LOG_RETENTION_DAYS`, minimum 1). Nothing else in the folder is touched.

If the folder cannot be created, the program prints one warning and keeps going with the
terminal only. Logging never stops the app.

### Reading one turn

Here are a few lines from a real demo turn (from [../observability.md](../observability.md);
the date and the level are cut). A learner sent buggy code, the tutor asked to run it, and
the learner said yes:

```text
07:21:29.227 | agent.graph | turn=d071e09d sess=5166ff00 | turn start route=turn
07:21:29.232 | agent.graph | turn=d071e09d sess=5166ff00 | <- analyze_code 0.3 ms patterns=['off_by_one_range'] parse_error=False
07:21:29.237 | agent.graph | turn=d071e09d sess=5166ff00 | <- classify 0.1 ms intent=debug_help stage=T concepts=0
07:21:29.241 | agent.graph | turn=d071e09d sess=5166ff00 | <- retrieve 3.3 ms chunks=5 grounded=True cache_hit=False sources=['Sample Python Basics']
07:21:29.244 | agent.graph | turn=d071e09d sess=5166ff00 | <- policy 0.1 ms mode=hint level=0 can_show=False offer=False offer_quiz=False reasons=['hints given: 0'] tools=['trace_python']
07:21:29.245 | agent.graph | turn=d071e09d sess=5166ff00 | <- approve_run 0.0 ms paused
07:21:36.123 | api.app     | turn=d071e09d sess=5166ff00 | approval granted remember=True
07:21:36.145 | tools.runner | turn=d071e09d sess=5166ff00 | tool trace_python via=inprocess 16.3 ms ok=True
07:21:36.148 | agent.nodes | turn=d071e09d sess=5166ff00 | generate tier=standard cap=250 -> ok
07:21:36.151 | agent.graph | turn=d071e09d sess=5166ff00 | <- update_state 0.2 ms hints_given=1 stage=T reveals=0 quiz_index=None
07:21:36.153 | api.app     | turn=d071e09d sess=5166ff00 | api done ttft_ms=25 total_ms=28 awaiting_approval=False citations=5 degraded=False guarded=False cache_hit=False stage=T hints_given=1 learner=no
```

How to read it:

- `turn=d071e09d` is the turn's ID (its first 8 characters). Search for it to get every line
  of one turn: `grep turn=d071e09d logs/<DATE>/*.log`.
- `sess=5166ff00` is a scrambled form (a hash) of the session ID, never the real ID.
- `<- analyze_code 0.3 ms ...` means the step `analyze_code` finished in 0.3 milliseconds,
  followed by a short summary. Here it found the `off_by_one_range` bug pattern.
- `policy ... mode=hint level=0 ... reasons=['hints given: 0']` is the decision made by code,
  and why.
- `approve_run ... paused` is the turn waiting for "Run my code". Seven seconds later,
  `approval granted` is the learner's click.
- `generate tier=standard cap=250 -> ok` is one model call: which tier, the token cap, and
  the outcome (`ok`, `empty`, or `error <TYPE>`). A fallback adds a line
  `generate falling back to tier=...`.
- `api done ttft_ms=25 total_ms=28` is the time to the first word of the reply and the total
  time, in milliseconds.

For even more detail, set `CODEBUDDY_LOG_LEVEL=DEBUG`: each step's start and each cache
lookup get their own line.

### What is never logged

Logs hold **metadata only**: names, times, counts, yes/no values, modes, levels, tier names,
bug pattern IDs and book titles. They never hold the learner's message, the code, the reply,
a prompt, a learner ID or token, or the raw session ID. A test sends secret marker strings
through every part of a turn and checks that none of them reach any log
(`tests/integration/test_logging_flow.py`).

One limit: error details in `.errors.log` come from libraries such as OpenAI or Qdrant and
could, in principle, repeat part of a request. The access log also records client IP
addresses.

## 2. Langfuse tracing: a timeline of each turn

[Langfuse](06-glossary.md#langfuse) is a website for watching AI apps. CodeBuddy can send
it one **trace** per turn. A trace is a timeline of one turn: one bar for the whole turn
(the root **span**), and inside it one bar for each step. A **generation** is a span for a
model call. Langfuse then draws charts over many turns.

Not tested live: tracing was checked against a fake Langfuse and the library's source code,
never against the real Langfuse cloud.

### Setup in 6 steps

1. Create a free account on the Langfuse cloud website and create a project.
2. In the project, open Settings, then API keys, and create a key pair. Copy the public key
   (starts with `pk-lf-`) and the secret key (starts with `sk-lf-`).
3. Add them to `.env`:

   ```dotenv
   LANGFUSE_PUBLIC_KEY=<PUBLIC_KEY>
   LANGFUSE_SECRET_KEY=<SECRET_KEY>
   LANGFUSE_BASE_URL=https://cloud.langfuse.com
   ```

   Use `https://us.cloud.langfuse.com` if your project is in the US region.

4. Install the extra:

   ```bash
   uv sync --extra ui --extra trace
   ```

5. Restart the API (`uv run uvicorn codebuddy.api.app:app --port 8000`).

   What you should see: a start line `tracing on: Langfuse host=... sample_rate=...`, and
   `curl localhost:8000/healthz` shows `"tracing_enabled":true`. If tracing is off, one line
   says why (switched off, a key missing, the package missing, or the client failed).

6. Ask the tutor a question, wait a few seconds, and open Tracing in your Langfuse project.
   Traces are sent in the background in batches, so they appear after a short delay.

The keyless demo, the UI, ingestion and the offline evaluation never send traces.

### What a trace shows

- A root span named `tutor-turn`, with the route (turn, show-answer, approve), the mode and
  the hint level.
- One child span per step that ran (`classify`, `retrieve`, `policy`, `generate`, and so on),
  with the same summary as its log line.
- One generation per model call: model ID, tier, token cap, tokens used, and the outcome.
- One span per tool call, such as `tool:trace_python`.

A turn paused for "Run my code" gives two traces, one before and one after the click.

### Scores

A **score** is a number or a yes/no attached to a trace, so Langfuse can chart it:

| Score | Meaning |
|---|---|
| `ttft_ms` | Milliseconds until the first word of the reply. The target is under 1000 ms for 95% of turns |
| `total_ms` | Milliseconds for the whole turn |
| `cache_hit` | The reply came from the answer cache |
| `guarded` | The leak guard stopped the model's reply |
| `degraded` | Every model tier failed |
| `quiz` | The turn started or answered a quiz |

A dashboard recipe (charts for speed, fallback rate, reveal rate) is in
[../observability.md](../observability.md#dashboard-recipe).

### Privacy

Langfuse is a third party, so CodeBuddy sends **metadata only**, the same kind as the logs.
It never sends the learner's message, code, the reply, prompts, book text, memory notes,
learner IDs, or the raw session ID. A test checks this with secret marker strings
(`tests/integration/test_tracing_flow.py`).

### Turning it off

Set `CODEBUDDY_TRACING_ENABLED=false`, or remove the two keys, and restart the API. To keep
only some traces, set `CODEBUDDY_TRACE_SAMPLE_RATE` between 0 and 1 (default 1, all).

## 3. RAGAS: scoring answer quality

[RAGAS](06-glossary.md#ragas) is a library that grades RAG answers. It uses an AI model as a
**judge**: a model that reads the question, the book passages and the reply, and scores them.
CodeBuddy's runner is `src/codebuddy/eval/ragas_run.py`.

It runs a **golden set**: 20 questions with hand-written correct answers (the **reference**),
in `src/codebuddy/eval/golden/ragas.jsonl`. Each question goes through the real tutor graph.
The runner forces an explanation (not a hint), because hints hold the answer back on
purpose and would score badly for the wrong reason.

### The four scores

All scores run from 0 (bad) to 1 (good). The judge is your standard-tier model.

**Faithfulness: does the reply stick to the book?** The judge splits the reply into claims
and checks each against the passages. It catches made-up facts (hallucinations).

> Passage: "`range(n)` stops before `n`." Reply: "`range(5)` gives 0 to 4. It is the
> fastest way to loop." The first claim is supported, the second is not in the passage.
> Faithfulness = 1 of 2 = 0.5.

**Answer relevancy: does the reply answer the question asked?** The judge writes questions
that the reply would answer, and compares them with the real question.

> Question: "What does `range(3)` produce?" A reply about `range(3)` scores high. A reply
> about how `while` loops work scores low, even if it is true. A Socratic reply that ends in
> a question can score a little lower than a direct one.

**Context precision: are the useful passages ranked first?** The judge marks each passage
useful or not, using the reference, and rewards useful passages near the top.

> Five passages come back. The one about `range` is first: high precision. The one about
> `range` is fifth, after four about strings: low precision.

**Context recall: did the search find everything the answer needs?** The judge splits the
reference into claims and checks whether the passages contain each one.

> Reference: "`range(n)` starts at 0 and stops before `n`." The passages mention "stops
> before `n`" but nowhere say it starts at 0. Context recall = 1 of 2 = 0.5.

Faithfulness and answer relevancy grade the **reply**. Context precision and recall grade
the **search**.

### How to run it

RAGAS needs library versions that clash with the main project, so it lives in its own
private environment, `.venv-evals/`.

#### Step 1: build the evaluation environment (once)

```bash
bash evals/setup.sh
```

What you should see: packages being installed, then
`Ready: .venv-evals/bin/python -m codebuddy.eval.ragas_run --help`.

#### Step 2: make sure `.env` has your keys

`OPENAI_API_KEY` and the three `CODEBUDDY_MODEL_*` IDs are required; the runner refuses to
start without them. The Langfuse keys are optional.

#### Step 3: a cheap first run

```bash
.venv-evals/bin/python -m codebuddy.eval.ragas_run --index sample --limit 3
```

`--index sample` builds a temporary knowledge base from `data/sample/python_basics.md`,
which the 20 golden questions were written from. `--limit 3` scores only the first 3.

#### Step 4: the full run, and other options

```bash
.venv-evals/bin/python -m codebuddy.eval.ragas_run --index sample
.venv-evals/bin/python -m codebuddy.eval.ragas_run --index real --fail-under faithfulness=0.8
.venv-evals/bin/python -m codebuddy.eval.ragas_run --metrics faithfulness,context_recall --no-langfuse
```

| Option | Meaning |
|---|---|
| `--index sample` or `real` | The sample file, or your configured knowledge base |
| `--limit N` | Only the first N questions |
| `--metrics a,b` | Only these scores |
| `--no-langfuse` | Do not send results to Langfuse |
| `--out PATH` | Where to write the report (default `data/eval/ragas-<UTC TIME>.json`) |
| `--fail-under metric=value` | Exit with code 2 if that score's average is below the value |

> **Warning: this costs money.** Every question makes real OpenAI calls. With all four
> scores, each question costs about 6 judge calls plus 1 per passage (5 by default), so
> about 11, plus 2 calls to make the reply. The full 20 questions are about 220 judge calls
> plus 40 pipeline calls. Start with `--limit 3`.

Not tested live: the runner was tested with fakes only. Treat your first run as a test.

### How to read the results

- The terminal prints one row per question and a `mean` (average) row.
- The JSON report has `config` (models, versions, settings), `means`, and `items` (each
  question with its passages, reply and scores). A score shown as `-` means that metric
  failed on that item; the run continues.
- In Langfuse, the dataset `codebuddy-ragas` holds the questions. Each run is named like
  `p5-sample-20261102T081500Z` (prompt version, index version, time), so you can compare two
  runs side by side, for example before and after a prompt change.

Rough guide: low faithfulness means the tutor says things the book does not; low context
recall means the search misses material, so fix retrieval before blaming the model.

These traces contain the golden questions and replies. That is allowed only because golden
questions are test data, not learner data.

### RAGAS versus the offline evaluation

| | `uv run python -m codebuddy.eval.run` | RAGAS runner |
|---|---|---|
| Models | Fake, scripted | Real OpenAI models |
| Cost | Free | Paid per question |
| Result | The same every time | Varies a little between runs |
| Checks | The machinery: leak guard, bug patterns, escalation rules, fix detection, whether search finds expected text | Quality: grounded, on-topic replies and good search |
| When | Every change; must print `PASS` | By hand, before and after a big change |

The offline evaluation is the safety gate. RAGAS is the quality exam.

Next: [05-troubleshooting.md](05-troubleshooting.md).
