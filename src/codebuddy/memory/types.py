"""Value types for long-term learner memory."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MemoryKind(StrEnum):
    SEMANTIC = "semantic"  # facts about the learner, from what they said
    EPISODIC = "episodic"  # what happened in a past session
    PROCEDURAL = "procedural"  # how a past problem was worked through


@dataclass(frozen=True)
class MemoryItem:
    kind: MemoryKind
    text: str
    id: str = ""
    score: float = 0.0
    created_at: str = ""


@dataclass(frozen=True)
class Episode:
    session_id: str
    stage: str
    hints_given: int
    outcome: str  # "in_progress" or "revealed"

    def summary(self) -> str:
        return (
            f"Session {self.session_id}: stage {self.stage}, "
            f"{self.hints_given} hints, outcome {self.outcome}"
        )
