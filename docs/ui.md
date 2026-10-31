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
| Chat | The thread of the open chat. Each tutor reply has, above it, a collapsed step summary such as "Worked for 1.4 s · 4 steps" (open it to see each step), and below it a small caption ("Hint 2: look here", "Explanation", "Full answer", "You fixed it", "Quiz 2 of 5 (medium)", plus "instant" when cached) and a collapsed **References (N)** expander. Inside, the book title appears once and each row is `[n] <section>`, for example `[1] 2.10 Debugging` |
| Live steps | While the tutor works, a status box lists the `step` events as they arrive (running, then done with a short detail). When the first token arrives it collapses to the summary and the reply streams below it |
| **Show answer** | Under the latest tutor reply only, once the server allows it (after the first hint). Primary style, with the caption "Stuck for a while is normal...", when the tutor offers the answer. Hidden after a reveal, while a quiz runs, and while a permission prompt is open. Sends `/v1/show-answer` |
| Quiz | **Try a quiz** (key `try_quiz`) appears under the latest reply when the tutor saw a fix (`meta.offer_quiz`). It sends `/v1/quiz`, and question 1 streams into the chat with the caption "Quiz 1 of 5 (easy)". Each new question's snippet (`meta.quiz_code`) replaces the text in the code box, so the learner fixes it there and sends. While a quiz runs (`meta.quiz` set), **Skip question** (`skip_question`) and **Stop quiz** (`stop_quiz`) sit under the latest reply; they send the turns "Skip this question." and "Stop the quiz." A correct answer and the next question arrive in one reply, so there is no Next button |
| Permission prompt | When the tutor wants to run the learner's code it appears as a tutor message with its step summary, the code, **Run my code** / **Don't run it**, and a "remember my choice for this chat" checkbox (one per chat). Nothing is said or run until the learner chooses. If the choice never reached the tutor (it could not connect) or was rate-limited (429), the prompt stays so the learner can choose again. Otherwise the prompt is dropped: if the server no longer holds the request (404), or the reply broke off after the server took it, the page says "That request expired. Send your message again." |
| Your code | A collapsed expander above the input; its label shows the line count when code is present ("Your code (5 lines)"). Each chat keeps its own code. Empty means no code is sent |
| Input | `st.chat_input`. When the server reports `stt_configured` it also accepts a voice recording. A recording goes to `/v1/stt`; the transcript appears in an editable "Heard" box with **Send** and **Discard**, so the learner reads and fixes it before anything is sent. Each chat keeps its own transcript, so switching chats never carries one across. If transcription fails the page says why: 503 "Voice input is off on this server.", 413 "That recording is too long.", 502 "Couldn't understand the recording.", each followed by "You can type your question instead." |
| Memory (Settings popover) | Box **Remember me across sessions**, unchecked on every fresh page. Ticking it mints a learner token and puts it in the URL as `?learner=`. A page opened with `?learner=` shows "This link contains a saved learner profile. Use it only if you created it." and a **Use this profile** button; only that click enables memory (the sidebar also notes that the link has a profile). While on: **Show what I remember** fetches the stored items and lists them by kind (only on that click, never on every rerun; the list is dropped after Forget), and **Forget me** deletes them all and turns memory off. Turns carry the token as `learner_id` |
| Warnings | A warning when the reply came from course material only (model outage). A failed call shows a plain sentence, never a URL or the server's JSON, and the unsent question is dropped. By status: unreachable "Can't reach the tutor. Check that it is running."; 401 "The tutor needs an API key..."; 403 "Your saved profile is no longer valid. Turn memory off and on again." (the token is dropped, so turning memory on mints a new one); 409 starts a new chat and says so; 429 "Too many requests. Wait a minute and try again."; anything else "Something went wrong. Please try again." Memory calls (mint, list, Forget) answer 503 with "Memory is turned off on the server." |
| Toolbar | `.streamlit/config.toml` sets `[client] toolbarMode = "minimal"`, so the page menu shows no developer options |

## Chats and sessions

Each chat is one server session. Its state lives in `st.session_state.chats` (a list, newest
first), and `chat_id` names the open one. A chat holds `session_id`, `messages` (role, content,
meta, done, steps, elapsed), `stage`, `can_show`, `offer`, `quiz_offer` (Try a quiz is shown),
`quiz` (the running quiz's `{"index", "total", "difficulty", "score"}`, or none), `pending` (a turn waiting for
permission, with its steps), `code`, `remember` (the "remember my choice" box, kept across chat
switches), `transcript` (what voice input heard, waiting to be edited and sent), `voice_note` (why
the last recording could not be transcribed), and `learner` (the token its session is bound to on
the server, or none; set only after a turn or Show answer sent with a token succeeds). **New chat**
on an empty chat does nothing; a chat with no messages is replaced rather than piling up. Chats
last as long as the browser tab.

The server binds a session to the first learner token it sees and answers 409 to any later turn
with another token or none. The UI therefore starts a new chat (new `session_id`) when:

- the learner clicks **Forget me** (chats made under the forgotten token are also removed; the
  code moves to the new chat),
- the learner clicks **Use this profile** (the code moves to the new chat),
- the open chat is bound to a token that is no longer active (memory was turned off). The page
  says "Your memory setting changed, so your next message starts a new chat", hides Show answer,
  and moves the next message, with the code, into a new chat,
- the server answers 409 anyway. The page drops the unsent message, opens a new chat with the
  code, and says so.

Other session state keys: `learner_id` (the token while known), `remember_me` (the opt-in box),
`memory_note` (result text for Forget or a failed mint), `memory_items` (the token and the items
last fetched by Show what I remember), `turn_note` (the notice after a 409 or a failed permission
choice), `client` (the `TutorClient`, or a test stub). Widget keys: `new_chat`, `chat_<session_id>`,
`code_<session_id>`, `transcript_<session_id>`, `remember_<session_id>`, `show_answer`,
`try_quiz`, `skip_question`, `stop_quiz`, `approve_run`, `decline_run`, `send_transcript`, `discard_transcript`, `use_profile`,
`show_memories`, `forget_me`.

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
(per-chat remember box, a kept prompt when the tutor is unreachable, the expired sentence on 404),
transcript editing, per-chat transcripts and the voice 503 sentence. `AppTest` cannot submit audio,
so those tests seed the chat's transcript or patch `st.chat_input` to return a recording; recording
in a browser needs a manual check. `tests/integration/test_ui_memory.py` covers the opt-in box,
**Use this profile**, Forget me (both keep the code), the memory 503 sentence, the on-demand memory
list, the session rotation that avoids 409 (including after Show answer), and the error sentences
for 403, 409, 429 and an unreachable API. `tests/unit/test_ui_client.py` covers SSE parsing and
error handling with `httpx.MockTransport`. `tests/integration/test_ui_quiz.py` covers Try a quiz
appearing only after a confirmed fix, the quiz snippet landing in the code box, the quiz caption,
and Skip question and Stop quiz. No server is needed. See [testing.md](testing.md).

The layout was checked in headless Chromium (Playwright) against the demo API.
