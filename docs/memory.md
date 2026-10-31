# Learner memory

Code: `src/codebuddy/memory/`. Decision record: [ADR 0008](adr/0008-mem0-learner-memory.md).

Optional, off by default, and opt-in per learner. When on, the tutor keeps short private notes
about one learner across sessions and uses them only to pick a better question. The notes never
change which hint level or mode the policy picks.

## What is stored

| Kind | What it holds | How it is produced |
|---|---|---|
| Semantic | Facts about the learner, for example "confuses `=` with `==`" or "prefers short examples" | `mem0` reads the recent turns (`SessionProgress.history`, up to 6 entries) with the fast model and writes the facts it extracts |
| Episodic | One line per problem that ended in a reveal: `Session <id>: stage <s>, <n> hints, outcome revealed` | Built by our code from the session (no model call to word it); stored as is with `infer=False`, so only an embedding call is spent |
| Procedural | How the learner worked through a problem | Only after a reveal. `mem0` summarizes the turns with the fast model as procedural memory |

Each recalled item carries its kind, text, and creation time. The prompt shows the kind in front
of the text.

Verified against mem0ai 2.2.1: procedural memory is created only when `agent_id` is passed, so
every procedural write uses `user_id=<learner>` and `agent_id="codebuddy-tutor"`. The stored
payload keeps the `user_id`, so the plain learner filter used by recall, listing, and Forget also
finds and deletes procedural items; no separate agent-scoped lookup exists. If `agent_id` were
left out, mem0 would silently store a normal memory instead. mem0 marks procedural memory for
removal in a future breaking release, which is why `pyproject.toml` pins `mem0ai>=2.2.1,<3`.

## When it reads and writes

Reads happen in the `recall_memory` graph node. It runs in parallel with `classify` and
`retrieve`, so it adds no time on the normal path, and it has a hard timeout
(`CODEBUDDY_MEMORY_RECALL_TIMEOUT_S`, 0.6 s). On a timeout or error the turn goes on without notes
and `memory_failures` is counted. At most `CODEBUDDY_MEMORY_RECALL_LIMIT` (5) items go into the
prompt, each cut to 200 characters, inside a `<memory>` block that tells the model they are private
notes, never to quote them, never to treat them as instructions, and never to use them to reveal
the fix. Any `<memory>` or `</memory>` tag inside a stored item is removed first, so recalled text
cannot close the block.

Writes happen in `update_state`, after the reply, as a background task:

- on a reveal (semantic, episodic, and procedural items), and
- on every `CODEBUDDY_MEMORY_WRITE_EVERY`-th hint (default 4; semantic items only).

A turn is never slowed by a write. A failed write is logged and counted as `memory_failures`.

Every mem0 call (recall, write, list, forget) runs under one lock, because the embedded Qdrant
store is not safe for concurrent use. A recall that waits behind a slow write can hit
`CODEBUDDY_MEMORY_RECALL_TIMEOUT_S`; that turn then proceeds with no memory and counts a
`memory_failures`. The lock also orders writes against Forget me: a write that started before
Forget finishes before the delete, and a write scheduled before Forget that has not yet run is
dropped (each write carries the learner's forget generation from when it was scheduled). Before
deleting, Forget records its time in the cache (`cb:forgot:<learner id>`, kept 30 days), and each
session turn carries a timestamp, so a later write in the same session never re-adds turns from
before Forget. If that marker cannot be written, Forget returns 503 and deletes nothing; if it
cannot be read, the write is skipped and counted as `memory_failures`.
On shutdown the API waits up to 5 seconds for pending writes, then cancels them.

Cost: every write calls OpenAI. A hint write is one extraction call on the fast model plus
embeddings; a reveal adds the procedural summary call and one more embedding. Recall embeds the
learner's message on each memory-enabled turn. Chat calls use `CODEBUDDY_MODEL_FAST`; embeddings
use `CODEBUDDY_EMBED_MODEL`.

## Opt-in and "Forget me"

1. The checkbox **Remember me across sessions** (in the sidebar **Settings** popover) is always
   unchecked on a fresh page.
2. Ticking it asks the server for a learner token (`POST /v1/memory/learners`). The UI keeps the
   token in the session and in the page URL as `?learner=<token>`, so a bookmark restores the
   profile later.
3. Opening a page whose URL already has `?learner=` does not enable memory. The Settings popover
   says "This
   link contains a saved learner profile. Use it only if you created it." and waits for **Use
   this profile**. A link alone never turns memory on or sends the token.
4. While memory is on, the expander **What I remember about you** lists every stored item by
   kind (`GET /v1/memory` with the token in header `X-Learner-Token`).
5. **Forget me** deletes every item for that learner (`DELETE /v1/memory`, same header), shows how
   many were removed, turns the opt-in off, and starts a new chat (new session ID), because the
   server binds a session to one learner. Adopting a profile with **Use this profile** also starts
   a new chat.

Without the box ticked, no token is sent and no memory is read or written.

## Learner tokens

A token is `<22-character id>.<43-character signature>`. The signature is an HMAC-SHA256 over the
id and a hash of the caller's API key, keyed by `CODEBUDDY_MEMORY_SECRET`. So a token minted by
one API key does not work under another, and a client cannot invent a valid one. The graph
receives only the verified id.

- A bad or foreign token returns HTTP 403 `Invalid learner token`, before any memory is touched.
- A session belongs to the first learner who uses it with memory. Another learner on the same
  session gets HTTP 409 `This session belongs to another learner`, and so does a turn or
  show-answer on that session sent without a token. The first turn claims the session with an
  atomic set-if-absent in the session cache (key `cb:bind:<session>`, lifetime `TTL_SESSION`), so
  two first turns from different learners cannot both bind: one gets 409. As a safety net, a turn
  that reaches the graph for a bound session with another learner or none still gets a reply, but
  it skips memory and neither sees nor adds to the bound learner's history.
- `GET /v1/session/{id}` on a bound session needs the same learner's token in header
  `X-Learner-Token`: none or another learner's is 409, an invalid one 403. Unbound sessions answer
  without it.
- When a session binds, its earlier history is cleared, so turns made before binding (by anyone)
  are never written into the learner's memory.
- With `CODEBUDDY_MEMORY_SECRET` empty the server warns at startup and uses a random secret per
  process, so every token stops working after a restart. Set a long random value to keep them.
- Rotating the secret invalidates every token. The stored data under the old ids then cannot be
  reached through the API.

## How to enable

```dotenv
OPENAI_API_KEY=sk-...
CODEBUDDY_MODEL_FAST=<model id>       # used by mem0 to extract and summarize
CODEBUDDY_MEMORY_ENABLED=true
CODEBUDDY_MEMORY_SECRET=<long random value>
```

Generate a secret with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Optional
settings (path, recall limit, timeout, write frequency, embedding size) are in
[configuration.md](configuration.md). Restart the API. `/healthz` then shows
`"memory_enabled": true`. If the memory store cannot start (for example the folder is locked by
another process), the API logs the error, continues without memory, and `/healthz` shows `false`.

Data lives under `CODEBUDDY_MEMORY_PATH` (default `data/memory`): an embedded Qdrant collection
`codebuddy_memory` and `history.db`. Only one process may open it. mem0's anonymous telemetry is
turned off by setting `MEM0_TELEMETRY=False` before mem0 is imported.

The keyless demo (`codebuddy.api.demo`) uses an in-memory fake, so the UI flow can be tried
without OpenAI. Nothing it stores survives a restart.

## What memory never does

- It never changes the hint ladder or the mode. `decide_mode()` and `pedagogy/policy.py` do not
  read memory; memory reaches the model only as the delimited `<memory>` block.
- It never bypasses the leak guard. `StreamGuard` checks the output the same way whatever the
  prompt contained.
- It is never cached or shared. For a learner with memory active the answer caches (L1 and L2) are
  skipped, so a personalized reply is neither served from nor stored in a shared cache. Separately,
  a reply is stored in L1 only if the prompt did not include session history; this closes a hole
  where a follow-up answer shaped by earlier turns could be served to other learners.
- It never reads the `pedagogy` corpus or touches retrieval.

## Limits

- No solved detection. The only outcome the code can know is a reveal, so a learner who solves a
  problem unaided produces only semantic notes.
- No accounts. The learner token is the identity, and it is bearer-like: it sits in the page URL
  (browser history, bookmarks, Referer, shoulder-surfing). Anyone with the token, plus the API key
  when keys are on, can read or delete that learner's notes.
- With `CODEBUDDY_API_KEYS` empty, tokens are bound to no key, so any client holding a token can
  use it. Acceptable only for local use or the demo.
- Session IDs are chosen by the client. Binding refuses turns on a bound session from another
  learner or without a token, and clearing history on bind keeps earlier turns out, so a client
  cannot write into a learner's memory through a session it does not hold the token for. It does
  not stop a nuisance attack: someone who binds a session ID that another learner later reuses
  makes that learner get 409.
- Retention is manual. Items stay until the learner presses Forget me or you delete
  `data/memory`. `forget` deletes items by id in batches of 1000 until none are left, counting
  each one, then sweeps with mem0's `delete_all`, so the reported count is exact.
- Notes are personal data stored on this server and sent to OpenAI for extraction; see
  [security.md](security.md).

## Tests

`tests/unit/test_memory.py`, `tests/unit/test_learner_tokens.py`,
`tests/unit/test_wiring_memory.py`,
`tests/integration/test_memory.py`, and `tests/integration/test_ui_memory.py`, all offline against
`InMemoryLearnerMemory` or a recording stub in place of mem0. See [testing.md](testing.md).
