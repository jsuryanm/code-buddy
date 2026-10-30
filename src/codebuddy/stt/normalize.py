"""Turn spoken programming phrases into the symbols learners mean."""

from __future__ import annotations

import re

VOCAB_PROMPT = (
    "Programming lesson. Terms: for loop, while loop, if statement, else, elif, list, "
    "dictionary, tuple, string, integer, float, boolean, function, return, variable, "
    "index, IndexError, TypeError, NameError, recursion, base case, range, len, print, "
    "append, off-by-one, i++, ==, !=, <=, >=."
)

_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(\w+) plus plus\b", re.I), r"\1++"),
    (re.compile(r"\b(\w+) minus minus\b", re.I), r"\1--"),
    (re.compile(r"\bnot equals?( to)?\b", re.I), "!="),
    (re.compile(r"\bequals equals\b|\bdouble equals\b", re.I), "=="),
    (re.compile(r"\bless than or equal to\b", re.I), "<="),
    (re.compile(r"\bgreater than or equal to\b", re.I), ">="),
    (re.compile(r"\bplus equals\b", re.I), "+="),
    (re.compile(r"\bminus equals\b", re.I), "-="),
]


def normalize_transcript(text: str) -> str:
    out = text.strip()
    for pattern, replacement in _RULES:
        out = pattern.sub(replacement, out)
    return re.sub(r"\s+", " ", out)
