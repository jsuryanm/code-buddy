# Streamlit UI

Code: `src/codebuddy/ui/app.py` (page) and `src/codebuddy/ui/client.py` (HTTP/SSE client).
The UI holds no tutoring logic; it renders what the API streams.

## Run

```bash
uv sync --extra ui
uv run uvicorn codebuddy.api.app:app --port 8000     # or codebuddy.api.demo:app for no keys
uv run streamlit run src/codebuddy/ui/app.py          # http://localhost:8501
```

Set `CODEBUDDY_API_URL` to point at another API host; the sidebar field overrides it per session.

## What you see

| Area | Behavior |
|---|---|
| Sidebar | API URL, API key (password field, defaults to `CODEBUDDY_API_KEY`), language, **New session** (fresh session ID, clears chat and progress), API health with cache type, short session ID |
| Stage bar | P, C, D, I, T with the current PCDIT stage highlighted. Updates from the classifier after each turn |
| Your code | Collapsible text box. Its contents are sent with every message. Empty means no code |
| **Show answer** | Disabled until the first hint. Becomes the primary button and an info banner appears when the tutor offers the answer. Sends `/v1/show-answer`. Disabled again after a reveal |
| Chat | History plus the streaming reply. Under each tutor reply: a caption such as "Hint 2: look here", "Explanation", or "instant (cached)", then numbered citations |
| Voice | A microphone widget (shown only when the server reports `stt_configured`). A recording is sent to `/v1/stt`; the transcript appears in an editable box with a **Send transcript** button, so the learner reads and fixes it first |
| Permission prompt | When the tutor wants to run the learner's code it shows the code, a **Run my code** / **Don't run it** pair, and a "remember for this session" checkbox. Nothing is said or run until the learner chooses |
| Warnings | A warning when the reply came from course material only (model outage); an error with a retry hint if the API cannot be reached |

## How it maps to the API

```mermaid
sequenceDiagram
    participant U as Learner
    participant S as Streamlit
    participant A as FastAPI
    U->>S: message (+ code box)
    S->>A: POST /v1/turn
    A-->>S: meta, token..., done
    S-->>U: stream tokens (st.write_stream)
    S->>S: store stage, can_show, offer; st.rerun()
```

`st.rerun()` after each turn refreshes the controls that sit above the chat (the Show answer
button and stage bar are drawn before the reply is known).

Session state keys: `session_id`, `messages` (role, content, meta, done), `stage`, `can_show`,
`offer`, `pending` (a turn waiting for permission), `transcript` / `transcript_edit` / `last_audio`
(voice), plus the widget keys `code`, `show_answer`, `approve_run`, `decline_run`, `remember`, and
`send_transcript`.

## Extending

- **New control**: add it in `main()`; send extra fields through `TutorClient` and the API schema.
- **Different backend URL per user**: not supported; one sidebar value per browser session.

## Testing

`tests/integration/test_ui_voice_approval.py` covers the permission prompt and transcript editing
(the recording itself cannot be simulated; test the microphone by hand).
`tests/integration/test_ui_smoke.py` runs the real script with Streamlit's `AppTest` and a stub
client injected through `st.session_state["client"]`. `tests/unit/test_ui_client.py` covers SSE
parsing and error handling with `httpx.MockTransport`. No server is needed. See
[testing.md](testing.md).

Not covered by tests: the visual layout in a real browser (no browser was available when this was
built). Look at it once yourself.
