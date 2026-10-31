"""Frustration and show-answer signals (spec 8.4)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from codebuddy.schemas import SessionProgress

_SHOW_ANSWER = re.compile(
    r"\b(show (me )?the (full )?(answer|solution)|give me the (answer|solution)|"
    r"just (tell|show) me|reveal the (answer|solution))\b",
    re.IGNORECASE,
)
_GIVE_UP = re.compile(
    r"\b(i give up|this is stupid|i('| a)?m (so )?(stuck|frustrated|lost)|"
    r"i don'?t (get|understand) (it|this)|this makes no sense)\b",
    re.IGNORECASE,
)

# During a quiz: "stop/skip the quiz" ends it, a plain "skip" moves to the next question.
_STOP_QUIZ = re.compile(r"\b(stop|end|quit|exit|skip|leave) (the |this )?quiz\b", re.IGNORECASE)
_SKIP_QUESTION = re.compile(r"\bskip\b", re.IGNORECASE)


@dataclass(frozen=True)
class Signals:
    give_up_phrase: bool = False
    repeated_submission: bool = False
    hints_without_progress: bool = False
    fixed: bool = False  # the learner fixed the bug (pedagogy.policy.fixed_it); not frustration

    @property
    def any(self) -> bool:
        return self.give_up_phrase or self.repeated_submission or self.hints_without_progress


def asks_for_answer(message: str) -> bool:
    """Explicit request to see the answer. Always honored (spec 8.2, 8.4)."""
    return bool(_SHOW_ANSWER.search(message))


def stops_quiz(message: str) -> bool:
    return bool(_STOP_QUIZ.search(message))


def skips_question(message: str) -> bool:
    return bool(_SKIP_QUESTION.search(message))


def detect_signals(message: str, progress: SessionProgress, fixed: bool = False) -> Signals:
    return Signals(
        give_up_phrase=bool(_GIVE_UP.search(message)),
        repeated_submission=progress.repeated_submissions >= 2,
        hints_without_progress=progress.hints_given >= 3,
        fixed=fixed,
    )
