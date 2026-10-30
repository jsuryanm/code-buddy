import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from qdrant_client import QdrantClient

from codebuddy.config import Settings
from tests.helpers import HashSparse


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        model_fast="fast",
        model_standard="standard",
        model_heavy="heavy",
        qdrant_path=str(tmp_path / "index"),
        relevance_threshold=0.0,
    )


@pytest.fixture
def embeddings() -> DeterministicFakeEmbedding:
    return DeterministicFakeEmbedding(size=32)


@pytest.fixture
def sparse() -> HashSparse:
    return HashSparse()


@pytest.fixture
def qdrant() -> QdrantClient:
    return QdrantClient(":memory:")
