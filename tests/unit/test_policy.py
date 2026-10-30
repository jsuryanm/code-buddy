import pytest

from codebuddy.pedagogy.frustration import Signals, asks_for_answer, detect_signals
from codebuddy.pedagogy.policy import decide_mode
from codebuddy.schemas import HintLevel, Intent, Mode, SessionProgress


def progress(**kw) -> SessionProgress:
    return SessionProgress(session_id="s", **kw)


def test_first_debug_turn_is_diagnostic_question():
    d = decide_mode(Intent.DEBUG_HELP, progress(), Signals(), now=0)
    assert d.mode is Mode.HINT and d.level is HintLevel.DIAGNOSE
    assert not d.can_show_answer and not d.offer_answer


@pytest.mark.parametrize("given,expected", [(0, 0), (1, 1), (2, 2), (3, 3), (4, 3), (9, 3)])
def test_ladder_advances_but_never_reveals_by_itself(given, expected):
    d = decide_mode(Intent.DEBUG_HELP, progress(hints_given=given), Signals(), now=0)
    assert d.mode is Mode.HINT and d.level == expected


def test_show_answer_available_after_first_hint():
    d = decide_mode(Intent.DEBUG_HELP, progress(hints_given=1), Signals(), now=0)
    assert d.can_show_answer


def test_explicit_request_reveals_even_on_first_turn():
    d = decide_mode(Intent.SHOW_ANSWER, progress(), Signals(), now=0)
    assert d.mode is Mode.REVEAL and d.level is HintLevel.REVEAL


def test_turn_cap_offers_answer():
    d = decide_mode(Intent.DEBUG_HELP, progress(hints_given=4), Signals(), now=0, max_turns=4)
    assert d.offer_answer and d.can_show_answer


def test_time_cap_offers_answer():
    d = decide_mode(
        Intent.DEBUG_HELP, progress(hints_given=1, started_at=100.0), Signals(), now=100.0 + 601
    )
    assert d.offer_answer


def test_frustration_offers_answer_early():
    d = decide_mode(Intent.DEBUG_HELP, progress(hints_given=1), Signals(give_up_phrase=True), now=0)
    assert d.offer_answer


def test_concept_question_is_explained_directly():
    assert decide_mode(Intent.CONCEPT_QUESTION, progress(), Signals(), 0).mode is Mode.EXPLAIN


def test_off_topic_redirects():
    assert decide_mode(Intent.OFF_TOPIC, progress(), Signals(), 0).mode is Mode.REDIRECT


@pytest.mark.parametrize(
    "text", ["just show me the answer", "Give me the solution", "show the full answer please"]
)
def test_asks_for_answer(text):
    assert asks_for_answer(text)


def test_does_not_treat_ordinary_question_as_answer_request():
    assert not asks_for_answer("why is my loop off by one?")


def test_signals_from_progress_and_phrases():
    s = detect_signals("I give up", progress(hints_given=3, repeated_submissions=2))
    assert s.give_up_phrase and s.hints_without_progress and s.repeated_submission
    assert not detect_signals("hello", progress()).any
