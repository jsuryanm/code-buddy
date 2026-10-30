import pytest

from codebuddy.config import Settings
from codebuddy.memory import (
    Episode,
    InMemoryLearnerMemory,
    MemoryItem,
    MemoryKind,
)
from codebuddy.memory.mem0_store import AGENT_ID, Mem0LearnerMemory, build_config

HISTORY = [
    {"role": "learner", "text": "my for loop skips the last element"},
    {"role": "tutor", "text": "What does range(len(nums) - 1) produce?"},
]
MESSAGES = [
    {"role": "user", "content": "my for loop skips the last element"},
    {"role": "assistant", "content": "What does range(len(nums) - 1) produce?"},
]
REVEALED = Episode(session_id="s1", stage="debug", hints_given=3, outcome="revealed")
IN_PROGRESS = Episode(session_id="s1", stage="debug", hints_given=1, outcome="in_progress")


async def test_fake_stores_kinds_per_outcome():
    mem = InMemoryLearnerMemory()
    await mem.remember("a", HISTORY, IN_PROGRESS)
    kinds = [i.kind for i in await mem.all("a")]
    assert kinds == [MemoryKind.SEMANTIC, MemoryKind.EPISODIC]

    await mem.remember("a", HISTORY, REVEALED)
    items = await mem.all("a")
    assert MemoryKind.PROCEDURAL in [i.kind for i in items]
    assert "Session s1: stage debug, 3 hints, outcome revealed" in [i.text for i in items]
    assert all(i.text != HISTORY[1]["text"] for i in items)  # tutor turns are not semantic


async def test_fake_recall_ranks_by_overlap_and_isolates_learners():
    mem = InMemoryLearnerMemory()
    await mem.remember("a", [{"role": "learner", "text": "recursion confuses me"}], IN_PROGRESS)
    await mem.remember("a", [{"role": "learner", "text": "for loop skips last"}], IN_PROGRESS)
    await mem.remember("b", [{"role": "learner", "text": "for loop skips last"}], IN_PROGRESS)

    got = await mem.recall("a", "why does my for loop skip the last item", limit=1)
    assert [i.text for i in got] == ["for loop skips last"]
    assert await mem.recall("c", "for loop") == []


async def test_fake_forget_returns_count_and_leaves_others():
    mem = InMemoryLearnerMemory()
    await mem.remember("a", HISTORY, REVEALED)
    await mem.remember("b", HISTORY, IN_PROGRESS)
    assert await mem.forget("a") == 3
    assert await mem.all("a") == []
    assert len(await mem.all("b")) == 2


class StubMem0:
    def __init__(self, results=None):
        self.calls = []
        self.results = results if results is not None else {"results": []}

    def add(self, messages, **kwargs):
        self.calls.append(("add", messages, kwargs))
        return {"results": []}

    def search(self, query, **kwargs):
        self.calls.append(("search", query, kwargs))
        return self.results

    def get_all(self, **kwargs):
        self.calls.append(("get_all", kwargs))
        return self.results

    def delete_all(self, **kwargs):
        self.calls.append(("delete_all", kwargs))
        return {"message": "Memories deleted successfully!"}


async def test_mem0_remember_revealed_adds_three_memories():
    stub = StubMem0()
    await Mem0LearnerMemory(Settings(), memory=stub).remember("a", HISTORY, REVEALED)
    semantic, episodic, procedural = stub.calls
    assert semantic == ("add", MESSAGES, {"user_id": "a", "metadata": {"kind": "semantic"}})

    _, text, kwargs = episodic
    assert text == "Session s1: stage debug, 3 hints, outcome revealed"
    at = kwargs["metadata"].pop("at")
    assert at.startswith("20") and "T" in at
    assert kwargs == {
        "user_id": "a",
        "run_id": "s1",
        "infer": False,
        "metadata": {"kind": "episodic", "stage": "debug", "hints_given": 3, "outcome": "revealed"},
    }
    assert procedural == (
        "add",
        MESSAGES,
        {
            "user_id": "a",
            "agent_id": AGENT_ID,
            "memory_type": "procedural_memory",
            "metadata": {"kind": "procedural"},
        },
    )


async def test_mem0_remember_in_progress_is_semantic_only():
    stub = StubMem0()
    await Mem0LearnerMemory(Settings(), memory=stub).remember("a", HISTORY, IN_PROGRESS)
    assert stub.calls == [("add", MESSAGES, {"user_id": "a", "metadata": {"kind": "semantic"}})]


ROWS = [
    {"id": "1", "memory": "struggles with off-by-one", "score": 0.9, "created_at": "t1"},
    {"id": "2", "memory": "Session s1", "score": 0.5, "metadata": {"kind": "episodic"}},
]
EXPECTED = [
    MemoryItem(MemoryKind.SEMANTIC, "struggles with off-by-one", "1", 0.9, "t1"),
    MemoryItem(MemoryKind.EPISODIC, "Session s1", "2", 0.5, ""),
]


@pytest.mark.parametrize("shape", [{"results": ROWS}, ROWS])
async def test_mem0_recall_tolerates_both_result_shapes(shape):
    stub = StubMem0(results=shape)
    got = await Mem0LearnerMemory(Settings(), memory=stub).recall("a", "loops", limit=2)
    assert got == EXPECTED
    assert stub.calls == [("search", "loops", {"filters": {"user_id": "a"}, "top_k": 2})]


async def test_mem0_forget_counts_then_deletes():
    stub = StubMem0(results={"results": ROWS})
    assert await Mem0LearnerMemory(Settings(), memory=stub).forget("a") == 2
    assert [c[0] for c in stub.calls] == ["get_all", "delete_all"]
    assert stub.calls[0][1]["filters"] == {"user_id": "a"}
    assert stub.calls[1] == ("delete_all", {"user_id": "a"})


def test_build_config_requires_model_fast():
    with pytest.raises(RuntimeError, match="CODEBUDDY_MODEL_FAST"):
        build_config(Settings(model_fast=None))


def test_build_config_is_valid_for_installed_mem0():
    from mem0.configs.base import MemoryConfig

    cfg = build_config(Settings(model_fast="fast-model", memory_path="data/mem"))
    assert cfg["vector_store"]["config"] == {
        "path": "data/mem",
        "collection_name": "codebuddy_memory",
        "embedding_model_dims": 1536,
    }
    assert cfg["llm"] == {"provider": "openai", "config": {"model": "fast-model"}}
    assert cfg["history_db_path"] == "data/mem/history.db"
    MemoryConfig(**cfg)  # validates keys without building clients
