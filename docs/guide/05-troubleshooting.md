# Troubleshooting

Find your symptom in the left column. Each row says what is probably wrong and how to fix
it. This page covers running on your own computer.

## First, look at the log

Most problems explain themselves in the log. Every program prints the path of its log file
on its first line (`log=logs/<DATE>/<APP>_<TIME>.log`). Warnings and errors, with full
details, are in the file next to it that ends in `.errors.log`.

A failed start ends with a line like `... failed: <ErrorType>. Hint: <WHAT TO DO>`. Read
the hint first. More on logs:
[04-logs-tracing-and-evaluation.md](04-logs-tracing-and-evaluation.md#1-logs-what-the-program-wrote-down).

To check the API from a terminal:

```bash
curl localhost:8000/healthz
```

## Starting up

| Symptom | Cause | Fix |
|---|---|---|
| `RuntimeError: Set model IDs in the environment: ...` when the API starts | One of `CODEBUDDY_MODEL_FAST`, `_STANDARD`, `_HEAVY` is empty | Set all three in `.env` (see [02](02-run-it-on-your-computer.md#4-real-mode-the-env-file)) |
| Hint `OPENAI_API_KEY is not set: add it to .env` | No OpenAI key | Add `OPENAI_API_KEY=<YOUR_KEY>` to `.env` in the project folder |
| `uv: command not found` | uv is not installed, or the terminal was opened before installing it | Install uv, then open a new terminal |
| First start is slow | The word-search model `Qdrant/bm25` is downloaded once | Wait; later starts are fast |
| Hint `check UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN in .env` | Wrong Upstash address or token | Copy both again from the Upstash console, or remove both to use the in-memory cache |
| `/healthz` shows `"cache": "memory"` | Upstash variables are missing | Fine for trying it out. Sessions are lost when the API restarts. Set both Upstash variables to keep them |
| Port already in use | Another program (often an old API) uses port 8000 or 8501 | Stop the old program with `Ctrl+C` in its terminal, or pick another port, for example `--port 8001`, and set `CODEBUDDY_API_URL=http://localhost:8001` before starting the UI |

## The UI cannot talk to the API

| Symptom | Cause | Fix |
|---|---|---|
| Sidebar says "Can't reach the tutor", or the page says "Can't reach the tutor. Check that it is running." | The API is not running, or the UI looks at the wrong address | Start the API first (terminal 1). If it runs on another address or port, set `CODEBUDDY_API_URL` before starting Streamlit |
| "The tutor needs an API key. Set CODEBUDDY_API_KEY and restart the page." (HTTP 401, `Missing or invalid API key`) | The server has `CODEBUDDY_API_KEYS` set, and the UI sent no key or a wrong one | Set `CODEBUDDY_API_KEY` to one of the server's keys in the UI's environment, then restart Streamlit |
| "Your saved profile is no longer valid. Turn memory off and on again." (HTTP 403, `Invalid learner token`) | The learner token was made with another `CODEBUDDY_MEMORY_SECRET`, another API key, or before a restart with no secret set | Untick and tick **Remember me across sessions** to get a new token. Set `CODEBUDDY_MEMORY_SECRET` so tokens survive restarts |
| "This chat belongs to another memory setting, so a new chat was started." (HTTP 409, `This session belongs to another learner`) | The chat's session was first used with memory by another learner, or memory was switched off in the middle | Nothing to do: the UI already opened a new chat. Send the message again |
| "Too many requests. Wait a minute and try again." (HTTP 429) | The rate limit was hit (default 30 per minute per caller) | Wait for the number of seconds in the `Retry-After` header, or raise `CODEBUDDY_RATE_LIMIT_PER_MINUTE` (`0` turns it off) |
| "That request expired. Send your message again." after **Run my code** | The paused turn is older than 15 minutes, or was already answered | Send the message again |
| "Something went wrong. Please try again." | Any other error | Check the API's `.errors.log` |

## Replies

| Symptom | Cause | Fix |
|---|---|---|
| The model returned an empty reply (log: `generate tier=... -> empty`, then `empty model reply (mode=..., tier=...)`) | The model used its whole token budget, often on hidden "reasoning" | Usually nothing: the tutor already retried once on the same tier with 4 times the cap (at most 4000 tokens), then moved to the next lighter tier (heavy, then standard, then fast). If it keeps happening, pick a non-reasoning model for that tier, raise `CODEBUDDY_MAX_TOKENS_*`, or lower `CODEBUDDY_REASONING_EFFORT` |
| Log: `model call failed (mode=..., tier=...): <ErrorType>` | Bad key, wrong model ID, no internet, or a timeout (3 s fast, 5 s standard, 30 s heavy) | Check the key and model IDs. The tutor falls back to the next lighter tier by itself |
| "The tutor had trouble answering. Try again in a moment." or a reply that only quotes the course notes | Every tier failed, so the reply is **degraded** (written by code) | Look for `model call failed` lines in the log for the cause. A degraded turn does not count as a hint |
| Replies cite nothing or say the context is missing | The knowledge base is empty | Ingest documents (see [02](02-run-it-on-your-computer.md#6-add-documents-ingestion)) and check `data/index/manifest.json` exists and lists them |
| A reply ends early, mid-sentence | It hit the token cap for its mode | Raise the matching `CODEBUDDY_MAX_TOKENS_*` setting |
| A hint stops and a different question is added | The leak guard caught corrected code and replaced the rest with a safe question | Working as designed. The log says `stopped by the leak guard` |
| The tutor never asks to run my code | Tools are off (`CODEBUDDY_TOOLS_ENABLED=false`), the code has a syntax error, you chose "remember" earlier in this chat, or the message was a concept question | Check each. A new chat asks again |

## The knowledge base (Qdrant)

| Symptom | Cause | Fix |
|---|---|---|
| Hint `the Qdrant folder is locked: stop the API (or the other process) first` | The embedded knowledge base in `data/index/` can be opened by one program at a time. Usually the API is running while you ingest | Stop the API, run ingestion, start the API again. Or use a Qdrant server (`CODEBUDDY_QDRANT_URL`) |
| `Could not reach Qdrant at <HOST>` | The Qdrant server or Qdrant Cloud address is wrong or down | Check `QDRANT_CLUSTER_ENDPOINT` (or `CODEBUDDY_QDRANT_URL`) and `QDRANT_API_KEY`. Remove them to go back to the embedded folder |
| Server works but replies cite nothing | The server has no collections with your prefix yet | Run ingestion again with the same settings: it writes to the server |
| `PDF ingestion needs the extra: uv sync --extra pdf` | The `pdf` extra is not installed | `uv sync --extra ui --extra pdf` |
| Segfault during PDF ingestion on WSL | PyTorch crashes while looking for a GPU | Start the command with an empty `CUDA_VISIBLE_DEVICES=`, for example `CUDA_VISIBLE_DEVICES= uv run python -m codebuddy.rag.ingest ...` |
| `<FILE>: unchanged, skipped` | The file was already ingested into this same target (local folder or cluster) and has not changed | Nothing to do, or add `--force` to ingest it again anyway |

## Voice

| Symptom | Cause | Fix |
|---|---|---|
| No microphone in the message box, or "Voice input is off on this server." | The server has no speech provider | Set `GROQ_API_KEY` in `.env` and restart the API. `/healthz` then shows `"stt_configured": true` |
| The microphone does nothing | The browser blocked microphone access | Allow the microphone for the page in the browser's site settings. Browsers allow it on `localhost`; on other addresses they usually require HTTPS |
| "That recording is too long." | Over the size limit (10 MB, `CODEBUDDY_STT_MAX_BYTES`) | Record a shorter question |
| "Couldn't understand the recording." | Groq (and the fallback, if set) failed | Type the question instead. The API log has the cause |

## Memory

| Symptom | Cause | Fix |
|---|---|---|
| No **Remember me** box in Settings, or "Memory is turned off on the server." | Memory is off on the server | Set `CODEBUDDY_MEMORY_ENABLED=true` and restart |
| `/healthz` shows `"memory_enabled": false` after turning it on | The memory store failed to start, often because `data/memory/` is locked by another process or `CODEBUDDY_MODEL_FAST` is missing | Read the API log. The API runs without memory meanwhile |

## Logs, tracing and evaluation

| Symptom | Cause | Fix |
|---|---|---|
| A warning that the log folder cannot be created, and no files in `logs/` | No permission to write there, or a file called `logs` is in the way | Fix the folder's permissions, or set `CODEBUDDY_LOG_DIR` to a folder you can write. The app keeps running and logs to the terminal |
| Old log files disappear | Files older than 5 days are deleted at start | Raise `CODEBUDDY_LOG_RETENTION_DAYS` |
| No traces in Langfuse | Tracing is off: a key is missing, the `trace` extra is not installed, `CODEBUDDY_TRACING_ENABLED=false`, or you are using the demo (which never traces) | Read the API's start lines: one line says why tracing is off. `/healthz` shows `"tracing_enabled"`. Install with `uv sync --extra ui --extra trace` |
| Traces appear late | They are sent in batches in the background | Wait a few seconds. They are also flushed when the API stops |
| Traces in the wrong Langfuse project or none at all | `LANGFUSE_BASE_URL` points to the other region | Use `https://cloud.langfuse.com` (EU) or `https://us.cloud.langfuse.com` (US), matching your project |
| `ragas_run: ragas is not installed in this Python: build the evals environment with evals/setup.sh` | You ran the RAGAS runner with `uv run`; ragas only lives in `.venv-evals/` | Run `bash evals/setup.sh` once, then use `.venv-evals/bin/python -m codebuddy.eval.ragas_run ...` |
| `ragas_run: OPENAI_API_KEY is not set` or `Set model IDs in the environment` | The runner needs your key and all three model IDs | Add them to `.env` |
| Offline evaluation prints `FAIL` | A pedagogy rule or the leak guard changed behavior | Read which metric failed. Run `uv run pytest -q` to find the broken rule |

## Still stuck?

- The reference troubleshooting table: [../setup.md](../setup.md#troubleshooting).
- Every setting: [../configuration.md](../configuration.md).
- Words you do not know: [06-glossary.md](06-glossary.md).
