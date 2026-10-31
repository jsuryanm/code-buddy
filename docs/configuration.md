# Configuration

Settings load from environment variables and `.env` (`src/codebuddy/config.py`, pydantic-settings).
Variables with the `CODEBUDDY_` prefix map to the fields below, case-insensitive. A few
third-party variables are read directly by their libraries. The ingest CLI and the API start-up
also load `.env` into the process environment (`load_dotenv`), so those libraries find
`OPENAI_API_KEY`, `GROQ_API_KEY`, and the Upstash variables there too.

## Third-party variables (no prefix)

| Variable | Used by | Notes |
|---|---|---|
| `OPENAI_API_KEY` | `langchain-openai` chat and embeddings | Required for live use |
| `UPSTASH_REDIS_REST_URL` | `upstash-redis` | If both Upstash variables are set the API uses Upstash; otherwise an in-process cache and a warning |
| `UPSTASH_REDIS_REST_TOKEN` | `upstash-redis` | |
| `GROQ_API_KEY` | `groq` SDK | Enables voice input. Without it `/v1/stt` returns 503 and the UI hides the microphone |
| `CODEBUDDY_API_KEY` | Streamlit UI | Key sent to the API when the server requires one. Unset means no key. Environment only; the UI has no field for it |
| `MEM0_TELEMETRY` | `mem0` | Set to `False` by our code before mem0 is imported (`setdefault`), so mem0 sends no usage data. Set it yourself to `True` only if you want that |
| `CODEBUDDY_API_URL` | Streamlit UI | Default `http://localhost:8000`. Environment only; the UI has no field for it (prefix kept for consistency; read by the UI, not by `Settings`) |

## Settings (`CODEBUDDY_<NAME>`)

### Models

| Name | Default | Meaning |
|---|---|---|
| `MODEL_FAST` | none (required) | Classification and redirects. Small, low latency. Also the last fallback |
| `MODEL_STANDARD` | none (required) | Hints and explanations. Falls back to fast |
| `MODEL_HEAVY` | none (required) | Full-answer reveals. Falls back to standard |
| `EMBED_MODEL` | `text-embedding-3-small` | Embedding model for ingestion and queries. Changing it needs a new `INDEX_VERSION` and re-ingestion |

Fallback chain: heavy, then standard, then fast, then degraded mode (see
[architecture.md](architecture.md)). Timeouts and retries are set in `src/codebuddy/llm.py`.

### Versions (cache invalidation)

| Name | Default | Meaning |
|---|---|---|
| `INDEX_VERSION` | `v1` | Part of the Qdrant collection name (`cb_<corpus>_<version>`) and of answer and retrieval cache keys. Bump it after re-chunking or changing the embedding model |
| `PROMPT_VERSION` | `p5` | Part of answer cache keys. Bump it after editing prompts so old cached answers stop matching |

### Pedagogy

| Name | Default | Meaning |
|---|---|---|
| `LADDER_MAX_TURNS` | `6` | After this many hints on one problem the tutor offers the full answer. The 5-hint frustration signal fires first, so with the defaults the offer comes after 5 hints |
| `LADDER_MAX_SECONDS` | `600` | After this long on one problem the tutor offers the full answer |

| `MAX_TOKENS_HINT` | `250` | Output token cap for hint replies. Backstop for the word limits in the prompts |
| `MAX_TOKENS_EXPLAIN` | `320` | Output token cap for concept explanations |
| `MAX_TOKENS_REVEAL` | `900` | Output token cap for full answers (code plus the short why) |
| `MAX_TOKENS_REDIRECT` | `90` | Output token cap for off-topic redirects |

The caps apply per mode, on every tier including fallbacks. A reply that hits one is cut off, so
keep them above the prompt word limits. The cap is sent as `max_completion_tokens`, which on
reasoning models also counts the hidden reasoning tokens: a reasoning model can spend the whole cap
thinking and return no text. An empty reply is treated as a degraded reply (the course-material
fallback, `degraded: true`, the `degraded` counter). With reasoning models in a tier, raise the
`MAX_TOKENS_*` values, or use non-reasoning models for the tiers.

The tutor never reveals on its own; it offers, and the learner decides. See
[pedagogy-policy.md](pedagogy-policy.md).

### Vector store and retrieval

| Name | Default | Meaning |
|---|---|---|
| `QDRANT_PATH` | `data/index` | Embedded Qdrant storage and `manifest.json`. Single process only |
| `QDRANT_URL` | none | Use a Qdrant server instead (also creates payload indexes) |
| `RETRIEVE_K` | `30` | Candidates fetched from hybrid search |
| `RERANK_TOP` | `5` | Chunks kept after reranking and given to the model |
| `REFINE_TIMEOUT_S` | `0.5` | How long a turn waits for the second retrieval (the classifier's query). On timeout the first result is kept, `refine_timeouts` in `/v1/metrics` goes up, and the search finishes in the background so it still warms the L3 and L4 caches |
| `RELEVANCE_THRESHOLD` | `0.15` | A reply is "grounded" only if the best chunk scores at least this. Meaningful with a real reranker (scores 0 to 1). The no-op reranker scores 1.0, so any hit counts as grounded |
| `USE_CROSS_ENCODER` | `false` | Use the local cross-encoder reranker (needs `--extra rerank`; downloads `BAAI/bge-reranker-base`) |

### Speech-to-text

| Name | Default | Meaning |
|---|---|---|
| `STT_MODEL` | `whisper-large-v3-turbo` | Groq Whisper model |
| `STT_FALLBACK_MODEL` | none | OpenAI transcription model used if Groq fails. Off when unset; needs `OPENAI_API_KEY` |
| `STT_LANGUAGE` | `en` | Language hint (improves accuracy and speed) |
| `STT_MAX_BYTES` | 10000000 | Largest accepted upload (HTTP 413 above it) |

### Tools, sandbox, checkpoints

| Name | Default | Meaning |
|---|---|---|
| `TOOLS_ENABLED` | `true` | `false` turns tool use off, so learner code is never run |
| `MCP_ENABLED` | `true` | Call tools through the MCP stdio server; `false` calls them in-process |
| `SANDBOX_TIMEOUT_S` | `3.0` | Wall-clock limit for a run |
| `SANDBOX_MEMORY_MB` | `256` | Address-space limit for a run |
| `SANDBOX_BACKEND` | `local` | Which `SandboxBackend` runs traces. Only `local` is included; an unknown name raises `ValueError`. See [tools-and-approvals.md](tools-and-approvals.md#stronger-isolation) |
| `CHECKPOINT_PATH` | `data/checkpoints.sqlite` | SQLite file holding paused turns (grows; prune when needed) |

### API protection

| Name | Default | Meaning |
|---|---|---|
| `API_KEYS` | empty | Comma-separated keys. Empty leaves `/v1/*` open |
| `RATE_LIMIT_PER_MINUTE` | `30` | Per caller; `0` disables |
| `CORS_ORIGINS` | empty | Comma-separated allowed origins; empty disables CORS |

### Optional features (off by default)

| Name | Default | Meaning |
|---|---|---|
| `SEMANTIC_CACHE_THRESHOLD` | `0.0` | Cosine similarity needed for an L2 hit on concept questions. `0` is off. Tune on real questions first: "for loop" and "while loop" questions are close in embedding space, so a threshold that is too low serves the wrong answer. Costs one embedding call per uncached concept question |
| `SEMANTIC_CACHE_MAX` | `500` | Entries kept in the semantic index |
| `JUDGE_SAMPLE_RATE` | `0.0` | Share of hint replies re-checked by the fast model for leaks the rule guard cannot see. Runs after the reply is sent; results appear in `/v1/metrics` and the log |

### Learner memory (off by default)

| Name | Default | Meaning |
|---|---|---|
| `MEMORY_ENABLED` | `false` | Turn on opt-in long-term learner memory. Needs `OPENAI_API_KEY` and `MODEL_FAST`. See [memory.md](memory.md) |
| `MEMORY_PATH` | `data/memory` | Embedded Qdrant data and `history.db`. Single process only |
| `MEMORY_SECRET` | empty | Signs learner tokens. Empty: a random secret per process with a startup warning, so tokens stop working after a restart. Changing it invalidates every token. Held as a secret value, so a `repr` of `Settings` hides it |
| `MEMORY_RECALL_LIMIT` | `5` | Notes put into a prompt |
| `MEMORY_RECALL_TIMEOUT_S` | `0.6` | Recall is abandoned after this, and the turn goes on without notes |
| `MEMORY_WRITE_EVERY` | `4` | Write on every Nth hint (minimum 1); a reveal always writes |
| `MEMORY_EMBEDDING_DIMS` | `1536` | Vector size in the memory store. Must match `EMBED_MODEL`; changing it needs a new `MEMORY_PATH` |

### Cache TTLs (seconds)

| Name | Default | Layer |
|---|---|---|
| `TTL_ANSWER` | 86400 (1 day) | L1 concept answers |
| `TTL_EMBEDDING` | 2592000 (30 days) | L3 query embeddings |
| `TTL_RETRIEVAL` | 10800 (3 hours) | L4 retrieval results |
| `TTL_SESSION` | 7200 (2 hours) | L6 session progress and recent history |
| `TTL_LOCK` | 30 | Single-flight lock for identical concurrent misses |

## Where code reads configuration

| File | Reads |
|---|---|
| `config.py` | Defines `Settings`; `get_settings()` is cached for the process |
| `llm.py` | Model IDs, embedding model |
| `api/wiring.py` | Upstash variables, Qdrant, reranker choice, all TTLs |
| `agent/nodes.py` | Ladder caps, versions, `model_standard` (cache key), sandbox timeout |
| `api/app.py`, `api/security.py` | API keys, rate limit, CORS, STT limits, judge rate |
| `tools/functions.py` | Sandbox timeout, memory, and backend |
| `memory/mem0_store.py` | `MODEL_FAST`, `EMBED_MODEL`, and the `MEMORY_*` path and size settings |
| `agent/nodes.py` (memory) | `MEMORY_RECALL_LIMIT`, `MEMORY_RECALL_TIMEOUT_S`, `MEMORY_WRITE_EVERY` |
| `api/app.py` (memory) | `MEMORY_SECRET` |
| `rag/ingest.py` and `rag/store.py` | Qdrant location, index version |

## Hard-coded values worth knowing

| Where | Value | Why |
|---|---|---|
| `agent/nodes.py` | message 4000 chars, code 8000 chars | Input size caps |
| `agent/nodes.py` | 6 history entries, 500 chars each | Conversation memory sent to the model |
| `agent/nodes.py` | lock wait 1.5 s | How long a duplicate concurrent miss waits for the first to fill the cache |
| `rag/chunking.py` | 800 to 2000 characters per chunk | About 200 to 500 tokens at 4 characters per token |
| `llm.py` | timeouts 3 s fast, 5 s standard, 30 s heavy | So fallback fires before the latency budget is gone |
| `pedagogy/frustration.py` | 5 hints without progress, 2 repeated submissions | Frustration signals |
| `sandbox/check.py` | 4000 characters; imports `math`, `random`, `string` | Sandbox allowlist |
| `rag/query.py` | query 300 characters, 6 code names, RRF k=60 | Retrieval query size and fusion |
| `agent/deps.py` | 2 history entries, 200 characters each | Context the classifier sees to resolve "it" and "that" |
| `api/security.py` | 15 minutes | How long a paused turn can wait for approval |
