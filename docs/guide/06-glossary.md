# Glossary

Plain-language meanings of the technical words in this guide, in alphabetical order. Where
a word has a specific meaning in CodeBuddy, that is given too.

### API

Application programming interface: a program that other programs talk to by sending
requests. CodeBuddy's API is a web server (`src/codebuddy/api/app.py`) at
`http://localhost:8000` by default. The UI is its main caller.

### Answer relevancy

A [RAGAS](#ragas) score from 0 to 1: does the reply answer the question that was asked? A
reply that drifts off topic scores low, even if everything in it is true.

### Approval (permission prompt)

The pause before the tutor runs a learner's code. The UI shows **Run my code** and **Don't
run it**. Nothing runs until the learner chooses. In code this is the `approve_run` step.

### BM25

A classic word-matching search method. It ranks text by how often the search words appear
in it, giving more weight to rare words. Good at exact terms such as `IndexError`.
CodeBuddy uses the `Qdrant/bm25` model from the `fastembed` library.

### Cache

A store of results that were already worked out, so they can be reused instead of computed
again. See [cache layers](#cache-layers-l1-to-l6).

### Cache layers (L1 to L6)

CodeBuddy's caches, numbered after the design document:

- **L1 answers**: replies to concept questions and redirects with no code attached. 1 day.
- **L2 semantic**: points a *similar* question to an L1 answer, using
  [embeddings](#embedding). Off by default.
- **L3 embeddings**: the embeddings of search queries. 30 days.
- **L4 retrieval**: search results for a query. 3 hours.
- **L5 tool results**: not built.
- **L6 session**: each [session](#session)'s progress and short history. 2 hours.

Hints and reveals are never cached.

### Checkpoint

A saved snapshot of a turn in progress. When the tutor pauses to ask "may I run your
code?", the turn is saved as a checkpoint so it can continue after the click. Stored in
`data/checkpoints.sqlite` by default.

### Chunk

A small piece of a document, 800 to 2000 characters in CodeBuddy. Documents are cut into
chunks so the search can return just the relevant part.

### Classifier

The step that reads the learner's message and labels it with an [intent](#intent), a
[PCDIT](#pcdit) stage and a search query. It uses the fast-tier model, with simple rules as
a backup.

### Collection

A named group of chunks inside [Qdrant](#qdrant). CodeBuddy keeps each [corpus](#corpus) in
its own collection, named `<PREFIX>_<CORPUS>_<INDEX_VERSION>`, for example
`cb_fundamentals_v1`.

### Context precision

A [RAGAS](#ragas) score from 0 to 1: are the useful passages ranked at the top of the
search results?

### Context recall

A [RAGAS](#ragas) score from 0 to 1: do the search results contain everything the correct
answer needs?

### Corpus

A set of documents for one purpose. CodeBuddy has two: `fundamentals` (Think Python,
shown to learners) and `pedagogy` (the PCDIT paper, never reachable from a learner turn).
Plural: corpora.

### Degraded reply

A short reply written by code when every model [tier](#tier) failed. The turn counts for
nothing: no hint step, no history, nothing cached.

### Docker

A tool that packages a program with everything it needs into a **container**, so it runs
the same on any computer. See [03-run-with-docker.md](03-run-with-docker.md).

### Embedding

A list of numbers that stands for the meaning of a piece of text. Texts with similar
meanings get similar lists, so a computer can find "related" text by comparing numbers.
CodeBuddy uses OpenAI's `text-embedding-3-small` by default.

### `.env` file

A text file in the project folder that holds settings and secret keys, one `NAME=value` per
line. Never shared or uploaded. The template is `.env.example`.

### Extra

An optional group of libraries you install only if you need it, for example
`uv sync --extra pdf`. CodeBuddy's extras are `ui`, `pdf`, `rerank` and `trace`.

### Fallback

Using a backup when the first choice fails. When a model call fails, CodeBuddy falls back
to the next lighter [tier](#tier): heavy, then standard, then fast.

### FastAPI

A Python library for building web [APIs](#api). CodeBuddy's API is built with it.

### Faithfulness

A [RAGAS](#ragas) score from 0 to 1: what share of the claims in the reply are supported by
the retrieved passages? Low faithfulness means [hallucination](#hallucination).

### Generation

In [Langfuse](#langfuse), a [span](#span) that records one model call: model, tokens used
and outcome.

### Golden set

A fixed list of test questions with known correct answers. CodeBuddy's RAGAS golden set has
20 questions in `src/codebuddy/eval/golden/ragas.jsonl`.

### Groq and Whisper

Whisper is a speech-to-text model: it turns a voice recording into text. Groq is a company
that runs it fast. CodeBuddy uses it for voice input when `GROQ_API_KEY` is set.

### Hallucination

When an AI model states something that sounds right but is not true or not supported by
its sources.

### Hash

A short fingerprint computed from some data. The same data always gives the same hash, but
you cannot get the data back from it. CodeBuddy logs a hash of the session ID instead of the
ID itself.

### Hint ladder

The five levels of help, from 0 (where the problem is, plus a question) to 4 (the full
answer). The tutor climbs one level per hint but never past 3 on its own. See
[01, the hint ladder](01-how-the-tutor-works.md#the-hint-ladder).

### Hybrid search

Running two kinds of search at once, meaning search with [embeddings](#embedding) and word
search with [BM25](#bm25), then merging the results with [RRF](#rrf).

### Ingestion

Reading documents, cutting them into [chunks](#chunk), computing their
[embeddings](#embedding), and storing them in the knowledge base. Command:
`uv run python -m codebuddy.rag.ingest`.

### Intent

What the learner wants this turn: `debug_help`, `concept_question`, `problem_start`,
`show_answer`, or `off_topic`.

### LangChain

A Python library with building blocks for AI apps: model clients, prompts, vector stores.

### LangGraph

A library, built on [LangChain](#langchain), for writing an AI app as a graph of steps
(nodes). CodeBuddy's tutor graph is in `src/codebuddy/agent/graph.py`.

### Langfuse

A website for watching AI apps. It stores [traces](#trace) and draws charts. CodeBuddy
sends it metadata only.

### Leak guard

See [StreamGuard](#streamguard).

### LLM (model)

Large language model: an AI that reads text and writes text, such as OpenAI's GPT models.
In this guide "model" means an LLM unless it says otherwise.

### Localhost

The name of your own computer on a network. `http://localhost:8000` means "port 8000 on
this computer".

### Log

A text file where a program writes one line for each thing it does. CodeBuddy's logs are in
`logs/<YYYY-MM-DD>/`.

### loguru

The Python logging library CodeBuddy uses to write its logs.

### MCP

Model Context Protocol: a standard way for AI apps to call [tools](#tool) that run in a
separate program. CodeBuddy's tool server is `src/codebuddy/mcp_server/`; the API starts it
by itself.

### mem0 (long-term memory)

The library behind CodeBuddy's optional long-term memory: short private notes about a
learner kept across sessions. Off by default and opt-in per learner.

### Metadata

Data about data: names, times, counts, yes/no values. CodeBuddy's logs and traces hold
metadata only, never what the learner wrote.

### Mode

The kind of reply the [policy](#policy) chose: `hint`, `explain`, `reveal`, `redirect`,
`confirm`, or a quiz reply.

### Node

One step in a [LangGraph](#langgraph) graph, such as `classify` or `generate`.

### PCDIT

A five-step way to solve programming problems: **P**roblem definition, **C**oncrete cases,
**D**esign of algorithm, **I**mplementation, **T**esting. From the paper "Steps Before
Syntax" (arXiv:2109.08896). The UI's stage line shows the learner's current step.

### Policy

The plain Python function that decides what kind of help to give each turn,
`decide_mode()` in `src/codebuddy/pedagogy/policy.py`. It makes no AI call.

### Port

A numbered door on a computer that a server listens on. The API uses 8000 and the UI 8501
by default.

### Prompt

The text sent to a model: instructions plus the material it should use.

### Prompt version

A label (`CODEBUDDY_PROMPT_VERSION`, currently `p5`) that is part of every answer cache
key. Changing it after a prompt edit makes old cached answers stop matching.

### Pseudo-code

A plan written in plain words but laid out like code, for example "for each valid position:
add the item to the total". It shows the steps without being real Python.

### Qdrant

The search database that holds CodeBuddy's knowledge base. It can run as files on disk
(embedded, the default), as a server, or on Qdrant Cloud.

### RAG

Retrieval-augmented generation: first search a knowledge base for relevant passages
(retrieval), then ask a model to write an answer using them (generation). It keeps answers
tied to real course material.

### RAGAS

A library that scores RAG answers using a model as a judge. CodeBuddy uses four of its
scores: [faithfulness](#faithfulness), [answer relevancy](#answer-relevancy),
[context precision](#context-precision) and [context recall](#context-recall).

### Rate limit

A cap on how many requests one caller may send per minute. CodeBuddy's default is 30; over
it the API answers HTTP 429.

### Redis and Upstash

Redis is a fast database often used as a [cache](#cache). Upstash runs Redis for you on the
internet. CodeBuddy uses Upstash when its two variables are set, otherwise a cache inside
the API process.

### Reranker

A second step after search that re-orders the results by how well each one really matches
the question. CodeBuddy's default reranker keeps the order; an optional cross-encoder
reranker (`--extra rerank`) reads question and passage together to score them.

### RRF

Reciprocal rank fusion: a simple way to merge two ranked lists. Items near the top of
either list end up near the top of the merged list.

### Sandbox

A restricted place to run untrusted code. CodeBuddy's sandbox is a separate Python process
with a time limit, a memory limit and a short list of allowed modules. It is a safety net,
not a security boundary.

### Score

In [Langfuse](#langfuse), a number or yes/no value attached to a [trace](#trace), such as
`ttft_ms` or `degraded`. In [RAGAS](#ragas), a quality number from 0 to 1.

### Session

Everything the tutor remembers about one chat: hints given, stage, the last 6 messages.
Kept for 2 hours after the last turn. Each **New chat** is a new session.

### Socratic

Teaching by asking questions that lead the learner to the answer, instead of telling it.
Named after the philosopher Socrates.

### Span

In tracing, one bar on a [trace](#trace)'s timeline: one step, with a start and an end time.
Spans can contain other spans.

### SSE

Server-Sent Events: a simple way for a server to send a stream of small messages over one
HTTP connection. CodeBuddy streams each reply word by word this way.

### Static analysis

Checking code by reading it, without running it. CodeBuddy uses Python's `ast` parser to
find five common beginner bug patterns.

### Streaming

Sending a reply in small pieces as it is written, so the learner starts reading at once.

### StreamGuard

CodeBuddy's leak guard (`src/codebuddy/pedagogy/guard.py`). It sits between the model and
the learner and stops any line that looks like corrected code at hint levels 0 to 3.

### Streamlit

A Python library for building web pages. CodeBuddy's UI (`src/codebuddy/ui/app.py`) is
built with it.

### Tier

A class of model chosen by job: **fast** (small and quick), **standard** (mid-size), and
**heavy** (most capable). You set the model ID for each in `.env`.

### Token

A piece of a word that models read and write. In English one token is about 4 characters.
Models are billed and limited by tokens.

### Tool

A helper program the tutor can call, such as `trace_python`, which runs the learner's code
in the [sandbox](#sandbox). In CodeBuddy, rules choose tools, never the model.

### Trace

A timeline of one turn, made of [spans](#span), sent to [Langfuse](#langfuse).

### TTFT

Time to first token: how long until the first word of the reply appears. CodeBuddy's target
is under 1 second for 95% of turns.

### Turn

One learner message and the tutor's reply to it.

### uv

A fast tool that installs Python and a project's libraries. `uv sync` installs, `uv run`
runs a command inside the project.

### Uvicorn

The program that runs CodeBuddy's API server, for example
`uv run uvicorn codebuddy.api.app:app --port 8000`.

### Vector database

A database that stores [embeddings](#embedding) and finds the ones closest to a query.
[Qdrant](#qdrant) is one.

### WSL

Windows Subsystem for Linux: a way to run Linux inside Windows. The author develops
CodeBuddy on it.
