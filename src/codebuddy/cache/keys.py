"""Cache key builders (spec 10.3, 10.4).

Keys fold in everything that changes the right answer: hint level, mode, and the
index, prompt, and model versions. Bumping any version invalidates old entries.
"""

from __future__ import annotations

import hashlib
import json
import re

PREFIX = "cb"


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _digest(*parts: object) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def answer_key(
    query: str,
    *,
    mode: str,
    hint_level: int | None,
    learner_level: str,
    index_version: str,
    prompt_version: str,
    model_id: str,
) -> str:
    return f"{PREFIX}:ans:" + _digest(
        normalize(query), mode, hint_level, learner_level, index_version, prompt_version, model_id
    )


def embedding_key(text: str, embed_model: str) -> str:
    return f"{PREFIX}:emb:" + _digest(text, embed_model)


def retrieval_key(query: str, corpus: str, filters: dict, index_version: str) -> str:
    return f"{PREFIX}:ret:" + _digest(normalize(query), corpus, filters, index_version)


def session_key(session_id: str) -> str:
    return f"{PREFIX}:sess:{session_id}"


FORGOT_TTL = 30 * 24 * 60 * 60  # outlives any session that still holds turns from before Forget


def forgot_key(learner_id: str) -> str:
    """When the learner last pressed Forget me; older session turns are never written again."""
    return f"{PREFIX}:forgot:{learner_id}"


def lock_key(key: str) -> str:
    return f"{PREFIX}:lock:{key}"
