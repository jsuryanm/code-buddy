"""Qdrant Cloud settings: alias names, collection prefix, client wiring, startup log line."""

import logging

import pytest
from loguru import logger
from pydantic import ValidationError
from qdrant_client import QdrantClient

from codebuddy.config import Settings
from codebuddy.rag import store as store_module
from codebuddy.rag.retrieve import Retriever
from codebuddy.rag.store import collection_name, get_store, make_client

KEY = "SENTINELQDRANTKEY"
URL = "https://abc.cloud.qdrant.io:6333/path?x=1"
NAMES = (
    "CODEBUDDY_QDRANT_URL",
    "QDRANT_CLUSTER_ENDPOINT",
    "CODEBUDDY_QDRANT_API_KEY",
    "QDRANT_API_KEY",
    "CODEBUDDY_QDRANT_COLLECTION_PREFIX",
    "QDRANT_COLLECTION_NAME",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for n in NAMES:
        monkeypatch.delenv(n, raising=False)


def make(monkeypatch, **env) -> Settings:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Settings(_env_file=None)


@pytest.mark.parametrize(
    ("env", "url"),
    [
        ({}, None),
        ({"CODEBUDDY_QDRANT_URL": "https://a"}, "https://a"),
        ({"QDRANT_CLUSTER_ENDPOINT": "https://b"}, "https://b"),
        (
            {"CODEBUDDY_QDRANT_URL": "https://a", "QDRANT_CLUSTER_ENDPOINT": "https://b"},
            "https://a",
        ),
    ],
)
def test_endpoint_aliases(monkeypatch, env, url):
    assert make(monkeypatch, **env).qdrant_url == url


def test_key_and_prefix_aliases_and_precedence(monkeypatch):
    s = make(monkeypatch, QDRANT_API_KEY=KEY, QDRANT_COLLECTION_NAME="tutor")
    assert s.qdrant_api_key.get_secret_value() == KEY and s.qdrant_collection_prefix == "tutor"
    s = make(monkeypatch, CODEBUDDY_QDRANT_COLLECTION_PREFIX="mine")
    assert s.qdrant_collection_prefix == "mine"  # prefixed name wins over QDRANT_COLLECTION_NAME
    assert KEY not in repr(s) and KEY not in str(s.model_dump())


def test_unprefixed_names_are_read_from_the_env_file(tmp_path):
    f = tmp_path / "x.env"
    f.write_text(
        f"QDRANT_CLUSTER_ENDPOINT=https://c\nQDRANT_API_KEY={KEY}\nQDRANT_COLLECTION_NAME=z\n"
    )
    s = Settings(_env_file=f)
    assert (s.qdrant_url, s.qdrant_collection_prefix) == ("https://c", "z")
    assert s.qdrant_api_key.get_secret_value() == KEY


@pytest.mark.parametrize("bad", ["a b", "a/b", "", "x.y"])
def test_prefix_is_validated(monkeypatch, bad):
    monkeypatch.setenv("QDRANT_COLLECTION_NAME", bad)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_default_prefix_keeps_existing_names():
    s = Settings(_env_file=None)
    assert collection_name("fundamentals", s) == "cb_fundamentals_v1"
    assert collection_name(
        "pedagogy", s.model_copy(update={"qdrant_collection_prefix": "t-1"})
    ) == ("t-1_pedagogy_v1")


def test_make_client_passes_url_and_key(monkeypatch):
    seen = {}

    class Fake:
        def __init__(self, **kw):
            seen.update(kw)

        def get_collections(self):
            return []

    monkeypatch.setattr(store_module, "QdrantClient", Fake)
    make_client(Settings(_env_file=None, qdrant_url=URL, qdrant_api_key=KEY))
    assert seen == {"url": URL, "api_key": KEY}


def test_unreachable_server_gives_a_plain_message_without_the_key(monkeypatch):
    class Down:
        def __init__(self, **kw):
            pass

        def get_collections(self):
            raise ConnectionError(f"boom {KEY}")

    monkeypatch.setattr(store_module, "QdrantClient", Down)
    with pytest.raises(RuntimeError) as err:
        make_client(Settings(_env_file=None, qdrant_url=URL, qdrant_api_key=KEY))
    msg = str(err.value)
    assert msg == (
        "Could not reach Qdrant at abc.cloud.qdrant.io: ConnectionError. "
        "Check QDRANT_CLUSTER_ENDPOINT and QDRANT_API_KEY."
    )


def test_startup_line_has_host_and_prefix_but_never_the_key(monkeypatch, caplog):
    class Ok:
        def __init__(self, **kw):
            pass

        def get_collections(self):
            return []

    monkeypatch.setattr(store_module, "QdrantClient", Ok)
    lines: list[str] = []
    sink = logger.add(lines.append, level="DEBUG", format="{message}")
    s = Settings(_env_file=None, qdrant_url=URL, qdrant_api_key=KEY, qdrant_collection_prefix="t")
    try:
        with caplog.at_level(logging.DEBUG):
            make_client(s, ("fundamentals",))
    finally:
        logger.remove(sink)
    text = " ".join(r.getMessage() for r in caplog.records)
    assert (
        "qdrant=server host=abc.cloud.qdrant.io prefix=t collections=['t_fundamentals_v1']" in text
    )
    assert KEY not in text and "/path" not in text and "x=1" not in text


def test_key_without_endpoint_warns_and_stays_embedded(tmp_path, caplog):
    s = Settings(_env_file=None, qdrant_api_key=KEY, qdrant_path=str(tmp_path / "i"))
    with caplog.at_level(logging.INFO):
        client = make_client(s)
    client.close()
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "qdrant=embedded path=" in text and "no endpoint" in text and KEY not in text


async def test_custom_prefix_keeps_the_corpus_split(embeddings, sparse):
    s = Settings(_env_file=None, qdrant_collection_prefix="tenant", relevance_threshold=0.0)
    client = QdrantClient(":memory:")
    stores = {c: get_store(c, client, embeddings, sparse, s) for c in ("fundamentals", "pedagogy")}
    assert stores["pedagogy"].collection_name == "tenant_pedagogy_v1"
    assert {c.name for c in client.get_collections().collections} == {
        "tenant_fundamentals_v1",
        "tenant_pedagogy_v1",
    }
    learner = Retriever(stores, s, allowed={"fundamentals"})
    with pytest.raises(PermissionError):
        await learner.retrieve("anything", corpus="pedagogy")
