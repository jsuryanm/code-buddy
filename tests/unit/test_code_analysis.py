import pytest

from codebuddy.agent.code_analysis import analyze

CASES = {
    "off_by_one_range": "nums = [1, 2]\nfor i in range(len(nums) + 1):\n    print(nums[i])\n",
    "uninitialized_accumulator": "for n in [1, 2]:\n    total += n\n",
    "mutating_while_iterating": "items = [1, 2, 3]\nfor x in items:\n    items.remove(x)\n",
    "missing_base_case": "def f(n):\n    return f(n - 1)\n",
    "shadowed_builtin": "list = [1, 2]\nprint(list)\n",
}


@pytest.mark.parametrize("pattern,code", CASES.items())
def test_detects_pattern(pattern, code):
    assert pattern in analyze(code).patterns


def test_clean_code_has_no_patterns():
    code = "total = 0\nfor n in [1, 2, 3]:\n    total += n\nprint(total)\n"
    assert analyze(code).patterns == []


def test_recursion_with_base_case_is_fine():
    code = "def f(n):\n    if n == 0:\n        return 0\n    return f(n - 1)\n"
    assert "missing_base_case" not in analyze(code).patterns


def test_accumulator_initialized_in_function_scope_is_fine():
    code = "def s(xs):\n    t = 0\n    for x in xs:\n        t += x\n    return t\n"
    assert "uninitialized_accumulator" not in analyze(code).patterns


def test_syntax_error_is_reported_not_raised():
    feats = analyze("for i in range(3)\n    print(i)\n")
    assert feats.parse_error and "line" in feats.parse_error


def test_empty_code():
    assert analyze(None).patterns == [] and analyze("  ").parse_error is None
