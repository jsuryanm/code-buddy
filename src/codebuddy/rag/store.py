"""Qdrant vector store, one collection per corpus (spec 9.3).

Dev uses an embedded index on disk (single process). Set CODEBUDDY_QDRANT_URL (or the Qdrant
Cloud name QDRANT_CLUSTER_ENDPOINT) and optionally QDRANT_API_KEY for a server. Collections are
named `<prefix>_<corpus>_<index_version>`; the prefix is QDRANT_COLLECTION_NAME (default `cb`).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from urllib.parse import urlparse

from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore, RetrievalMode, SparseEmbeddings
from qdrant_client import QdrantClient, models

from codebuddy.config import Settings

log = logging.getLogger("codebuddy.rag")

DENSE = "dense"
SPARSE = "sparse"
KNOWN_CORPORA = ("fundamentals", "pedagogy")


def qdrant_host(url: str) -> str:
    """Host only: no key, credentials, path or query ever reach a log line."""
    parsed = urlparse(url if "//" in url else f"//{url}")
    return parsed.hostname or "?"


def qdrant_target(settings: Settings) -> str:
    if settings.qdrant_url:
        return f"server host={qdrant_host(settings.qdrant_url)}"
    return f"embedded path={settings.qdrant_path}"


def make_client(settings: Settings, corpora: Sequence[str] = ()) -> QdrantClient:
    """Open the store and log where it points. A server is probed so a bad endpoint or key
    fails here with a plain message instead of deep inside the first search."""
    if settings.qdrant_url:
        names = [collection_name(c, settings) for c in corpora]
        log.info(
            "qdrant=server host=%s prefix=%s collections=%s",
            qdrant_host(settings.qdrant_url),
            settings.qdrant_collection_prefix,
            names,
        )
        key = settings.qdrant_api_key
        client = QdrantClient(
            url=settings.qdrant_url, api_key=key.get_secret_value() if key else None
        )
        try:
            client.get_collections()
        except Exception as exc:
            raise RuntimeError(
                f"Could not reach Qdrant at {qdrant_host(settings.qdrant_url)}: "
                f"{type(exc).__name__}. Check QDRANT_CLUSTER_ENDPOINT and QDRANT_API_KEY."
            ) from None
        return client
    log.info("qdrant=embedded path=%s", settings.qdrant_path)
    if settings.qdrant_api_key:
        log.warning(
            "QDRANT_API_KEY is set but no endpoint is: using the embedded index. "
            "Set QDRANT_CLUSTER_ENDPOINT to use a server."
        )
    if os.environ.get("QDRANT_CLUSTER_ENDPOINT", None) == "":
        log.warning("QDRANT_CLUSTER_ENDPOINT is empty: using the embedded index")
    return QdrantClient(path=settings.qdrant_path)


def collection_name(corpus: str, settings: Settings) -> str:
    safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in corpus)
    return f"{settings.qdrant_collection_prefix}_{safe}_{settings.index_version}"


def get_store(
    corpus: str,
    client: QdrantClient,
    embeddings: Embeddings,
    sparse: SparseEmbeddings,
    settings: Settings,
) -> QdrantVectorStore:
    name = collection_name(corpus, settings)
    if not client.collection_exists(name):
        size = len(embeddings.embed_query("dimension probe"))
        client.create_collection(
            collection_name=name,
            vectors_config={DENSE: models.VectorParams(size=size, distance=models.Distance.COSINE)},
            sparse_vectors_config={SPARSE: models.SparseVectorParams()},
        )
        if settings.qdrant_url:  # payload indexes only matter (and only work) on a server
            for field in ("metadata.concept", "metadata.content_type", "metadata.language"):
                client.create_payload_index(name, field, models.PayloadSchemaType.KEYWORD)
    return QdrantVectorStore(
        client=client,
        collection_name=name,
        embedding=embeddings,
        sparse_embedding=sparse,
        retrieval_mode=RetrievalMode.HYBRID,
        vector_name=DENSE,
        sparse_vector_name=SPARSE,
    )


def build_filter(filters: dict[str, str] | None) -> models.Filter | None:
    if not filters:
        return None
    return models.Filter(
        must=[
            models.FieldCondition(key=f"metadata.{k}", match=models.MatchValue(value=v))
            for k, v in filters.items()
        ]
    )
