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

## Prompt injection

Learner messages, code, retrieved text, and tool output are placed inside delimiters and the
prompts say to treat them as data. This reduces but does not eliminate injection risk. The
important defenses are structural: the model cannot choose tools or hint levels (rules do), the
leak guard checks output independent of the model, and the model has no write access to anything.

## Code execution

See [tools-and-approvals.md](tools-and-approvals.md#the-sandbox). In short: only after the
learner agrees, restricted by an allowlist and resource limits, offline where the host supports
`unshare -rn`, and not a hard boundary. Before a public launch:

1. Run the sandbox in a container with no network, a read-only filesystem, a small memory limit, and no secrets.
2. Or turn execution off: `CODEBUDDY_TOOLS_ENABLED=false` starts the API with no tool runner,
   so learner code is never run and no permission prompt appears. (`CODEBUDDY_MCP_ENABLED=false`
   only changes how tools are called, in-process instead of over MCP, and does not disable them.)
3. Keep the approval prompt. It is the human check for the one risky action.

## Secrets

`.env` is gitignored and `.claude/settings.json` denies Claude Code reads of `.env*`. Keys:
`OPENAI_API_KEY`, `GROQ_API_KEY`, `UPSTASH_REDIS_REST_*`, `CODEBUDDY_API_KEYS`. The Docker image
contains no secrets; pass them at runtime. Rotate a key by changing the environment and restarting.

## Not done yet

TLS (use a proxy), per-user accounts and authorization, audit log of approvals beyond counters,
dependency and image scanning, a threat review of the MCP boundary beyond the in-process tool set.
