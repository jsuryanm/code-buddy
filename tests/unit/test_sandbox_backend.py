import pytest

from codebuddy.config import Settings
from codebuddy.sandbox import backend as backend_mod
from codebuddy.sandbox.backend import LocalSandbox, get_backend
from codebuddy.tools import functions

CONTRACT_KEYS = {"ran", "ok", "error", "stdout", "truncated", "timed_out", "trace", "violations"}


async def test_local_sandbox_runs_and_returns_contract_keys():
    out = await LocalSandbox().run("print(1)", timeout_s=3.0, memory_mb=256)
    assert CONTRACT_KEYS <= out.keys()
    assert out["ran"] and out["ok"] and out["stdout"].strip() == "1"


def test_get_backend_default_and_unknown():
    assert get_backend("local").name == "local"
    with pytest.raises(ValueError) as exc:
        get_backend("nope")
    assert str(exc.value) == (
        "Unknown sandbox backend 'nope'. Available: local. "
        "See docs/tools-and-approvals.md (Stronger isolation)."
    )


class FakeBackend:
    name = "fake"

    def __init__(self):
        self.calls = []

    async def run(self, code, *, timeout_s, memory_mb):
        self.calls.append((code, timeout_s, memory_mb))
        return {"ran": True, "ok": True}


@pytest.fixture
def fake(monkeypatch):
    backend = FakeBackend()
    monkeypatch.setitem(backend_mod.BACKENDS, "fake", lambda: backend)
    settings = Settings(sandbox_backend="fake", sandbox_timeout_s=1.5, sandbox_memory_mb=64)
    monkeypatch.setattr(functions, "get_settings", lambda: settings)
    return backend


async def test_trace_python_uses_configured_backend(fake):
    out = await functions.trace_python("print(1)")
    assert out == {"ran": True, "ok": True}
    assert fake.calls == [("print(1)", 1.5, 64)]


async def test_trace_python_checks_allowlist_before_backend(fake):
    out = await functions.trace_python("import os")
    assert out["ran"] is False and out["violations"]
    assert fake.calls == []
