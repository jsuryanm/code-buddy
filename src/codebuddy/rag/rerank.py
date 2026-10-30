"""Reranking. A plain function over candidates, no framework needed (spec 15.1)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class RetrievedChunk:
    text: str
    score: float
    meta: dict = field(default_factory=dict)

    @property
    def source(self) -> str:
        return str(self.meta.get("title") or self.meta.get("source", ""))

    @property
    def section(self) -> str:
        return str(self.meta.get("section", ""))

    @property
    def corpus(self) -> str:
        return str(self.meta.get("corpus", ""))


class Reranker(Protocol):
    async def rerank(
        self, query: str, chunks: list[RetrievedChunk], top: int
    ) -> list[RetrievedChunk]: ...


class NoopReranker:
    """Keeps retrieval order. Scores become 1.0 because ordering gives no confidence."""

    async def rerank(
        self, query: str, chunks: list[RetrievedChunk], top: int
    ) -> list[RetrievedChunk]:
        return [RetrievedChunk(c.text, 1.0, c.meta) for c in chunks[:top]]


class CrossEncoderReranker:
    """Local cross-encoder (needs the `rerank` extra: sentence-transformers).

    Scores are squashed to 0-1 so the relevance threshold means the same thing for any model.
    """

    def __init__(self, model_name: str = "BAAI/bge-reranker-base"):
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install the extra: uv sync --extra rerank") from exc
        self._model = CrossEncoder(model_name)

    async def rerank(
        self, query: str, chunks: list[RetrievedChunk], top: int
    ) -> list[RetrievedChunk]:  # pragma: no cover - needs model download
        import math

        if not chunks:
            return []
        raw = await asyncio.to_thread(self._model.predict, [(query, c.text) for c in chunks])
        scored = [
            RetrievedChunk(c.text, 1 / (1 + math.exp(-float(s))), c.meta)
            for c, s in zip(chunks, raw, strict=True)
        ]
        return sorted(scored, key=lambda c: c.score, reverse=True)[:top]
