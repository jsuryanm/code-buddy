from __future__ import annotations

from typing import TypedDict

from pydantic import BaseModel, Field

from codebuddy.agent.code_analysis import CodeFeatures
from codebuddy.memory.types import MemoryItem
from codebuddy.rag.retrieve import RetrievalResult
from codebuddy.schemas import Citation, Decision, Intent, PcditStage, SessionProgress


class Classification(BaseModel):
    """Structured output of the fast-tier classifier."""

    intent: Intent = Field(description="What the learner wants this turn")
    stage: PcditStage = Field(description="PCDIT stage the learner is working in")
    concepts: list[str] = Field(default_factory=list, description="Programming concepts involved")
    search_query: str = Field(description="Standalone query to search the course material")


class TutorState(TypedDict, total=False):
    # input
    session_id: str
    message: str
    code: str | None
    language: str
    learner_id: str | None
    action: str | None  # "skip" or "stop" from the UI's quiz buttons
    # working state
    foreign: bool  # the session is bound to another learner: leave its history alone
    code_changed: bool  # the code differs from the last code sent (for fix detection)
    quiz_turn: bool  # this turn answered a running quiz (graded by code)
    scripted: str | None  # a reply written by code (quiz), streamed without a model call
    quiz_code: str | None  # the next quiz question's snippet, sent to the UI's code box
    quiz_prior: dict | None  # the quiz before this turn's grading (kept if the hint degrades)
    progress: SessionProgress
    features: CodeFeatures
    cache_key: str | None
    cached_reply: str | None
    cache_locked: bool
    classification: Classification
    retrieval: RetrievalResult
    decision: Decision
    tool_plan: list[str]
    approved: bool
    runtime: dict | None
    cases: list[dict]
    memories: list[MemoryItem]
    # output
    reply: str
    citations: list[Citation]
    degraded: bool
    guarded: bool
    cache_hit: bool
