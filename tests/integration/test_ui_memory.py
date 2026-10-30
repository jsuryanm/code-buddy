from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from codebuddy.ui.client import ApiError  # noqa: E402

APP = str(Path(__file__).parents[2] / "src" / "codebuddy" / "ui" / "app.py")
META = {"mode": "hint", "level": 0, "can_show_answer": True, "offer_answer": False, "stage": "T"}
BOX = "remember_me"
TOKEN = "t" * 22 + "." + "s" * 43


class Stub:
    def __init__(self, memory_enabled=True):
        self.memory_enabled = memory_enabled
        self.turns, self.shows, self.forgotten, self.minted = [], [], [], []
        self.items = [
            {"kind": "semantic", "text": "Mixes up range bounds", "created_at": ""},
            {"kind": "episodic", "text": "Saw the full answer on loops", "created_at": ""},
        ]

    def health(self):
        return {"status": "ok", "cache": "memory", "models_configured": True,
                "stt_configured": False, "memory_enabled": self.memory_enabled}  # fmt: skip

    def stream_turn(self, session_id, message, code, language="python", learner_id=None):
        self.turns.append(learner_id)
        return iter([("meta", META), ("token", {"text": "Hmm."}), ("done", {"citations": []})])

    def stream_show_answer(self, session_id, code, language="python", learner_id=None):
        self.shows.append(learner_id)
        return iter([("token", {"text": "Answer."}), ("done", {"citations": []})])

    def new_learner(self):
        self.minted.append(f"{len(self.minted):022d}.{'m' * 43}")
        return self.minted[-1]

    def memories(self, learner_id):
        return self.items

    def forget(self, learner_id):
        self.forgotten.append(learner_id)
        return len(self.items)


def make_app(client, query=None) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=10)
    at.session_state["client"] = client
    if query:
        at.query_params.update(query)
    return at.run()


def test_box_is_hidden_when_memory_is_disabled():
    at = make_app(Stub(memory_enabled=False))
    assert not at.exception
    assert not [c for c in at.checkbox if c.key == BOX]


def test_enabling_asks_the_server_for_a_token_and_turns_carry_it():
    stub = Stub()
    at = make_app(stub)
    assert at.checkbox(key=BOX).value is False
    at.chat_input[0].set_value("hi").run()
    assert stub.turns == [None]

    at.checkbox(key=BOX).check().run()
    lid = at.session_state["learner_id"]
    assert stub.minted == [lid] and at.query_params["learner"] == lid
    at.chat_input[0].set_value("again").run()
    assert stub.turns == [None, lid]
    at.button(key="show_answer").click().run()
    assert stub.shows == [lid]
    assert any("Mixes up range bounds" in str(e.value) for e in at.markdown)
    assert stub.minted == [lid]


def test_the_ui_never_generates_ids_itself():
    assert "secrets" not in Path(APP).read_text()


def test_a_url_token_does_not_enable_memory_until_the_learner_accepts_it():
    stub = Stub()
    at = make_app(stub, {"learner": TOKEN})
    assert at.checkbox(key=BOX).value is False
    assert any("contains a saved learner profile" in str(e.value) for e in at.sidebar.markdown)
    at.chat_input[0].set_value("hi").run()
    assert stub.turns == [None] and stub.minted == []
    at.button(key="use_profile").click().run()
    assert at.checkbox(key=BOX).value is True and at.session_state["learner_id"] == TOKEN
    at.chat_input[0].set_value("again").run()
    assert stub.turns == [None, TOKEN] and stub.minted == []


def test_ticking_the_box_with_a_url_token_mints_a_new_one():
    stub = Stub()
    at = make_app(stub, {"learner": TOKEN})
    at.checkbox(key=BOX).check().run()
    assert at.session_state["learner_id"] == stub.minted[0] != TOKEN
    assert at.query_params["learner"] == stub.minted[0]


def test_mint_failure_is_shown_and_leaves_memory_off():
    stub = Stub()

    def boom():
        raise ApiError("down")

    stub.new_learner = boom
    at = make_app(stub)
    at.checkbox(key=BOX).check().run()
    assert not at.exception and at.sidebar.error
    assert at.checkbox(key=BOX).value is False
    at.chat_input[0].set_value("hi").run()
    assert stub.turns == [None]


def accepted(stub) -> AppTest:
    at = make_app(stub, {"learner": TOKEN})
    return at.button(key="use_profile").click().run()


def test_forget_me_deletes_and_clears_state():
    stub = Stub()
    at = accepted(stub)
    at.button(key="forget_me").click().run()
    assert not at.exception
    assert stub.forgotten == [TOKEN]
    assert at.checkbox(key=BOX).value is False
    assert not at.session_state["learner_id"] and "learner" not in at.query_params
    assert any("2" in str(e.value) and "deleted" in str(e.value) for e in at.sidebar.markdown)
    at.chat_input[0].set_value("hi").run()
    assert stub.turns == [None]


def test_forget_failure_is_shown_not_raised():
    stub = Stub()

    def boom(_):
        raise ApiError("down")

    stub.forget = boom
    at = accepted(stub)
    at.button(key="forget_me").click().run()
    assert not at.exception and at.sidebar.error
