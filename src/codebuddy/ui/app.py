"""Streamlit front end. A thin client: all tutoring logic lives in the API.

Run:  uv run streamlit run src/codebuddy/ui/app.py   (API on http://localhost:8000)
"""

from __future__ import annotations

import hashlib
import os
import secrets
import uuid

import streamlit as st

from codebuddy.ui.client import ApiError, TutorClient

STAGES = [
    ("P", "Problem"),
    ("C", "Cases"),
    ("D", "Design"),
    ("I", "Implement"),
    ("T", "Test"),
]
LEVEL_NAMES = {
    0: "Hint 1: think it through",
    1: "Hint 2: look here",
    2: "Hint 3: the concept",
    3: "Hint 4: a plan",
    4: "Full answer",
}
MEMORY_BOX = "remember_me"
RESET_KEYS = (
    "session_id",
    "messages",
    "stage",
    "can_show",
    "offer",
    "pending",
    "transcript",
    "transcript_edit",
    "last_audio",
)


def init_state() -> None:
    ss = st.session_state
    ss.setdefault("session_id", uuid.uuid4().hex)
    ss.setdefault("messages", [])  # {role, content, meta, done}
    ss.setdefault("stage", "P")
    ss.setdefault("can_show", False)
    ss.setdefault("offer", False)
    ss.setdefault("pending", None)  # a turn waiting for permission to run the learner's code


def get_client(base_url: str, api_key: str | None) -> TutorClient:
    # Tests inject a stub through session_state["client"].
    return st.session_state.get("client") or TutorClient(base_url, api_key=api_key or None)


def stage_bar(current: str) -> None:
    cols = st.columns(len(STAGES))
    for col, (letter, name) in zip(cols, STAGES, strict=True):
        label = f"**{letter}** {name}"
        col.markdown(f":blue-background[{label}]" if letter == current else label)


def render_meta(meta: dict | None, done: dict | None) -> None:
    if not meta:
        return
    badges = []
    if meta.get("mode") == "hint" and meta.get("level") is not None:
        badges.append(LEVEL_NAMES[meta["level"]])
    elif meta.get("mode") == "reveal":
        badges.append(LEVEL_NAMES[4])
    elif meta.get("mode") == "explain":
        badges.append("Explanation")
    if meta.get("cached"):
        badges.append("instant (cached)")
    if badges:
        st.caption(" · ".join(badges))
    if done:
        if done.get("degraded"):
            st.warning("The tutor model was unavailable, so this is course material only.")
        for i, c in enumerate(done.get("citations", []), start=1):
            label = f"[{i}] {c['source']}" + (f", {c['section']}" if c.get("section") else "")
            st.caption(label)


def run_stream(events) -> tuple[str, dict | None, dict | None, dict | None]:
    """Consume SSE events, streaming tokens into the page.

    Returns (text, meta, done, approval). `approval` is set when the tutor paused to ask
    permission to run the learner's code.
    """
    box: dict = {"meta": None, "done": None, "approval": None}

    def tokens():
        for kind, data in events:
            if kind == "meta":
                box["meta"] = data
            elif kind == "token":
                yield data["text"]
            elif kind == "approval":
                box["approval"] = data
            elif kind == "done":
                box["done"] = data
            elif kind == "error":
                raise ApiError(data.get("message", "error"))

    text = st.write_stream(tokens())
    return str(text or ""), box["meta"], box["done"], box["approval"]


def apply_result(text: str, meta: dict | None, done: dict | None, approval: dict | None) -> None:
    ss = st.session_state
    if text:
        ss.messages.append({"role": "assistant", "content": text, "meta": meta, "done": done})
    ss.pending = approval
    if done and done.get("stage"):
        ss.stage = done["stage"]
    if meta:
        ss.can_show = bool(meta.get("can_show_answer")) or (done or {}).get("hints_given", 0) >= 1
        ss.offer = bool(meta.get("offer_answer"))
        if meta.get("mode") == "reveal":
            ss.can_show, ss.offer = False, False


def handle_voice(client, enabled: bool) -> None:
    """Record, transcribe, and let the learner edit the text before sending."""
    ss = st.session_state
    if not enabled:
        st.caption("Voice input is off: the server has no speech-to-text configured.")
        return
    audio = st.audio_input("Or ask by voice", key="mic")
    if audio is not None:
        data = audio.getvalue()
        digest = hashlib.sha1(data).hexdigest()
        if digest != ss.get("last_audio"):
            ss.last_audio = digest
            try:
                ss.transcript = client.transcribe(data, audio.name or "speech.wav", audio.type)
                ss.transcript_edit = ss.transcript
            except ApiError as exc:
                st.warning(f"{exc}. You can type your question instead.")


def forget_me(client) -> None:
    """Button callback: delete the server-side memory, then reset the opt-in."""
    ss = st.session_state
    try:
        ss["forget_result"] = f"{client.forget(ss['learner_id'])} remembered items deleted."
    except ApiError as exc:
        ss["forget_result"] = f"error: {exc}"
        return
    ss["learner_id"] = None
    ss[MEMORY_BOX] = False
    st.query_params.pop("learner", None)


def memory_sidebar(client) -> str | None:
    """Opt-in box, what is remembered, and "Forget me". Returns the learner id while enabled."""
    ss = st.session_state
    if MEMORY_BOX not in ss:
        ss[MEMORY_BOX] = "learner" in st.query_params
        if ss[MEMORY_BOX]:
            ss["learner_id"] = st.query_params["learner"]
    if st.checkbox("Remember me across sessions", key=MEMORY_BOX):
        if not ss.get("learner_id"):
            ss["learner_id"] = secrets.token_urlsafe(16)
        st.query_params["learner"] = ss["learner_id"]
    st.caption(
        "If on, the server stores short notes about what you struggle with and which answers "
        "you were shown. Bookmark this page to keep them. 'Forget me' deletes them."
    )
    if ss.get("forget_result"):
        (st.error if ss["forget_result"].startswith("error") else st.markdown)(
            ss.pop("forget_result")
        )
    if not ss.get(MEMORY_BOX):
        return None
    with st.expander("What I remember about you"):
        try:
            items = client.memories(ss["learner_id"])
        except ApiError as exc:
            st.warning(str(exc))
            items = []
        if not items:
            st.caption("Nothing yet.")
        for kind in sorted({i["kind"] for i in items}):
            st.markdown(f"**{kind}**")
            for item in (i for i in items if i["kind"] == kind):
                st.markdown(f"- {item['text']}")
    st.button("Forget me", key="forget_me", on_click=forget_me, args=(client,))
    return ss["learner_id"]


def main() -> None:
    st.set_page_config(page_title="CodeBuddy", page_icon="🧭", layout="wide")
    init_state()
    ss = st.session_state

    learner_id = None
    with st.sidebar:
        st.title("CodeBuddy")
        base_url = st.text_input("API URL", os.getenv("CODEBUDDY_API_URL", "http://localhost:8000"))
        api_key = st.text_input("API key", os.getenv("CODEBUDDY_API_KEY", ""), type="password")
        language = st.selectbox("Language", ["python"])
        if st.button("New session"):
            for key in RESET_KEYS:
                ss.pop(key, None)
            st.rerun()
        client = get_client(base_url, api_key)
        health = client.health()
        if health is None:
            st.error("API not reachable")
        else:
            st.success(f"API ok · cache: {health.get('cache')}")
            if not health.get("models_configured"):
                st.warning("Model IDs are not configured on the server.")
            st.caption(
                f"Tools: {health.get('tools', 'off')} · voice: "
                f"{'on' if health.get('stt_configured') else 'off'}"
            )
            if health.get("memory_enabled"):
                learner_id = memory_sidebar(client)
        st.caption(f"Session {ss.session_id[:8]}")

    st.subheader("Let's work it out together")
    stage_bar(ss.stage)

    with st.expander("Your code", expanded=True):
        code = st.text_area(
            "Paste the code you are working on",
            key="code",
            height=220,
            label_visibility="collapsed",
            placeholder="# paste your code here",
        )

    show_clicked = st.button(
        "Show answer",
        key="show_answer",
        disabled=not ss.can_show,
        type="primary" if ss.offer else "secondary",
        help="Available after your first hint. No need to justify, just ask.",
    )
    if ss.offer:
        st.info("Stuck for a while is normal. You can see the full answer whenever you like.")

    for m in ss.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m["role"] == "assistant":
                render_meta(m.get("meta"), m.get("done"))

    # Permission request: the tutor will not run the learner's code without asking.
    approve_clicked = decline_clicked = False
    if ss.pending:
        with st.chat_message("assistant"):
            st.markdown(f"**{ss.pending['message']}**")
            st.caption("It runs in a restricted sandbox with no network and shows what happened.")
            st.code(ss.pending.get("code", ""), language="python")
            st.checkbox("Remember my choice for this session", value=True, key="remember")
            left, right = st.columns(2)
            approve_clicked = left.button("Run my code", key="approve_run", type="primary")
            decline_clicked = right.button("Don't run it", key="decline_run")

    handle_voice(client, bool(health and health.get("stt_configured")))
    send_transcript = False
    if ss.get("transcript"):
        st.text_area("Transcript (edit before sending)", key="transcript_edit", height=80)
        send_transcript = st.button("Send transcript", key="send_transcript")

    prompt = st.chat_input("What are you stuck on?")
    if send_transcript:
        prompt = (ss.get("transcript_edit") or "").strip() or None
        ss.pop("transcript", None)
        ss.pop("transcript_edit", None)

    if not (prompt or show_clicked or approve_clicked or decline_clicked):
        return

    session_id = ss.session_id
    who = {"learner_id": learner_id} if learner_id else {}
    if approve_clicked or decline_clicked:
        turn_id = ss.pending["turn_id"]
        decision = approve_clicked
        ss.pending = None
        events = lambda: client.stream_approve(  # noqa: E731
            session_id, turn_id, decision, ss.get("remember", True)
        )
        user_text = None
    elif show_clicked:
        user_text = "Show me the full answer."
        events = lambda: client.stream_show_answer(  # noqa: E731
            session_id, code or None, language, **who
        )
    else:
        user_text = prompt
        events = lambda: client.stream_turn(  # noqa: E731
            session_id, prompt, code or None, language, **who
        )

    if user_text:
        ss.messages.append({"role": "user", "content": user_text})
        with st.chat_message("user"):
            st.markdown(user_text)
    with st.chat_message("assistant"):
        try:
            text, meta, done, approval = run_stream(events())
        except ApiError as exc:
            st.error(str(exc))
            st.caption("Check that the API is running, then send your message again.")
            if user_text:
                ss.messages.pop()
            return
        render_meta(meta, done)

    apply_result(text, meta, done, approval)
    st.rerun()  # refresh the controls above the chat


main()
