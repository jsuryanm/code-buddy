"""Shared enums and models for the tutor."""

from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Literal

from pydantic import BaseModel, Field

# Server-issued learner token: "<id>.<signature>" (see api/security.py LearnerTokens).
LEARNER_TOKEN = r"^[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}$"


class PcditStage(StrEnum):
    """PCDIT stages (Kurniawan et al., arXiv:2109.08896)."""

    P = "P"  # Problem definition
    C = "C"  # Concrete cases
    D = "D"  # Design of algorithm
    I = "I"  # Implementation  # noqa: E741
    T = "T"  # Testing


class Intent(StrEnum):
    CONCEPT_QUESTION = "concept_question"
    DEBUG_HELP = "debug_help"
    PROBLEM_START = "problem_start"
    SHOW_ANSWER = "show_answer"
    OFF_TOPIC = "off_topic"


class HintLevel(IntEnum):
    """Hint ladder. Corrected code is allowed only at REVEAL."""

    DIAGNOSE = 0  # diagnostic question: trace or predict
    LOCATE = 1  # narrow to a region
    NAME_CONCEPT = 2  # name the concept at fault
    SCAFFOLD = 3  # pseudo-code or analogous worked example
    REVEAL = 4  # full solution + transfer question


class Mode(StrEnum):
    """What the tutor does this turn. Chosen by pedagogy.policy, never by the LLM."""

    HINT = "hint"  # hint ladder level in Decision.level
    EXPLAIN = "explain"  # direct concept explanation (no learner bug involved)
    REVEAL = "reveal"
    REDIRECT = "redirect"  # off topic
    CONFIRM = "confirm"  # the learner fixed the bug: confirm it and offer a quiz
    QUIZ = "quiz"  # a quiz question, grade, or summary written by code (no model call)


class Decision(BaseModel):
    mode: Mode
    level: HintLevel | None = None
    offer_answer: bool = False  # tutor ends the reply by offering the full answer
    can_show_answer: bool = False  # UI enables the Show-answer button
    offer_quiz: bool = False  # UI shows the Try-a-quiz button (after a fix is detected)
    quiz_concept: str | None = None  # concept name of the fixed bug, never the pattern id
    after_fix: bool = False  # CONFIRM follow-up: acknowledge the learner's explanation
    quiz: dict | None = None  # {"index", "total", "difficulty", "score"} while a quiz runs
    reasons: list[str] = Field(default_factory=list)


class SessionProgress(BaseModel):
    """Per-problem progress, persisted in the session cache (spec layer L6)."""

    session_id: str
    problem_key: str = ""
    hints_given: int = 0
    started_at: float = 0.0
    last_submission_hash: str = ""
    repeated_submissions: int = 0
    stage: PcditStage = PcditStage.P
    reveals: int = 0
    run_permission: str = "ask"  # learner's choice for running their code: ask, allow, deny
    history: list[dict[str, str]] = Field(default_factory=list)  # last few turns, truncated
    learner_id: str | None = None  # bound on first use with memory; one learner per session
    last_patterns: list[str] = Field(default_factory=list)  # bug patterns in the last code sent
    # Fingerprint of that buggy code (policy.shape: function names, statement count; no text).
    last_shape: dict | None = None
    quiz_offer: str = ""  # pattern id of the last fixed bug: what a quiz would be about
    # Active quiz: {"pattern", "index" (0 to 4), "score", "results": [bool], "tries"}.
    quiz: dict | None = None


class Citation(BaseModel):
    source: str
    section: str = ""
    corpus: str = "fundamentals"


class TurnRequest(BaseModel):
    session_id: str
    message: str
    code: str | None = None
    language: str = "python"
    learner_id: str | None = Field(default=None, pattern=LEARNER_TOKEN)
    action: Literal["skip", "stop"] | None = None  # the UI's quiz buttons; typed text is a message


class ShowAnswerRequest(BaseModel):
    session_id: str
    code: str | None = None
    language: str = "python"
    learner_id: str | None = Field(default=None, pattern=LEARNER_TOKEN)


class QuizRequest(BaseModel):
    session_id: str
    learner_id: str | None = Field(default=None, pattern=LEARNER_TOKEN)


class ApproveRequest(BaseModel):
    session_id: str
    turn_id: str
    approve: bool
    remember: bool = True  # keep the answer for the rest of the session
