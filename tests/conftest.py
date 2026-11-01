import os

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from loguru import logger
from qdrant_client import QdrantClient

from codebuddy.config import Settings
from tests.helpers import HashSparse

# Subprocesses started by tests (the MCP server) inherit this, so they never write logs/.
os.environ["CODEBUDDY_LOG_TO_FILE"] = "false"


@pytest.fixture(autouse=True)
def quiet_loguru():
    """No loguru sinks in tests: quiet output and no logs/ folder. caplog tests use stdlib."""
    logger.remove()
    yield
    logger.remove()


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
