"""Retrieval: filter -> hybrid search -> rerank -> threshold (spec 9.4).

Learner-facing retrievers are built with allowed={"fundamentals", ...}. The `pedagogy`
corpus is only reachable through a retriever that explicitly allows it, so the model
cannot leak what it never retrieves (spec 9.3).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from langchain_qdrant import QdrantVectorStore

from codebuddy.cache import keys
from codebuddy.cache.layers import CachedEmbeddings, RetrievalCache
from codebuddy.config import Settings
from codebuddy.rag.rerank import NoopReranker, Reranker, RetrievedChunk
from codebuddy.rag.store import build_filter


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk]
    grounded: bool
    cache_hit: bool = False


class Retriever:
    def __init__(
        self,
        stores: dict[str, QdrantVectorStore],
        settings: Settings,
        *,
        allowed: set[str],
        embeddings: CachedEmbeddings | None = None,
        reranker: Reranker | None = None,
        cache: RetrievalCache | None = None,
    ):
        self._stores = stores
        self._settings = settings
        self._allowed = allowed
        self._embeddings = embeddings
        self._reranker = reranker or NoopReranker()
        self._cache = cache

    async def retrieve(
        self, query: str, *, corpus: str = "fundamentals", filters: dict[str, str] | None = None
    ) -> RetrievalResult:
        if corpus not in self._allowed:
            raise PermissionError(f"This retriever may not read the '{corpus}' corpus")
        if corpus not in self._stores:
            return RetrievalResult([], grounded=False)

        s = self._settings
        key = keys.retrieval_key(query, corpus, filters or {}, s.index_version)
        if self._cache and (hit := await self._cache.get(key)) is not None:
            chunks = [RetrievedChunk(**c) for c in hit]
            return RetrievalResult(chunks, self._grounded(chunks), cache_hit=True)

        if self._embeddings:
            await self._embeddings.warm_query(query)
        raw = await asyncio.to_thread(
            self._stores[corpus].similarity_search_with_score,
            query,
            k=s.retrieve_k,
            filter=build_filter(filters),
        )
        candidates = [
            RetrievedChunk(doc.page_content, float(score), doc.metadata) for doc, score in raw
        ]
        chunks = await self._reranker.rerank(query, candidates, s.rerank_top)
        if self._cache:
            await self._cache.put(
                key, [{"text": c.text, "score": c.score, "meta": c.meta} for c in chunks]
            )
        return RetrievalResult(chunks, self._grounded(chunks))

    def _grounded(self, chunks: list[RetrievedChunk]) -> bool:
        return bool(chunks) and chunks[0].score >= self._settings.relevance_threshold
