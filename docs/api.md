# HTTP API

Base URL `http://localhost:8000`. The app is `codebuddy.api.app:app` (`api/app.py`). Interactive
OpenAPI docs are served at `/docs`.

## Endpoints

| Method and path | Purpose |
|---|---|
| `GET /healthz` | Status, cache type, whether models and speech are configured, tool mode (`mcp`, `local`, `off`), sandbox network isolation, whether a key is required. Always open |
| `POST /v1/turn` | Send a learner message (optionally with code). Streams the reply as SSE |
| `POST /v1/show-answer` | Learner asks for the full answer. Streams a reveal as SSE |
| `POST /v1/approve` | Answer a permission request raised by a turn. Streams the rest of that turn |
| `POST /v1/stt` | Upload recorded audio (multipart field `audio`); returns `{"text", "provider"}` |
| `GET /v1/session/{id}` | `{"stage", "hints_given", "reveals", "can_show_answer", "run_permission"}` |
| `GET /v1/metrics` | Counters: turns, cache hits, guard stops, degraded replies, approvals, STT use, judge results, rate-limited requests |

When `CODEBUDDY_API_KEYS` is set every `/v1/*` route needs `Authorization: Bearer <key>` or
`X-API-Key: <key>` (HTTP 401 otherwise). Requests over `CODEBUDDY_RATE_LIMIT_PER_MINUTE` get
HTTP 429 with a `Retry-After` header. See [security.md](security.md).

### `POST /v1/turn`

```json
{
  "session_id": "any stable string for one learner and problem session",
  "message": "my sum crashes with an IndexError",
  "code": "nums = [1, 2, 3]\n...",
  "language": "python"
}
```

`code` is optional. An empty or blank `message` returns HTTP 422. The session ID is a client
choice; sessions expire after 2 hours without activity (`TTL_SESSION`).

### `POST /v1/approve`

```json
{ "session_id": "same id", "turn_id": "from the approval event", "approve": true, "remember": true }
```

Resumes a turn that paused to ask whether the tutor may run the learner's code. `remember: true`
keeps the answer for the rest of the session. HTTP 404 if the turn is unknown, already answered,
expired (15 minutes), or belongs to another session. The response is a normal event stream (`meta`,
`token`, `done`).

### `POST /v1/stt`

Multipart upload, field name `audio`, content type `audio/*` (browsers record `audio/wav` or
`audio/webm`). Errors: 413 over `STT_MAX_BYTES`, 415 wrong type, 422 empty, 502 every provider
failed, 503 no provider configured. The text has spoken symbols fixed ("i plus plus" becomes `i++`).

### `POST /v1/show-answer`

```json
{ "session_id": "same id", "code": "optional current code", "language": "python" }
```

Equivalent to sending the message "Show me the full answer." The policy always honors it, even
on the first turn, and resets the hint ladder afterwards.

## Streaming response

Content type `text/event-stream`. Each event has an `event:` name and one JSON `data:` line.

| Event | When | Data |
|---|---|---|
| `meta` | Once, before the first token | `mode` (`hint`, `explain`, `reveal`, `redirect`), `level` (0 to 4 or null), `stage` (P, C, D, I, T), `can_show_answer`, `offer_answer`, `cached` |
| `token` | Many | `{"text": "..."}` text already approved by the leak guard |
| `approval` | When the tutor needs permission to run the learner's code (no tokens come before it) | `turn_id`, `tool`, `message`, `code` (preview) |
| `done` | Once, last | `turn_id`, `awaiting_approval`, `citations[]`, `degraded`, `guarded`, `cache_hit`, `stage`, `hints_given`, `ttft_ms`, `total_ms` |
| `error` | On an unexpected failure | `{"message": "..."}` |

`ttft_ms` is the time from receiving the request to the first `token` event, the number the
spec's "under one second" target applies to. It is also logged by the `codebuddy.api` logger.
Each citation is `{"source", "section", "corpus"}`; the order matches the `[1]`, `[2]` markers the
model uses in its text.

### Example

```bash
curl -N -X POST localhost:8000/v1/turn \
  -H 'content-type: application/json' \
  -d '{"session_id":"demo","message":"my sum crashes","code":"nums=[1,2,3]\ntotal=0\nfor i in range(len(nums)+1):\n    total += nums[i]\n"}'
```

```
event: meta
data: {"type": "meta", "mode": "hint", "level": 0, "stage": "T", "can_show_answer": false, "offer_answer": false, "cached": false}

event: token
data: {"text": "What "}
...
event: done
data: {"citations": [...], "degraded": false, "guarded": false, "cache_hit": false, "stage": "T", "hints_given": 1, "ttft_ms": 412, "total_ms": 1630}
```

(`ttft_ms` above is illustrative; real values depend on the model.)

## Reading the stream in Python

`codebuddy.ui.client.parse_sse()` parses the stream, and `TutorClient` wraps the endpoints:

```python
from codebuddy.ui.client import TutorClient

client = TutorClient("http://localhost:8000")
for event, data in client.stream_turn("demo", "why is my loop wrong?", code):
    if event == "token":
        print(data["text"], end="")
```

## Notes

- Authentication and rate limits are opt-in (above). With no keys configured the API is open;
  keep it on localhost.
- CORS is off unless `CODEBUDDY_CORS_ORIGINS` is set. The Streamlit UI calls the API server-side,
  so it does not need it.
- Run a single worker (`uvicorn ... --port 8000`) while using embedded Qdrant.
