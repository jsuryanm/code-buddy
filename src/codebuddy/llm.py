"""OpenAI model tiers built through LangChain (spec 11).

fast -> standard -> heavy. Generation falls back from a heavier tier to the next lighter one on
an error or an empty reply (agent/nodes.py), so the learner gets a (slightly weaker) answer
instead of a failure.
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.embeddings import Embeddings
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from codebuddy.config import Settings

# Values the installed openai SDK accepts for reasoning_effort that suit a tutor reply.
REASONING_EFFORTS = ("minimal", "low", "medium", "high")
_REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def is_reasoning_model(model_id: str) -> bool:
    """True for OpenAI reasoning models. This is a name-prefix check (gpt-5*, o1*, o3*, o4*),
    used only to decide whether to send `reasoning_effort`; model IDs still come from env."""
    name = model_id.lower().rsplit("/", 1)[-1]
    # gpt-5-chat is not a reasoning model.
    return name.startswith(_REASONING_PREFIXES) and not name.startswith("gpt-5-chat")


def _chat(model_id: str, settings: Settings, timeout: int) -> ChatOpenAI:
    kwargs: dict = {}
    if is_reasoning_model(model_id):
        effort = settings.reasoning_effort.lower()
        kwargs["reasoning_effort"] = effort if effort in REASONING_EFFORTS else "low"
    return ChatOpenAI(model=model_id, timeout=timeout, max_retries=1, **kwargs)


@dataclass
class Tiers:
    """Chat models per tier, tried heavy -> standard -> fast by `generate`. `fast_base` is the
    model used for structured output."""

    fast: Runnable
    standard: Runnable
    heavy: Runnable
    fast_base: object | None = None

    def chain(self, tier: str) -> list[tuple[str, Runnable]]:
        """The named tier, then each lighter one; a model shared by two tiers is tried once."""
        names = ("heavy", "standard", "fast")
        out: list[tuple[str, Runnable]] = []
        for name in names[names.index(tier) :]:
            model = getattr(self, name)
            if all(model is not m for _, m in out):
                out.append((name, model))
        return out


def build_tiers(settings: Settings) -> Tiers:
    fast_id, standard_id, heavy_id = settings.require_models()
    fast = _chat(fast_id, settings, 3)
    standard = _chat(standard_id, settings, 5)
    heavy = _chat(heavy_id, settings, 30)
    return Tiers(fast=fast, standard=standard, heavy=heavy, fast_base=fast)


def build_embeddings(settings: Settings) -> Embeddings:
    return OpenAIEmbeddings(model=settings.embed_model)
