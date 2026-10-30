"""Shared enums and models for the tutor."""

from __future__ import annotations

from enum import IntEnum, StrEnum

from pydantic import BaseModel, Field


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


class Decision(BaseModel):
    mode: Mode
    level: HintLevel | None = None
    offer_answer: bool = False  # tutor ends the reply by offering the full answer
    can_show_answer: bool = False  # UI enables the Show-answer button
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


class Citation(BaseModel):
    source: str
    section: str = ""
    corpus: str = "fundamentals"


class TurnRequest(BaseModel):
    session_id: str
    message: str
    code: str | None = None
    language: str = "python"
    learner_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{16,64}$")


class ShowAnswerRequest(BaseModel):
    session_id: str
    code: str | None = None
    language: str = "python"
    learner_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{16,64}$")


class ApproveRequest(BaseModel):
    session_id: str
    turn_id: str
    approve: bool
    remember: bool = True  # keep the answer for the rest of the session
