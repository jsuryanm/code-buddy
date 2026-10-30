"""OpenAI model tiers built through LangChain (spec 11).

fast -> standard -> heavy. A heavier tier falls back to the next lighter one on error,
so the learner gets a (slightly weaker) answer instead of a failure.
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.embeddings import Embeddings
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from codebuddy.config import Settings


@dataclass
class Tiers:
    """Chat runnables per tier. `fast_base` is the raw model used for structured output."""

    fast: Runnable
    standard: Runnable
    heavy: Runnable
    fast_base: object | None = None


def build_tiers(settings: Settings) -> Tiers:
    fast_id, standard_id, heavy_id = settings.require_models()
    fast = ChatOpenAI(model=fast_id, timeout=3, max_retries=1)
    standard = ChatOpenAI(model=standard_id, timeout=5, max_retries=1).with_fallbacks([fast])
    heavy = ChatOpenAI(model=heavy_id, timeout=30, max_retries=1).with_fallbacks([standard])
    return Tiers(fast=fast, standard=standard, heavy=heavy, fast_base=fast)


def build_embeddings(settings: Settings) -> Embeddings:
    return OpenAIEmbeddings(model=settings.embed_model)
