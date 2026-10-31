from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("streamlit")
import streamlit  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

from codebuddy.ui.client import ApiError  # noqa: E402

APP = str(Path(__file__).parents[2] / "src" / "codebuddy" / "ui" / "app.py")

META = {"mode": "hint", "level": 0, "can_show_answer": True, "offer_answer": False, "stage": "T"}


class Stub:
    def __init__(self):
        self.turns, self.approvals, self.transcribed = [], [], []

    def health(self):
        return {"status": "ok", "cache": "memory", "models_configured": True,
                "stt_configured": True, "tools": "local"}  # fmt: skip

    def stream_turn(self, session_id, message, code, language="python"):
        self.turns.append((message, code))
        if code and "crash" in message:
            return iter(
                [
                    (
                        "approval",
                        {
                            "turn_id": "t1",
                            "tool": "trace_python",
                            "code": code,
                            "message": "Run your code in a safe sandbox to see what happens?",
                        },
                    ),
                    ("done", {"turn_id": "t1", "awaiting_approval": True, "citations": []}),
                ]
            )
        return iter(
            [
                ("meta", META),
                ("token", {"text": "Tell me more."}),
                ("done", {"citations": [], "stage": "T", "hints_given": 1}),
            ]
        )

    def stream_approve(self, session_id, turn_id, approve, remember=True):
        self.approvals.append((turn_id, approve, remember))
        return iter(
            [
                ("meta", META),
                (
                    "token",
                    {
                        "text": "It ran and raised IndexError, so what is i?"
                        if approve
                        else "No problem. What is i on the last pass?"
                    },
                ),
                ("done", {"citations": [], "stage": "T", "hints_given": 1}),
            ]
        )

    def stream_show_answer(self, *a, **k):
        return iter([])

    def transcribe(self, audio, filename="speech.wav", content_type="audio/wav"):
        self.transcribed.append(audio)
        return "why does my loop crash"


def make_app(client) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=10)
    at.session_state["client"] = client
    return at.run()


def texts(at: AppTest) -> list[str]:
    return [md.value for m in at.chat_message for md in m.markdown]


def chat(at: AppTest) -> dict:
    sid = at.session_state["chat_id"]
    return next(c for c in at.session_state["chats"] if c["session_id"] == sid)


def code_box(at: AppTest):
    return at.text_area(key=f"code_{at.session_state['chat_id']}")


def test_permission_prompt_appears_and_approving_continues_the_turn():
    stub = Stub()
    at = make_app(stub)
    code_box(at).set_value("for i in range(4):\n    print(nums[i])").run()
    at.chat_input[0].set_value("my loop will crash").run()
    assert not at.exception
    assert chat(at)["pending"]["turn_id"] == "t1"
    assert at.button(key="approve_run") is not None and at.button(key="decline_run") is not None
    assert not [t for t in texts(at) if "IndexError" in t]  # nothing said before the decision

    at.button(key="approve_run").click().run()
    assert not at.exception
    assert stub.approvals == [("t1", True, True)]
    assert any("IndexError" in t for t in texts(at))
    assert chat(at)["pending"] is None


def test_declining_continues_without_running():
    stub = Stub()
    at = make_app(stub)
    code_box(at).set_value("print(nums[9])").run()
    at.chat_input[0].set_value("it will crash").run()
    at.button(key="decline_run").click().run()
    assert stub.approvals == [("t1", False, True)]
    assert any(t.startswith("No problem") for t in texts(at))


def transcript_key(at: AppTest) -> str:
    return f"transcript_{at.session_state['chat_id']}"


def seeded(stub, text: str) -> AppTest:
    at = make_app(stub)
    chat(at)["transcript"] = text
    return at.run()


def test_transcript_can_be_edited_before_sending():
    stub = Stub()
    at = seeded(stub, "why is my loop wrong")
    assert at.text_area(key=transcript_key(at)).value == "why is my loop wrong"
    at.text_area(key=transcript_key(at)).set_value("why is my for loop off by one").run()
    at.button(key="send_transcript").click().run()
    assert not at.exception
    assert stub.turns == [("why is my for loop off by one", None)]
    assert not chat(at)["transcript"]
    assert "why is my for loop off by one" in texts(at)


def test_transcript_can_be_discarded():
    stub = Stub()
    at = seeded(stub, "noise")
    at.button(key="discard_transcript").click().run()
    assert not at.exception and stub.turns == []
    assert not [t for t in at.text_area if t.key == transcript_key(at)]
    assert not chat(at)["transcript"]


@pytest.fixture
def recordings(monkeypatch):
    """AppTest cannot submit audio, so the next chat_input call returns a queued recording."""
    queue: list = []
    real = streamlit.chat_input

    def chat_input(*args, **kwargs):
        value = real(*args, **kwargs)
        if queue:
            audio = SimpleNamespace(getvalue=lambda: b"RIFF", name="speech.wav", type="audio/wav")
            return SimpleNamespace(text=queue.pop(0), audio=audio)
        return value

    monkeypatch.setattr(streamlit, "chat_input", chat_input)
    return queue


def test_a_transcript_stays_with_the_chat_it_was_heard_in(recordings):
    stub = Stub()
    at = make_app(stub)
    at.chat_input[0].set_value("hi").run()
    first = at.session_state["chat_id"]
    recordings.append("")
    at.run()
    assert not at.exception
    assert at.text_area(key=f"transcript_{first}").value == "why does my loop crash"

    at.button(key="new_chat").click().run()
    assert at.session_state["chat_id"] != first
    assert not [t for t in at.text_area if t.key.startswith("transcript_")]

    at.button(key=f"chat_{first}").click().run()
    assert at.text_area(key=f"transcript_{first}").value == "why does my loop crash"


def test_turned_off_voice_has_its_own_sentence(recordings):
    stub = Stub()

    def off(*a, **k):
        raise ApiError("API returned 503", status=503)

    stub.transcribe = off
    at = make_app(stub)
    recordings.append("")
    at.run()
    assert not at.exception
    warnings = [w.value for w in at.warning]
    assert warnings == ["Voice input is off on this server. You can type your question instead."]


def test_remember_my_choice_is_per_chat():
    stub = Stub()
    at = make_app(stub)
    code_box(at).set_value("print(nums[9])").run()
    at.chat_input[0].set_value("it will crash").run()
    first = at.session_state["chat_id"]
    at.checkbox(key=f"remember_{first}").uncheck().run()
    at.button(key="approve_run").click().run()
    assert stub.approvals == [("t1", True, False)]

    at.button(key="new_chat").click().run()
    code_box(at).set_value("print(nums[9])").run()
    at.chat_input[0].set_value("it will crash").run()
    assert at.checkbox(key=f"remember_{at.session_state['chat_id']}").value is True
    at.button(key="approve_run").click().run()
    assert stub.approvals == [("t1", True, False), ("t1", True, True)]


def test_remember_my_choice_survives_switching_chats():
    stub = Stub()
    at = make_app(stub)
    code_box(at).set_value("print(nums[9])").run()
    at.chat_input[0].set_value("it will crash").run()
    first = at.session_state["chat_id"]
    at.checkbox(key=f"remember_{first}").uncheck().run()

    at.button(key="new_chat").click().run()
    assert at.session_state["chat_id"] != first
    at.button(key=f"chat_{first}").click().run()
    assert at.checkbox(key=f"remember_{first}").value is False
    at.button(key="approve_run").click().run()
    assert stub.approvals == [("t1", True, False)]


def failed_approval(status, reached=None) -> tuple[Stub, AppTest]:
    stub = Stub()

    def boom(*a, **k):
        raise ApiError(f"API returned {status}", status=status, reached=reached)

    stub.stream_approve = boom
    at = make_app(stub)
    code_box(at).set_value("print(nums[9])").run()
    at.chat_input[0].set_value("it will crash").run()
    return stub, at.button(key="approve_run").click().run()


def test_an_unreachable_approval_keeps_the_prompt():
    _, at = failed_approval(None)
    assert not at.exception
    assert chat(at)["pending"]["turn_id"] == "t1"
    assert at.button(key="approve_run") is not None
    assert "Can't reach the tutor. Check that it is running." in [i.value for i in at.info]


def test_an_expired_approval_says_so_and_drops_the_prompt():
    _, at = failed_approval(404)
    assert not at.exception
    assert chat(at)["pending"] is None
    assert not [b for b in at.button if b.key in ("approve_run", "decline_run")]
    assert "That request expired. Send your message again." in [i.value for i in at.info]


def test_a_rate_limited_approval_keeps_the_prompt():
    _, at = failed_approval(429)
    assert not at.exception
    assert chat(at)["pending"]["turn_id"] == "t1"
    assert at.button(key="approve_run") is not None
    assert "Too many requests. Wait a minute and try again." in [i.value for i in at.info]


def test_an_approval_dropped_after_the_server_took_it_drops_the_prompt():
    _, at = failed_approval(None, reached=True)
    assert not at.exception
    assert chat(at)["pending"] is None
    assert not [b for b in at.button if b.key in ("approve_run", "decline_run")]
    assert "That request expired. Send your message again." in [i.value for i in at.info]


def test_a_404_on_a_normal_turn_shows_the_generic_sentence():
    stub = Stub()

    def gone(*a, **k):
        raise ApiError("API returned 404", status=404)

    stub.stream_turn = gone
    at = make_app(stub)
    at.chat_input[0].set_value("hello").run()
    assert not at.exception
    assert [e.value for e in at.error] == ["Something went wrong. Please try again."]


def test_chat_input_accepts_audio_only_when_voice_is_configured():
    stub = Stub()
    at = make_app(stub)
    assert at.chat_input[0].proto.accept_audio is True
    stub.health = lambda: {"status": "ok", "stt_configured": False}
    at.run()
    assert at.chat_input[0].proto.accept_audio is False
