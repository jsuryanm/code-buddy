"""The tools themselves: plain functions shared by the MCP server and the local runner."""

from __future__ import annotations

import ast

from codebuddy.agent.code_analysis import PATTERNS, analyze
from codebuddy.config import get_settings
from codebuddy.sandbox.runner import run_python

_LIST_NAMES = {"nums", "numbers", "items", "lst", "xs", "values", "data", "arr", "array", "lines"}
_INT_NAMES = {"n", "k", "x", "y", "num", "count", "limit", "size", "start", "stop"}
_STR_NAMES = {"s", "text", "word", "name", "sentence", "line", "string"}


async def analyze_python(code: str) -> dict:
    """Find common beginner bug patterns in Python code. Static only; nothing is executed."""
    feats = analyze(code)
    return {
        "syntax_error": feats.parse_error,
        "patterns": [
            {"id": p, "concept": PATTERNS[p].concept, "symptom": PATTERNS[p].symptom}
            for p in feats.patterns
        ],
        "loops": feats.loops,
        "functions": feats.functions,
    }


async def suggest_cases(code: str) -> dict:
    """Suggest small concrete inputs for each function, to help learners work examples by hand."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return {"cases": [], "syntax_error": f"{exc.msg} (line {exc.lineno})"}
    cases: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        params = [a.arg for a in node.args.args]
        ideas: list[str] = []
        for p in params:
            if p in _LIST_NAMES:
                ideas += [f"{p} = []", f"{p} = [5]", f"{p} = [1, 2, 3]", f"{p} = [-1, 0, 4]"]
            elif p in _INT_NAMES:
                ideas += [f"{p} = 0", f"{p} = 1", f"{p} = 5", f"{p} = -2"]
            elif p in _STR_NAMES:
                ideas += [f'{p} = ""', f'{p} = "a"', f'{p} = "abc"']
        if params and not ideas:
            ideas = [f"pick a tiny value for {p}" for p in params]
        cases.append({"function": node.name, "parameters": params, "try_these": ideas[:8]})
    return {"cases": cases}


async def trace_python(code: str) -> dict:
    """Run learner code in the sandbox. Returns output, any error with its line, and a trace
    of variable values for the first and last steps."""
    s = get_settings()
    return await run_python(code, timeout_s=s.sandbox_timeout_s, memory_mb=s.sandbox_memory_mb)


TOOLS = {
    "analyze_python": analyze_python,
    "suggest_cases": suggest_cases,
    "trace_python": trace_python,
}
