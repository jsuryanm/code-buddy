# Security notes

What protects the system today, what does not, and what to do before exposing it.

## API access

| Control | Setting | Behavior |
|---|---|---|
| API keys | `CODEBUDDY_API_KEYS` (comma-separated) | Every `/v1/*` route requires `Authorization: Bearer <key>` or `X-API-Key: <key>`. Comparison is constant-time against every configured key. `/healthz` stays open. Empty means open (localhost only) |
| Rate limit | `CODEBUDDY_RATE_LIMIT_PER_MINUTE` (default 30, 0 disables) | Fixed one-minute window per caller (API key, else client address). HTTP 429 with `Retry-After`. Counted in the cache, so it holds across workers when Upstash is configured |
| CORS | `CODEBUDDY_CORS_ORIGINS` | Off unless set. Only the listed origins, `GET` and `POST` |

Limits to know about: one shared key per caller group, no per-user accounts, no key rotation
tooling, and behind a reverse proxy the client address is the proxy's unless you handle
`X-Forwarded-For` yourself. The rate limit window is fixed, not sliding, so bursts at a window edge
can reach twice the limit.

## Learner data

- Session progress and the last six messages (500 characters each) live in the session cache for
  2 hours. With Upstash they are stored in your Upstash database; without it, in process memory.
- Learner code and messages go to OpenAI (chat) and, for voice, audio goes to Groq. Both are third
  parties; check their data terms for your learners (minors, institutions).
- Logs record a hash of the session ID, never the message or code, except the judge's reason text.
  The leak judge sends the learner's code and the reply to OpenAI when sampling is on.
- `/v1/metrics` exposes counters only.

### Long-term memory (opt-in)

Off unless `CODEBUDDY_MEMORY_ENABLED=true`, and then only for a learner who ticks the box. Details
in
[memory.md](memory.md). What to know:

- Stored: short notes about what the learner struggles with, one line per problem that ended in a
  reveal, and a summary of how they worked. Held on this server under `CODEBUDDY_MEMORY_PATH`
  (`data/memory`), unencrypted. Protect the folder and back it up like any personal data.
- Sent to OpenAI: the recent turns on each write (extraction and summary) and the learner's message
  on each recall (embedding). Check OpenAI's data terms, especially for minors.
- mem0 telemetry is disabled (`MEM0_TELEMETRY=False` is set before mem0 loads). Importing mem0 may
  still create a local `~/.mem0/` folder; nothing is sent.
- Identity is a signed learner token (HMAC keyed by `CODEBUDDY_MEMORY_SECRET` and bound to the
  caller's API key), not an account. The token travels in the page URL, so treat it like a
  password: browser history, bookmarks, and Referer headers can leak it. A link never enables
  memory by itself; the UI asks first ("Use this profile").
- A session belongs to the first learner who uses it with memory. Session IDs are client-chosen, so
  a hostile client can bind an ID that another learner later reuses and cause a 409 for them. It
  cannot read or write the other learner's notes: a bound session refuses turns without the
  matching token, and binding clears earlier history so it never reaches memory. The first bind
  is an atomic set-if-absent, so two concurrent first turns cannot both claim a session. The
  session status route (`GET /v1/session/{id}`) also needs the matching token once bound.
- With `CODEBUDDY_API_KEYS` empty a token is bound to no key, so anyone holding it can use it. Run
  memory without API keys only on localhost or in the demo.
- If `CODEBUDDY_MEMORY_SECRET` is empty the server warns and uses a random per-process secret, so
  tokens die on restart. Rotating the secret also strands the stored data. The setting is held as
  a secret value and does not appear in a `repr` of `Settings`.
- Recalled notes are untrusted data: they are placed in a `<memory>` block with `<memory>` tags
  stripped, and cannot change the hint level or bypass the leak guard.
- The list and forget routes take the token in header `X-Learner-Token`, never in the path, so
  it does not end up in access logs.
- Retention is manual: Forget me (`DELETE /v1/memory`) or delete `data/memory`. Forget deletes
  every item, however many, and reports the exact count.

## Prompt injection

Learner messages, code, retrieved text, and tool output are placed inside delimiters and the
prompts say to treat them as data. This reduces but does not eliminate injection risk. The
important defenses are structural: the model cannot choose tools or hint levels (rules do), the
leak guard checks output independent of the model, and the model has no write access to anything.

## Code execution

See [tools-and-approvals.md](tools-and-approvals.md#the-sandbox). In short: only after the
learner agrees, restricted by an allowlist and resource limits, offline where the host supports
`unshare -rn`, and not a hard boundary. Before a public launch:

1. Run the sandbox in a container with no network, a read-only filesystem, a small memory limit, and
   no secrets.
2. Or turn execution off: `CODEBUDDY_TOOLS_ENABLED=false` starts the API with no tool runner,
   so learner code is never run and no permission prompt appears. (`CODEBUDDY_MCP_ENABLED=false`
   only changes how tools are called, in-process instead of over MCP, and does not disable them.)
3. Keep the approval prompt. It is the human check for the one risky action.
4. For stronger isolation, plug a remote sandbox in behind `SandboxBackend`; none is included.
   See [tools-and-approvals.md](tools-and-approvals.md#stronger-isolation).

## Secrets

`.env` is gitignored and `.claude/settings.json` denies Claude Code reads of `.env*`. Keys:
`OPENAI_API_KEY`, `GROQ_API_KEY`, `UPSTASH_REDIS_REST_*`, `CODEBUDDY_API_KEYS`,
`CODEBUDDY_MEMORY_SECRET`. The ingest CLI and the API load `.env` into the process environment at
startup. The Docker image
contains no secrets; pass them at runtime. Rotate a key by changing the environment and restarting.

## Not done yet

TLS (use a proxy), per-user accounts and authorization, audit log of approvals beyond counters,
dependency and image scanning, a threat review of the MCP boundary beyond the in-process tool set.
