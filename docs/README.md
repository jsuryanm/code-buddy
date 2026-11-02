# CodeBuddy documentation

CodeBuddy is a RAG-based programming tutor. It guides beginners through the PCDIT process
(Problem definition, Concrete cases, Design of algorithm, Implementation, Testing) with
Socratic hints instead of handing out answers, and always lets them reach the full answer.

## Beginner guide

New to AI apps, RAG, servers or Python projects? Start with the guide in [guide/](guide/README.md).
It explains everything in plain words, in reading order:

| Page | Read it to |
|---|---|
| [guide/README.md](guide/README.md) | Start here: what CodeBuddy is, the 5-minute picture, where to go next |
| [guide/01-how-the-tutor-works.md](guide/01-how-the-tutor-works.md) | Follow one learner turn step by step: hints, Show answer, quiz, memory, caches, models |
| [guide/02-run-it-on-your-computer.md](guide/02-run-it-on-your-computer.md) | Install, try the keyless demo, set up `.env`, ingest documents, tour the UI |
| [guide/04-logs-tracing-and-evaluation.md](guide/04-logs-tracing-and-evaluation.md) | Read logs, trace turns in Langfuse, score answers with RAGAS |
| [guide/05-troubleshooting.md](guide/05-troubleshooting.md) | Match a symptom to its cause and fix |
| [guide/06-glossary.md](guide/06-glossary.md) | Look up any technical word |

The rest of this folder is the reference manual:

| Document | Read it to |
|---|---|
| [setup.md](setup.md) | Install, configure, ingest documents, and run the API and UI |
| [configuration.md](configuration.md) | Look up every environment variable and setting |
| [architecture.md](architecture.md) | Understand the code: modules, request flow, graph, caching |
| [api.md](api.md) | Call the HTTP API and parse the streaming events |
| [pedagogy-policy.md](pedagogy-policy.md) | See exactly how hints, escalation, and the leak guard behave |
| [rag-and-ingestion.md](rag-and-ingestion.md) | Add documents, understand chunking, metadata, and corpora |
| [ui.md](ui.md) | Use and extend the Streamlit front end, including voice and approvals |
| [tools-and-approvals.md](tools-and-approvals.md) | Understand the MCP tools, the code sandbox, and the permission prompt |
| [memory.md](memory.md) | Learn what long-term learner memory stores, its opt-in and privacy limits, and how to enable it |
| [observability.md](observability.md) | Find and read the logs: one turn line by line, layout, retention, privacy |
| [security.md](security.md) | Know what is protected, what is not, and what to do before going public |
| [testing.md](testing.md) | Run tests and the offline eval, and write new tests |
| [evaluation.md](evaluation.md) | Score real RAG answers with RAGAS on a golden set and read the runs in Langfuse |
| [corpus-manifest.md](corpus-manifest.md) | Track source documents and their licences |
| [adr/](adr/) | Read why key decisions were made |

The product specification is [../PROJECT_SPEC.md](../PROJECT_SPEC.md). It describes the full
target design. These docs describe what is built today (slice 1) and say where the two differ.

## Status

Built and tested offline (482 tests, offline eval passing):

- Pedagogy policy, hint ladder, streaming leak guard, optional sampled LLM judge
- Static analysis of learner Python (five bug patterns)
- Cache layers L1 (answers), optional L2 (semantic), L3 (embeddings), L4 (retrieval), L6 (session)
  on Upstash Redis or memory
- RAG ingestion and hybrid retrieval on Qdrant; code-aware queries and fusion with the classifier's standalone query
- LangGraph tutor agent with durable checkpoints, FastAPI streaming API, Streamlit UI
- Voice input: Groq Whisper (optional OpenAI fallback) behind `/v1/stt`, voice recording in the chat
  input with an editable transcript
- MCP tool server (analysis, concrete-case suggestions, sandboxed tracing) and a learner approval
  step before any code runs
- Opt-in long-term learner memory on mem0 (semantic, episodic, procedural notes), signed learner
  tokens, "Forget me" ([memory.md](memory.md))
- A `SandboxBackend` seam for code execution (only the local backend is included)
- API keys, rate limiting, CORS, counters at `/v1/metrics`
- Offline evals
- Plain-language logs with loguru in `logs/YYYY-MM-DD/`, metadata only ([observability.md](observability.md))
- Optional Langfuse traces per turn with scores (TTFT, total time, cache hit, guarded, degraded,
  quiz), metadata only (`--extra trace`, [observability.md](observability.md#langfuse-tracing))
- A manual RAGAS runner on a 20-item golden set (faithfulness, answer relevancy, context precision
  and recall), reported to a JSON file and Langfuse; tested with fakes only, not run live
  ([evaluation.md](evaluation.md))

Not built yet: instructor features (corpus approval queue, learner reports), per-user accounts
(memory uses bearer-like learner tokens instead), Langfuse dashboards and alerts, a hard sandbox boundary (needs
a container or a remote sandbox adapter), LLM-written synthetic questions for ingestion,
solved tracking across sessions and concept mastery for the learner model
(fix detection within a session is built; see [pedagogy-policy.md](pedagogy-policy.md)).

Run once for real: PDF ingestion with Docling and OpenAI embeddings, on the two PDFs in the
corpus manifest.

Not yet exercised against real services: OpenAI chat replies, mem0 memory extraction, Groq Whisper,
Upstash Redis, the cross-encoder reranker, and the Qdrant server mode. The code
follows each library's documentation and is covered by fakes and, for MCP and the sandbox, by real
subprocesses, but treat the first live run as a test.
