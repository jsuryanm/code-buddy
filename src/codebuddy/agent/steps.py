"""Progress steps shown to the learner while a turn runs.

Labels and details are fixed, learner-friendly text. They never carry bug-pattern ids,
analysis findings, runtime errors, or code: the stream is public, the analysis is private.
"""

from __future__ import annotations

import re
from collections.abc import Callable

LABELS = {
    "analyze_code": "Reading your code",
    "check_cache": "Found a saved explanation",
    "classify": "Understanding your question",
    "retrieve": "Searching the course material",
    "recall_memory": "Remembering earlier sessions",
    "policy": "Choosing how to help",
    "run_tools": "Running your code safely",
    "generate": "Writing a reply",
}


def short_title(title: str) -> str:
    """ "Think Python: How to Think Like ... (v2.0.17)" -> "Think Python"."""
    short = re.sub(r"\s*\(.*?\)", "", title).split(":")[0].strip()
    return short or title


def emit_step(
    writer: Callable[[dict], None],
    key: str,
    status: str,
    detail: str | None = None,
    label: str | None = None,
) -> None:
    writer(
        {
            "type": "step",
            "key": key,
            "label": label or LABELS[key],
            "status": status,
            "detail": detail,
        }
    )
