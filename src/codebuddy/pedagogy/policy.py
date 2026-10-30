"""Pedagogy policy: decides what the tutor does this turn.

Pure function. The LLM only verbalizes the chosen mode (spec Section 8).
"""

from __future__ import annotations

from codebuddy.pedagogy.frustration import Signals
from codebuddy.schemas import Decision, HintLevel, Intent, Mode, SessionProgress

_LAST_HINT = HintLevel.SCAFFOLD


def decide_mode(
    intent: Intent,
    progress: SessionProgress,
    signals: Signals,
    now: float,
    *,
    max_turns: int = 4,
    max_seconds: int = 600,
) -> Decision:
    can_show = progress.hints_given >= 1

    if intent is Intent.SHOW_ANSWER:
        # An explicit request is always honored, even on the first turn.
        return Decision(
            mode=Mode.REVEAL,
            level=HintLevel.REVEAL,
            can_show_answer=True,
            reasons=["explicit show-answer request"],
        )
    if intent is Intent.OFF_TOPIC:
        return Decision(mode=Mode.REDIRECT, can_show_answer=can_show, reasons=["off topic"])
    if intent is Intent.CONCEPT_QUESTION:
        return Decision(mode=Mode.EXPLAIN, can_show_answer=can_show, reasons=["concept question"])

    # DEBUG_HELP or PROBLEM_START: walk the hint ladder, never past SCAFFOLD on our own.
    level = HintLevel(min(progress.hints_given, _LAST_HINT))
    reasons = [f"hints given: {progress.hints_given}"]

    elapsed = (now - progress.started_at) if progress.started_at else 0.0
    offer = False
    if progress.hints_given >= max_turns:
        offer = True
        reasons.append("turn cap reached")
    if elapsed >= max_seconds:
        offer = True
        reasons.append("time cap reached")
    if signals.any:
        offer = True
        reasons.append("frustration signal")

    return Decision(
        mode=Mode.HINT,
        level=level,
        offer_answer=offer,
        can_show_answer=can_show or offer,
        reasons=reasons,
    )
