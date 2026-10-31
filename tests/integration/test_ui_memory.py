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
        self.sessions = []
        self.listed = 0
        self.bound = {}  # mimics the server: a session binds to the first token it sees
        self.items = [
            {"kind": "semantic", "text": "Mixes up range bounds", "created_at": ""},
            {"kind": "episodic", "text": "Saw the full answer on loops", "created_at": ""},
        ]

    def health(self):
        return {"status": "ok", "cache": "memory", "models_configured": True,
                "stt_configured": False, "memory_enabled": self.memory_enabled}  # fmt: skip

    def bind(self, session_id, learner_id):
        bound = self.bound.get(session_id)
        if bound and bound != learner_id:
            raise ApiError("This session belongs to another learner", status=409)
        if learner_id:
            self.bound[session_id] = learner_id

    def stream_turn(self, session_id, message, code, language="python", learner_id=None):
        self.bind(session_id, learner_id)
        self.turns.append(learner_id)
        self.sessions.append(session_id)
        return iter([("meta", META), ("token", {"text": "Hmm."}), ("done", {"citations": []})])

    def stream_show_answer(self, session_id, code, language="python", learner_id=None):
        self.bind(session_id, learner_id)
        self.shows.append(learner_id)
        return iter([("token", {"text": "Answer."}), ("done", {"citations": []})])

    def new_learner(self):
        self.minted.append(f"{len(self.minted):022d}.{'m' * 43}")
        return self.minted[-1]

    def memories(self, learner_id):
        self.listed += 1
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
    assert stub.listed == 0  # the remembered items load only on request
    at.button(key="show_memories").click().run()
    assert stub.listed == 1
    assert any("Mixes up range bounds" in str(e.value) for e in at.markdown)
    at.chat_input[0].set_value("once more").run()
    assert stub.listed == 1
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


def assert_no_conflict(stub) -> None:
    """Mimic the server: a session binds to the first token it sees; after that, a turn with
    another token or none is answered with 409."""
    bound: dict = {}
    for sid, lid in zip(stub.sessions, stub.turns, strict=True):
        if sid in bound:
            assert lid == bound[sid], "the server would answer 409"
        elif lid:
            bound[sid] = lid


def test_forget_then_re_enable_uses_a_new_session():
    stub = Stub()
    at = accepted(stub)
    at.chat_input[0].set_value("hi").run()
    first = stub.sessions[-1]
    at.button(key="forget_me").click().run()
    assert first not in [c["session_id"] for c in at.session_state["chats"]]
    at.chat_input[0].set_value("no memory now").run()
    at.checkbox(key=BOX).check().run()
    at.chat_input[0].set_value("remember me again").run()
    assert stub.turns == [TOKEN, None, stub.minted[0]]
    assert stub.sessions[1] != first and stub.sessions[2] == stub.sessions[1]
    assert_no_conflict(stub)


def test_adopting_a_link_token_starts_a_new_chat():
    stub = Stub()
    at = make_app(stub, {"learner": TOKEN})
    at.chat_input[0].set_value("hi").run()
    before = stub.sessions[-1]
    at.button(key="use_profile").click().run()
    at.chat_input[0].set_value("again").run()
    assert stub.sessions[-1] != before and stub.turns == [None, TOKEN]
    assert len(at.session_state["chats"]) == 2


def test_turning_memory_off_moves_the_next_message_to_a_new_chat():
    stub = Stub()
    at = accepted(stub)
    at.chat_input[0].set_value("hi").run()
    at.checkbox(key=BOX).uncheck().run()
    assert any("starts a new chat" in c.value for c in at.caption)
    assert not [b for b in at.button if b.key == "show_answer"]
    at.chat_input[0].set_value("without memory").run()
    assert stub.turns == [TOKEN, None] and stub.sessions[0] != stub.sessions[1]
    assert_no_conflict(stub)


def test_show_answer_binds_the_chat_so_turning_memory_off_starts_a_new_chat():
    stub = Stub()
    at = make_app(stub)
    at.chat_input[0].set_value("hi").run()
    at.checkbox(key=BOX).check().run()
    at.button(key="show_answer").click().run()
    assert stub.shows == [stub.minted[0]]
    at.checkbox(key=BOX).uncheck().run()
    assert any("starts a new chat" in c.value for c in at.caption)
    at.chat_input[0].set_value("without memory").run()
    assert not at.exception and not at.error
    assert stub.turns == [None, None] and stub.sessions[0] != stub.sessions[1]


def test_a_failed_show_answer_does_not_bind_the_chat():
    stub = Stub()

    def boom(*a, **k):
        raise ApiError("down")

    stub.stream_show_answer = boom
    at = make_app(stub)
    at.chat_input[0].set_value("hi").run()
    at.checkbox(key=BOX).check().run()
    at.button(key="show_answer").click().run()
    sid = at.session_state["chat_id"]
    chat = next(c for c in at.session_state["chats"] if c["session_id"] == sid)
    assert chat["learner"] is None


def failing_turn(status):
    stub = Stub()

    def boom(*a, **k):
        raise ApiError(f'API returned {status}: {{"detail": "x"}} http://api', status=status)

    stub.stream_turn = boom
    return stub


def shown(at) -> str:
    return " ".join(str(e.value) for e in [*at.error, *at.info, *at.caption, *at.markdown])


def test_a_403_says_the_saved_profile_is_no_longer_valid():
    at = accepted(failing_turn(403))
    at.chat_input[0].set_value("hi").run()
    assert not at.exception
    assert "Your saved profile is no longer valid. Turn memory off and on again." in shown(at)
    assert "http" not in shown(at) and "detail" not in shown(at)
    at.checkbox(key=BOX).uncheck().run()
    at.checkbox(key=BOX).check().run()
    assert at.session_state["learner_id"] not in (None, TOKEN)  # a fresh token was minted


def test_a_429_asks_the_learner_to_wait():
    at = make_app(failing_turn(429))
    at.chat_input[0].set_value("hi").run()
    assert "Too many requests. Wait a minute and try again." in shown(at)
    assert "http" not in shown(at) and "detail" not in shown(at)


def test_unreachable_api_has_a_plain_message():
    at = make_app(failing_turn(None))
    at.chat_input[0].set_value("hi").run()
    assert "Can't reach the tutor. Check that it is running." in shown(at)
    assert "http" not in shown(at)


def test_a_409_starts_a_new_chat_and_says_so():
    stub = Stub()
    at = make_app(stub)
    at.chat_input[0].set_value("hi").run()
    first = at.session_state["chat_id"]
    stub.bound[first] = TOKEN  # the server holds this session for another learner
    at.chat_input[0].set_value("again").run()
    assert not at.exception
    assert at.session_state["chat_id"] != first
    assert "new chat" in shown(at) and "http" not in shown(at)
    at.chat_input[0].set_value("again").run()
    assert stub.sessions[-1] != first
