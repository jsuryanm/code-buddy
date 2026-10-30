# CodeBuddy documentation

CodeBuddy is a RAG-based programming tutor. It guides beginners through the PCDIT process
(Problem definition, Concrete cases, Design of algorithm, Implementation, Testing) with
Socratic hints instead of handing out answers, and always lets them reach the full answer.

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
| [security.md](security.md) | Know what is protected, what is not, and what to do before going public |
| [deployment.md](deployment.md) | Containerize and run it (Dockerfile, compose, CI; untested) |
| [testing.md](testing.md) | Run tests and the offline eval, and write new tests |
| [corpus-manifest.md](corpus-manifest.md) | Track source documents and their licences |
| [adr/](adr/) | Read why key decisions were made |

The product specification is [../PROJECT_SPEC.md](../PROJECT_SPEC.md). It describes the full
target design. These docs describe what is built today (slice 1) and say where the two differ.

## Status

Built and tested offline (155 tests, offline eval passing):

- Pedagogy policy, hint ladder, streaming leak guard, optional sampled LLM judge
- Static analysis of learner Python (five bug patterns)
- Cache layers L1 (answers), optional L2 (semantic), L3 (embeddings), L4 (retrieval), L6 (session) on Upstash Redis or memory
- RAG ingestion and hybrid retrieval on Qdrant; query rewriting for short follow-ups
- LangGraph tutor agent with durable checkpoints, FastAPI streaming API, Streamlit UI
- Voice input: Groq Whisper (optional OpenAI fallback) behind `/v1/stt`, microphone widget with an editable transcript
- MCP tool server (analysis, concrete-case suggestions, sandboxed tracing) and a learner approval step before any code runs
- API keys, rate limiting, CORS, counters at `/v1/metrics`
- Dockerfile, compose file, and CI workflow (written, not run)
- Offline evals

Not built yet: instructor features (corpus approval queue, learner reports), per-user accounts,
Langfuse tracing, a hard sandbox boundary (needs a container), LLM-written synthetic questions
for ingestion, deployment automation.

Not yet exercised against real services (no API keys were available during development):
OpenAI chat and embeddings, Groq Whisper, Upstash Redis, PDF parsing with Docling, the
cross-encoder reranker, the Qdrant server mode, and the Docker files. The code follows each
library's documentation and is covered by fakes and, for MCP and the sandbox, by real
subprocesses, but treat the first live run as a test.
