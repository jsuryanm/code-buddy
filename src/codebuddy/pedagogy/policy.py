"""Pedagogy policy: decides what the tutor does this turn.

Pure function. The LLM only verbalizes the chosen mode (spec Section 8).
"""

from __future__ import annotations

from codebuddy.agent.code_analysis import PATTERNS, CodeFeatures
from codebuddy.pedagogy.frustration import Signals
from codebuddy.schemas import Decision, HintLevel, Intent, Mode, SessionProgress

_LAST_HINT = HintLevel.SCAFFOLD
SHOW_AFTER_HINTS = 4  # the Show answer button is enabled after this many hints


FIX_KEEPS = 0.6  # a fix keeps at least this share of the statements the buggy code had


def shape(features: CodeFeatures) -> dict:
    """Fingerprint of code for fix detection: function names and statement count, never text."""
    return {"functions": sorted(set(features.functions)), "statements": features.statements}


def fixed_it(progress: SessionProgress, features: CodeFeatures | None, code_changed: bool) -> bool:
    """The learner fixed the bug, judged from their code alone, never from what they say.

    True when the last code they sent had bug patterns, this code is different, it parses,
    none of those patterns remain, and it is still the same program: the functions it had are
    all there and it keeps at least 60% of its statements (deleting the code is not a fix).
    """
    if not (progress.last_patterns and code_changed and features) or features.parse_error:
        return False
    if any(p in features.patterns for p in progress.last_patterns):
        return False
    before = progress.last_shape
    if not before:
        return False
    return (
        set(before["functions"]) <= set(features.functions)
        and features.statements >= FIX_KEEPS * before["statements"]
    )


def decide_mode(
    intent: Intent,
    progress: SessionProgress,
    signals: Signals,
    now: float,
    *,
    max_turns: int = 6,
    max_seconds: int = 600,
) -> Decision:
    decision = _decide(intent, progress, signals, now, max_turns, max_seconds)
    # A fixed bug's quiz stays on offer until it starts, a new problem, or a new bug.
    if progress.quiz_offer in PATTERNS and progress.quiz is None:
        decision.offer_quiz = True
        decision.quiz_concept = PATTERNS[progress.quiz_offer].concept
    return decision


def _decide(
    intent: Intent,
    progress: SessionProgress,
    signals: Signals,
    now: float,
    max_turns: int,
    max_seconds: int,
) -> Decision:
    can_show = progress.hints_given >= SHOW_AFTER_HINTS

    if intent is Intent.SHOW_ANSWER:
        # An explicit request is always honored, even on the first turn.
        return Decision(
            mode=Mode.REVEAL,
            level=HintLevel.REVEAL,
            can_show_answer=True,
            reasons=["explicit show-answer request"],
        )
    if signals.fixed and intent is not Intent.PROBLEM_START:
        fixed = next((p for p in progress.last_patterns if p in PATTERNS), None)
        return Decision(
            mode=Mode.CONFIRM,
            offer_quiz=fixed is not None,
            quiz_concept=PATTERNS[fixed].concept if fixed else None,
            reasons=["bug fixed"],
        )
    if signals.after_fix and intent is Intent.DEBUG_HELP:
        # The learner answered the "why does your fix work?" question with the same fixed code.
        return Decision(mode=Mode.CONFIRM, after_fix=True, reasons=["explained the fix"])
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
