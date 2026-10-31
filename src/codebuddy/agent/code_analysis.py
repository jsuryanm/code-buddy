"""Static analysis of the learner's Python code: finds known novice bug patterns.

Never executes the code. Patterns feed the tutor privately; the pedagogy policy decides
how much of a finding the learner may see (spec 9.5).
"""

from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass, field

_BUILTINS_OFTEN_SHADOWED = {"list", "dict", "sum", "max", "min", "len", "str", "int", "set", "id"}
# Names safe to put in a search query: built-in functions and methods of the built-in
# containers. Anything else the code calls is the learner's own identifier and stays out.
_KNOWN_CALLS = frozenset(
    name
    for scope in (builtins, list, dict, str, set)
    for name in dir(scope)
    if name.islower() and not name.startswith("_") and callable(getattr(scope, name))
) - {"print"}  # in nearly every snippet, so it tells the search nothing
MAX_CALLS = 6


@dataclass(frozen=True)
class BugPattern:
    id: str
    concept: str
    symptom: str
    questions: tuple[str, ...]
    search_terms: tuple[str, ...] = ()  # plain words the course material uses for it


PATTERNS: dict[str, BugPattern] = {
    p.id: p
    for p in (
        BugPattern(
            "off_by_one_range",
            "loop bounds",
            "range() goes one past the last valid index",
            (
                "What is the value of `i` on the very last pass of the loop?",
                "How many items does the list have, and what is the largest valid index?",
            ),
            ("range", "len", "index", "off-by-one"),
        ),
        BugPattern(
            "uninitialized_accumulator",
            "variable initialization",
            "an accumulator is updated before it is given a starting value",
            (
                "What value does the variable hold the first time the loop updates it?",
                "Where in your code does that variable first get a value?",
            ),
            ("accumulator", "starting value", "total"),
        ),
        BugPattern(
            "mutating_while_iterating",
            "iteration and mutation",
            "the list is changed while the loop walks over it",
            (
                "What happens to the positions of the remaining items when one is removed?",
                "Trace the loop by hand on [1, 2, 3]. Which items does it visit?",
            ),
            ("loop", "list", "remove", "items"),
        ),
        BugPattern(
            "missing_base_case",
            "recursion",
            "a recursive function has no condition that stops the recursion",
            (
                "What input makes this function stop calling itself?",
                "Trace the function with the smallest input you can think of. What happens?",
            ),
            ("recursive function", "base case", "calls itself"),
        ),
        BugPattern(
            "shadowed_builtin",
            "names and scope",
            "a variable reuses the name of a built-in function",
            (
                "What does the name you chose mean in Python before your assignment?",
                "What happens when you try to call it after assigning to it?",
            ),
            ("built-in function", "variable name"),
        ),
    )
}


@dataclass
class CodeFeatures:
    parse_error: str | None = None
    patterns: list[str] = field(default_factory=list)
    loops: int = 0
    functions: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)  # built-ins and container methods called


def analyze(code: str | None) -> CodeFeatures:
    if not code or not code.strip():
        return CodeFeatures()
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return CodeFeatures(parse_error=f"{exc.msg} (line {exc.lineno})")

    feats = CodeFeatures()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            _note_call(node, feats.calls)
        if isinstance(node, ast.For | ast.While):
            feats.loops += 1
        if isinstance(node, ast.FunctionDef):
            feats.functions.append(node.name)
            if _is_recursive_without_guard(node):
                found.add("missing_base_case")
        if isinstance(node, ast.For):
            if _range_len_plus(node):
                found.add("off_by_one_range")
            if _mutates_iterable(node):
                found.add("mutating_while_iterating")
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in _BUILTINS_OFTEN_SHADOWED:
                    found.add("shadowed_builtin")
    if _uninitialized_accumulator(tree):
        found.add("uninitialized_accumulator")
    feats.patterns = sorted(found)
    return feats


def _note_call(node: ast.Call, calls: list[str]) -> None:
    func = node.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
    if name in _KNOWN_CALLS and name not in calls and len(calls) < MAX_CALLS:
        calls.append(name)


def _range_len_plus(node: ast.For) -> bool:
    it = node.iter
    if not (isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.func.id == "range"):
        return False
    for arg in it.args:
        if (
            isinstance(arg, ast.BinOp)
            and isinstance(arg.op, ast.Add)
            and isinstance(arg.left, ast.Call)
            and isinstance(arg.left.func, ast.Name)
            and arg.left.func.id == "len"
        ):
            return True
    return False


def _mutates_iterable(node: ast.For) -> bool:
    if not isinstance(node.iter, ast.Name):
        return False
    name = node.iter.id
    for sub in ast.walk(node):
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr in {"remove", "append", "pop", "insert"}
            and isinstance(sub.func.value, ast.Name)
            and sub.func.value.id == name
        ):
            return True
    return False


def _is_recursive_without_guard(fn: ast.FunctionDef) -> bool:
    calls_self = any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == fn.name
        for n in ast.walk(fn)
    )
    has_guard = any(isinstance(n, ast.If) for n in ast.walk(fn))
    return calls_self and not has_guard


def _uninitialized_accumulator(tree: ast.AST) -> bool:
    """Flag `x += ...` when x was never assigned before in the same scope body."""
    scopes = [tree] + [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    for scope in scopes:
        assigned: set[str] = set()
        if isinstance(scope, ast.FunctionDef):
            assigned |= {a.arg for a in scope.args.args}
        if _scan_body(getattr(scope, "body", []), assigned):
            return True
    return False


def _scan_body(body: list[ast.stmt], assigned: set[str]) -> bool:
    for stmt in body:
        if isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        assigned.add(n.id)
        elif isinstance(stmt, ast.AugAssign) and isinstance(stmt.target, ast.Name):
            if stmt.target.id not in assigned:
                return True
        elif isinstance(stmt, ast.For | ast.While | ast.If | ast.With | ast.Try):
            if isinstance(stmt, ast.For):
                for n in ast.walk(stmt.target):
                    if isinstance(n, ast.Name):
                        assigned.add(n.id)
            inner = list(getattr(stmt, "body", [])) + list(getattr(stmt, "orelse", []))
            if _scan_body(inner, assigned):
                return True
        elif isinstance(stmt, ast.FunctionDef):
            continue  # separate scope, handled by caller
    return False
