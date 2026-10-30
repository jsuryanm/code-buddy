"""Tool risk classes and the approval rule (spec 12.3, 12.4)."""

from __future__ import annotations

from enum import StrEnum


class Risk(StrEnum):
    READ = "read"  # static, no side effects: always allowed
    EXECUTE = "execute"  # runs learner code: needs the learner's permission
    WRITE_SHARED = "write_shared"  # changes shared data: needs an administrator (not exposed yet)


TOOL_RISK: dict[str, Risk] = {
    "analyze_python": Risk.READ,
    "suggest_cases": Risk.READ,
    "trace_python": Risk.EXECUTE,
}


def decide_permission(tool: str, permission: str) -> str:
    """Return 'run', 'ask', or 'skip' for a tool given the learner's stored permission.

    permission is the learner's choice for running their code: 'ask' (default), 'allow', 'deny'.
    """
    risk = TOOL_RISK[tool]
    if risk is Risk.READ:
        return "run"
    if risk is Risk.EXECUTE:
        return {"allow": "run", "deny": "skip"}.get(permission, "ask")
    return "skip"  # WRITE_SHARED never auto-runs
