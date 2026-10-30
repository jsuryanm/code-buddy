from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

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


def test_transcript_can_be_edited_before_sending():
    stub = Stub()
    at = AppTest.from_file(APP, default_timeout=10)
    at.session_state["client"] = stub
    at.session_state["transcript"] = "why is my loop wrong"
    at.session_state["transcript_edit"] = "why is my loop wrong"
    at.run()
    assert at.text_area(key="transcript_edit").value == "why is my loop wrong"
    at.text_area(key="transcript_edit").set_value("why is my for loop off by one").run()
    at.button(key="send_transcript").click().run()
    assert not at.exception
    assert stub.turns == [("why is my for loop off by one", None)]
    assert "transcript" not in at.session_state or not at.session_state["transcript"]
    assert "why is my for loop off by one" in texts(at)


def test_transcript_can_be_discarded():
    stub = Stub()
    at = AppTest.from_file(APP, default_timeout=10)
    at.session_state["client"] = stub
    at.session_state["transcript"] = "noise"
    at.session_state["transcript_edit"] = "noise"
    at.run()
    at.button(key="discard_transcript").click().run()
    assert not at.exception and stub.turns == []
    assert not [t for t in at.text_area if t.key == "transcript_edit"]


def test_chat_input_accepts_audio_only_when_voice_is_configured():
    stub = Stub()
    at = make_app(stub)
    assert at.chat_input[0].proto.accept_audio is True
    stub.health = lambda: {"status": "ok", "stt_configured": False}
    at.run()
    assert at.chat_input[0].proto.accept_audio is False
