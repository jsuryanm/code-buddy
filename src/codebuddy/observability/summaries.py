"""Safe, whitelisted summaries of node updates for logs.

Each node has a whitelist of state keys and a function that turns each into metadata: numbers,
booleans, short enum values, tool names and source titles. Unknown keys are dropped, never
stringified, so learner messages, code, replies, prompts and learner ids cannot reach a log.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from functools import lru_cache
from typing import Any


@lru_cache(maxsize=4096)
def hash_session(session_id: str | None) -> str:
    """A short, stable tag for a session id: the first 8 hex of its sha256 ("-" when absent)."""
    if not session_id:
        return "-"
    return hashlib.sha256(session_id.encode()).hexdigest()[:8]


def _enum(value: Any) -> Any:
    return getattr(value, "value", value)


def _retrieval(r: Any) -> dict:
    titles = list(dict.fromkeys(c.source[:60] for c in r.chunks if c.source))
    return {
        "chunks": len(r.chunks),
        "grounded": r.grounded,
        "cache_hit": r.cache_hit,
        "sources": titles,
    }


def _decision(d: Any) -> dict:
    return {
        "mode": _enum(d.mode),
        "level": None if d.level is None else int(d.level),
        "can_show": d.can_show_answer,
        "offer": d.offer_answer,
        "offer_quiz": d.offer_quiz,
        "reasons": list(d.reasons),  # written by pedagogy/policy.py, never learner text
    }


def _progress(p: Any) -> dict:
    return {
        "hints_given": p.hints_given,
        "stage": _enum(p.stage),
        "reveals": p.reveals,
        "quiz_index": p.quiz.get("index") if p.quiz else None,
    }


Extract = Callable[[Any], dict]

WHITELIST: dict[str, dict[str, Extract]] = {
    "load_state": {
        "code": lambda v: {"has_code": bool(v)},
        "code_changed": lambda v: {"code_changed": bool(v)},
        "foreign": lambda v: {"foreign": bool(v)},
    },
    "analyze_code": {
        "features": lambda f: {
            "patterns": list(f.patterns),  # pattern ids from code_analysis.PATTERNS
            "parse_error": bool(f.parse_error),
        },
    },
    "check_cache": {
        "cache_hit": lambda v: {"hit": bool(v)},
        "cache_locked": lambda v: {"locked": bool(v)},
        "cache_key": lambda v: {"cacheable": v is not None},
    },
    "emit_cached": {
        "decision": lambda d: {"mode": _enum(d.mode)},
        "reply": lambda v: {"reply_chars": len(v or "")},
    },
    "classify": {
        "classification": lambda c: {
            "intent": _enum(c.intent),
            "stage": _enum(c.stage),
            "concepts": len(c.concepts),
        },
    },
    "retrieve": {"retrieval": _retrieval},
    "refine_retrieval": {"retrieval": _retrieval},
    "recall_memory": {"memories": lambda m: {"memories": len(m or [])}},
    "policy": {
        "decision": _decision,
        "tool_plan": lambda p: {"tools": list(p or [])},
        "quiz_turn": lambda v: {"quiz_turn": bool(v)},
    },
    "approve_run": {"approved": lambda v: {"approved": bool(v)}},
    "run_tools": {
        "runtime": lambda r: {"traced": bool(r and r.get("ran"))},
        "cases": lambda c: {"cases": len(c or [])},
    },
    "generate": {
        "reply": lambda v: {"reply_chars": len(v or "")},
        "guarded": lambda v: {"guarded": bool(v)},
        "degraded": lambda v: {"degraded": bool(v)},
    },
    "update_state": {"progress": _progress},
}

# Nodes that may return nothing; say so instead of logging an empty summary.
EMPTY = {"refine_retrieval": {"refined": False}, "run_tools": {"ran": False}}


def safe_summary(node: str, update: Any) -> dict:
    """Metadata about a node's update. Never raises; unknown nodes and keys give nothing."""
    allowed = WHITELIST.get(node)
    if not allowed or not isinstance(update, dict):
        return {}
    if not update:
        return dict(EMPTY.get(node, {}))
    out: dict = {}
    for key, extract in allowed.items():
        if key in update:
            try:
                out |= extract(update[key])
            except Exception:  # an odd value must not break a turn; its key is left out
                continue
    return out


def format_summary(summary: dict) -> str:
    return " ".join(f"{k}={v}" for k, v in summary.items())
