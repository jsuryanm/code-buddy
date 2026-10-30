import logging

from codebuddy.api import wiring
from codebuddy.config import Settings
from codebuddy.memory.mem0_store import Mem0LearnerMemory


def settings(enabled: bool) -> Settings:
    return Settings(_env_file=None, memory_enabled=enabled)


async def test_disabled_builds_nothing():
    assert await wiring.build_memory(settings(False)) is None


async def test_enabled_returns_warmed_mem0_memory(monkeypatch):
    warmed = []

    async def warm(self):
        warmed.append(self)

    monkeypatch.setattr(Mem0LearnerMemory, "warm", warm)
    memory = await wiring.build_memory(settings(True))
    assert isinstance(memory, Mem0LearnerMemory) and warmed == [memory]


async def test_warm_failure_logs_and_continues_without_memory(monkeypatch, caplog):
    async def warm(self):
        raise RuntimeError("qdrant locked")

    monkeypatch.setattr(Mem0LearnerMemory, "warm", warm)
    with caplog.at_level(logging.ERROR, logger="codebuddy.api"):
        assert await wiring.build_memory(settings(True)) is None
    assert "Learner memory failed to start" in caplog.text and "qdrant locked" in caplog.text
