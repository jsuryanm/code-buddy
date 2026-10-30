"""Offline stand-ins for models, used by tests and by `python -m codebuddy.eval.run`."""

from __future__ import annotations

import re
import zlib

from langchain_core.messages import AIMessageChunk
from langchain_qdrant import SparseEmbeddings, SparseVector


class HashSparse(SparseEmbeddings):
    """Bag-of-words sparse vectors with hashed indices. No model download."""

    def _vec(self, text: str) -> SparseVector:
        counts: dict[int, float] = {}
        for tok in re.findall(r"[a-z0-9_]+", text.lower()):
            idx = zlib.crc32(tok.encode()) % 100_000
            counts[idx] = counts.get(idx, 0.0) + 1.0
        return SparseVector(indices=list(counts), values=list(counts.values()))

    def embed_documents(self, texts: list[str]) -> list[SparseVector]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> SparseVector:
        return self._vec(text)


class ScriptedChat:
    """Chat model stand-in: replays scripted replies token by token and records prompts."""

    def __init__(self, replies: list[str] | None = None, fail: bool = False):
        self.replies = list(replies or [])
        self.fail = fail
        self.calls: list[list[tuple[str, str]]] = []

    async def astream(self, messages, *args, **kwargs):
        self.calls.append(list(messages))
        if self.fail:
            raise RuntimeError("model unavailable")
        text = self.replies.pop(0) if self.replies else "Okay."
        for token in re.findall(r"\S+\s*|\s+", text):
            yield AIMessageChunk(content=token)
