from pathlib import Path

import pytest

from codebuddy.cache.layers import CachedEmbeddings, RetrievalCache
from codebuddy.cache.memory import InMemoryCache
from codebuddy.rag.chunking import chunk_markdown
from codebuddy.rag.ingest import html_to_markdown, ingest_file
from codebuddy.rag.manifest import Manifest
from codebuddy.rag.retrieve import Retriever
from codebuddy.rag.store import get_store

SAMPLE = Path(__file__).parents[2] / "data" / "sample"


def test_code_block_is_never_split_from_its_section():
    code = "\n".join(f"x{i} = {i}" for i in range(300))
    md = f"# Title\n\n## Big\n\nIntro text.\n\n```python\n{code}\n```\n\nAfter."
    chunks = chunk_markdown(md, {"title": "T", "source": "t.md"})
    holders = [c for c in chunks if "```python" in c.text]
    assert len(holders) == 1
    assert holders[0].text.count("```") == 2


def test_chunk_metadata_and_stable_ids():
    md = (SAMPLE / "python_basics.md").read_text()
    meta = {"title": "Sample", "source": "python_basics.md", "corpus": "fundamentals"}
    a = chunk_markdown(md, meta)
    b = chunk_markdown(md, meta)
    assert [c.id for c in a] == [c.id for c in b]
    types = {c.meta["content_type"] for c in a}
    assert {"example", "explanation", "exercise", "common-bug"} <= types
    assert all(c.meta["parent"] for c in a)
    assert any("Loops" in c.meta["section"] for c in a)


def test_html_is_converted_to_markdown():
    md = html_to_markdown("<h1>Loops</h1><p>Repeat.</p><pre>for i in x:\n  pass</pre>")
    assert md.startswith("# Loops") and "```" in md and "for i in x:" in md


@pytest.fixture
def stores(qdrant, embeddings, sparse, settings):
    return {
        c: get_store(c, qdrant, embeddings, sparse, settings) for c in ("fundamentals", "pedagogy")
    }


def test_ingest_is_idempotent_and_recorded(stores, settings, tmp_path):
    manifest = Manifest(tmp_path / "manifest.json")
    path = SAMPLE / "python_basics.md"
    kw = dict(
        corpus="fundamentals", store=stores["fundamentals"], manifest=manifest, settings=settings
    )
    first = ingest_file(path, licence="original", **kw)
    assert first > 0
    assert ingest_file(path, licence="original", **kw) == 0  # unchanged, skipped
    forced = ingest_file(path, licence="original", force=True, **kw)
    assert forced == first
    count = stores["fundamentals"].client.count(stores["fundamentals"].collection_name).count
    assert count == first  # same IDs overwritten, no duplicates
    assert manifest.entries()[0].licence == "original"


async def test_retrieval_finds_relevant_chunk_and_caches(stores, settings, embeddings, tmp_path):
    manifest = Manifest(tmp_path / "m.json")
    ingest_file(
        SAMPLE / "python_basics.md",
        corpus="fundamentals",
        store=stores["fundamentals"],
        manifest=manifest,
        settings=settings,
    )
    cache = InMemoryCache()
    retriever = Retriever(
        stores,
        settings,
        allowed={"fundamentals"},
        embeddings=CachedEmbeddings(embeddings, cache, "fake", ttl=60),
        cache=RetrievalCache(cache, ttl=60),
    )
    first = await retriever.retrieve("what is an off-by-one error in a loop")
    assert first.grounded and not first.cache_hit
    assert any("off-by-one" in c.text for c in first.chunks)
    again = await retriever.retrieve("what is an off-by-one error in a loop")
    assert again.cache_hit and [c.text for c in again.chunks] == [c.text for c in first.chunks]


async def test_learner_retriever_cannot_read_pedagogy(stores, settings):
    learner = Retriever(stores, settings, allowed={"fundamentals"})
    with pytest.raises(PermissionError):
        await learner.retrieve("anything", corpus="pedagogy")
    internal = Retriever(stores, settings, allowed={"fundamentals", "pedagogy"})
    assert (await internal.retrieve("anything", corpus="pedagogy")).chunks == []


async def test_filters_restrict_results(stores, settings, tmp_path):
    ingest_file(
        SAMPLE / "python_basics.md",
        corpus="fundamentals",
        store=stores["fundamentals"],
        manifest=Manifest(tmp_path / "m.json"),
        settings=settings,
    )
    r = Retriever(stores, settings, allowed={"fundamentals"})
    res = await r.retrieve("loop", filters={"content_type": "exercise"})
    assert res.chunks and all(c.meta["content_type"] == "exercise" for c in res.chunks)
