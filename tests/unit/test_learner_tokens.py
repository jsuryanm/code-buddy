import re

import pytest
from pydantic import ValidationError

from codebuddy.api.security import LearnerTokens
from codebuddy.config import Settings
from codebuddy.schemas import LEARNER_TOKEN

tokens = LearnerTokens(b"k" * 32)


def test_issue_and_verify_round_trip():
    token = tokens.issue(None)
    assert re.fullmatch(LEARNER_TOKEN, token)
    learner_id = tokens.verify(token, None)
    assert learner_id == token.split(".")[0]
    assert tokens.issue(None) != token


def test_tampered_id_or_signature_fails():
    learner_id, sig = tokens.issue(None).split(".")
    flipped = ("A" if learner_id[0] != "A" else "B") + learner_id[1:]
    assert tokens.verify(f"{flipped}.{sig}", None) is None
    bad_sig = sig[:-1] + ("A" if sig[-1] != "A" else "B")
    assert tokens.verify(f"{learner_id}.{bad_sig}", None) is None
    assert tokens.verify(learner_id, None) is None
    assert tokens.verify("", None) is None
    assert LearnerTokens(b"other" * 8).verify(f"{learner_id}.{sig}", None) is None


def test_token_is_bound_to_the_api_key_that_minted_it():
    token = tokens.issue("key-a")
    assert tokens.verify(token, "key-a")
    assert tokens.verify(token, "key-b") is None
    assert tokens.verify(token, None) is None


def test_write_every_must_be_positive():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, memory_write_every=0)


def test_memory_secret_is_hidden_from_repr():
    settings = Settings(_env_file=None, memory_secret="x" * 32)
    assert "x" * 32 not in repr(settings)
    assert settings.memory_secret.get_secret_value() == "x" * 32
