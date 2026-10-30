"""L2 semantic cache: finds a stored answer for a question phrased differently (spec 10.3).

Off by default (threshold 0). Concept answers are short and the failure mode is serving the
answer to a *different* question ("for loop" vs "while loop"), so tune the threshold on real
questions before enabling it, and review false positives.
"""

from __future__ import annotations

import json

import numpy as np

from codebuddy.cache.base import Cache


class SemanticIndex:
    def __init__(
        self, cache: Cache, *, namespace: str, threshold: float, max_entries: int, ttl: int
    ):
        self._cache, self._ns = cache, namespace
        self._threshold, self._max, self._ttl = threshold, max_entries, ttl

    @property
    def enabled(self) -> bool:
        return self._threshold > 0

    @property
    def _key(self) -> str:
        return f"cb:sem:{self._ns}"

    async def _load(self) -> list[dict]:
        raw = await self._cache.get(self._key)
        return json.loads(raw) if raw else []

    async def find(self, vector: list[float]) -> str | None:
        """Answer-cache key of the closest stored question, if similar enough."""
        if not self.enabled:
            return None
        entries = await self._load()
        if not entries:
            return None
        matrix = np.array([e["v"] for e in entries], dtype=float)
        query = np.array(vector, dtype=float)
        denom = np.linalg.norm(matrix, axis=1) * np.linalg.norm(query)
        scores = (matrix @ query) / np.where(denom == 0, 1, denom)
        best = int(scores.argmax())
        return entries[best]["k"] if scores[best] >= self._threshold else None

    async def add(self, vector: list[float], answer_key: str) -> None:
        if not self.enabled:
            return
        entries = [e for e in await self._load() if e["k"] != answer_key]
        entries.append({"k": answer_key, "v": vector})
        await self._cache.set(self._key, json.dumps(entries[-self._max :]), self._ttl)
