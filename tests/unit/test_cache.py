import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from codebuddy.cache import keys
from codebuddy.cache.layers import (
    AnswerCache,
    CachedAnswer,
    CachedEmbeddings,
    RetrievalCache,
    SessionStore,
    is_answer_cacheable,
)
from codebuddy.cache.memory import InMemoryCache
from codebuddy.schemas import Decision, HintLevel, Mode


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


BASE = dict(
    mode="hint",
    hint_level=1,
    learner_level="beginner",
    index_version="v1",
    prompt_version="p1",
    model_id="m",
)


def test_answer_key_ignores_case_and_spacing():
    assert keys.answer_key("What  is a LOOP?", **BASE) == keys.answer_key("what is a loop?", **BASE)


@pytest.mark.parametrize(
    "field,value",
    [
        ("mode", "reveal"),
        ("hint_level", 2),
        ("index_version", "v2"),
        ("prompt_version", "p2"),
        ("model_id", "other"),
    ],
)
def test_answer_key_changes_with_context(field, value):
    assert keys.answer_key("q", **BASE) != keys.answer_key("q", **{**BASE, field: value})


async def test_memory_cache_ttl_and_nx():
    clock = Clock()
    c = InMemoryCache(clock)
    await c.set("a", "1", ttl=10)
    assert await c.get("a") == "1"
    assert await c.set_nx("a", "2", 10) is False
    clock.now = 11
    assert await c.get("a") is None
    assert await c.set_nx("a", "2", 10) is True


async def test_incr_sets_ttl_once():
    clock = Clock()
    c = InMemoryCache(clock)
    assert await c.incr("n", ttl=5) == 1
    clock.now = 3
    assert await c.incr("n", ttl=5) == 2
    clock.now = 6
    assert await c.incr("n", ttl=5) == 1


async def test_answer_cache_roundtrip_and_single_flight():
    c = InMemoryCache()
    cache = AnswerCache(c, ttl=60)
    assert await cache.get("k") is None
    assert await cache.try_lock("k") is True
    assert await cache.try_lock("k") is False
    await cache.put("k", CachedAnswer("hello", [{"source": "x"}]))
    assert (await cache.get("k")).text == "hello"
    await cache.unlock("k")
    assert await cache.try_lock("k") is True


async def test_wait_for_times_out_then_finds_value():
    cache = AnswerCache(InMemoryCache(), ttl=60)
    assert await cache.wait_for("k", timeout=0.1) is None
    await cache.put("k", CachedAnswer("ready"))
    assert (await cache.wait_for("k", timeout=0.1)).text == "ready"


def test_only_concept_answers_without_code_are_cacheable():
    explain = Decision(mode=Mode.EXPLAIN)
    reveal = Decision(mode=Mode.REVEAL, level=HintLevel.REVEAL)
    hint = Decision(mode=Mode.HINT, level=HintLevel.DIAGNOSE)
    assert is_answer_cacheable(explain, has_code=False)
    assert not is_answer_cacheable(explain, has_code=True)
    assert not is_answer_cacheable(reveal, has_code=False)
    assert not is_answer_cacheable(hint, has_code=False)


async def test_embedding_cache_hits_second_time():
    inner = DeterministicFakeEmbedding(size=8)
    store = InMemoryCache()
    first = CachedEmbeddings(inner, store, "fake", ttl=60)
    assert await first.warm_query("loops") is False
    # A fresh instance (new process) finds the vector in the shared cache.
    second = CachedEmbeddings(inner, store, "fake", ttl=60)
    assert await second.warm_query("loops") is True
    assert second.embed_query("loops") == inner.embed_query("loops")


async def test_retrieval_cache_and_session_store():
    store = InMemoryCache()
    r = RetrievalCache(store, ttl=60)
    await r.put("k", [{"text": "t"}])
    assert await r.get("k") == [{"text": "t"}]
    s = SessionStore(store, ttl=60)
    p = await s.load("abc")
    assert p.hints_given == 0
    p.hints_given = 2
    await s.save(p)
    assert (await s.load("abc")).hints_given == 2
