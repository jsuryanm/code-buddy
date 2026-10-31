import pytest

from codebuddy.agent.code_analysis import analyze
from codebuddy.config import Settings
from codebuddy.pedagogy.frustration import Signals, asks_for_answer, detect_signals
from codebuddy.pedagogy.policy import decide_mode, fixed_it, shape
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


@pytest.mark.parametrize("given,enabled", [(0, False), (1, False), (3, False), (4, True)])
def test_show_answer_is_enabled_after_the_fourth_hint(given, enabled):
    d = decide_mode(Intent.DEBUG_HELP, progress(hints_given=given), Signals(), now=0)
    assert d.can_show_answer is enabled


@pytest.mark.parametrize(
    "signals,started",
    [(Signals(give_up_phrase=True), 0.0), (Signals(repeated_submission=True), 0.0),
     (Signals(), 100.0)],
)  # fmt: skip
def test_early_triggers_enable_show_answer_before_four_hints(signals, started):
    p = progress(hints_given=1, started_at=started)
    d = decide_mode(Intent.DEBUG_HELP, p, signals, now=started + 601)
    assert d.can_show_answer and d.offer_answer


def test_explicit_request_reveals_even_on_first_turn():
    d = decide_mode(Intent.SHOW_ANSWER, progress(), Signals(), now=0)
    assert d.mode is Mode.REVEAL and d.level is HintLevel.REVEAL


def test_turn_cap_offers_answer():
    d = decide_mode(Intent.DEBUG_HELP, progress(hints_given=3), Signals(), now=0, max_turns=3)
    assert d.offer_answer and d.can_show_answer


def test_ladder_turn_cap_defaults_to_six():
    assert Settings().ladder_max_turns == 6
    assert not decide_mode(
        Intent.DEBUG_HELP, progress(hints_given=5), Signals(), now=0
    ).offer_answer
    assert decide_mode(Intent.DEBUG_HELP, progress(hints_given=6), Signals(), now=0).offer_answer


@pytest.mark.parametrize(
    "given,offered", [(0, False), (1, False), (2, False), (4, False), (5, True), (6, True)]
)
def test_answer_is_offered_after_five_hints(given, offered):
    signals = detect_signals("still stuck", progress(hints_given=given))
    assert signals.hints_without_progress is offered
    d = decide_mode(Intent.DEBUG_HELP, progress(hints_given=given), signals, now=0)
    assert d.offer_answer is offered and d.can_show_answer is (given >= 4)
    assert d.level == min(given, 3)  # hints 4 and 5 stay at level 3


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
    s = detect_signals("I give up", progress(hints_given=5, repeated_submissions=2))
    assert s.give_up_phrase and s.hints_without_progress and s.repeated_submission
    assert not detect_signals("hello", progress()).any


# -- fixed detection and CONFIRM -------------------------------------------------------

BUGGY = "nums = [1, 2]\nfor i in range(len(nums) + 1):\n    print(nums[i])\n"
FIXED = "nums = [1, 2]\nfor i in range(len(nums)):\n    print(nums[i])\n"


SHAPE = shape(analyze(BUGGY))


def test_fixed_when_the_pattern_is_gone_and_the_code_changed():
    p = progress(last_patterns=["off_by_one_range"], last_shape=SHAPE)
    assert fixed_it(p, analyze(FIXED), code_changed=True)


def test_shape_keeps_function_names_and_the_statement_count_never_the_code():
    code = "def f(xs):\n    for i in range(len(xs) + 1):\n        print(xs[i])\n"
    assert shape(analyze(code)) == {"functions": ["f"], "statements": 3}


@pytest.mark.parametrize(
    "last,code,changed",
    [
        (["off_by_one_range"], BUGGY, True),  # pattern still present
        (["off_by_one_range"], FIXED, False),  # code unchanged
        (["off_by_one_range"], "for i in range(3)\n    pass\n", True),  # parse error
        ([], FIXED, True),  # nothing was wrong before
        (["off_by_one_range"], "# nothing\n", True),  # code deleted
        (["off_by_one_range"], "pass\n", True),
        (["off_by_one_range"], "print(1)\n", True),  # unrelated code
    ],
)
def test_not_fixed(last, code, changed):
    p = progress(last_patterns=last, last_shape=SHAPE if last else None)
    assert not fixed_it(p, analyze(code), changed)


def test_a_fix_must_keep_the_functions_it_had():
    before = "def show(nums):\n    for i in range(len(nums) + 1):\n        print(nums[i])\n"
    after = "def other(nums):\n    for i in range(len(nums)):\n        print(nums[i])\n"
    p = progress(last_patterns=["off_by_one_range"], last_shape=shape(analyze(before)))
    assert not fixed_it(p, analyze(after), True)
    assert fixed_it(p, analyze(after.replace("other", "show")), True)


def test_no_fingerprint_means_no_fix():
    assert not fixed_it(progress(last_patterns=["off_by_one_range"]), analyze(FIXED), True)


@pytest.mark.xfail(strict=True, reason="analyze() does not flag nums[i + 1] in range(len(nums))")
def test_moving_the_bug_to_the_index_is_not_a_fix():
    moved = "nums = [1, 2]\nfor i in range(len(nums)):\n    print(nums[i + 1])\n"
    p = progress(last_patterns=["off_by_one_range"], last_shape=SHAPE)
    assert not fixed_it(p, analyze(moved), True)


def test_saying_it_is_fixed_is_not_enough():
    p = progress(last_patterns=["off_by_one_range"], last_shape=SHAPE)
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


# -- the quiz offer persists -------------------------------------------------------------


@pytest.mark.parametrize("intent", [Intent.DEBUG_HELP, Intent.CONCEPT_QUESTION, Intent.OFF_TOPIC])
def test_a_pending_quiz_offer_is_repeated_on_every_reply(intent):
    p = progress(quiz_offer="off_by_one_range")
    d = decide_mode(intent, p, Signals(), now=0)
    assert d.offer_quiz and d.quiz_concept == "loop bounds"


def test_no_quiz_offer_while_a_quiz_runs_or_without_a_fix():
    running = progress(quiz_offer="off_by_one_range", quiz={"pattern": "off_by_one_range"})
    assert not decide_mode(Intent.CONCEPT_QUESTION, running, Signals(), now=0).offer_quiz
    assert not decide_mode(Intent.DEBUG_HELP, progress(), Signals(), now=0).offer_quiz


def test_the_reflection_after_a_fix_is_acknowledged_not_hinted():
    p = progress(quiz_offer="off_by_one_range")
    d = decide_mode(Intent.DEBUG_HELP, p, Signals(after_fix=True), now=0)
    assert d.mode is Mode.CONFIRM and d.after_fix and d.level is None
    assert d.offer_quiz and not d.offer_answer
    concept = decide_mode(Intent.CONCEPT_QUESTION, p, Signals(after_fix=True), now=0)
    assert concept.mode is Mode.EXPLAIN  # a real question still gets an answer
