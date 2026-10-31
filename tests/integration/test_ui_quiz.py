from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).parents[2] / "src" / "codebuddy" / "ui" / "app.py")
BUGGY = "for i in range(len(xs) + 1):\n    print(xs[i])\n"
FIXED = "for i in range(len(xs)):\n    print(xs[i])\n"
SNIPPET = 'letters = ["a"]\nfor i in range(len(letters) + 1):\n    print(letters[i])\n'
NEXT = "scores = [70]\nfor i in range(len(scores) + 1):\n    print(scores[i])\n"


def meta(mode, **kw):
    base = {"mode": mode, "level": None, "can_show_answer": False, "offer_answer": False,
            "offer_quiz": False, "quiz_concept": None, "quiz": None, "quiz_code": None,
            "stage": "T", "cached": False}  # fmt: skip
    return {**base, **kw}


def reply(m, text):
    return iter([("meta", m), ("token", {"text": text}), ("done", {"stage": "T"})])


class QuizStub:
    def __init__(self):
        self.turns, self.actions, self.quizzes, self.finish = [], [], 0, False

    def health(self):
        return {"status": "ok", "models_configured": True}

    def stream_turn(self, session_id, message, code, language="python", action=None):
        self.turns.append((message, code))
        self.actions.append(action)
        if code == FIXED:
            return reply(meta("confirm", offer_quiz=True, quiz_concept="loop bounds"), "Fixed!")
        if action == "stop":
            return reply(meta("quiz"), "Quiz stopped. You got 0 of 1.")
        if self.finish:
            return reply(meta("quiz"), "Correct.\n\nQuiz finished: you got 5 of 5.")
        quiz = {"index": 1, "total": 5, "difficulty": "easy", "score": 0}
        if action == "skip":
            return reply(meta("quiz", quiz=quiz, quiz_code=NEXT), "Here is one way. Quiz 2")
        return reply(meta("hint", level=0, can_show_answer=True), "What is i?")

    def stream_quiz(self, session_id):
        self.quizzes += 1
        quiz = {"index": 0, "total": 5, "difficulty": "easy", "score": 0}
        return reply(meta("quiz", quiz=quiz, quiz_code=SNIPPET), "Quiz 1 of 5 (easy).")


def start(stub) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=10)
    at.session_state["client"] = stub
    return at.run()


def code_box(at):
    return at.text_area(key=f"code_{at.session_state['chat_id']}")


def keys(at) -> set[str]:
    return {b.key for b in at.button}


def send(at, code, text):
    code_box(at).set_value(code).run()
    at.chat_input[0].set_value(text).run()


def test_try_a_quiz_appears_only_after_a_confirmed_fix():
    at = start(QuizStub())
    send(at, BUGGY, "my loop crashes")
    assert "try_quiz" not in keys(at) and "show_answer" in keys(at)  # the stub enables it
    send(at, FIXED, "like this?")
    assert not at.exception
    assert "try_quiz" in keys(at) and "show_answer" not in keys(at)
    assert "You fixed it" in [c.value for m in at.chat_message for c in m.caption]


def test_quiz_click_streams_question_one_into_the_code_box_and_shows_quiz_controls():
    stub = QuizStub()
    at = start(stub)
    send(at, FIXED, "like this?")  # the stub confirms any fixed code
    at.button(key="try_quiz").click().run()
    assert not at.exception and stub.quizzes == 1
    assert code_box(at).value == SNIPPET
    assert "Quiz 1 of 5 (easy)" in [c.value for m in at.chat_message for c in m.caption]
    assert {"skip_question", "stop_quiz"} <= keys(at) and "try_quiz" not in keys(at)
    assert "show_answer" not in keys(at)


def test_skip_moves_on_and_stop_ends_the_quiz():
    stub = QuizStub()
    at = start(stub)
    send(at, FIXED, "like this?")
    at.button(key="try_quiz").click().run()
    at.button(key="skip_question").click().run()
    assert stub.turns[-1] == ("Skip this question.", SNIPPET) and stub.actions[-1] == "skip"
    assert code_box(at).value == NEXT
    assert "Quiz 2 of 5 (easy)" in [c.value for m in at.chat_message for c in m.caption]
    at.button(key="stop_quiz").click().run()
    assert stub.turns[-1][0] == "Stop the quiz." and stub.actions[-1] == "stop"
    assert not ({"skip_question", "stop_quiz", "try_quiz"} & keys(at))


def test_stop_restores_the_learners_own_code():
    at = start(QuizStub())
    send(at, FIXED, "like this?")
    at.button(key="try_quiz").click().run()
    assert code_box(at).value == SNIPPET
    at.button(key="stop_quiz").click().run()
    assert not at.exception and code_box(at).value == FIXED


def test_the_summary_restores_the_learners_own_code():
    stub = QuizStub()
    at = start(stub)
    send(at, FIXED, "like this?")
    at.button(key="try_quiz").click().run()
    stub.finish = True
    at.chat_input[0].set_value("done").run()
    assert not at.exception and code_box(at).value == FIXED


def test_show_answer_follows_the_server_not_the_hint_count():
    class Early(QuizStub):
        def stream_turn(self, session_id, message, code, language="python", action=None):
            done = ("done", {"stage": "T", "hints_given": 1})
            return iter([("meta", meta("hint", level=0)), ("token", {"text": "Q?"}), done])

    at = start(Early())
    send(at, BUGGY, "my loop crashes")
    assert "show_answer" not in keys(at)  # one hint is not enough any more
