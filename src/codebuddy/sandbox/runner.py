"""Run learner Python in a locked-down subprocess and report what happened.

Layers: AST allowlist (check.py), restricted builtins and import allowlist, resource limits
(CPU, memory, file size), a wall-clock timeout, an empty environment, a throwaway working
directory, and `unshare -rn` (no network) when the host allows it.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
from functools import lru_cache

from codebuddy.sandbox.check import check_code
from codebuddy.sandbox.harness import HARNESS


@lru_cache(maxsize=1)
def _unshare_prefix() -> tuple[str, ...]:
    """`unshare -rn` drops network access. Probe once; fall back to no prefix."""
    import subprocess

    exe = shutil.which("unshare")
    if exe is None:
        return ()
    probe = subprocess.run([exe, "-rn", "true"], capture_output=True, check=False)
    return (exe, "-rn") if probe.returncode == 0 else ()


def network_isolated() -> bool:
    return bool(_unshare_prefix())


async def run_python(
    code: str, *, timeout_s: float = 3.0, cpu_s: int = 2, memory_mb: int = 256
) -> dict:
    """Never raises for learner mistakes. Returns ok, error, stdout, trace, and violations."""
    violations = check_code(code)
    if violations:
        return {"ran": False, "violations": violations}

    payload = json.dumps({"code": code, "memory_mb": memory_mb, "cpu_s": cpu_s})
    with tempfile.TemporaryDirectory(prefix="cb-sandbox-") as cwd:
        proc = await asyncio.create_subprocess_exec(
            *_unshare_prefix(),
            sys.executable,
            "-I",
            "-S",
            "-c",
            HARNESS,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={},
            cwd=cwd,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(payload.encode()), timeout=timeout_s)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return {"ran": True, "ok": False, "timed_out": True, "violations": [],
                    "error": {"type": "Timeout", "message": "ran too long (infinite loop?)",
                              "line": None}, "stdout": "", "trace": []}  # fmt: skip
    try:
        result = json.loads(out.decode())
    except ValueError:
        reason = err.decode(errors="replace")[-200:] or f"exit code {proc.returncode}"
        return {"ran": True, "ok": False, "timed_out": False, "violations": [],
                "error": {"type": "SandboxError", "message": reason, "line": None},
                "stdout": "", "trace": []}  # fmt: skip
    return {"ran": True, "timed_out": False, "violations": [], **result}
