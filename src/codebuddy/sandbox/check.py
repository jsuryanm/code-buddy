"""Static allowlist for learner code before it is run (beginner fundamentals only).

This is defense in depth, not a security boundary. Production must also run the sandbox
inside a container or microVM with no network and no secrets (spec Section 18).
"""

from __future__ import annotations

import ast

MAX_CODE_CHARS = 4000
ALLOWED_IMPORTS = {"math", "random", "string"}
FORBIDDEN_NAMES = {
    "eval", "exec", "compile", "open", "input", "__import__", "globals", "locals", "vars",
    "dir", "getattr", "setattr", "delattr", "hasattr", "type", "object", "breakpoint", "help",
    "exit", "quit", "memoryview", "bytearray", "super", "classmethod", "staticmethod",
    "property", "__builtins__", "__build_class__", "__loader__", "__spec__",
}  # fmt: skip
FORBIDDEN_ATTRS = {"format", "format_map", "mro", "gi_frame", "cr_frame", "tb_frame"}
FORBIDDEN_NODES = (ast.ClassDef, ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith)


def check_code(code: str) -> list[str]:
    """Return a list of violations; empty means the code may run."""
    if len(code) > MAX_CODE_CHARS:
        return [f"code longer than {MAX_CODE_CHARS} characters"]
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"syntax error: {exc.msg} (line {exc.lineno})"]

    problems: list[str] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", "?")
        if isinstance(node, FORBIDDEN_NODES):
            problems.append(f"line {line}: {type(node).__name__} is not allowed")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_IMPORTS:
                    problems.append(f"line {line}: import {alias.name} is not allowed")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in ALLOWED_IMPORTS or node.level:
                problems.append(f"line {line}: import from {node.module} is not allowed")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            problems.append(f"line {line}: name '{node.id}' is not allowed")
        elif isinstance(node, ast.Attribute) and (
            node.attr.startswith("_") or node.attr in FORBIDDEN_ATTRS
        ):
            problems.append(f"line {line}: attribute '{node.attr}' is not allowed")
    return problems
