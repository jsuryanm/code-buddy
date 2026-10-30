"""Where learner code runs. `trace_python` picks a backend by `CODEBUDDY_SANDBOX_BACKEND`.

The allowlist check (`check.check_code`) runs before any backend is called, so a backend only
ever receives code that already passed it. A backend must return a dict with these keys:

- `ran`: bool, whether the code was executed
- `ok`: bool, whether it finished without an error
- `error`: `{"type": str, "message": str, "line": int | None}`, or None
- `stdout`: str, captured output
- `truncated`: bool, whether output was cut at the cap
- `timed_out`: bool, whether the wall-clock limit was hit
- `trace`: list of `{"line": int, "vars": dict}`
- `violations`: list of str, reasons the code was refused

Only `local` is included. See docs/tools-and-approvals.md (Stronger isolation).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from codebuddy.sandbox.runner import run_python


class SandboxBackend(Protocol):
    name: str

    async def run(self, code: str, *, timeout_s: float, memory_mb: int) -> dict: ...


class LocalSandbox:
    """The in-host subprocess sandbox from runner.py."""

    name = "local"

    async def run(self, code: str, *, timeout_s: float, memory_mb: int) -> dict:
        return await run_python(code, timeout_s=timeout_s, memory_mb=memory_mb)


BACKENDS: dict[str, Callable[[], SandboxBackend]] = {"local": LocalSandbox}


def get_backend(name: str) -> SandboxBackend:
    try:
        factory = BACKENDS[name]
    except KeyError:
        raise ValueError(
            f"Unknown sandbox backend '{name}'. Available: {', '.join(BACKENDS)}. "
            "See docs/tools-and-approvals.md (Stronger isolation)."
        ) from None
    return factory()
