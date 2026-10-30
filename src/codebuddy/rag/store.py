"""Qdrant vector store, one collection per corpus (spec 9.3).

Dev uses an embedded index on disk (single process). Set CODEBUDDY_QDRANT_URL for a server.
"""

from __future__ import annotations

from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore, RetrievalMode, SparseEmbeddings
from qdrant_client import QdrantClient, models

from codebuddy.config import Settings

DENSE = "dense"
SPARSE = "sparse"
KNOWN_CORPORA = ("fundamentals", "pedagogy")


def make_client(settings: Settings) -> QdrantClient:
    if settings.qdrant_url:
        return QdrantClient(url=settings.qdrant_url)
    return QdrantClient(path=settings.qdrant_path)


def collection_name(corpus: str, settings: Settings) -> str:
    safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in corpus)
    return f"cb_{safe}_{settings.index_version}"


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
