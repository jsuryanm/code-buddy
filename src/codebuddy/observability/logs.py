"""Logging setup with loguru (docs/observability.md).

One set of files per process start, in a folder per day (local time):

    logs/YYYY-MM-DD/<app>_HH-MM-SS.log          flow log
    logs/YYYY-MM-DD/<app>_HH-MM-SS.errors.log   WARNING and up, tracebacks without variables
    logs/YYYY-MM-DD/<app>_HH-MM-SS.jsonl        optional (CODEBUDDY_LOG_JSON=true)

plus stderr. File sinks write from a background thread (enqueue=True), so logging never waits
on the disk during a turn. Files older than CODEBUDDY_LOG_RETENTION_DAYS are deleted at start.

The existing stdlib loggers (codebuddy.*) and uvicorn's are forwarded into loguru by an
InterceptHandler. Third-party libraries stay at WARNING, so their INFO lines (which can hold
request details) do not reach the files. Each entrypoint calls setup_logging first; create_app
with injected deps (tests) does not, so tests do not write logs/.
"""

from __future__ import annotations

import inspect
import logging
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger

from codebuddy.config import Settings

APPS = ("api", "demo", "ui", "ingest", "eval", "ragas", "mcp")
LINE = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <7} | {extra[mod]: <14} | "
    "turn={extra[turn]} sess={extra[sess]} | {message}\n"
)
SAFETY_ROTATION = "50 MB"  # only for a runaway process; normally one file per run
PRUNED_SUFFIXES = (".log", ".jsonl", ".zip")
UVICORN = ("uvicorn", "uvicorn.error", "uvicorn.access")
_SESSION_PATH = re.compile(r"/v1/session/[^\s?\"]+")
_pruned: list[int] = []  # [files removed, retention days] from the last setup_logging


def flow_format(record) -> str:
    """One line per record; tracebacks go to the errors file and stderr only."""
    return LINE


def traceback_format(record) -> str:
    return LINE + "{exception}"


def redact_path(text: str) -> str:
    """Access log lines carry the request path; /v1/session/{id} would expose a session id."""
    return _SESSION_PATH.sub("/v1/session/<id>", text)


def _patch(record) -> None:
    extra = record["extra"]
    extra.setdefault("turn", "-")
    extra.setdefault("sess", "-")
    extra["mod"] = (record["name"] or "-").removeprefix("codebuddy.")


class InterceptHandler(logging.Handler):
    """Forwards stdlib log records to loguru (the recipe from the loguru README)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = inspect.currentframe(), 0
        while frame is not None:
            name = frame.f_code.co_filename
            frozen = "importlib" in name and "_bootstrap" in name
            if depth > 0 and not (name == logging.__file__ or frozen):
                break
            frame = frame.f_back
            depth += 1
        message = record.getMessage()
        if record.name == "uvicorn.access":
            message = redact_path(message)
        logger.opt(depth=depth, exception=record.exc_info).log(level, message)


def prune_logs(log_dir: str | Path, days: int, now: float | None = None) -> int:
    """Delete log files under `log_dir` older than `days` (by mtime), then date folders left
    empty. Only *.log, *.jsonl and *.zip; symlinks are never followed or deleted. Returns the
    number of files removed."""
    root = Path(log_dir)
    if not root.is_dir() or root.is_symlink():
        return 0
    cutoff = (time.time() if now is None else now) - days * 86400
    removed = 0
    for folder, _dirs, files in os.walk(root, topdown=False, followlinks=False):
        here = Path(folder)
        for name in files:
            path = here / name
            try:
                if path.is_symlink() or not name.endswith(PRUNED_SUFFIXES):
                    continue
                if path.lstat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                continue
        if here != root and not here.is_symlink():
            try:
                here.rmdir()  # only succeeds when empty
            except OSError:
                pass
    return removed


def setup_logging(settings: Settings, app: str = "api") -> Path | None:
    """Install the sinks and the stdlib bridge; return the flow log path (None: stderr only).
    Safe to call more than once. A log folder that cannot be created never stops the app."""
    level = settings.log_level.upper()
    logger.remove()  # loguru's default sink and any from an earlier call
    logger.configure(patcher=_patch)
    safe = {"backtrace": False, "diagnose": False, "enqueue": True}  # never print variables
    logger.add(sys.stderr, level=level, format=traceback_format, **safe)

    flow: Path | None = None
    removed = 0
    if settings.log_to_file:
        started = datetime.now()  # local time
        folder = Path(settings.log_dir) / started.strftime("%Y-%m-%d")
        stem = f"{app}_{started.strftime('%H-%M-%S')}"
        try:
            removed = prune_logs(settings.log_dir, settings.log_retention_days)
            folder.mkdir(parents=True, exist_ok=True)
            files = {"rotation": SAFETY_ROTATION, "encoding": "utf-8", **safe}
            flow = folder / f"{stem}.log"
            logger.add(flow, level=level, format=flow_format, **files)
            logger.add(
                folder / f"{stem}.errors.log", level="WARNING", format=traceback_format, **files
            )
            if settings.log_json:
                logger.add(folder / f"{stem}.jsonl", level=level, serialize=True, **files)
        except OSError as exc:
            flow = None
            logger.warning(
                "cannot write logs to {} ({}): logging to stderr only. Hint: check the folder "
                "permissions or set CODEBUDDY_LOG_DIR",
                settings.log_dir,
                type(exc).__name__,
            )

    root = logging.getLogger()
    if not any(isinstance(h, InterceptHandler) for h in root.handlers):
        root.addHandler(InterceptHandler())
    logging.getLogger("codebuddy").setLevel(logger.level(level).no)
    for name in UVICORN:
        uv = logging.getLogger(name)
        uv.handlers, uv.propagate = [InterceptHandler()], False
    _pruned[:] = [removed, settings.log_retention_days] if flow is not None else []
    return flow


# -- plain-language start, config and failure lines shared by every entrypoint ---------------


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=1,
            cwd=Path(__file__).parent,
        )
        return out.stdout.strip() or "-"
    except (OSError, subprocess.SubprocessError):
        return "-"


def _version() -> str:
    try:
        return version("codebuddy")
    except PackageNotFoundError:
        return "-"


def log_start(app: str, what: str, flow: Path | None) -> None:
    logger.info(
        "starting {} (app={} version={} git={} python={}) log={}",
        what,
        app,
        _version(),
        _git_sha(),
        platform.python_version(),
        flow or "stderr only",
    )
    if _pruned:
        logger.info("old logs removed: {} file(s) older than {} days", *_pruned)


def describe_config(settings: Settings, **extra: object) -> str:
    """A config summary without secrets: model ids, versions, store mode (host only), switches."""
    s = settings
    if s.qdrant_url:
        qdrant = f"server host={urlparse(s.qdrant_url).hostname or '?'}"
    else:
        qdrant = f"embedded path={s.qdrant_path}"
    parts = {
        "models": f"fast={s.model_fast} standard={s.model_standard} heavy={s.model_heavy}",
        "qdrant": qdrant,
        "index": s.index_version,
        "prompt": s.prompt_version,
        "memory": "on" if s.memory_enabled else "off",
        "tools": ("mcp" if s.mcp_enabled else "inprocess") if s.tools_enabled else "off",
        **extra,
    }
    return " ".join(f"{k}={v}" for k, v in parts.items())


def failure_hint(exc: BaseException) -> str:
    """A plain hint for the startup failures people actually hit."""
    text = str(exc)
    if "api_key" in text.lower() or "OPENAI_API_KEY" in text:
        return "OPENAI_API_KEY is not set: add it to .env"
    if "Set model IDs" in text:
        return "set CODEBUDDY_MODEL_FAST, _STANDARD and _HEAVY in .env"
    if "already accessed by another instance" in text:
        return "the Qdrant folder is locked: stop the API (or the other process) first"
    if "UPSTASH" in text:
        return "check UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN in .env"
    return "see the .errors.log file next to this log for the traceback"


def log_failure(what: str, exc: BaseException, started: float | None = None) -> None:
    elapsed = "" if started is None else f" after {time.perf_counter() - started:.1f} s"
    logger.opt(exception=exc).error(
        "{} failed{}: {}. Hint: {}", what, elapsed, type(exc).__name__, failure_hint(exc)
    )
