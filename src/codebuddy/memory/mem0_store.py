"""Learner memory on mem0 (open source), stored in an embedded Qdrant under `memory_path`.

Notes on the installed mem0 (2.2.x):
- `search` and `get_all` take ids in `filters=`; top-level `user_id` raises.
- Procedural memory is only created when `agent_id` is passed. It is also given `user_id`, so
  the learner's `user_id` filter finds and deletes it with the rest.
- `delete_all` returns no count and `get_all` returns at most `top_k` rows, so `forget` deletes
  in batches by id and counts as it goes, then sweeps with `delete_all`.

Every mem0 call runs under one lock: the embedded Qdrant store is not safe for concurrent use,
and it orders a background write against Forget. A per-learner epoch, bumped by `forget`, drops
writes that were scheduled or waiting for the lock when the learner asked to be forgotten.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codebuddy.config import Settings
from codebuddy.memory.types import Episode, MemoryItem, MemoryKind

os.environ.setdefault("MEM0_TELEMETRY", "False")  # read once when mem0 is first imported

AGENT_ID = "codebuddy-tutor"
COLLECTION = "codebuddy_memory"
LIST_LIMIT = 1000  # get_all defaults to 20; also the batch size for forget
ROLES = {"learner": "user", "tutor": "assistant"}


def build_config(settings: Settings) -> dict[str, Any]:
    if not settings.model_fast:
        raise RuntimeError("Learner memory needs CODEBUDDY_MODEL_FAST set in the environment")
    return {
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "path": settings.memory_path,
                "collection_name": COLLECTION,
                "embedding_model_dims": settings.memory_embedding_dims,
            },
        },
        "llm": {"provider": "openai", "config": {"model": settings.model_fast}},
        "embedder": {
            "provider": "openai",
            "config": {
                "model": settings.embed_model,
                "embedding_dims": settings.memory_embedding_dims,
            },
        },
        "history_db_path": str(Path(settings.memory_path) / "history.db"),
    }


def _rows(result: Any) -> list[dict]:
    return result.get("results", []) if isinstance(result, dict) else list(result)


def _item(row: dict) -> MemoryItem:
    return MemoryItem(
        kind=MemoryKind((row.get("metadata") or {}).get("kind", MemoryKind.SEMANTIC)),
        text=row.get("memory", ""),
        id=str(row.get("id", "")),
        score=float(row.get("score") or 0.0),
        created_at=row.get("created_at") or "",
    )


class Mem0LearnerMemory:
    def __init__(self, settings: Settings, memory: Any = None) -> None:
        self._settings = settings
        self._memory = memory
        self._lock = asyncio.Lock()
        self._epochs: dict[str, int] = {}

    def _mem(self) -> Any:
        if self._memory is None:
            from mem0 import Memory

            self._memory = Memory.from_config(build_config(self._settings))
        return self._memory

    async def _locked(self, fn: Callable[[], Any]) -> Any:
        """Run `fn` in a thread while holding the lock. Shielded, so a caller's timeout cannot
        release the lock while the thread is still using the store."""

        async def run() -> Any:
            async with self._lock:
                return await asyncio.to_thread(fn)

        return await asyncio.shield(run())

    async def warm(self) -> None:
        """Build the mem0 instance off the event loop (opens Qdrant and the history DB)."""
        await self._locked(self._mem)

    async def recall(self, learner_id: str, query: str, limit: int = 5) -> list[MemoryItem]:
        result = await self._locked(
            lambda: self._mem().search(query, filters={"user_id": learner_id}, top_k=limit)
        )
        return [_item(r) for r in _rows(result)]

    def generation(self, learner_id: str) -> int:
        return self._epochs.get(learner_id, 0)

    async def remember(
        self,
        learner_id: str,
        history: list[dict[str, str]],
        episode: Episode,
        *,
        since: int | None = None,
    ) -> None:
        # The caller passes the epoch from when it scheduled the write; else take it now,
        # before waiting for the lock.
        epoch = self.generation(learner_id) if since is None else since
        messages = [{"role": ROLES[h["role"]], "content": h["text"]} for h in history]

        def write() -> None:
            if self.generation(learner_id) == epoch:  # else forgotten since scheduling
                self._write(learner_id, messages, episode)

        await self._locked(write)

    def _write(self, learner_id: str, messages: list[dict], episode: Episode) -> None:
        mem = self._mem()
        mem.add(messages, user_id=learner_id, metadata={"kind": MemoryKind.SEMANTIC.value})
        if episode.outcome != "revealed":
            return
        meta = {
            "kind": MemoryKind.EPISODIC.value,
            "stage": episode.stage,
            "hints_given": episode.hints_given,
            "outcome": episode.outcome,
            "at": datetime.now(UTC).isoformat(),
        }
        mem.add(
            episode.summary(),
            user_id=learner_id,
            run_id=episode.session_id,
            infer=False,
            metadata=meta,
        )
        mem.add(
            messages,
            user_id=learner_id,
            agent_id=AGENT_ID,
            memory_type="procedural_memory",
            metadata={"kind": MemoryKind.PROCEDURAL.value},
        )

    def _get_all(self, learner_id: str) -> list[dict]:
        return _rows(self._mem().get_all(filters={"user_id": learner_id}, top_k=LIST_LIMIT))

    async def all(self, learner_id: str) -> list[MemoryItem]:
        return [_item(r) for r in await self._locked(lambda: self._get_all(learner_id))]

    async def forget(self, learner_id: str) -> int:
        def delete() -> int:
            self._epochs[learner_id] = self._epochs.get(learner_id, 0) + 1
            count = 0
            while batch := self._get_all(learner_id):
                for row in batch:
                    self._mem().delete(row["id"])
                count += len(batch)
            self._mem().delete_all(user_id=learner_id)  # final sweep (say, expired items)
            return count

        return await self._locked(delete)
