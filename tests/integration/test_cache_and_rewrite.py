import numpy as np

from codebuddy.agent.state import Classification
from codebuddy.cache.memory import InMemoryCache
from codebuddy.cache.semantic import SemanticIndex
from codebuddy.rag.rerank import RetrievedChunk
from codebuddy.rag.retrieve import RetrievalResult
from codebuddy.schemas import Intent, PcditStage
from tests.helpers import ScriptedChat

BUGGY = "nums = [1, 2, 3]\nfor i in range(len(nums) + 1):\n    print(nums[i])\n"


async def test_semantic_index_threshold_and_replacement():
    idx = SemanticIndex(InMemoryCache(), namespace="n", threshold=0.9, max_entries=2, ttl=60)
    await idx.add([1.0, 0.0], "a")
    await idx.add([0.0, 1.0], "b")
    assert await idx.find([0.99, 0.05]) == "a"
    assert await idx.find([0.7, 0.7]) is None  # not close enough to either
    await idx.add([1.0, 0.0], "a")  # same key replaces instead of duplicating
    await idx.add([0.5, 0.5], "c")  # oldest entry drops at max_entries
    assert await idx.find([0.0, 1.0]) is None or await idx.find([0.0, 1.0]) == "c"


async def test_semantic_index_is_off_by_default():
    idx = SemanticIndex(InMemoryCache(), namespace="n", threshold=0.0, max_entries=5, ttl=60)
    await idx.add([1.0], "a")
    assert not idx.enabled and await idx.find([1.0]) is None


class PhraseEmbeddings:
    """Two phrasings of one question share a direction; others point elsewhere."""

    async def aembed_query(self, text: str) -> list[float]:
        same = "loop" in text.lower()
        vec = np.array([1.0, 0.1] if same else [0.1, 1.0])
        return vec.tolist()


async def test_rephrased_concept_question_hits_the_semantic_cache(make_harness):
    model = ScriptedChat(["A loop repeats code [1]."])
    h = make_harness(standard=model)
    h.deps.embeddings = PhraseEmbeddings()
    h.deps.semantic = SemanticIndex(
        InMemoryCache(), namespace="t", threshold=0.95, max_entries=10, ttl=60
    )
    first = await h.turn("what is a loop")
    assert not first["state"].get("cache_hit")
    second = await h.turn("Could you explain loops to me?")
    assert second["state"]["cache_hit"] is True and second["text"] == first["text"]
    assert len(model.calls) == 1
    assert (await h.deps.metrics.snapshot())["semantic_hits"] == 1

    other = await h.turn("what is recursion")  # different direction: no false positive
    assert not other["state"].get("cache_hit")


class FollowUpClassifier:
    def __init__(self):
        self.progress = []

    async def classify(self, message, code, progress):
        self.progress.append(progress)
        return Classification(
            intent=Intent.DEBUG_HELP,
            stage=PcditStage.T,
            concepts=["loop bounds"],
            search_query="off-by-one error in a loop",
        )


def context_of(model: ScriptedChat) -> str:
    return model.calls[-1][1][1]


def spy_queries(h) -> list[str]:
    calls = []
    original = h.deps.retriever.retrieve

    async def spy(query, **kw):
        calls.append(query)
        return await original(query, **kw)

    h.deps.retriever.retrieve = spy
    return calls


async def test_follow_up_retrieval_fuses_the_classifier_query(make_harness):
    model = ScriptedChat(["Q one?", "Q two?"])
    h = make_harness(standard=model)
    h.deps.classifier = FollowUpClassifier()
    calls = spy_queries(h)
    await h.turn("my loop crashes", code=BUGGY)
    await h.turn("and why?", code=BUGGY + "# retry\n")
    assert "off-by-one" in context_of(model)
    assert calls[-2].startswith("and why?") and calls[-1].startswith("off-by-one error")
    assert "nums" not in calls[-1]  # code identifiers never reach the search


async def test_long_messages_also_get_the_second_query(make_harness):
    model = ScriptedChat(["Q one?"])
    h = make_harness(standard=model)
    h.deps.classifier = FollowUpClassifier()
    calls = spy_queries(h)
    await h.turn("this is a much longer message about my loop crashing again today", code=BUGGY)
    assert len(calls) == 2  # first turn, no history, long message: still fused


async def test_refine_merges_instead_of_replacing(make_harness):
    h = make_harness(standard=ScriptedChat(["Q?"]))
    h.deps.classifier = FollowUpClassifier()
    first = RetrievedChunk("first only", 0.9, {"content_hash": "1"})
    second = RetrievedChunk("second only", 0.4, {"content_hash": "2"})

    async def fake(query, **kw):
        hit = second if query.startswith("off-by-one") else first
        return RetrievalResult([hit], grounded=True)

    h.deps.retriever.retrieve = fake
    out = await h.turn("my loop crashes", code=BUGGY)
    texts = [c.text for c in out["state"]["retrieval"].chunks]
    assert texts == ["first only", "second only"]
    assert out["state"]["retrieval"].grounded


async def test_same_query_skips_the_second_retrieval(make_harness):
    h = make_harness(standard=ScriptedChat(["Q?"]))  # heuristic classifier echoes the message
    calls = spy_queries(h)
    await h.turn("my loop crashes", code=BUGGY)
    assert len(calls) == 1


async def test_foreign_turn_gets_no_history_and_no_second_query(make_harness):
    h = make_harness(standard=ScriptedChat(["Q?", "Q?"]))
    classifier = FollowUpClassifier()
    h.deps.classifier = classifier
    await h.turn("why is my loop wrong", code=BUGGY, learner_id="learner-0123456789ab")
    calls = spy_queries(h)
    await h.turn("and why?", code=BUGGY)  # bound to another learner: a foreign turn
    assert classifier.progress[-1].history == []
    assert len(calls) == 1
    assert (await h.deps.sessions.load("s1")).history  # the owner's history is untouched
