import numpy as np

from codebuddy.agent.state import Classification
from codebuddy.cache.memory import InMemoryCache
from codebuddy.cache.semantic import SemanticIndex
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
    async def classify(self, message, code, progress):
        return Classification(
            intent=Intent.DEBUG_HELP,
            stage=PcditStage.T,
            search_query="off-by-one error in a loop",
        )


def context_of(model: ScriptedChat) -> str:
    return model.calls[-1][1][1]


async def test_short_follow_up_is_rewritten_before_retrieval(make_harness):
    model = ScriptedChat(["Q one?", "Q two?"])
    h = make_harness(standard=model)
    h.deps.classifier = FollowUpClassifier()
    await h.turn("my loop crashes", code=BUGGY)
    await h.turn("and why?", code=BUGGY + "# retry\n")
    assert "off-by-one" in context_of(model)


async def test_long_messages_are_not_rewritten(make_harness):
    calls = []
    model = ScriptedChat(["Q one?", "Q two?"])
    h = make_harness(standard=model)
    h.deps.classifier = FollowUpClassifier()
    original = h.deps.retriever.retrieve

    async def spy(query, **kw):
        calls.append(query)
        return await original(query, **kw)

    h.deps.retriever.retrieve = spy
    await h.turn("my loop crashes", code=BUGGY)
    before = len(calls)
    await h.turn(
        "this is a much longer message about my loop crashing again today", code=BUGGY + "# x\n"
    )
    assert len(calls) - before == 1  # one retrieval, no second pass
