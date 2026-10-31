import ast
from collections import Counter

import pytest

from codebuddy.agent.code_analysis import PATTERNS, analyze
from codebuddy.pedagogy.quiz import (
    BANK,
    DIFFERENT,
    NUDGE,
    TOTAL,
    advance,
    close_to,
    new_quiz,
    quiz_meta,
)
from codebuddy.sandbox.runner import run_python

ITEMS = [(p, i, item) for p, items in BANK.items() for i, item in enumerate(items)]


def test_every_pattern_has_five_questions_two_easy_two_medium_one_hard():
    assert set(BANK) == set(PATTERNS)
    for items in BANK.values():
        assert len(items) == TOTAL
        assert [i.difficulty for i in items] == ["easy", "easy", "medium", "medium", "hard"]
        assert Counter(i.difficulty for i in items) == {"easy": 2, "medium": 2, "hard": 1}


@pytest.mark.parametrize("pattern,index,item", ITEMS)
def test_snippet_has_exactly_its_bug_and_solution_has_none(pattern, index, item):
    snippet, solution = analyze(item.snippet), analyze(item.solution)
    assert snippet.parse_error is None and snippet.patterns == [pattern]
    assert solution.parse_error is None and solution.patterns == []
    assert item.pattern == pattern


@pytest.mark.parametrize("pattern,index,item", ITEMS)
async def test_snippet_fails_when_run_and_solution_prints_the_expected_output(pattern, index, item):
    body = ast.parse(item.snippet).body
    assert any(not isinstance(n, ast.FunctionDef) for n in body), "a call or driver line"
    bad = await run_python(item.snippet, timeout_s=5)
    assert bad["ran"], bad
    assert bad.get("error") or bad.get("timed_out") or bad["stdout"].strip() != item.expect
    good = await run_python(item.solution, timeout_s=5)
    assert good["ran"] and good["ok"] and not good.get("error"), good
    assert good["stdout"].strip() == item.expect


@pytest.mark.parametrize("pattern,index,item", ITEMS)
def test_every_solution_counts_as_close_to_its_question(pattern, index, item):
    assert close_to(item.solution, analyze(item.solution), item.snippet)


def answer(quiz, code="", message="here"):
    return advance(quiz, message, analyze(code or None), code or None)


def test_correct_answer_scores_and_sends_the_next_question():
    quiz = new_quiz("off_by_one_range")
    step = answer(quiz, BANK["off_by_one_range"][0].solution)
    assert step.text.startswith("Correct.") and "Quiz 2 of 5 (easy)" in step.text
    assert step.quiz["index"] == 1 and step.quiz["score"] == 1 and step.quiz["results"] == [True]
    assert step.code == BANK["off_by_one_range"][1].snippet
    assert BANK["off_by_one_range"][1].snippet in step.text


def test_first_wrong_try_asks_for_a_hint_second_reveals_and_moves_on():
    quiz = new_quiz("uninitialized_accumulator")
    snippet = BANK["uninitialized_accumulator"][0].snippet
    first = answer(quiz, snippet + "# try\n")
    assert first.text is None and first.quiz["tries"] == 1 and first.quiz["index"] == 0
    second = answer(first.quiz, snippet + "# still\n")
    assert BANK["uninitialized_accumulator"][0].solution in second.text
    assert second.quiz["index"] == 1 and second.quiz["score"] == 0
    assert second.quiz["results"] == [False] and second.quiz["tries"] == 0


def test_a_parse_error_is_a_wrong_try():
    broken = BANK["off_by_one_range"][0].snippet.replace(":", "", 1)
    step = answer(new_quiz("off_by_one_range"), broken)
    assert step.text is None and step.quiz["tries"] == 1


@pytest.mark.parametrize(
    "pattern,code",
    [
        ("off_by_one_range", "pass\n"),
        ("off_by_one_range", "# nothing\n"),
        ("off_by_one_range", "print(1)\n"),
        ("missing_base_case", "def other(n):\n    return 1\n\n\nprint(other(3))\n"),
        # keeps the text of the call but drops the function it calls
        ("missing_base_case", "print(factorial(5))\n"),
    ],
)
def test_different_code_is_not_graded_and_costs_no_try(pattern, code):
    quiz = new_quiz(pattern)
    if pattern == "missing_base_case":
        quiz["index"] = 1  # factorial
    step = answer(quiz, code)
    assert step.text == DIFFERENT and step.quiz == quiz and step.code is None


def test_a_fix_that_drops_the_function_is_different_code():
    quiz = {**new_quiz("missing_base_case"), "index": 1}
    renamed = BANK["missing_base_case"][1].solution.replace("factorial", "fact")
    assert answer(quiz, renamed).text == DIFFERENT


@pytest.mark.parametrize("message", ["skip", "Skip this question", "just show me the answer"])
def test_skip_or_answer_request_reveals_the_solution(message):
    step = advance(new_quiz("shadowed_builtin"), message, analyze(None), None)
    assert BANK["shadowed_builtin"][0].solution in step.text
    assert step.quiz["index"] == 1 and step.quiz["results"] == [False]


def test_stop_ends_the_quiz():
    quiz = {**new_quiz("off_by_one_range"), "index": 2, "score": 1, "results": [True, False]}
    step = advance(quiz, "stop the quiz", analyze(None), None)
    assert step.quiz is None and "1 of 2" in step.text


@pytest.mark.parametrize("tweak", [lambda c: c, lambda c: "\n" + c.replace("\n", "  \n") + "\n"])
def test_unchanged_question_code_gets_a_nudge_and_no_try(tweak):
    quiz = new_quiz("off_by_one_range")
    step = answer(quiz, tweak(BANK["off_by_one_range"][0].snippet))
    assert step.text == NUDGE and step.quiz == quiz and step.code is None


def test_unchanged_code_with_skip_still_skips():
    quiz = new_quiz("off_by_one_range")
    step = answer(quiz, BANK["off_by_one_range"][0].snippet, "skip")
    assert step.quiz["index"] == 1 and BANK["off_by_one_range"][0].solution in step.text


def test_a_message_without_code_is_not_a_quiz_turn():
    assert advance(new_quiz("off_by_one_range"), "what is range?", analyze(None), None) is None


def test_after_the_fifth_question_a_summary_names_what_to_review():
    quiz = {
        **new_quiz("missing_base_case"),
        "index": 4,
        "score": 3,
        "results": [True, False, True, True],
    }
    step = answer(quiz, BANK["missing_base_case"][4].solution)
    assert step.quiz is None and step.code is None
    assert "4 of 5" in step.text and "easy" in step.text and "hard" not in step.text


def test_quiz_meta_hides_the_pattern():
    meta = quiz_meta({**new_quiz("off_by_one_range"), "index": 2})
    assert meta == {"index": 2, "total": 5, "difficulty": "medium", "score": 0}
    assert quiz_meta(None) is None


@pytest.mark.parametrize("message", ["should I skip the + 1?", "I want to stop the quiz soon"])
def test_skip_or_stop_inside_a_sentence_is_an_answer_not_a_command(message):
    quiz = new_quiz("off_by_one_range")
    step = answer(quiz, BANK["off_by_one_range"][0].solution, message)
    assert step.text.startswith("Correct.")


@pytest.mark.parametrize("message", ["Stop the quiz.", "quit quiz", "  end this quiz!"])
def test_a_whole_message_stop_request_stops(message):
    assert advance(new_quiz("off_by_one_range"), message, analyze(None), None).quiz is None


def test_the_ui_buttons_send_an_explicit_action():
    quiz = new_quiz("off_by_one_range")
    skipped = advance(quiz, "Skip this question please, thanks", analyze(None), None, "skip")
    assert skipped.quiz["index"] == 1
    assert advance(quiz, "anything", analyze(None), None, "stop").quiz is None


def test_a_question_about_unchanged_code_gets_one_hint_and_costs_no_try():
    quiz = {**new_quiz("off_by_one_range"), "tries": 1}
    step = answer(quiz, BANK["off_by_one_range"][0].snippet, "what does range return?")
    assert step.text is None and step.quiz == quiz
