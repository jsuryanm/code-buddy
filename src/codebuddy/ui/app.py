"""Streamlit front end. A thin client: all tutoring logic lives in the API.

Run:  uv run streamlit run src/codebuddy/ui/app.py
The API address comes from CODEBUDDY_API_URL (default http://localhost:8000) and the key, when
the server needs one, from CODEBUDDY_API_KEY. Neither is shown to the learner.
"""

from __future__ import annotations

import os
import time
import uuid

import streamlit as st

from codebuddy.ui.client import ApiError, TutorClient

LANGUAGE = "python"
STAGES = [("P", "Problem"), ("C", "Cases"), ("D", "Design"), ("I", "Implement"), ("T", "Test")]
LEVEL_NAMES = {
    0: "Hint 1: think it through",
    1: "Hint 2: look here",
    2: "Hint 3: the concept",
    3: "Hint 4: a plan",
    4: "Full answer",
}
MEMORY_BOX = "remember_me"
TITLE_CHARS = 40
AVATARS = {"user": ":material/person:", "assistant": ":material/school:"}
# Chat titles in the sidebar read like a list, not like centered buttons.
SIDEBAR_CSS = """<style>
section[data-testid="stSidebar"] .stButton button { justify-content: flex-start; }
</style>"""
# What the learner reads when a call fails. Never the URL or the server's JSON.
ERRORS = {
    None: "Can't reach the tutor. Check that it is running.",
    401: "The tutor needs an API key. Set CODEBUDDY_API_KEY and restart the page.",
    403: "Your saved profile is no longer valid. Turn memory off and on again.",
    404: "That request expired. Send your message again.",
    409: "This chat belongs to another memory setting, so a new chat was started. "
    "Send your message again.",
    429: "Too many requests. Wait a minute and try again.",
}
VOICE_ERRORS = {
    503: "Voice input is off on this server.",
    413: "That recording is too long.",
    502: "Couldn't understand the recording.",
}
MEMORY_ERRORS = {503: "Memory is turned off on the server."}
GENERIC_ERROR = "Something went wrong. Please try again."


def error_text(exc: ApiError, extra: dict | None = None) -> str:
    """The sentence for a failed call; `extra` overrides ERRORS for one kind of call."""
    return {**ERRORS, **(extra or {})}.get(exc.status, GENERIC_ERROR)


def drop_invalid_profile() -> None:
    """After a 403 the token is useless: forget it so turning memory on again mints a new one."""
    st.session_state["learner_id"] = None
    st.query_params.pop("learner", None)


# ---------- state: one tab holds several chats, each with its own server session ----------


def new_chat(code: str = "") -> dict:
    return {
        "session_id": uuid.uuid4().hex,
        "messages": [],  # {role, content, meta, done, steps, elapsed}
        "stage": "P",
        "can_show": False,
        "offer": False,
        "pending": None,  # a turn waiting for permission to run the learner's code
        "code": code,
        "learner": None,  # the learner token this chat's session is bound to on the server
        "transcript": None,  # what voice input heard, waiting to be edited and sent
        "voice_note": None,  # why the last recording could not be transcribed
    }


def init_state() -> None:
    ss = st.session_state
    if not ss.get("chats"):
        ss.chats = [new_chat()]
        ss.chat_id = ss.chats[0]["session_id"]


def find_chat(session_id: str | None) -> dict | None:
    return next((c for c in st.session_state.chats if c["session_id"] == session_id), None)


def current_chat() -> dict:
    return find_chat(st.session_state.chat_id)


def is_empty(chat: dict) -> bool:
    return not chat["messages"] and not chat["pending"]


def start_new_chat(code: str = "") -> dict:
    """Open a fresh chat (new session id) at the top of the list. An unused chat is replaced."""
    ss = st.session_state
    current = find_chat(ss.get("chat_id"))
    if current is not None and is_empty(current):
        ss.chats.remove(current)
    chat = new_chat(code)
    ss.chats.insert(0, chat)
    ss.chat_id = chat["session_id"]
    return chat


def on_new_chat() -> None:
    if not is_empty(current_chat()):
        start_new_chat()


def switch_chat(session_id: str) -> None:
    st.session_state.chat_id = session_id


def chat_title(chat: dict) -> str:
    first = next((m["content"] for m in chat["messages"] if m["role"] == "user"), "")
    first = " ".join(first.split())
    if not first:
        return "New chat"
    return first if len(first) <= TITLE_CHARS else first[: TITLE_CHARS - 3].rstrip() + "..."


def get_client() -> TutorClient:
    # Tests inject a stub through session_state["client"].
    ss = st.session_state
    if "client" not in ss:
        url = os.getenv("CODEBUDDY_API_URL", "http://localhost:8000")
        ss.client = TutorClient(url, api_key=os.getenv("CODEBUDDY_API_KEY") or None)
    return ss.client


# ---------- memory (opt-in, lives in the Settings popover) ----------


def active_learner() -> str | None:
    """The learner token sent with turns: only while the opt-in box is ticked."""
    ss = st.session_state
    return ss.get("learner_id") if ss.get(MEMORY_BOX) else None


def forget_me(client) -> None:
    """Button callback: delete the server-side memory, reset the opt-in, start a new chat.

    The server binds a session to one learner, so chats made under the forgotten token are
    dropped and a new chat (new session id) begins.
    """
    ss = st.session_state
    token = ss["learner_id"]
    try:
        ss["memory_note"] = f"{client.forget(token)} remembered items deleted."
    except ApiError as exc:
        ss["memory_note"] = f"error: {error_text(exc, MEMORY_ERRORS)}"
        if exc.status == 403:
            drop_invalid_profile()
        return
    ss.pop("memory_items", None)
    ss["learner_id"] = None
    ss[MEMORY_BOX] = False
    st.query_params.pop("learner", None)
    code = current_chat()["code"]
    ss.chats = [c for c in ss.chats if c["learner"] != token]
    start_new_chat(code)


def enable_memory(client) -> None:
    """Checkbox callback: ticking the box asks the server for a new learner token."""
    ss = st.session_state
    if not ss[MEMORY_BOX] or ss.get("learner_id"):
        return
    try:
        ss["learner_id"] = client.new_learner()
    except ApiError as exc:
        ss["memory_note"] = f"error: {error_text(exc, MEMORY_ERRORS)}"
        ss[MEMORY_BOX] = False
        return
    st.query_params["learner"] = ss["learner_id"]


def use_profile() -> None:
    """Button callback: the learner chose the profile in the link. A link alone never does."""
    ss = st.session_state
    ss["learner_id"] = st.query_params["learner"]
    ss[MEMORY_BOX] = True
    start_new_chat(current_chat()["code"])  # a different learner: the server refuses the old one


def load_memories(client) -> None:
    """Button callback: fetch what is remembered. Only on request, never on every rerun."""
    ss = st.session_state
    token = ss["learner_id"]
    try:
        ss["memory_items"] = (token, client.memories(token))
    except ApiError as exc:
        ss["memory_note"] = f"error: {error_text(exc, MEMORY_ERRORS)}"
        if exc.status == 403:
            drop_invalid_profile()


def memory_settings(client) -> None:
    """Opt-in box, what is remembered, and "Forget me"."""
    ss = st.session_state
    st.checkbox(
        "Remember me across sessions", key=MEMORY_BOX, on_change=enable_memory, args=(client,)
    )
    if "learner" in st.query_params and not ss.get(MEMORY_BOX):
        st.markdown("This link contains a saved learner profile. Use it only if you created it.")
        st.button("Use this profile", key="use_profile", on_click=use_profile)
    st.caption(
        "If on, the server stores short notes about what you struggle with and which answers "
        "you were shown. Bookmark this page to keep them. 'Forget me' deletes them."
    )
    if ss.get("memory_note"):
        note = ss.pop("memory_note")
        if note.startswith("error: "):
            st.error(note.removeprefix("error: "))
        else:
            st.markdown(note)
    if not ss.get(MEMORY_BOX) or not ss.get("learner_id"):
        return
    st.button("Show what I remember", key="show_memories", on_click=load_memories, args=(client,))
    token, items = ss.get("memory_items") or (None, [])
    if token == ss["learner_id"]:
        if not items:
            st.caption("Nothing remembered yet.")
        for kind in sorted({i["kind"] for i in items}):
            st.markdown(f"**{kind}**")
            for item in (i for i in items if i["kind"] == kind):
                st.markdown(f"- {item['text']}")
    st.button("Forget me", key="forget_me", on_click=forget_me, args=(client,))


# ---------- sidebar ----------


def sidebar(client, health: dict | None) -> None:
    ss = st.session_state
    with st.sidebar:
        st.markdown(SIDEBAR_CSS, unsafe_allow_html=True)
        st.markdown("### CodeBuddy")
        st.button(
            "New chat", key="new_chat", icon=":material/add:", on_click=on_new_chat, width="stretch"
        )
        listed = [c for c in ss.chats if c["messages"]]
        if listed:
            st.caption("Chats")
        for chat in listed:
            sid = chat["session_id"]
            st.button(
                chat_title(chat),
                key=f"chat_{sid}",
                type="secondary" if sid == ss.chat_id else "tertiary",
                on_click=switch_chat,
                args=(sid,),
                width="stretch",
                wrap=False,
            )
        st.divider()
        if health is None:
            st.caption(":material/cloud_off: Can't reach the tutor")
            return
        st.caption(":material/check_circle: Connected")
        if not health.get("models_configured"):
            st.caption("The tutor's models are not configured on the server.")
        if health.get("memory_enabled"):
            if "learner" in st.query_params and not ss.get(MEMORY_BOX):
                st.caption("This link has a saved profile. Open Settings to use it.")
            with st.popover("Settings", icon=":material/settings:", width="stretch"):
                memory_settings(client)


# ---------- the thread ----------


def stage_line(current: str) -> None:
    parts = [
        f":blue-background[**{name}**]" if letter == current else f":gray[{name}]"
        for letter, name in STAGES
    ]
    st.markdown(" &nbsp;›&nbsp; ".join(parts))


def steps_summary(steps: list[dict], elapsed: float | None) -> str:
    n = len(steps)
    count = f"{n} step" + ("" if n == 1 else "s")
    return f"Worked for {elapsed:.1f} s · {count}" if elapsed is not None else count


def steps_markdown(steps: list[dict]) -> str:
    lines = []
    for s in steps:
        icon = ":material/check:" if s["status"] == "done" else ":material/more_horiz:"
        detail = f" :gray[· {s['detail']}]" if s.get("detail") else ""
        lines.append(f"{icon} {s['label']}{detail}")
    return "  \n".join(lines)


def section_name(citation: dict) -> str:
    """ "Think Python › 2.10 Debugging" -> "2.10 Debugging"."""
    section = citation.get("section") or ""
    return section.split("›")[-1].strip() or citation["source"]


def render_references(citations: list[dict]) -> None:
    if not citations:
        return
    sources = list(dict.fromkeys(c["source"] for c in citations))
    with st.expander(f"References ({len(citations)})", icon=":material/menu_book:"):
        if len(sources) == 1:
            st.caption(sources[0])
        rows = []
        for i, c in enumerate(citations, start=1):
            where = f" :gray[({c['source']})]" if len(sources) > 1 else ""
            rows.append(f"[{i}] {section_name(c)}{where}")
        st.markdown("  \n".join(rows))


def reply_caption(meta: dict | None) -> str:
    if not meta:
        return ""
    badges = []
    if meta.get("mode") == "hint" and meta.get("level") is not None:
        badges.append(LEVEL_NAMES[meta["level"]])
    elif meta.get("mode") == "reveal":
        badges.append(LEVEL_NAMES[4])
    elif meta.get("mode") == "explain":
        badges.append("Explanation")
    if meta.get("cached"):
        badges.append("instant")
    return " · ".join(badges)


def render_footer(meta: dict | None, done: dict | None) -> None:
    """Caption, outage warning, and the collapsed references under a tutor reply."""
    caption = reply_caption(meta)
    if caption:
        st.caption(caption)
    if done and done.get("degraded"):
        st.warning("The tutor model was unavailable, so this is course material only.")
    render_references((done or {}).get("citations") or [])


def show_answer_button(chat: dict) -> bool:
    if chat["offer"]:
        st.caption("Stuck for a while is normal. You can see the full answer whenever you like.")
    return st.button(
        "Show answer",
        key="show_answer",
        icon=":material/visibility:",
        type="primary" if chat["offer"] else "secondary",
        help="Available after your first hint. No need to justify, just ask.",
    )


def render_steps(record: dict) -> None:
    """The collapsed step summary of a finished turn."""
    if record.get("steps"):
        label = steps_summary(record["steps"], record.get("elapsed"))
        with st.status(label, state="complete", expanded=False):
            st.markdown(steps_markdown(record["steps"]))


def render_thread(chat: dict, stale: bool) -> bool:
    """Draw past messages. Returns True when Show answer (under the latest reply) was clicked."""
    messages = chat["messages"]
    latest = max((i for i, m in enumerate(messages) if m["role"] == "assistant"), default=-1)
    allow_show = chat["can_show"] and not chat["pending"] and not stale
    clicked = False
    for i, m in enumerate(messages):
        with st.chat_message(m["role"], avatar=AVATARS[m["role"]]):
            render_steps(m)
            st.markdown(m["content"])
            if m["role"] == "assistant":
                render_footer(m.get("meta"), m.get("done"))
                if i == latest and allow_show:
                    clicked = show_answer_button(chat)
    return clicked


def permission_prompt(chat: dict) -> tuple[bool, bool]:
    """The tutor will not run the learner's code without asking. Returns (approve, decline)."""
    pending = chat["pending"]
    with st.chat_message("assistant", avatar=AVATARS["assistant"]):
        render_steps(pending)
        st.markdown(f"**{pending['message']}**")
        st.caption("It runs in a restricted sandbox with no network and shows what happened.")
        st.code(pending.get("code", ""), language="python")
        st.checkbox(
            "Remember my choice for this chat", value=True, key=f"remember_{chat['session_id']}"
        )
        left, right = st.columns(2)
        approve = left.button(
            "Run my code", key="approve_run", type="primary", icon=":material/play_arrow:"
        )
        decline = right.button("Don't run it", key="decline_run")
    return approve, decline


def code_box(chat: dict) -> str:
    """Collapsed "Your code" box. Each chat keeps its own text."""
    lines = len(chat["code"].splitlines())
    label = f"Your code ({lines} line{'' if lines == 1 else 's'})" if lines else "Your code"
    with st.expander(label, icon=":material/code:"):
        chat["code"] = st.text_area(
            "Paste the code you are working on",
            value=chat["code"],
            key=f"code_{chat['session_id']}",
            height=220,
            label_visibility="collapsed",
            placeholder="# paste your code here",
        )
    return chat["code"]


# ---------- voice ----------


def transcribe(client, chat: dict, text: str, audio) -> None:
    """A recording from the chat input becomes an editable transcript, never a sent message."""
    try:
        heard = client.transcribe(audio.getvalue(), audio.name or "speech.wav", audio.type)
    except ApiError as exc:
        chat["voice_note"] = f"{error_text(exc, VOICE_ERRORS)} You can type your question instead."
        return
    chat["transcript"] = " ".join(part for part in (text, heard) if part)
    st.session_state.pop(f"transcript_{chat['session_id']}", None)  # show the new text


def discard_transcript(chat: dict) -> None:
    chat["transcript"] = None
    st.session_state.pop(f"transcript_{chat['session_id']}", None)


def transcript_box(chat: dict) -> str | None:
    """Show 'Heard: ...' for editing. Returns the text when the learner clicks Send.

    Each chat keeps its own transcript, so switching chats never carries one across.
    """
    if chat["voice_note"]:
        st.warning(chat["voice_note"])
        chat["voice_note"] = None
    if not chat["transcript"]:
        return None
    with st.container(border=True):
        chat["transcript"] = st.text_area(
            "Heard (edit before sending)",
            value=chat["transcript"],
            key=f"transcript_{chat['session_id']}",
            height=80,
        )
        left, right = st.columns(2)
        send = left.button("Send", key="send_transcript", type="primary", icon=":material/send:")
        right.button("Discard", key="discard_transcript", on_click=discard_transcript, args=(chat,))
    if not send:
        return None
    text = (chat["transcript"] or "").strip()
    discard_transcript(chat)
    return text or None


def read_chat_input(client, chat: dict, voice: bool) -> str | None:
    value = st.chat_input("What are you stuck on?", accept_audio=voice)
    if value is None or isinstance(value, str):
        return value or None
    if value.audio is not None:
        transcribe(client, chat, value.text, value.audio)
        st.rerun()  # show the transcript box above the input
    return value.text or None


# ---------- one turn ----------


def stream_reply(events) -> dict:
    """Show live steps in a status box, then stream the reply below it.

    The box collapses to "Worked for N s · K steps" when the first token arrives.
    Returns {text, meta, done, approval, steps, elapsed}.
    """
    out: dict = {"meta": None, "done": None, "approval": None, "steps": {}, "elapsed": None}
    started = time.monotonic()
    slot = st.empty()
    box: dict = {}

    def show_steps() -> None:
        if "status" not in box:
            box["status"] = slot.status("Working on it", expanded=True)
            box["body"] = box["status"].empty()
        box["body"].markdown(steps_markdown(list(out["steps"].values())))

    def close_steps() -> None:
        if out["elapsed"] is None:
            out["elapsed"] = time.monotonic() - started
            if "status" in box:
                label = steps_summary(list(out["steps"].values()), out["elapsed"])
                box["status"].update(label=label, state="complete", expanded=False)

    def tokens():
        for kind, data in events:
            if kind == "step":
                out["steps"][data["key"]] = data
                show_steps()
            elif kind == "meta":
                out["meta"] = data
            elif kind == "token":
                close_steps()
                yield data["text"]
            elif kind == "approval":
                out["approval"] = data
            elif kind == "done":
                out["done"] = data
            elif kind == "error":
                if "status" in box:
                    box["status"].update(label="Something went wrong", state="error")
                raise ApiError(data.get("message", "error"), status=500)
        close_steps()

    out["text"] = str(st.write_stream(tokens()) or "")
    out["steps"] = list(out["steps"].values())
    return out


def apply_result(chat: dict, result: dict) -> None:
    meta, done = result["meta"], result["done"]
    if result["text"]:
        chat["messages"].append(
            {
                "role": "assistant",
                "content": result["text"],
                "meta": meta,
                "done": done,
                "steps": result["steps"],
                "elapsed": result["elapsed"],
            }
        )
    approval = result["approval"]
    # The steps that led to the question are shown with the permission prompt.
    chat["pending"] = approval and {
        **approval,
        "steps": result["steps"],
        "elapsed": result["elapsed"],
    }
    if done and done.get("stage"):
        chat["stage"] = done["stage"]
    if meta:
        hints = (done or {}).get("hints_given", 0)
        chat["can_show"] = bool(meta.get("can_show_answer")) or hints >= 1
        chat["offer"] = bool(meta.get("offer_answer"))
        if meta.get("mode") == "reveal":
            chat["can_show"], chat["offer"] = False, False


def run_turn(
    chat: dict, user_text: str | None, events, learner: str | None = None
) -> ApiError | None:
    """Stream one turn. A turn sent with a learner token binds the chat to it once it succeeds.

    Returns the error when the call failed, so the caller can decide what to keep.
    """
    if user_text:
        chat["messages"].append({"role": "user", "content": user_text})
        with st.chat_message("user", avatar=AVATARS["user"]):
            st.markdown(user_text)
    with st.chat_message("assistant", avatar=AVATARS["assistant"]):
        try:
            result = stream_reply(events())
        except ApiError as exc:
            if user_text:
                chat["messages"].pop()
            if exc.status == 409:  # the server holds this session for another learner
                st.session_state["turn_note"] = error_text(exc)
                start_new_chat(chat["code"])
                st.rerun()
            if exc.status == 403:
                drop_invalid_profile()
            st.error(error_text(exc))
            return exc
        render_footer(result["meta"], result["done"])
    if learner and result["done"] is not None:
        chat["learner"] = learner
    apply_result(chat, result)
    st.rerun()  # redraw the thread so only the latest reply carries Show answer


# ---------- page ----------


def main() -> None:
    st.set_page_config(page_title="CodeBuddy", page_icon=":material/school:")
    init_state()
    client = get_client()
    health = client.health()
    sidebar(client, health)

    chat = current_chat()
    learner = active_learner()
    # The server binds a session to one learner; a chat from another memory setting is read-only.
    stale = chat["learner"] is not None and chat["learner"] != learner

    st.markdown("#### Let's work it out together")
    stage_line(chat["stage"])
    show_clicked = render_thread(chat, stale)
    approve = decline = False
    if chat["pending"]:
        approve, decline = permission_prompt(chat)
    if stale:
        st.caption("Your memory setting changed, so your next message starts a new chat.")
    if st.session_state.get("turn_note"):
        st.info(st.session_state.pop("turn_note"))
    code = code_box(chat)
    prompt = transcript_box(chat)
    typed = read_chat_input(client, chat, bool(health and health.get("stt_configured")))
    prompt = prompt or typed

    session_id = chat["session_id"]
    who = {"learner_id": learner} if learner else {}
    if approve or decline:
        pending, remember = chat["pending"], st.session_state.get(f"remember_{session_id}", True)
        chat["pending"] = None
        turn_id = pending["turn_id"]
        failed = run_turn(
            chat, None, lambda: client.stream_approve(session_id, turn_id, approve, remember)
        )
        if failed is not None:
            # Unreachable or rate-limited: the server never took the request, so ask again.
            # Anything else (404: already taken or expired) drops the prompt.
            if failed.status in (None, 429):
                chat["pending"] = pending
            st.session_state["turn_note"] = error_text(failed)
            st.rerun()  # redraw so the prompt shows only if it was kept
    elif show_clicked:
        run_turn(
            chat,
            "Show me the full answer.",
            lambda: client.stream_show_answer(session_id, code or None, LANGUAGE, **who),
            learner,
        )
    elif prompt:
        if stale:
            chat = start_new_chat(code)
            session_id = chat["session_id"]
        run_turn(
            chat,
            prompt,
            lambda: client.stream_turn(session_id, prompt, code or None, LANGUAGE, **who),
            learner,
        )


main()
