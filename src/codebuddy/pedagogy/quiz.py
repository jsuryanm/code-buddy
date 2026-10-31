"""Quiz after a fix: five questions on the bug pattern the learner just fixed.

Rules in code, no model. The snippets are hand-written and checked by `analyze()` in the tests,
so each one has exactly its intended bug and each `solution` has none. Difficulty rises: two
easy (short, obvious), two medium (the bug inside a slightly longer function), one hard (the
bug less visible, in a nested loop or a helper). Each answer is graded from the code: it parses
and the pattern is gone. A first wrong try gets one guarded level-0 hint from the model; a
second wrong try, "skip", or a request for the answer shows the stored solution and moves on.
Code sent back unchanged is not graded: it gets a short nudge, or one hint when the message is
a question, and costs no try. Code that is no longer the question's code (deleted, replaced,
functions dropped) is not graded either.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

from codebuddy.agent.code_analysis import CodeFeatures, analyze
from codebuddy.pedagogy.frustration import asks_for_answer, skips_question, stops_quiz

TOTAL = 5
DIFFICULTIES = ("easy", "easy", "medium", "medium", "hard")
ASK = "Find the bug, fix it in the code box, and send it."
NUDGE = "Edit the code in the box to fix the bug, then send it."
DIFFERENT = "That looks like different code. Fix the bug in the question's code and send it."
CLOSE_RATIO = 0.6  # how similar an answer must stay to the question's code (difflib ratio)
KEEP_STATEMENTS = 0.6  # and the share of the question's statements it must keep


@dataclass(frozen=True)
class QuizItem:
    pattern: str
    difficulty: str
    snippet: str  # buggy; has a call or driver line so it can be run
    solution: str
    expect: str  # what the solution prints (stripped); the snippet fails or prints otherwise


def _set(pattern: str, *items: tuple[str, str, str]) -> list[QuizItem]:
    return [QuizItem(pattern, d, *item) for d, item in zip(DIFFICULTIES, items, strict=True)]


BANK: dict[str, list[QuizItem]] = {
    "off_by_one_range": _set(
        "off_by_one_range",
        (
            'letters = ["a", "b", "c"]\nfor i in range(len(letters) + 1):\n    print(letters[i])\n',
            'letters = ["a", "b", "c"]\nfor i in range(len(letters)):\n    print(letters[i])\n',
            "a\nb\nc",
        ),
        (
            "scores = [70, 85, 90]\nfor i in range(len(scores) + 1):\n"
            '    print("Score", i, "is", scores[i])\n',
            "scores = [70, 85, 90]\nfor i in range(len(scores)):\n"
            '    print("Score", i, "is", scores[i])\n',
            "Score 0 is 70\nScore 1 is 85\nScore 2 is 90",
        ),
        (
            "def count_long_words(words):\n    count = 0\n    for i in range(len(words) + 1):\n"
            "        if len(words[i]) > 5:\n            count += 1\n    return count\n"
            '\n\nprint(count_long_words(["banana", "kiwi", "cherries"]))\n',
            "def count_long_words(words):\n    count = 0\n    for i in range(len(words)):\n"
            "        if len(words[i]) > 5:\n            count += 1\n    return count\n"
            '\n\nprint(count_long_words(["banana", "kiwi", "cherries"]))\n',
            "2",
        ),
        (
            "def highest(temps):\n    best = temps[0]\n    for i in range(1, len(temps) + 1):\n"
            "        if temps[i] > best:\n            best = temps[i]\n    return best\n"
            "\n\nprint(highest([12, 30, 25]))\n",
            "def highest(temps):\n    best = temps[0]\n    for i in range(1, len(temps)):\n"
            "        if temps[i] > best:\n            best = temps[i]\n    return best\n"
            "\n\nprint(highest([12, 30, 25]))\n",
            "30",
        ),
        (
            "def print_grid(grid):\n    for row in grid:\n        for col in range(len(row) + 1):\n"
            '            print(row[col], end=" ")\n        print()\n'
            "\n\nprint_grid([[1, 2], [3, 4]])\n",
            "def print_grid(grid):\n    for row in grid:\n        for col in range(len(row)):\n"
            '            print(row[col], end=" ")\n        print()\n'
            "\n\nprint_grid([[1, 2], [3, 4]])\n",
            "1 2 \n3 4",
        ),
    ),
    "uninitialized_accumulator": _set(
        "uninitialized_accumulator",
        (
            "for price in [3, 4, 5]:\n    total += price\nprint(total)\n",
            "total = 0\nfor price in [3, 4, 5]:\n    total += price\nprint(total)\n",
            "12",
        ),
        (
            'words = ["hi", "there"]\nfor word in words:\n    count += 1\nprint(count)\n',
            'words = ["hi", "there"]\ncount = 0\nfor word in words:\n'
            "    count += 1\nprint(count)\n",
            "2",
        ),
        (
            "def average(numbers):\n    for n in numbers:\n        total += n\n"
            "    return total / len(numbers)\n\n\nprint(average([2, 4, 6]))\n",
            "def average(numbers):\n    total = 0\n    for n in numbers:\n        total += n\n"
            "    return total / len(numbers)\n\n\nprint(average([2, 4, 6]))\n",
            "4.0",
        ),
        (
            'def count_vowels(text):\n    for ch in text:\n        if ch in "aeiou":\n'
            '            vowels += 1\n    return vowels\n\n\nprint(count_vowels("banana"))\n',
            "def count_vowels(text):\n    vowels = 0\n    for ch in text:\n"
            '        if ch in "aeiou":\n            vowels += 1\n    return vowels\n'
            '\n\nprint(count_vowels("banana"))\n',
            "3",
        ),
        (
            "def total_sales(shops):\n    for shop in shops:\n        shop_total = 0\n"
            "        for sale in shop:\n            shop_total += sale\n"
            "            grand_total += sale\n    return grand_total\n"
            "\n\nprint(total_sales([[5, 10], [20]]))\n",
            "def total_sales(shops):\n    grand_total = 0\n    for shop in shops:\n"
            "        shop_total = 0\n        for sale in shop:\n            shop_total += sale\n"
            "            grand_total += sale\n    return grand_total\n"
            "\n\nprint(total_sales([[5, 10], [20]]))\n",
            "35",
        ),
    ),
    "mutating_while_iterating": _set(
        "mutating_while_iterating",
        (
            "numbers = [1, 2, 2, 3]\nfor n in numbers:\n    if n == 2:\n        numbers.remove(n)\n"
            "print(numbers)\n",
            "numbers = [1, 2, 2, 3]\nfor n in numbers[:]:\n    if n == 2:\n"
            "        numbers.remove(n)\nprint(numbers)\n",
            "[1, 3]",
        ),
        (
            'queue = ["a", "b", "c", "d"]\nfor item in queue:\n    print(item)\n    queue.pop(0)\n',
            'queue = ["a", "b", "c", "d"]\nfor item in queue[:]:\n    print(item)\n'
            "    queue.pop(0)\n",
            "a\nb\nc\nd",
        ),
        (
            "def remove_negatives(values):\n    for v in values:\n        if v < 0:\n"
            "            values.remove(v)\n    return values\n"
            "\n\nprint(remove_negatives([-1, -2, 3]))\n",
            "def remove_negatives(values):\n    for v in values[:]:\n        if v < 0:\n"
            "            values.remove(v)\n    return values\n"
            "\n\nprint(remove_negatives([-1, -2, 3]))\n",
            "[3]",
        ),
        (
            "def clean_scores(scores):\n    for s in scores:\n        if s > 100:\n"
            "            scores.pop(scores.index(s))\n    return scores\n"
            "\n\nprint(clean_scores([101, 150, 90]))\n",
            "def clean_scores(scores):\n    for s in scores[:]:\n        if s > 100:\n"
            "            scores.pop(scores.index(s))\n    return scores\n"
            "\n\nprint(clean_scores([101, 150, 90]))\n",
            "[90]",
        ),
        (
            "def remove_duplicates(groups):\n    for group in groups:\n        for item in group:\n"
            "            if group.count(item) > 1:\n                group.remove(item)\n"
            '    return groups\n\n\nprint(remove_duplicates([[1, 1, 1, 1], ["a", "b"]]))\n',
            "def remove_duplicates(groups):\n    for group in groups:\n"
            "        for item in group[:]:\n"
            "            if group.count(item) > 1:\n                group.remove(item)\n"
            '    return groups\n\n\nprint(remove_duplicates([[1, 1, 1, 1], ["a", "b"]]))\n',
            "[[1], ['a', 'b']]",
        ),
    ),
    "missing_base_case": _set(
        "missing_base_case",
        (
            "def countdown(n):\n    print(n)\n    countdown(n - 1)\n\n\ncountdown(3)\n",
            "def countdown(n):\n    if n < 0:\n        return\n    print(n)\n    countdown(n - 1)\n"
            "\n\ncountdown(3)\n",
            "3\n2\n1\n0",
        ),
        (
            "def factorial(n):\n    return n * factorial(n - 1)\n\n\nprint(factorial(5))\n",
            "def factorial(n):\n    if n <= 1:\n        return 1\n"
            "    return n * factorial(n - 1)\n\n\nprint(factorial(5))\n",
            "120",
        ),
        (
            "def sum_list(items):\n    first = items[0]\n    rest = items[1:]\n"
            "    return first + sum_list(rest)\n\n\nprint(sum_list([1, 2, 3]))\n",
            "def sum_list(items):\n    if not items:\n        return 0\n    first = items[0]\n"
            "    rest = items[1:]\n    return first + sum_list(rest)\n"
            "\n\nprint(sum_list([1, 2, 3]))\n",
            "6",
        ),
        (
            "def count_digits(n):\n    n = n // 10\n    return 1 + count_digits(n)\n"
            "\n\nprint(count_digits(1234))\n",
            "def count_digits(n):\n    if n < 10:\n        return 1\n    n = n // 10\n"
            "    return 1 + count_digits(n)\n\n\nprint(count_digits(1234))\n",
            "4",
        ),
        (
            # Each name in the folder is a string; a string's items are strings again, so
            # without a stop for a single name the recursion never ends.
            "def total_size(folder):\n    size = 0\n    for item in folder:\n"
            "        size += total_size(item)\n    return size\n"
            '\n\nprint(total_size(["ab", ["cd", "e"]]))\n',
            "def total_size(folder):\n    if isinstance(folder, str):\n        return len(folder)\n"
            "    size = 0\n    for item in folder:\n        size += total_size(item)\n"
            '    return size\n\n\nprint(total_size(["ab", ["cd", "e"]]))\n',
            "5",
        ),
    ),
    "shadowed_builtin": _set(
        "shadowed_builtin",
        (
            "list = [3, 1, 2]\nprint(sorted(list))\nnumbers = list(range(5))\nprint(numbers)\n",
            "values = [3, 1, 2]\nprint(sorted(values))\nnumbers = list(range(5))\nprint(numbers)\n",
            "[1, 2, 3]\n[0, 1, 2, 3, 4]",
        ),
        (
            "sum = 0\nfor n in [1, 2, 3]:\n    sum = sum + n\nprint(sum([4, 5]))\n",
            "total = 0\nfor n in [1, 2, 3]:\n    total = total + n\nprint(sum([4, 5]))\n",
            "9",
        ),
        (
            'def describe(age):\n    str = "Age: "\n    return str + str(age)\n'
            "\n\nprint(describe(30))\n",
            'def describe(age):\n    label = "Age: "\n    return label + str(age)\n'
            "\n\nprint(describe(30))\n",
            "Age: 30",
        ),
        (
            "def longest_name(names):\n    max = 0\n    for name in names:\n"
            "        if len(name) > max:\n            max = len(name)\n"
            "    best = max(names, key=len)\n    return best, max\n"
            '\n\nprint(longest_name(["Al", "Beatrice"]))\n',
            "def longest_name(names):\n    longest = 0\n    for name in names:\n"
            "        if len(name) > longest:\n            longest = len(name)\n"
            "    best = max(names, key=len)\n    return best, longest\n"
            '\n\nprint(longest_name(["Al", "Beatrice"]))\n',
            "('Beatrice', 8)",
        ),
        (
            "def report(scores):\n    min = scores[0]\n    for s in scores:\n        if s < min:\n"
            "            min = s\n    spread = max(scores) - min\n    return spread, min(scores)\n"
            "\n\nprint(report([4, 9, 2]))\n",
            "def report(scores):\n    lowest = scores[0]\n    for s in scores:\n"
            "        if s < lowest:\n            lowest = s\n    spread = max(scores) - lowest\n"
            "    return spread, min(scores)\n\n\nprint(report([4, 9, 2]))\n",
            "(7, 2)",
        ),
    ),
}


def new_quiz(pattern: str) -> dict:
    return {"pattern": pattern, "index": 0, "score": 0, "results": [], "tries": 0}


def current(quiz: dict) -> QuizItem:
    return BANK[quiz["pattern"]][quiz["index"]]


def quiz_meta(quiz: dict | None) -> dict | None:
    """What the UI may know about a running quiz: never the pattern id or the solution."""
    if quiz is None:
        return None
    return {
        "index": quiz["index"],
        "total": TOTAL,
        "difficulty": current(quiz).difficulty,
        "score": quiz["score"],
    }


def question_text(quiz: dict) -> str:
    item = current(quiz)
    return (
        f"Quiz {quiz['index'] + 1} of {TOTAL} ({item.difficulty}). This code has the same "
        f"kind of bug you just fixed:\n\n```python\n{item.snippet}```\n\n{ASK}"
    )


@dataclass(frozen=True)
class QuizStep:
    quiz: dict | None  # the quiz after this turn; None once it is finished or stopped
    text: str | None  # reply written by code; None means "give one level-0 hint"
    code: str | None = None  # the next question's snippet, for the learner's code box


def _summary(quiz: dict) -> str:
    text = f"Quiz finished: you got {quiz['score']} of {TOTAL}."
    missed = [DIFFICULTIES[i] for i, ok in enumerate(quiz["results"]) if not ok]
    if missed:
        levels = " and ".join(dict.fromkeys(missed))
        text += f" Look again at the {levels} questions, since those are the ones you missed."
    else:
        text += " Well done, you spotted the bug every time."
    return text


def _move_on(quiz: dict, right: bool, lead: str) -> QuizStep:
    quiz = {
        **quiz,
        "score": quiz["score"] + right,
        "results": [*quiz["results"], right],
        "index": quiz["index"] + 1,
        "tries": 0,
    }
    if quiz["index"] >= TOTAL:
        return QuizStep(None, f"{lead}\n\n{_summary(quiz)}")
    return QuizStep(quiz, f"{lead}\n\n{question_text(quiz)}", current(quiz).snippet)


def _lines(code: str) -> list[str]:
    return [line.rstrip() for line in code.splitlines() if line.strip()]


def _same_code(a: str, b: str) -> bool:
    """Equal apart from blank lines and trailing spaces (the UI may reformat the code box)."""
    return _lines(a) == _lines(b)


def close_to(code: str, features: CodeFeatures, snippet: str) -> bool:
    """The answer is still the question's code: similar text, the same function names, and a
    comparable number of statements. Deleting the code or sending something else is not a fix."""
    a, b = "\n".join(_lines(code)), "\n".join(_lines(snippet))
    if difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() < CLOSE_RATIO:
        return False
    if features.parse_error:
        return True  # a typo in the right code is a wrong try, graded below
    question = analyze(snippet)
    return set(question.functions) <= set(features.functions) and (
        features.statements >= KEEP_STATEMENTS * question.statements
    )


def _reveal(quiz: dict) -> str:
    return f"Here is one way to fix it:\n\n```python\n{current(quiz).solution}```"


def advance(
    quiz: dict,
    message: str,
    features: CodeFeatures | None,
    code: str | None,
    action: str | None = None,
) -> QuizStep | None:
    """Grade one turn of a running quiz. None when the turn is not a quiz answer (no code and
    no skip or stop), so the tutor answers it normally and the quiz stays where it is.

    `action` comes from the UI's Skip question and Stop quiz buttons; typed text counts only
    when the whole message is a skip or stop request."""
    if action == "stop" or stops_quiz(message):
        answered = len(quiz["results"])
        return QuizStep(None, f"Quiz stopped. You got {quiz['score']} of {answered}.")
    if action == "skip" or skips_question(message) or asks_for_answer(message):
        return _move_on(quiz, False, _reveal(quiz))
    if not (code and features):
        return None
    if _same_code(code, current(quiz).snippet):
        if message.rstrip().endswith("?"):
            return QuizStep(quiz, None)  # a question about the code: one hint, no try counted
        return QuizStep(quiz, NUDGE)  # not an answer yet: no grading, no try counted
    if not close_to(code, features, current(quiz).snippet):
        return QuizStep(quiz, DIFFERENT)  # not graded, no try counted
    if features.parse_error is None and quiz["pattern"] not in features.patterns:
        return _move_on(quiz, True, "Correct.")
    if quiz["tries"] == 0:
        return QuizStep({**quiz, "tries": 1}, None)
    return _move_on(quiz, False, "Not quite. " + _reveal(quiz))
