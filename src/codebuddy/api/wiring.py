"""Builds production dependencies from settings and environment."""

from __future__ import annotations

import logging
import os
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite
from langchain_qdrant import FastEmbedSparse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from codebuddy.agent.deps import Deps, LLMClassifier
from codebuddy.agent.graph import checkpoint_serde
from codebuddy.cache.base import Cache
from codebuddy.cache.layers import AnswerCache, CachedEmbeddings, RetrievalCache, SessionStore
from codebuddy.cache.memory import InMemoryCache
from codebuddy.cache.semantic import SemanticIndex
from codebuddy.cache.upstash import UpstashCache
from codebuddy.config import Settings
from codebuddy.llm import build_embeddings, build_tiers
from codebuddy.memory.mem0_store import Mem0LearnerMemory
from codebuddy.metrics import Metrics
from codebuddy.pedagogy.judge import LeakJudge
from codebuddy.rag.rerank import CrossEncoderReranker, NoopReranker
from codebuddy.rag.retrieve import Retriever
from codebuddy.rag.store import get_store, make_client
from codebuddy.stt.transcribe import build_speech_to_text
from codebuddy.tools.runner import start_tool_runner

log = logging.getLogger("codebuddy.api")

LEARNER_CORPORA = ("fundamentals",)


def build_cache() -> tuple[Cache, str]:
    if os.getenv("UPSTASH_REDIS_REST_URL") and os.getenv("UPSTASH_REDIS_REST_TOKEN"):
        return UpstashCache(), "upstash"
    log.warning("Upstash credentials not set; using an in-process cache")
    return InMemoryCache(), "memory"


async def build_memory(settings: Settings) -> Mem0LearnerMemory | None:
    if not settings.memory_enabled:
        return None
    memory = Mem0LearnerMemory(settings)
    try:
        await memory.warm()  # open the stores now, not during a learner's first turn
    except Exception:
        log.exception("Learner memory failed to start; continuing without it")
        return None
    return memory


@dataclass
class Resources:
    deps: Deps
    cache_kind: str
    speech: Any
    judge: LeakJudge | None
    checkpointer: Any
    stack: AsyncExitStack  # closes the MCP session and the checkpoint database


async def build_resources(settings: Settings) -> Resources:
    stack = AsyncExitStack()
    try:
        cache, cache_kind = build_cache()
        embeddings = CachedEmbeddings(
            build_embeddings(settings), cache, settings.embed_model, settings.ttl_embedding
        )
        client = make_client(settings)
        sparse = FastEmbedSparse(model_name="Qdrant/bm25")
        stores = {c: get_store(c, client, embeddings, sparse, settings) for c in LEARNER_CORPORA}
        tiers = build_tiers(settings)
        retriever = Retriever(
            stores,
            settings,
            allowed=set(LEARNER_CORPORA),  # the pedagogy corpus is deliberately not reachable
            embeddings=embeddings,
            reranker=CrossEncoderReranker() if settings.use_cross_encoder else NoopReranker(),
            cache=RetrievalCache(cache, settings.ttl_retrieval),
        )

        tools = None
        if settings.tools_enabled:
            tools = await start_tool_runner(settings.mcp_enabled)
            stack.push_async_callback(tools.close)
        Path(settings.checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
        conn = await stack.enter_async_context(aiosqlite.connect(settings.checkpoint_path))
        saver = AsyncSqliteSaver(conn, serde=checkpoint_serde())

        namespace = f"{settings.index_version}:{settings.prompt_version}:{settings.model_standard}"
        deps = Deps(
            settings=settings,
            tiers=tiers,
            classifier=LLMClassifier(tiers.fast_base),
            retriever=retriever,
            sessions=SessionStore(cache, settings.ttl_session),
            answers=AnswerCache(cache, settings.ttl_answer, settings.ttl_lock),
            metrics=Metrics(cache),
            tools=tools,
            embeddings=embeddings,
            semantic=SemanticIndex(
                cache,
                namespace=namespace,
                threshold=settings.semantic_cache_threshold,
                max_entries=settings.semantic_cache_max,
                ttl=settings.ttl_answer,
            ),
            cache=cache,
            memory=await build_memory(settings),
        )
        judge = LeakJudge.from_model(tiers.fast_base) if settings.judge_sample_rate > 0 else None
        return Resources(deps, cache_kind, build_speech_to_text(settings), judge, saver, stack)
    except BaseException:
        await stack.aclose()
        raise
