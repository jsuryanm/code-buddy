from pathlib import Path

import pytest
from langgraph.types import Command

from codebuddy.agent.deps import Deps, HeuristicClassifier
from codebuddy.agent.graph import build_graph, run_turn
from codebuddy.cache.layers import AnswerCache, SessionStore
from codebuddy.cache.memory import InMemoryCache
from codebuddy.llm import Tiers
from codebuddy.rag.ingest import ingest_file
from codebuddy.rag.manifest import Manifest
from codebuddy.rag.retrieve import Retriever
from codebuddy.rag.store import get_store
from tests.helpers import ScriptedChat

SAMPLE = Path(__file__).parents[2] / "data" / "sample"


class Harness:
    def __init__(self, deps: Deps, tiers: Tiers):
        self.deps, self.tiers = deps, tiers
        self.graph = build_graph(deps)
        self.clock_now = 1_000.0

    @staticmethod
    def _collect(events: list[dict]) -> dict:
        meta = next((e for e in events if e["type"] == "meta"), {})
        text = "".join(e["text"] for e in events if e["type"] == "token")
        last = next(e for e in events if e["type"] == "final")
        return {
            "meta": meta,
            "text": text,
            "state": last["state"],
            "interrupt": last["interrupt"],
            "thread_id": last["thread_id"],
            "events": events,
        }

    async def turn(self, message: str, code: str | None = None, session: str = "s1") -> dict:
        inputs = {"session_id": session, "message": message, "code": code}
        return self._collect([e async for e in run_turn(self.graph, inputs)])

    async def resume(self, thread_id: str, approve: bool, remember: bool = True) -> dict:
        command = Command(resume={"approve": approve, "remember": remember})
        return self._collect([e async for e in run_turn(self.graph, command, thread_id)])


@pytest.fixture
def make_harness(settings, embeddings, sparse, qdrant, tmp_path):
    def build(fast=None, standard=None, heavy=None, tools=None) -> Harness:
        stores = {
            c: get_store(c, qdrant, embeddings, sparse, settings)
            for c in ("fundamentals", "pedagogy")
        }
        ingest_file(
            SAMPLE / "python_basics.md",
            corpus="fundamentals",
            store=stores["fundamentals"],
            manifest=Manifest(tmp_path / "m.json"),
            settings=settings,
            title="Sample Basics",
        )
        cache = InMemoryCache()
        tiers = Tiers(
            fast=fast or ScriptedChat(),
            standard=standard or ScriptedChat(),
            heavy=heavy or ScriptedChat(),
        )
        harness = Harness.__new__(Harness)
        deps = Deps(
            settings=settings,
            tiers=tiers,
            classifier=HeuristicClassifier(),
            retriever=Retriever(stores, settings, allowed={"fundamentals"}),
            sessions=SessionStore(cache, ttl=600),
            answers=AnswerCache(cache, ttl=600),
            clock=lambda: harness.clock_now,
            tools=tools,
        )
        Harness.__init__(harness, deps, tiers)
        return harness

    return build
