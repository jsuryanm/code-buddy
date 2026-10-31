"""Retrieval queries: what the tutor searches for, and how two result lists are merged.

The query is the learner's message plus plain words for what static analysis found. It never
holds the learner's code: only bug-pattern terms, "syntax error", and the names of built-ins
and container methods the code calls.
"""

from __future__ import annotations

from collections.abc import Iterable

from codebuddy.agent.code_analysis import PATTERNS, CodeFeatures
from codebuddy.rag.rerank import RetrievedChunk

MAX_QUERY_CHARS = 300
RRF_K = 60


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    return cut.rsplit(" ", 1)[0] if " " in cut else cut


def build_query(message: str, features: CodeFeatures | None, concepts: Iterable[str] = ()) -> str:
    """Message first, then the extra terms, without repeats, in at most MAX_QUERY_CHARS."""
    extras: list[str] = []
    if features:
        for p in features.patterns:
            extras += [PATTERNS[p].concept, *PATTERNS[p].search_terms]
        if features.parse_error:
            extras.append("syntax error")
        extras += features.calls
    extras += concepts
    seen = set(message.lower().split())
    kept = []
    for term in (" ".join(t.split()) for t in extras):
        if term and term.lower() not in seen:
            seen.add(term.lower())
            kept.append(term)
    tail = _clip(" ".join(kept), MAX_QUERY_CHARS // 2)
    head = " ".join(message.split())
    head = _clip(head, MAX_QUERY_CHARS - len(tail) - 1) if tail else head
    return _clip(" ".join(p for p in (head, tail) if p), MAX_QUERY_CHARS)


def _key(chunk: RetrievedChunk) -> str:
    return str(chunk.meta.get("content_hash") or chunk.text)


def rrf_merge(lists: list[list[RetrievedChunk]], top: int, k: int = RRF_K) -> list[RetrievedChunk]:
    """Reciprocal rank fusion. A chunk found by both queries rises; each keeps its best score."""
    fused: dict[str, float] = {}
    best: dict[str, RetrievedChunk] = {}
    for chunks in lists:
        for rank, chunk in enumerate(chunks):
            key = _key(chunk)
            fused[key] = fused.get(key, 0.0) + 1.0 / (k + rank + 1)
            if key not in best or chunk.score > best[key].score:
                best[key] = chunk
    order = sorted(fused, key=lambda key: fused[key], reverse=True)
    return [best[key] for key in order[:top]]
