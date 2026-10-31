"""Reasoning-model handling: effort only for reasoning ids; the empty-reply retry."""

import pytest

from codebuddy.config import Settings
from codebuddy.llm import build_tiers, is_reasoning_model


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("gpt-5-mini", True),
        ("gpt-5", True),
        ("o1-mini", True),
        ("o3", True),
        ("o4-mini", True),
        ("gpt-4o-mini", False),
        ("gpt-4.1", False),
        ("gpt-5-chat-latest", False),
    ],
)
def test_is_reasoning_model(model_id, expected):
    assert is_reasoning_model(model_id) is expected


def _tiers(effort="minimal"):
    s = Settings(
        _env_file=None,
        model_fast="gpt-4o-mini",
        model_standard="gpt-4o-mini",
        model_heavy="gpt-5-mini",
        reasoning_effort=effort,
    )
    t = build_tiers(s)
    return t.fast, t.standard, t.heavy


def test_reasoning_effort_is_sent_only_to_reasoning_models(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    fast, standard, heavy = _tiers()
    assert fast.reasoning_effort is None and standard.reasoning_effort is None
    assert heavy.reasoning_effort == "minimal"
    assert "reasoning_effort" not in fast._get_request_payload([("human", "hi")])
    assert heavy._get_request_payload([("human", "hi")])["reasoning_effort"] == "minimal"


def test_an_unknown_effort_falls_back_to_low(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    assert _tiers("bogus")[2].reasoning_effort == "low"
