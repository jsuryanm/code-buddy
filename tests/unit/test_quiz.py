from collections import Counter

import pytest

from codebuddy.agent.code_analysis import PATTERNS, analyze
from codebuddy.pedagogy.quiz import BANK, NUDGE, TOTAL, advance, new_quiz, quiz_meta

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
    step = answer(new_quiz("off_by_one_range"), "for i in range(3)\n    pass\n")
    assert step.text is None and step.quiz["tries"] == 1


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
