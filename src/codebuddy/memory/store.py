"""The learner memory interface and an in-memory fake for tests."""

from __future__ import annotations

import re
from typing import Protocol

from codebuddy.memory.types import Episode, MemoryItem, MemoryKind


class LearnerMemory(Protocol):
    async def recall(self, learner_id: str, query: str, limit: int = 5) -> list[MemoryItem]: ...

    def generation(self, learner_id: str) -> int:
        """Bumped by every `forget`; a write scheduled under an older generation is dropped."""
        ...

    async def remember(
        self,
        learner_id: str,
        history: list[dict[str, str]],
        episode: Episode,
        *,
        since: int | None = None,
    ) -> None: ...

    async def all(self, learner_id: str) -> list[MemoryItem]: ...

    async def forget(self, learner_id: str) -> int: ...


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


class InMemoryLearnerMemory:
    """Keeps items per learner in a dict; recall ranks by word overlap with the query."""

    def __init__(self) -> None:
        self._items: dict[str, list[MemoryItem]] = {}
        self._generations: dict[str, int] = {}

    def generation(self, learner_id: str) -> int:
        return self._generations.get(learner_id, 0)

    async def recall(self, learner_id: str, query: str, limit: int = 5) -> list[MemoryItem]:
        q = _words(query)
        scored = [(len(q & _words(i.text)), i) for i in self._items.get(learner_id, [])]
        ranked = sorted((s for s in scored if s[0]), key=lambda s: s[0], reverse=True)
        return [i for _, i in ranked[:limit]]

    async def remember(
        self,
        learner_id: str,
        history: list[dict[str, str]],
        episode: Episode,
        *,
        since: int | None = None,
    ) -> None:
        if since is not None and since != self.generation(learner_id):
            return  # forgotten after the write was scheduled
        items = self._items.setdefault(learner_id, [])
        learner = [h["text"] for h in history if h["role"] == "learner"]
        items += [MemoryItem(MemoryKind.SEMANTIC, text) for text in learner]
        items.append(MemoryItem(MemoryKind.EPISODIC, episode.summary()))
        if episode.outcome == "revealed":
            text = f"Worked through stage {episode.stage} with {episode.hints_given} hints"
            items.append(MemoryItem(MemoryKind.PROCEDURAL, text))

    async def all(self, learner_id: str) -> list[MemoryItem]:
        return list(self._items.get(learner_id, []))

    async def forget(self, learner_id: str) -> int:
        self._generations[learner_id] = self.generation(learner_id) + 1
        return len(self._items.pop(learner_id, []))
