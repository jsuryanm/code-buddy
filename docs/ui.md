# Streamlit UI

Code: `src/codebuddy/ui/app.py` (page) and `src/codebuddy/ui/client.py` (HTTP/SSE client).
The UI holds no tutoring logic; it renders what the API streams.

## Run

```bash
uv sync --extra ui
uv run uvicorn codebuddy.api.app:app --port 8000     # or codebuddy.api.demo:app for no keys
uv run streamlit run src/codebuddy/ui/app.py          # http://localhost:8501
```

The UI reads the API address from `CODEBUDDY_API_URL` (default `http://localhost:8000`) and, when
the server requires a key, the key from `CODEBUDDY_API_KEY` (unset means no key). Neither appears
on the page. The language is always `python`; it is sent with every turn but not shown.

## What you see

| Area | Behavior |
|---|---|
| Sidebar | App name, **New chat**, and the chats of this browser tab (title is the first learner message cut to 40 characters, newest first, the open chat highlighted; click one to switch). A chat appears in the list once it has a message. At the bottom: one line "Connected" or "Can't reach the tutor", and a **Settings** popover that holds the memory controls (only when the server reports `memory_enabled`) |
| Stage line | Problem, Cases, Design, Implement, Test on one line with the current PCDIT stage highlighted. Updates from the classifier after each turn |
| Chat | The thread of the open chat. Each tutor reply has, above it, a collapsed step summary such as "Worked for 1.4 s · 4 steps" (open it to see each step), and below it a small caption ("Hint 2: look here", "Explanation", "Full answer", plus "instant" when cached) and a collapsed **References (N)** expander. Inside, the book title appears once and each row is `[n] <section>`, for example `[1] 2.10 Debugging` |
| Live steps | While the tutor works, a status box lists the `step` events as they arrive (running, then done with a short detail). When the first token arrives it collapses to the summary and the reply streams below it |
| **Show answer** | Under the latest tutor reply only, once the server allows it (after the first hint). Primary style, with the caption "Stuck for a while is normal...", when the tutor offers the answer. Hidden after a reveal and while a permission prompt is open. Sends `/v1/show-answer` |
| Permission prompt | When the tutor wants to run the learner's code it appears as a tutor message with its step summary, the code, **Run my code** / **Don't run it**, and a "remember my choice for this chat" checkbox. Nothing is said or run until the learner chooses |
| Your code | A collapsed expander above the input; its label shows the line count when code is present ("Your code (5 lines)"). Each chat keeps its own code. Empty means no code is sent |
| Input | `st.chat_input`. When the server reports `stt_configured` it also accepts a voice recording. A recording goes to `/v1/stt`; the transcript appears in an editable "Heard" box with **Send** and **Discard**, so the learner reads and fixes it before anything is sent |
| Memory (Settings popover) | Box **Remember me across sessions**, unchecked on every fresh page. Ticking it mints a learner token and puts it in the URL as `?learner=`. A page opened with `?learner=` shows "This link contains a saved learner profile. Use it only if you created it." and a **Use this profile** button; only that click enables memory (the sidebar also notes that the link has a profile). While on: **What I remember about you** lists items by kind, and **Forget me** deletes them all and turns memory off. Turns carry the token as `learner_id` |
| Warnings | A warning when the reply came from course material only (model outage); an error with a retry hint if the API cannot be reached, and the unsent question is dropped |

## Chats and sessions

Each chat is one server session. Its state lives in `st.session_state.chats` (a list, newest
first), and `chat_id` names the open one. A chat holds `session_id`, `messages` (role, content,
meta, done, steps, elapsed), `stage`, `can_show`, `offer`, `pending` (a turn waiting for
permission, with its steps), `code`, and `learner` (the token its session is bound to on the
server, or none). **New chat** on an empty chat does nothing; a chat with no messages is replaced
rather than piling up. Chats last as long as the browser tab.

The server binds a session to the first learner token it sees and answers 409 to any later turn
with another token or none. The UI therefore starts a new chat (new `session_id`) when:

- the learner clicks **Forget me** (chats made under the forgotten token are also removed),
- the learner clicks **Use this profile**,
- the open chat is bound to a token that is no longer active (memory was turned off). The page
  says "Your memory setting changed, so your next message starts a new chat", hides Show answer,
  and moves the next message, with the code, into a new chat.

Other session state keys: `learner_id` (the token while known), `remember_me` (the opt-in box),
`memory_note` (result text for Forget or a failed mint), `transcript` / `transcript_edit` /
`voice_note` (voice), `client` (the `TutorClient`, or a test stub). Widget keys: `new_chat`,
`chat_<session_id>`, `code_<session_id>`, `show_answer`, `approve_run`, `decline_run`,
`remember`, `send_transcript`, `discard_transcript`, `use_profile`, `forget_me`.

## How it maps to the API

```mermaid
sequenceDiagram
    participant U as Learner
    participant S as Streamlit
    participant A as FastAPI
    U->>S: message (+ code box)
    S->>A: POST /v1/turn (session_id of the open chat)
    A-->>S: step..., meta, token..., done
    S-->>U: live steps, then stream tokens (st.write_stream)
    S->>S: store the reply, stage, can_show, offer; st.rerun()
```

`st.rerun()` after each turn redraws the thread, so Show answer moves to the newest reply and
the stage line updates.

## Extending

- **New control**: add a small function in `app.py` and call it from `main()`; send extra fields
  through `TutorClient` and the API schema.
- **Different backend per user**: not supported; the URL comes from the environment.
- **Chats across tabs or devices**: not supported; chats live in the tab's session state.

## Testing

`tests/integration/test_ui_smoke.py` runs the real script with Streamlit's `AppTest` and a stub
client injected through `st.session_state["client"]`: no developer widgets, steps in a status box
that collapses at the first token, collapsed references, Show answer only under the latest reply,
New chat and switching. `tests/integration/test_ui_voice_approval.py` covers the permission prompt
and transcript editing; `AppTest` cannot submit audio, so the transcript path is tested by seeding
session state and the microphone itself needs a manual check.
`tests/integration/test_ui_memory.py` covers the opt-in box, **Use this profile**, Forget me, and
the session rotation that avoids 409. `tests/unit/test_ui_client.py` covers SSE parsing and error
handling with `httpx.MockTransport`. No server is needed. See [testing.md](testing.md).

The layout was checked in headless Chromium (Playwright) against the demo API.
