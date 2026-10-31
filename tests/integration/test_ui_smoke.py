from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from codebuddy.ui.client import ApiError  # noqa: E402

APP = str(Path(__file__).parents[2] / "src" / "codebuddy" / "ui" / "app.py")
BOOK = "Think Python: How to Think Like a Computer Scientist (v2.0.17)"
STEPS = [
    ("step", {"key": "analyze_code", "label": "Reading your code", "status": "running",
              "detail": None}),
    ("step", {"key": "analyze_code", "label": "Reading your code", "status": "done",
              "detail": "3 lines"}),
    ("step", {"key": "retrieve", "label": "Searching the course material", "status": "running",
              "detail": None}),
    ("step", {"key": "retrieve", "label": "Found 2 passages", "status": "done",
              "detail": "Think Python"}),
]  # fmt: skip


class StubClient:
    def __init__(self):
        self.turns = []
        self.sessions = []
        self.hints = 0

    def health(self):
        return {"status": "ok", "cache": "memory", "models_configured": True}

    def stream_turn(self, session_id, message, code, language="python"):
        self.turns.append((message, code))
        self.sessions.append(session_id)
        self.hints += 1
        return iter(
            [
                *STEPS,
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
                        "citations": [
                            {"source": BOOK, "section": "Think Python › 2.10 Debugging"},
                            {"source": BOOK, "section": "Think Python › 7.3 The for loop"},
                        ],
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


def chats(at: AppTest) -> list[dict]:
    return at.session_state["chats"]


def current(at: AppTest) -> dict:
    sid = at.session_state["chat_id"]
    return next(c for c in chats(at) if c["session_id"] == sid)


def code_box(at: AppTest):
    return at.text_area(key=f"code_{at.session_state['chat_id']}")


def texts(at: AppTest) -> list[str]:
    return [md.value for m in at.chat_message for md in m.markdown]


def test_no_developer_widgets_and_no_show_answer_before_a_hint():
    at = make_app(StubClient())
    assert not at.exception
    assert not at.text_input and not at.selectbox
    assert not [b for b in at.button if b.key == "show_answer"]
    assert any("Connected" in c.value for c in at.sidebar.caption)


def test_turn_streams_reply_with_steps_and_collapsed_references():
    client = StubClient()
    at = make_app(client)
    code_box(at).set_value("for i in range(3):\n    pass").run()
    at.chat_input[0].set_value("my loop is wrong").run()
    assert not at.exception
    assert client.turns == [("my loop is wrong", "for i in range(3):\n    pass")]
    assert "my loop is wrong" in texts(at) and "What is i on the last pass?" in texts(at)
    assert current(at)["stage"] == "T"
    assert at.button(key="show_answer").disabled is False

    status = at.status[0]
    assert status.state == "complete" and status.label.startswith("Worked for ")
    assert status.label.endswith("2 steps") and not status.proto.expanded
    assert "Found 2 passages" in status.markdown[0].value  # the done label replaces the running one

    refs = [e for e in at.expander if e.label.startswith("References")]
    assert refs[0].label == "References (2)" and not refs[0].proto.expanded
    assert refs[0].caption[0].value == BOOK
    rows = refs[0].markdown[0].value
    assert "[1] 2.10 Debugging" in rows and "[2] 7.3 The for loop" in rows
    assert "Think Python ›" not in rows and BOOK not in rows
    assert "Your code (2 lines)" in [e.label for e in at.expander]


def test_show_answer_only_under_the_latest_reply_and_hidden_after_a_reveal():
    at = make_app(StubClient())
    at.chat_input[0].set_value("help").run()
    at.chat_input[0].set_value("still stuck").run()
    replies = [m for m in at.chat_message if m.name == "assistant"]
    assert [bool(m.button) for m in replies] == [False, True]

    at.button(key="show_answer").click().run()
    assert not at.exception
    assert "Here is the full answer." in texts(at)
    assert not [b for b in at.button if b.key == "show_answer"]


def test_new_chat_keeps_each_chats_messages_and_session():
    client = StubClient()
    at = make_app(client)
    at.chat_input[0].set_value("first question about loops").run()
    first = current(at)["session_id"]

    at.button(key="new_chat").click().run()
    assert len(chats(at)) == 2 and current(at)["session_id"] != first
    assert texts(at) == []
    at.chat_input[0].set_value("second question").run()
    second = current(at)["session_id"]
    assert client.sessions == [first, second]
    titles = [b.label for b in at.sidebar.button if b.key.startswith("chat_")]
    assert titles == ["second question", "first question about loops"]  # newest first

    at.button(key=f"chat_{first}").click().run()
    assert current(at)["session_id"] == first
    assert "first question about loops" in texts(at) and "second question" not in texts(at)
    at.chat_input[0].set_value("more on loops").run()
    assert client.sessions[-1] == first


def test_new_chat_on_an_empty_chat_does_not_pile_up_empty_chats():
    at = make_app(StubClient())
    at.button(key="new_chat").click().run()
    assert len(chats(at)) == 1


def test_long_titles_are_cut_to_40_characters():
    at = make_app(StubClient())
    at.chat_input[0].set_value("x" * 80).run()
    title = next(b.label for b in at.sidebar.button if b.key.startswith("chat_"))
    assert len(title) == 40 and title.endswith("...")


def test_each_chat_keeps_its_own_code():
    at = make_app(StubClient())
    code_box(at).set_value("print(1)").run()
    at.chat_input[0].set_value("one").run()
    first = current(at)["session_id"]
    at.button(key="new_chat").click().run()
    assert code_box(at).value == ""
    at.button(key=f"chat_{first}").click().run()
    assert code_box(at).value == "print(1)"


def test_unreachable_api_says_so_in_the_sidebar():
    client = StubClient()
    client.health = lambda: None
    at = make_app(client)
    assert any("Can't reach the tutor" in c.value for c in at.sidebar.caption)


class DroppingClient(StubClient):
    """Streams steps and one token, then the connection drops (no rerun, live widgets stay)."""

    def __init__(self, events):
        super().__init__()
        self.events = events

    def stream_turn(self, session_id, message, code, language="python"):
        def gen():
            yield from self.events
            raise ApiError("connection dropped")

        return gen()


def test_live_step_box_collapses_when_the_first_token_arrives():
    at = make_app(DroppingClient([*STEPS, ("token", {"text": "What is"})]))
    at.chat_input[0].set_value("help").run()
    assert not at.exception and at.error
    status = at.status[0]
    assert status.state == "complete" and not status.proto.expanded
    assert status.label.startswith("Worked for ") and status.label.endswith("2 steps")


def test_live_step_box_stays_open_until_a_token_and_shows_errors():
    at = make_app(DroppingClient([*STEPS[:1], ("error", {"message": "boom"})]))
    at.chat_input[0].set_value("help").run()
    status = at.status[0]
    assert status.state == "error"
    assert current(at)["messages"] == []  # the failed question is not kept


class DegradedClient(StubClient):
    """Every model tier failed: the server sent its code-written text with degraded=True."""

    def _degraded(self, mode, text):
        meta = {"mode": mode, "level": 0 if mode == "hint" else 4, "can_show_answer": True,
                "offer_answer": False, "stage": "T", "cached": False}  # fmt: skip
        done = {"citations": [], "degraded": True, "stage": "T", "hints_given": 1}
        return iter([("meta", meta), ("token", {"text": text}), ("done", done)])

    def stream_turn(self, session_id, message, code, language="python"):
        return self._degraded("hint", "Let's slow down. What should the output be?")

    def stream_show_answer(self, session_id, code, language="python"):
        return self._degraded("reveal", "I couldn't put the full answer together just now.")


TROUBLE = "The tutor had trouble answering. Try again in a moment."


def test_a_degraded_hint_shows_no_warning_and_a_degraded_reveal_keeps_show_answer():
    at = make_app(DegradedClient())
    at.chat_input[0].set_value("help").run()
    assert not at.exception and not at.warning
    at.button(key="show_answer").click().run()
    assert not at.exception
    assert [w.value for w in at.warning] == [TROUBLE]
    assert at.button(key="show_answer").disabled is False  # the learner can press it again
