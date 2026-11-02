import hashlib
import logging
import os
import re

import pytest
from loguru import logger

from codebuddy.agent.state import Classification
from codebuddy.config import Settings
from codebuddy.observability.logs import (
    InterceptHandler,
    describe_config,
    failure_hint,
    prune_logs,
    redact_path,
    safe_message,
    setup_logging,
)
from codebuddy.observability.summaries import format_summary, hash_session, safe_summary
from codebuddy.rag.rerank import RetrievedChunk
from codebuddy.rag.retrieve import RetrievalResult
from codebuddy.schemas import Decision, HintLevel, Intent, Mode, PcditStage, SessionProgress


@pytest.fixture
def stdlib_logging():
    """setup_logging changes the stdlib root and uvicorn loggers; put them back afterwards."""
    names = ["", "codebuddy", "uvicorn", "uvicorn.error", "uvicorn.access"]
    saved = {n: (list(logging.getLogger(n).handlers), logging.getLogger(n).level) for n in names}
    propagate = {n: logging.getLogger(n).propagate for n in names}
    yield
    for n, (handlers, level) in saved.items():
        lg = logging.getLogger(n)
        lg.handlers, lg.level, lg.propagate = handlers, level, propagate[n]


def test_hash_session_is_the_first_8_hex_of_sha256():
    assert hash_session("abc") == hashlib.sha256(b"abc").hexdigest()[:8]
    assert hash_session(None) == "-" and hash_session("") == "-"


def _settings(tmp_path, **kw) -> Settings:
    return Settings(_env_file=None, log_dir=str(tmp_path / "logs"), log_to_file=True, **kw)


def test_setup_logging_writes_a_dated_file_per_run_and_is_idempotent(tmp_path, stdlib_logging):
    setup_logging(_settings(tmp_path), app="ingest")
    flow = setup_logging(_settings(tmp_path), app="ingest")
    logger.info("hello flow")
    logger.warning("hello warning")
    logger.complete()
    assert flow.parent.parent == tmp_path / "logs"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", flow.parent.name)
    assert re.fullmatch(r"ingest_\d{2}-\d{2}-\d{2}\.log", flow.name)
    errors = flow.with_name(flow.name.replace(".log", ".errors.log"))
    assert flow.read_text().count("hello flow") == 1  # no duplicate sinks after a second call
    assert "hello warning" in errors.read_text() and "hello flow" not in errors.read_text()
    assert not list(flow.parent.glob("*.jsonl"))
    intercepts = [h for h in logging.getLogger().handlers if isinstance(h, InterceptHandler)]
    assert len(intercepts) == 1


def test_json_lines_are_optional(tmp_path, stdlib_logging):
    flow = setup_logging(_settings(tmp_path, log_json=True), app="eval")
    logger.info("as json")
    logger.complete()
    assert '"as json"' in flow.with_suffix(".jsonl").read_text()


def test_no_files_when_file_logging_is_off(tmp_path, stdlib_logging):
    settings = _settings(tmp_path).model_copy(update={"log_to_file": False})
    assert setup_logging(settings) is None
    logger.info("stderr only")
    logger.complete()
    assert not (tmp_path / "logs").exists()


def test_an_unwritable_log_folder_falls_back_to_stderr(tmp_path, stdlib_logging, capsys):
    blocker = tmp_path / "logs"
    blocker.write_text("a file where the folder should be")
    assert setup_logging(_settings(tmp_path)) is None
    logger.complete()
    assert "logging to stderr only" in capsys.readouterr().err


def test_stdlib_codebuddy_lines_land_in_the_flow_file(tmp_path, stdlib_logging):
    flow = setup_logging(_settings(tmp_path))
    logging.getLogger("codebuddy.api").info("bridged line %d", 7)
    logging.getLogger("some.library").info("third-party info stays out")
    logger.complete()
    text = flow.read_text()
    assert "bridged line 7" in text and "third-party info" not in text


def _aged(path, days, now):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    os.utime(path, (now - days * 86400, now - days * 86400))
    return path


def test_prune_logs_deletes_old_files_and_empty_date_folders_only(tmp_path):
    now = 1_800_000_000.0
    logs, outside = tmp_path / "logs", tmp_path / "outside"
    keep = _aged(logs / "2027-01-04" / "api_10-00-00.log", 4, now)
    old = [
        _aged(logs / "2027-01-02" / "api_10-00-00.log", 6, now),
        _aged(logs / "2027-01-02" / "api_10-00-00.errors.log", 6, now),
        _aged(logs / "2027-01-02" / "api_10-00-00.jsonl", 6, now),
        _aged(logs / "2027-01-03" / "eval_09-00-00.log.zip", 6, now),
    ]
    other = _aged(logs / "2027-01-03" / "notes.txt", 30, now)  # not a log file: kept
    target = _aged(outside / "secret.log", 30, now)
    (logs / "link.log").symlink_to(target)
    (logs / "linkdir").symlink_to(outside, target_is_directory=True)
    assert prune_logs(logs, 5, now=now) == 4
    assert keep.exists() and other.exists() and target.exists()
    assert not any(p.exists() for p in old)
    assert not (logs / "2027-01-02").exists()  # emptied: removed
    assert (logs / "2027-01-03").exists()  # still holds notes.txt
    assert (logs / "link.log").is_symlink() and (logs / "linkdir").is_symlink()
    assert prune_logs(tmp_path / "missing", 5, now=now) == 0


def test_config_summary_has_no_secrets():
    settings = Settings(
        _env_file=None,
        model_fast="f",
        qdrant_url="https://user:pw@qdrant.example.com:6333/x?api_key=k",
        api_keys="topsecret",
    )
    text = describe_config(settings, cache="memory")
    assert "fast=f" in text and "server host=qdrant.example.com" in text and "cache=memory" in text
    assert "pw" not in text and "api_key" not in text and "topsecret" not in text


def test_failure_hints_are_plain():
    assert "OPENAI_API_KEY" in failure_hint(RuntimeError("The api_key client option must be set"))
    locked = RuntimeError("Storage folder data/index is already accessed by another instance")
    assert "stop the API" in failure_hint(locked)


def test_access_log_paths_hide_session_ids():
    line = '127.0.0.1:5 - "GET /v1/session/my-secret-session HTTP/1.1" 200'
    assert "my-secret-session" not in redact_path(line)
    assert "/v1/session/<id>" in redact_path(line)
    assert redact_path('"POST /v1/turn HTTP/1.1" 200') == '"POST /v1/turn HTTP/1.1" 200'


def test_summaries_keep_only_whitelisted_metadata():
    chunk = RetrievedChunk("SECRET chunk text", 0.9, {"title": "Think Python", "section": "3"})
    update = {
        "retrieval": RetrievalResult([chunk, chunk], grounded=True, cache_hit=False),
        "message": "SECRET message",
    }
    out = safe_summary("retrieve", update)
    assert out == {"chunks": 2, "grounded": True, "cache_hit": False, "sources": ["Think Python"]}
    cls = Classification(
        intent=Intent.DEBUG_HELP, stage=PcditStage.D, concepts=["SECRET"], search_query="SECRET"
    )
    assert safe_summary("classify", {"classification": cls}) == {
        "intent": "debug_help",
        "stage": "D",
        "concepts": 1,
    }
    decision = Decision(mode=Mode.HINT, level=HintLevel.DIAGNOSE, reasons=["hints given: 0"])
    out = safe_summary("policy", {"decision": decision, "tool_plan": ["trace_python"]})
    assert out["mode"] == "hint" and out["level"] == 0 and out["tools"] == ["trace_python"]
    out = safe_summary("generate", {"reply": "SECRET reply", "guarded": False, "degraded": True})
    assert out == {"reply_chars": 12, "guarded": False, "degraded": True}
    progress = SessionProgress(session_id="SECRET", hints_given=2)
    assert "SECRET" not in format_summary(safe_summary("update_state", {"progress": progress}))
    assert safe_summary("unknown_node", {"message": "SECRET"}) == {}
    assert safe_summary("refine_retrieval", {}) == {"refined": False}


async def test_tool_calls_log_name_route_and_duration_but_not_the_code():
    from codebuddy.tools.runner import LocalToolRunner

    lines: list[str] = []
    logger.add(lines.append, level="INFO", format="{message}")
    await LocalToolRunner().call("trace_python", code="SECRET_CODE = 1\nprint(SECRET_CODE)\n")
    line = next(x for x in lines if x.startswith("tool trace_python"))
    assert "via=inprocess" in line and "ok=True" in line and " ms " in line
    assert not any("SECRET_CODE" in x for x in lines)


def test_file_sinks_prune_rotated_files_after_the_retention_days(
    tmp_path, stdlib_logging, monkeypatch
):
    added = []
    real_add = logger.add
    monkeypatch.setattr(logger, "add", lambda sink, **kw: added.append(kw) or real_add(sink, **kw))
    setup_logging(_settings(tmp_path, log_retention_days=3))
    files = [kw for kw in added if "rotation" in kw]
    assert files and all(kw["retention"].days == 3 for kw in files)


def test_only_allowlisted_libraries_keep_their_message():
    def record(name, msg="hello %s", exc=None):
        return logging.LogRecord(name, logging.WARNING, __file__, 1, msg, ("x",), exc)

    assert safe_message(record("uvicorn.error")) == "hello x"
    assert safe_message(record("langfuse._client")) == "hello x"
    assert safe_message(record("codebuddy.agent")) == "hello x"
    assert safe_message(record("httpx")) == "ext:httpx WARNING (message withheld)"
    assert safe_message(record("asyncio")) == "ext:asyncio WARNING (message withheld)"
    assert safe_message(record("codebuddyx")).startswith("ext:codebuddyx")
    exc = (KeyError, KeyError("secret"), None)
    assert safe_message(record("openai._base_client", exc=exc)).endswith("exc=KeyError")
