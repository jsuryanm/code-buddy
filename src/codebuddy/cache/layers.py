"""Cache layers built on the Cache protocol (spec 10.3).

L1 answers, L3 embeddings, L4 retrieval, L6 session state, plus a single-flight lock.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field

from langchain_core.embeddings import Embeddings

from codebuddy.cache import keys
from codebuddy.cache.base import Cache
from codebuddy.schemas import Decision, Mode, SessionProgress


def is_answer_cacheable(decision: Decision, has_code: bool) -> bool:
    """Cache knowledge, not personalization (spec 10.4).

    Only direct concept explanations and redirects are cacheable. Hints depend on the
    learner's code and progress, and reveals depend on their code, so they never are.
    """
    return decision.mode in {Mode.EXPLAIN, Mode.REDIRECT} and not has_code


@dataclass
class CachedAnswer:
    text: str
    citations: list[dict] = field(default_factory=list)


class AnswerCache:
    def __init__(self, cache: Cache, ttl: int, lock_ttl: int = 30):
        self._cache, self._ttl, self._lock_ttl = cache, ttl, lock_ttl

    async def get(self, key: str) -> CachedAnswer | None:
        raw = await self._cache.get(key)
        return CachedAnswer(**json.loads(raw)) if raw else None

    async def put(self, key: str, answer: CachedAnswer) -> None:
        await self._cache.set(key, json.dumps(asdict(answer)), self._ttl)

    async def try_lock(self, key: str) -> bool:
        """Single-flight: only one concurrent miss generates the answer."""
        return await self._cache.set_nx(keys.lock_key(key), "1", self._lock_ttl)

    async def unlock(self, key: str) -> None:
        await self._cache.delete(keys.lock_key(key))

    async def wait_for(self, key: str, timeout: float, interval: float = 0.05):
        """Poll for an answer another request is generating. None on timeout."""
        waited = 0.0
        while waited < timeout:
            hit = await self.get(key)
            if hit:
                return hit
            await asyncio.sleep(interval)
            waited += interval
        return None


class CachedEmbeddings(Embeddings):
    """Wraps an Embeddings model with the L3 cache.

    LangChain vector stores call the sync methods, so the async `warm_query` loads the
    vector from Redis (or computes it once) into a small in-process map first.
    """

    def __init__(
        self, inner: Embeddings, cache: Cache, model_name: str, ttl: int, max_local: int = 1024
    ):
        self._inner, self._cache = inner, cache
        self._model, self._ttl, self._max = model_name, ttl, max_local
        self._local: dict[str, list[float]] = {}

    async def warm_query(self, text: str) -> bool:
        """Make `embed_query(text)` free. Returns True when it came from cache."""
        if text in self._local:
            return True
        key = keys.embedding_key(text, self._model)
        raw = await self._cache.get(key)
        hit = raw is not None
        vector = json.loads(raw) if raw else await self._inner.aembed_query(text)
        if not hit:
            await self._cache.set(key, json.dumps(vector), self._ttl)
        self._remember(text, vector)
        return hit

    def _remember(self, text: str, vector: list[float]) -> None:
        if len(self._local) >= self._max:
            self._local.pop(next(iter(self._local)))
        self._local[text] = vector

    def embed_query(self, text: str) -> list[float]:
        return self._local.get(text) or self._inner.embed_query(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._inner.embed_documents(texts)

    async def aembed_query(self, text: str) -> list[float]:
        await self.warm_query(text)
        return self._local[text]


class RetrievalCache:
    def __init__(self, cache: Cache, ttl: int):
        self._cache, self._ttl = cache, ttl

    async def get(self, key: str) -> list[dict] | None:
        raw = await self._cache.get(key)
        return json.loads(raw) if raw else None

    async def put(self, key: str, chunks: list[dict]) -> None:
        await self._cache.set(key, json.dumps(chunks), self._ttl)


class SessionStore:
    def __init__(self, cache: Cache, ttl: int):
        self._cache, self._ttl = cache, ttl

    async def load(self, session_id: str) -> SessionProgress:
        raw = await self._cache.get(keys.session_key(session_id))
        if raw:
            return SessionProgress.model_validate_json(raw)
        return SessionProgress(session_id=session_id)

    async def save(self, progress: SessionProgress) -> None:
        await self._cache.set(
            keys.session_key(progress.session_id), progress.model_dump_json(), self._ttl
        )

    async def bind(self, session_id: str, learner_id: str) -> str:
        """Claim the session for `learner_id` unless someone holds it. Returns the owner.

        The claim lives as long as the session itself (the store's TTL)."""
        while not await self._cache.set_nx(keys.bind_key(session_id), learner_id, self._ttl):
            if (owner := await self.owner(session_id)) is not None:
                return owner  # else the claim expired in between: try again
        return learner_id

    async def owner(self, session_id: str) -> str | None:
        return await self._cache.get(keys.bind_key(session_id))
