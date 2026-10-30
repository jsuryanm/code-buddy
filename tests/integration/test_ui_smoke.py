from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).parents[2] / "src" / "codebuddy" / "ui" / "app.py")


class StubClient:
    def __init__(self):
        self.turns = []
        self.hints = 0

    def health(self):
        return {"status": "ok", "cache": "memory", "models_configured": True}

    def stream_turn(self, session_id, message, code, language="python"):
        self.turns.append((message, code))
        self.hints += 1
        return iter(
            [
                (
                    "meta",
                    {
                        "mode": "hint",
                        "level": 0,
                        "can_show_answer": self.hints >= 1,
                        "offer_answer": False,
                        "stage": "T",
                        "cached": False,
                    },
                ),
                ("token", {"text": "What is i on the last pass?"}),
                (
                    "done",
                    {
                        "citations": [{"source": "Sample", "section": "Loops"}],
                        "degraded": False,
                        "stage": "T",
                        "hints_given": self.hints,
                    },
                ),
            ]
        )

    def stream_show_answer(self, session_id, code, language="python"):
        return iter(
            [
                (
                    "meta",
                    {
                        "mode": "reveal",
                        "level": 4,
                        "can_show_answer": True,
                        "offer_answer": False,
                        "stage": "T",
                        "cached": False,
                    },
                ),
                ("token", {"text": "Here is the full answer."}),
                ("done", {"citations": [], "degraded": False, "stage": "T", "hints_given": 0}),
            ]
        )


def make_app(client) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=10)
    at.session_state["client"] = client
    return at.run()


def test_page_renders_with_show_answer_disabled():
    at = make_app(StubClient())
    assert not at.exception
    assert at.button(key="show_answer").disabled is True


def test_turn_streams_reply_and_enables_show_answer():
    client = StubClient()
    at = make_app(client)
    at.text_area(key="code").set_value("for i in range(3):\n    pass").run()
    at.chat_input[0].set_value("my loop is wrong").run()
    assert not at.exception
    assert client.turns == [("my loop is wrong", "for i in range(3):\n    pass")]
    contents = [m.markdown[0].value for m in at.chat_message if m.markdown]
    assert "my loop is wrong" in contents and "What is i on the last pass?" in contents
    assert at.session_state["stage"] == "T"
    assert at.button(key="show_answer").disabled is False


def test_show_answer_click_reveals_and_disables_button_again():
    at = make_app(StubClient())
    at.chat_input[0].set_value("help").run()
    at.button(key="show_answer").click().run()
    assert not at.exception
    contents = [m.markdown[0].value for m in at.chat_message if m.markdown]
    assert "Here is the full answer." in contents
    assert at.button(key="show_answer").disabled is True
