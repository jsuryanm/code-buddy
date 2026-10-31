# HTTP API

Base URL `http://localhost:8000`. The app is `codebuddy.api.app:app` (`api/app.py`). Interactive
OpenAPI docs are served at `/docs`.

## Endpoints

| Method and path | Purpose |
|---|---|
| `GET /healthz` | Status, cache type, whether models and speech are configured, tool mode (`mcp`, `local`, `off`), sandbox network isolation, `memory_enabled`, whether a key is required. Always open |
| `POST /v1/turn` | Send a learner message (optionally with code). Streams the reply as SSE |
| `POST /v1/show-answer` | Learner asks for the full answer. Streams a reveal as SSE |
| `POST /v1/quiz` | Start a five-question quiz on the bug the learner just fixed. Streams question 1 as SSE; no model call |
| `POST /v1/approve` | Answer a permission request raised by a turn. Streams the rest of that turn |
| `POST /v1/stt` | Upload recorded audio (multipart field `audio`); returns `{"text", "provider"}` |
| `GET /v1/session/{id}` | `{"stage", "hints_given", "reveals", "can_show_answer", "run_permission"}`. With memory on and the session bound to a learner, send that learner's token in header `X-Learner-Token`: missing or another learner's token is 409, an invalid one 403. A malformed `X-Learner-Token` header returns 422 |
| `POST /v1/memory/learners` | Mint a signed learner token for opt-in memory. Returns `{"learner_token"}`. 503 when memory is off |
| `GET /v1/memory` | List what is remembered for the learner in header `X-Learner-Token`: `{"items": [{"kind", "text", "created_at"}]}` |
| `DELETE /v1/memory` | Forget everything for the learner in header `X-Learner-Token`: `{"deleted": n}` |
| `GET /v1/metrics` | Counters: turns, cache hits, guard stops, degraded replies, approvals, STT use, judge results, rate-limited requests, memory recalls, writes, and failures, second-retrieval timeouts, and empty model replies (`empty_replies`) |

When `CODEBUDDY_API_KEYS` is set every `/v1/*` route needs `Authorization: Bearer <key>` or
`X-API-Key: <key>` (HTTP 401 otherwise). Requests over `CODEBUDDY_RATE_LIMIT_PER_MINUTE` get
HTTP 429 with a `Retry-After` header. See [security.md](security.md).

### `POST /v1/turn`

```json
{
  "session_id": "any stable string for one learner and problem session",
  "message": "my sum crashes with an IndexError",
  "code": "nums = [1, 2, 3]\n...",
  "language": "python",
  "learner_id": "optional learner token from POST /v1/memory/learners",
  "action": null
}
```

`code` is optional. `action` is optional: `"skip"` or `"stop"` while a quiz runs (the UI's Skip
question and Stop quiz buttons send it), so the button's text is never read as an answer. Any other
value returns 422. An empty or blank `message` returns HTTP 422. The session ID is a client
choice; sessions expire after 2 hours without activity (`TTL_SESSION`).

`learner_id` is the signed token, not a raw ID. Send it only for a learner who opted in to memory.
It is checked before the stream starts and ignored when memory is off. A malformed token returns
422; a well-formed token that is not valid for this server, secret, and API key returns 403
(`Invalid learner token`); a session already bound to a different learner, or a request without
`learner_id` on a bound session, returns 409 (`This session belongs to another learner`).
`POST /v1/show-answer` and `POST /v1/quiz` take the same field and errors.

### `POST /v1/approve`

```json
{ "session_id": "same id", "turn_id": "from the approval event", "approve": true, "remember": true }
```

Resumes a turn that paused to ask whether the tutor may run the learner's code. `remember: true`
keeps the answer for the rest of the session. HTTP 404 if the turn is unknown, already answered,
expired (15 minutes), or belongs to another session. The response is a normal event stream (`meta`,
`token`, `done`).

### Learner memory

```bash
curl -X POST localhost:8000/v1/memory/learners          # {"learner_token": "<id>.<signature>"}
curl -H "X-Learner-Token: <token>" localhost:8000/v1/memory             # list
curl -X DELETE -H "X-Learner-Token: <token>" localhost:8000/v1/memory   # forget
```

The token goes in a header, not the path, so it stays out of access logs. A missing or malformed
`X-Learner-Token` returns 422. `DELETE /v1/memory` returns 503 (`Could not forget right now;
please try again`) when the cache cannot record the forget marker; nothing is deleted then.

All three need the API key when keys are on, and the token is bound to the key that minted it.
The three routes return 503 when `CODEBUDDY_MEMORY_ENABLED` is off or the store failed to start,
and 403 for an invalid token (checked before the store is touched). See [memory.md](memory.md).

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

### `POST /v1/quiz`

```json
{ "session_id": "same id", "learner_id": "optional learner token" }
```

Available after a turn whose `meta` had `offer_quiz: true` (the tutor saw the learner fix a bug).
The offer stays on later replies until the quiz starts, a new problem begins, or new buggy code
arrives. While a quiz runs, this sends the current question again instead of starting over.
Starts five questions on that bug, two easy, two medium, one hard, from a hand-checked bank, and
streams question 1: a `meta` with `mode: "quiz"`, `quiz` and `quiz_code`, the question text as
`token` events (the buggy snippet in a python fence, then "Find the bug, fix it in the code box,
and send it."), and `done`. No model is called. HTTP 404 (`Nothing to quiz on yet: fix a bug
first`) before any fix (not 409, which means the session belongs to another learner); the API key, rate limit, and learner binding apply as for a turn.

Answers are ordinary `POST /v1/turn` calls with the fixed code in `code`. A correct answer streams
"Correct." and the next question in the same reply. Code sent back unchanged gets a short nudge
("Edit the code in the box to fix the bug, then send it."), or one level-0 hint when the message is
a question, and costs no try. Code that is no longer the question's code (deleted, replaced, its
functions dropped) gets "That looks like different code. Fix the bug in the question's code and
send it." and costs no try. A first wrong try gets one level-0 hint (a degraded hint does not use
up the try); a second wrong try, `action: "skip"`, or a message that is only "skip" shows the stored
solution and moves on; `action: "stop"` or a message that is only "stop quiz" ends it. After
question 5 the reply is a summary such as "you got 4 of 5". See
[pedagogy-policy.md](pedagogy-policy.md#quiz-after-a-fix).

Known limits, unchanged for now: two requests on one session at the same time are not serialized
(no session lock), so the last save wins; and a turn resumed through `/v1/approve` continues from
the session snapshot taken when it paused, so a quiz started in between can be overwritten.

## Streaming response

Content type `text/event-stream`. Each event has an `event:` name and one JSON `data:` line.

| Event | When | Data |
|---|---|---|
| `meta` | Once, before the first token | `mode` (`hint`, `explain`, `reveal`, `redirect`, `confirm`, `quiz`), `level` (0 to 4 or null), `stage` (P, C, D, I, T), `can_show_answer`, `offer_answer`, `offer_quiz`, `quiz_concept`, `quiz`, `quiz_code`, `cached` |
| `step` | Many, before the first token (parallel steps can interleave) | `key`, `label`, `status` (`running` or `done`), `detail` (or null). Progress text for the learner; never contains bug names, errors, findings, or code |
| `token` | Many | `{"text": "..."}` text already approved by the leak guard |
| `approval` | When the tutor needs permission to run the learner's code (no tokens come before it) | `turn_id`, `tool`, `message`, `code` (preview) |
| `done` | Once, last | `turn_id`, `awaiting_approval`, `citations[]`, `degraded`, `guarded`, `cache_hit`, `stage`, `hints_given`, `ttft_ms`, `total_ms` |
| `error` | On an unexpected failure | `{"message": "..."}` |

The UI labels a hint "Hint N" where N is `level + 1`, so level 0 shows as "Hint 1".

`confirm` means the tutor saw the learner fix their bug, or acknowledges the learner's explanation
of that fix on a later turn; it comes with `offer_quiz: true` and
`quiz_concept`, the concept name of the fixed bug (for example "loop bounds", never an internal
pattern id). `quiz` mode is a reply written by code: a quiz question, a grade with the next
question, a shown solution, a summary, or "Quiz stopped". While a quiz runs, `quiz` is
`{"index", "total": 5, "difficulty", "score"}` for the question now on screen (`index` counts from
0, so the UI shows `index + 1`), and `can_show_answer` is false; otherwise `quiz` is null. A quiz
hint is `mode: "hint"`, `level: 0` with `quiz` set. `quiz_code` is the snippet of a new question,
for the code box, and null on every other reply. After a
declined approval the resumed `/v1/approve` stream has no `run_tools` step; it goes straight to
`generate`.

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
data: {"type": "meta", "mode": "hint", "level": 0, "stage": "T", "can_show_answer": false, "offer_answer": false, "offer_quiz": false, "quiz_concept": null, "quiz": null, "quiz_code": null, "cached": false}

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
