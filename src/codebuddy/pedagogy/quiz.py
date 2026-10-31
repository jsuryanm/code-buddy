"""Quiz after a fix: five questions on the bug pattern the learner just fixed.

Rules in code, no model. The snippets are hand-written and checked by `analyze()` in the tests,
so each one has exactly its intended bug and each `solution` has none. Difficulty rises: two
easy (short, obvious), two medium (the bug inside a slightly longer function), one hard (the
bug less visible, in a nested loop or a helper). Each answer is graded from the code: it parses
and the pattern is gone. A first wrong try gets one guarded level-0 hint from the model; a
second wrong try, "skip", or a request for the answer shows the stored solution and moves on.
"""

from __future__ import annotations

from dataclasses import dataclass

from codebuddy.agent.code_analysis import CodeFeatures
from codebuddy.pedagogy.frustration import asks_for_answer, skips_question, stops_quiz

TOTAL = 5
DIFFICULTIES = ("easy", "easy", "medium", "medium", "hard")
ASK = "Find the bug, fix it in the code box, and send it."


@dataclass(frozen=True)
class QuizItem:
    pattern: str
    difficulty: str
    snippet: str
    solution: str


def _set(pattern: str, *pairs: tuple[str, str]) -> list[QuizItem]:
    return [QuizItem(pattern, d, s, f) for d, (s, f) in zip(DIFFICULTIES, pairs, strict=True)]


BANK: dict[str, list[QuizItem]] = {
    "off_by_one_range": _set(
        "off_by_one_range",
        (
            'letters = ["a", "b", "c"]\nfor i in range(len(letters) + 1):\n    print(letters[i])\n',
            'letters = ["a", "b", "c"]\nfor i in range(len(letters)):\n    print(letters[i])\n',
        ),
        (
            "scores = [70, 85, 90]\nfor i in range(len(scores) + 1):\n"
            '    print("Score", i, "is", scores[i])\n',
            "scores = [70, 85, 90]\nfor i in range(len(scores)):\n"
            '    print("Score", i, "is", scores[i])\n',
        ),
        (
            "def count_long_words(words):\n    count = 0\n    for i in range(len(words) + 1):\n"
            "        if len(words[i]) > 5:\n            count += 1\n    return count\n",
            "def count_long_words(words):\n    count = 0\n    for i in range(len(words)):\n"
            "        if len(words[i]) > 5:\n            count += 1\n    return count\n",
        ),
        (
            "def highest(temps):\n    best = temps[0]\n    for i in range(1, len(temps) + 1):\n"
            "        if temps[i] > best:\n            best = temps[i]\n    return best\n",
            "def highest(temps):\n    best = temps[0]\n    for i in range(1, len(temps)):\n"
            "        if temps[i] > best:\n            best = temps[i]\n    return best\n",
        ),
        (
            "def print_grid(grid):\n    for row in grid:\n        for col in range(len(row) + 1):\n"
            '            print(row[col], end=" ")\n        print()\n'
            "\n\nprint_grid([[1, 2], [3, 4]])\n",
            "def print_grid(grid):\n    for row in grid:\n        for col in range(len(row)):\n"
            '            print(row[col], end=" ")\n        print()\n'
            "\n\nprint_grid([[1, 2], [3, 4]])\n",
        ),
    ),
    "uninitialized_accumulator": _set(
        "uninitialized_accumulator",
        (
            "for price in [3, 4, 5]:\n    total += price\nprint(total)\n",
            "total = 0\nfor price in [3, 4, 5]:\n    total += price\nprint(total)\n",
        ),
        (
            'words = ["hi", "there"]\nfor word in words:\n    count += 1\nprint(count)\n',
            'words = ["hi", "there"]\ncount = 0\nfor word in words:\n'
            "    count += 1\nprint(count)\n",
        ),
        (
            "def average(numbers):\n    for n in numbers:\n        total += n\n"
            "    return total / len(numbers)\n",
            "def average(numbers):\n    total = 0\n    for n in numbers:\n        total += n\n"
            "    return total / len(numbers)\n",
        ),
        (
            'def count_vowels(text):\n    for ch in text:\n        if ch in "aeiou":\n'
            "            vowels += 1\n    return vowels\n",
            "def count_vowels(text):\n    vowels = 0\n    for ch in text:\n"
            '        if ch in "aeiou":\n            vowels += 1\n    return vowels\n',
        ),
        (
            "def total_sales(shops):\n    for shop in shops:\n        shop_total = 0\n"
            "        for sale in shop:\n            shop_total += sale\n"
            "            grand_total += sale\n    return grand_total\n",
            "def total_sales(shops):\n    grand_total = 0\n    for shop in shops:\n"
            "        shop_total = 0\n        for sale in shop:\n            shop_total += sale\n"
            "            grand_total += sale\n    return grand_total\n",
        ),
    ),
    "mutating_while_iterating": _set(
        "mutating_while_iterating",
        (
            "numbers = [1, 2, 2, 3]\nfor n in numbers:\n    if n == 2:\n        numbers.remove(n)\n"
            "print(numbers)\n",
            "numbers = [1, 2, 2, 3]\nfor n in numbers[:]:\n    if n == 2:\n"
            "        numbers.remove(n)\nprint(numbers)\n",
        ),
        (
            'queue = ["a", "b", "c", "d"]\nfor item in queue:\n    print(item)\n    queue.pop(0)\n',
            'queue = ["a", "b", "c", "d"]\nfor item in queue[:]:\n    print(item)\n'
            "    queue.pop(0)\n",
        ),
        (
            "def remove_negatives(values):\n    for v in values:\n        if v < 0:\n"
            "            values.remove(v)\n    return values\n",
            "def remove_negatives(values):\n    for v in values[:]:\n        if v < 0:\n"
            "            values.remove(v)\n    return values\n",
        ),
        (
            "def clean_scores(scores):\n    for s in scores:\n        if s > 100:\n"
            "            scores.pop(scores.index(s))\n    return scores\n",
            "def clean_scores(scores):\n    for s in scores[:]:\n        if s > 100:\n"
            "            scores.pop(scores.index(s))\n    return scores\n",
        ),
        (
            "def remove_duplicates(groups):\n    for group in groups:\n        for item in group:\n"
            "            if group.count(item) > 1:\n                group.remove(item)\n"
            "    return groups\n",
            "def remove_duplicates(groups):\n    for group in groups:\n"
            "        for item in group[:]:\n"
            "            if group.count(item) > 1:\n                group.remove(item)\n"
            "    return groups\n",
        ),
    ),
    "missing_base_case": _set(
        "missing_base_case",
        (
            "def countdown(n):\n    print(n)\n    countdown(n - 1)\n\n\ncountdown(3)\n",
            "def countdown(n):\n    if n < 0:\n        return\n    print(n)\n    countdown(n - 1)\n"
            "\n\ncountdown(3)\n",
        ),
        (
            "def factorial(n):\n    return n * factorial(n - 1)\n",
            "def factorial(n):\n    if n <= 1:\n        return 1\n"
            "    return n * factorial(n - 1)\n",
        ),
        (
            "def sum_list(items):\n    first = items[0]\n    rest = items[1:]\n"
            "    return first + sum_list(rest)\n",
            "def sum_list(items):\n    if not items:\n        return 0\n    first = items[0]\n"
            "    rest = items[1:]\n    return first + sum_list(rest)\n",
        ),
        (
            "def count_digits(n):\n    n = n // 10\n    return 1 + count_digits(n)\n",
            "def count_digits(n):\n    if n < 10:\n        return 1\n    n = n // 10\n"
            "    return 1 + count_digits(n)\n",
        ),
        (
            "def total_size(folder):\n    size = 0\n    for item in folder:\n"
            "        size += total_size(item)\n    return size\n"
            "\n\nprint(total_size([1, [2, 3]]))\n",
            "def total_size(folder):\n    if isinstance(folder, int):\n        return folder\n"
            "    size = 0\n    for item in folder:\n        size += total_size(item)\n"
            "    return size\n\n\nprint(total_size([1, [2, 3]]))\n",
        ),
    ),
    "shadowed_builtin": _set(
        "shadowed_builtin",
        (
            "list = [3, 1, 2]\nprint(sorted(list))\nnumbers = list(range(5))\n",
            "values = [3, 1, 2]\nprint(sorted(values))\nnumbers = list(range(5))\n",
        ),
        (
            "sum = 0\nfor n in [1, 2, 3]:\n    sum = sum + n\nprint(sum([4, 5]))\n",
            "total = 0\nfor n in [1, 2, 3]:\n    total = total + n\nprint(sum([4, 5]))\n",
        ),
        (
            'def describe(age):\n    str = "Age: "\n    return str + str(age)\n',
            'def describe(age):\n    label = "Age: "\n    return label + str(age)\n',
        ),
        (
            "def longest_name(names):\n    max = 0\n    for name in names:\n"
            "        if len(name) > max:\n            max = len(name)\n"
            "    best = max(names, key=len)\n    return best, max\n",
            "def longest_name(names):\n    longest = 0\n    for name in names:\n"
            "        if len(name) > longest:\n            longest = len(name)\n"
            "    best = max(names, key=len)\n    return best, longest\n",
        ),
        (
            "def report(scores):\n    min = scores[0]\n    for s in scores:\n        if s < min:\n"
            "            min = s\n    spread = max(scores) - min\n    return spread, min(scores)\n",
            "def report(scores):\n    lowest = scores[0]\n    for s in scores:\n"
            "        if s < lowest:\n            lowest = s\n    spread = max(scores) - lowest\n"
            "    return spread, min(scores)\n",
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


def _reveal(quiz: dict) -> str:
    return f"Here is one way to fix it:\n\n```python\n{current(quiz).solution}```"


def advance(
    quiz: dict, message: str, features: CodeFeatures | None, has_code: bool
) -> QuizStep | None:
    """Grade one turn of a running quiz. None when the turn is not a quiz answer (no code and
    no skip or stop), so the tutor answers it normally and the quiz stays where it is."""
    if stops_quiz(message):
        answered = len(quiz["results"])
        return QuizStep(None, f"Quiz stopped. You got {quiz['score']} of {answered}.")
    if skips_question(message) or asks_for_answer(message):
        return _move_on(quiz, False, _reveal(quiz))
    if not (has_code and features):
        return None
    if features.parse_error is None and quiz["pattern"] not in features.patterns:
        return _move_on(quiz, True, "Correct.")
    if quiz["tries"] == 0:
        return QuizStep({**quiz, "tries": 1}, None)
    return _move_on(quiz, False, "Not quite. " + _reveal(quiz))
