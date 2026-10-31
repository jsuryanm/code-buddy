import pytest

from codebuddy.agent.code_analysis import analyze
from codebuddy.pedagogy.frustration import Signals, asks_for_answer, detect_signals
from codebuddy.pedagogy.policy import decide_mode, fixed_it
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


# -- fixed detection and CONFIRM -------------------------------------------------------

BUGGY = "nums = [1, 2]\nfor i in range(len(nums) + 1):\n    print(nums[i])\n"
FIXED = "nums = [1, 2]\nfor i in range(len(nums)):\n    print(nums[i])\n"


def test_fixed_when_the_pattern_is_gone_and_the_code_changed():
    p = progress(last_patterns=["off_by_one_range"])
    assert fixed_it(p, analyze(FIXED), code_changed=True)
    assert fixed_it(p, analyze(FIXED), True, {"ran": True, "error": None, "timed_out": False})


@pytest.mark.parametrize(
    "last,code,changed,runtime",
    [
        (["off_by_one_range"], BUGGY, True, None),  # pattern still present
        (["off_by_one_range"], FIXED, False, None),  # code unchanged
        (["off_by_one_range"], "for i in range(3)\n    pass\n", True, None),  # parse error
        ([], FIXED, True, None),  # nothing was wrong before
        (["off_by_one_range"], FIXED, True, {"ran": True, "error": {"type": "IndexError"}}),
        (["off_by_one_range"], FIXED, True, {"ran": True, "error": None, "timed_out": True}),
    ],
)
def test_not_fixed(last, code, changed, runtime):
    assert not fixed_it(progress(last_patterns=last), analyze(code), changed, runtime)


def test_saying_it_is_fixed_is_not_enough():
    p = progress(last_patterns=["off_by_one_range"])
    assert not fixed_it(p, analyze(None), code_changed=False)


def test_fixed_signal_confirms_and_offers_a_quiz_by_concept():
    p = progress(hints_given=2, last_patterns=["off_by_one_range"])
    d = decide_mode(Intent.DEBUG_HELP, p, Signals(fixed=True), now=0)
    assert d.mode is Mode.CONFIRM and d.offer_quiz and d.quiz_concept == "loop bounds"
    assert not d.offer_answer and not d.can_show_answer


def test_explicit_reveal_beats_fixed_and_a_new_problem_is_not_a_fix():
    p = progress(last_patterns=["off_by_one_range"])
    assert decide_mode(Intent.SHOW_ANSWER, p, Signals(fixed=True), now=0).mode is Mode.REVEAL
    assert decide_mode(Intent.PROBLEM_START, p, Signals(fixed=True), now=0).mode is Mode.HINT


def test_fixed_is_not_a_frustration_signal():
    assert not Signals(fixed=True).any
    assert detect_signals("ok", progress(), fixed=True).fixed
