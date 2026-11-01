import logging
import re

import httpx
import pytest
from loguru import logger
from pydantic import SecretStr

from codebuddy.api import app as app_module
from codebuddy.api import wiring
from codebuddy.api.app import create_app
from codebuddy.memory.store import InMemoryLearnerMemory
from codebuddy.observability.logs import setup_logging
from codebuddy.observability.summaries import hash_session
from tests.helpers import ScriptedChat

NODES = ("load_state", "analyze_code", "check_cache", "classify", "retrieve", "policy")
MSG = "SENTINELMSG why does my loop crash"
CODE_MARK = "SENTINELCODE"
REPLY = "SENTINELREPLY"
SESSION = "SENTINELSESSION-raw-id"
BUGGY = (
    f"{CODE_MARK} = [1, 2, 3]\nfor i in range(len({CODE_MARK}) + 1):\n    print({CODE_MARK}[i])\n"
)


@pytest.fixture
def stdlib_logging():
    names = ["", "codebuddy", "uvicorn", "uvicorn.error", "uvicorn.access"]
    saved = {n: (list(logging.getLogger(n).handlers), logging.getLogger(n).level) for n in names}
    propagate = {n: logging.getLogger(n).propagate for n in names}
    yield
    for n, (handlers, level) in saved.items():
        lg = logging.getLogger(n)
        lg.handlers, lg.level, lg.propagate = handlers, level, propagate[n]


@pytest.fixture
def captured(tmp_path, settings, stdlib_logging):
    """All sinks on (DEBUG, JSON), plus an in-memory sink that keeps every record field."""
    lines: list[str] = []
    log_dir = tmp_path / "logs"
    setup_logging(
        settings.model_copy(
            update={
                "log_dir": str(log_dir),
                "log_to_file": True,
                "log_json": True,
                "log_level": "DEBUG",
            }
        )
    )
    logger.add(  # the same safety options as the real sinks: no variable values in tracebacks
        lines.append,
        level="DEBUG",
        format="{message} | {extra} | {exception}",
        backtrace=False,
        diagnose=False,
    )

    def everything() -> str:
        logger.complete()
        files = "".join(p.read_text() for p in log_dir.rglob("*") if p.is_file())
        assert files  # the dated files were written
        return "".join(lines) + files

    return lines, everything


async def test_every_node_logs_enter_and_exit_with_a_duration(make_harness, captured):
    lines, _ = captured
    h = make_harness(standard=ScriptedChat(["Q?"]))
    out = await h.turn("why does my loop crash", code=BUGGY, session="s9")
    turn = out["thread_id"][:8]
    for node in NODES + ("generate", "update_state"):
        assert any(line.startswith(f"-> {node}") for line in lines), node
        exits = [line for line in lines if line.startswith(f"<- {node} ")]
        assert exits, node
        ms = float(re.match(rf"<- {node} +([\d.]+) ms", exits[0]).group(1))
        assert ms >= 0
        assert f"'turn': '{turn}'" in exits[0] and f"'sess': '{hash_session('s9')}'" in exits[0]
    assert any(line.startswith("turn start route=turn") for line in lines)
    end = next(line for line in lines if line.startswith("turn end"))
    assert "mode=hint" in end and "ttft_ms=" in end and "total_ms=" in end


async def test_no_learner_text_code_reply_token_or_raw_session_reaches_any_sink(
    make_harness, captured
):
    _, everything = captured
    leaky = f"{REPLY} first\nfor {REPLY}_x in range(3):\n    pass\n"  # stopped by the guard
    h = make_harness(
        standard=ScriptedChat([f"{REPLY} what is i?", leaky]),
        heavy=ScriptedChat(fail=True),
        fast=ScriptedChat([f"{REPLY} answer"]),
        memory=InMemoryLearnerMemory(),
    )
    h.deps.settings = h.deps.settings.model_copy(
        update={"memory_secret": SecretStr("s" * 32), "memory_write_every": 1}
    )
    app = create_app(h.deps)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        token = (await client.post("/v1/memory/learners")).json()["learner_token"]
        learner_id = app.state.tokens.verify(token, None)
        body = {"session_id": SESSION, "message": MSG, "code": BUGGY, "learner_id": token}
        for _ in range(2):
            assert (await client.post("/v1/turn", json=body)).status_code == 200
        show = {"session_id": SESSION, "code": BUGGY, "learner_id": token}
        assert (await client.post("/v1/show-answer", json=show)).status_code == 200
        other = {"session_id": SESSION, "message": MSG}  # no token: refused with a 409
        assert (await client.post("/v1/turn", json=other)).status_code == 409
        await client.get(f"/v1/session/{SESSION}", headers={"X-Learner-Token": token})
    text = everything()
    assert "turn end" in text and "api done" in text and "<- generate" in text
    assert hash_session(SESSION) in text
    for secret in ("SENTINELMSG", CODE_MARK, REPLY, SESSION, token, learner_id):
        assert secret not in text, secret


async def test_production_lifespan_sets_up_logging_but_injected_deps_do_not(
    make_harness, monkeypatch
):
    calls = []
    monkeypatch.setattr(app_module, "setup_logging", lambda s, app: calls.append((s, app)))
    h = make_harness()
    injected = create_app(h.deps)
    async with injected.router.lifespan_context(injected):
        pass
    assert calls == []

    async def fake_build(settings):
        return wiring.Resources(h.deps, "fake", None, None, None, _Stack())

    monkeypatch.setattr(wiring, "build_resources", fake_build)
    monkeypatch.setattr(app_module, "get_settings", lambda: h.deps.settings)
    production = create_app()
    async with production.router.lifespan_context(production):
        pass
    assert calls == [(h.deps.settings, "api")]


class _Stack:
    async def aclose(self) -> None:
        return None
