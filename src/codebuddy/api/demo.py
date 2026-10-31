"""Keyless demo server: scripted tutor + the sample corpus. For trying the UI only.

    uv run uvicorn codebuddy.api.demo:app --port 8000

The replies are canned, not generated. Use the real app (codebuddy.api.app) with
OpenAI keys for actual tutoring.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.messages import AIMessageChunk
from qdrant_client import QdrantClient

from codebuddy.agent.deps import Deps, HeuristicClassifier
from codebuddy.api.app import create_app
from codebuddy.cache.layers import AnswerCache, SessionStore
from codebuddy.cache.memory import InMemoryCache
from codebuddy.config import Settings
from codebuddy.llm import Tiers
from codebuddy.memory.store import InMemoryLearnerMemory
from codebuddy.rag.fakes import HashSparse
from codebuddy.rag.ingest import ingest_file
from codebuddy.rag.manifest import Manifest
from codebuddy.rag.retrieve import Retriever
from codebuddy.rag.store import get_store
from codebuddy.stt.transcribe import Transcript
from codebuddy.tools.runner import LocalToolRunner

SAMPLE = Path(__file__).parents[3] / "data" / "sample"

HINTS = {
    0: "The crash happens on the last pass of your loop, at `total += nums[i]`. There `i` "
    "is one past the end, so it asks for an item your list does not have (an IndexError). "
    "What is the biggest `i` your loop line lets through?",
    1: "Look at your loop line. Your list has 3 items, so the last valid index is 2, but "
    "your `range` goes one step further. Think about what the stop value should be. "
    "Which number should the loop stop before?",
    2: "This is an off-by-one error: `range(n)` stops before `n`, and indexes end at "
    "n - 1 [1]. Trace it: i = 0, 1, 2 are fine, i = 3 is past the end. What does that say "
    "about your loop line?",
    3: "Plan: start the total at zero, visit each valid index once, add the item. "
    "Which step of your loop breaks that plan?",
}
REVEAL = (
    "Here is the fixed loop:\n\n```python\nnums = [1, 2, 3]\ntotal = 0\n"
    "for i in range(len(nums)):\n    total += nums[i]\n```\n\n"
    "`range(len(nums) + 1)` made `i` reach 3, but the last index is 2. "
    "What would you change to add only the first two items?"
)

CONFIRM = (
    "Nice work, that fixed it: your loop now stops at the last valid index. In one sentence, "
    "why does your change work? When you are ready, try a short quiz on the same kind of bug."
)

AFTER_FIX = (
    "Yes, that is the idea: the loop now stops before it runs past the end. The short quiz on "
    "the same kind of bug is still there when you want it."
)


class DemoTutor:
    """Picks a canned reply from the hint level named in the system prompt."""

    async def astream(self, messages, *args, **kwargs):
        system = messages[0][1]
        if "Show the complete corrected solution" in system:
            text = REVEAL
        elif (m := re.search(r"Hint level (\d)", system)) and int(m.group(1)) in HINTS:
            text = HINTS[int(m.group(1))]
        elif "The learner fixed the bug" in system:
            text = CONFIRM
        elif "The learner already fixed the bug" in system:
            text = AFTER_FIX
        elif "Explain the concept directly" in system:
            text = (
                "A loop repeats a block of code, visiting one item at a time [1]. "
                "What would you loop over?"
            )
        else:
            text = "That is outside what I can help with here. Ask me a programming question!"
        for token in re.findall(r"\S+\s*", text):
            yield AIMessageChunk(content=token)


class DemoSpeech:
    """Pretends to transcribe so the microphone widget can be tried without a Groq key."""

    async def transcribe(self, audio: bytes, filename: str = "speech.wav") -> Transcript:
        return Transcript("Why does my loop crash with an index error?", "demo")


def build_demo_deps() -> Deps:
    settings = Settings(
        _env_file=None,
        model_fast="demo",
        model_standard="demo",
        model_heavy="demo",
        relevance_threshold=0.0,
        qdrant_path=tempfile.mkdtemp(),
    )
    embeddings, sparse = DeterministicFakeEmbedding(size=32), HashSparse()
    store = get_store("fundamentals", QdrantClient(":memory:"), embeddings, sparse, settings)
    ingest_file(
        SAMPLE / "python_basics.md",
        corpus="fundamentals",
        store=store,
        manifest=Manifest(Path(settings.qdrant_path) / "m.json"),
        settings=settings,
        title="Sample Python Basics",
    )
    cache = InMemoryCache()
    tutor = DemoTutor()
    return Deps(
        settings=settings,
        tiers=Tiers(fast=tutor, standard=tutor, heavy=tutor),
        classifier=HeuristicClassifier(),
        retriever=Retriever({"fundamentals": store}, settings, allowed={"fundamentals"}),
        sessions=SessionStore(cache, ttl=3600),
        answers=AnswerCache(cache, ttl=3600),
        tools=LocalToolRunner(),  # real sandbox, so the permission prompt is genuine
        memory=InMemoryLearnerMemory(),
    )


app = create_app(build_demo_deps(), cache_kind="demo (in-memory)", speech=DemoSpeech())
