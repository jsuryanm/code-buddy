import pytest

from codebuddy.tools.functions import analyze_python, suggest_cases, trace_python
from codebuddy.tools.policy import decide_permission
from codebuddy.tools.runner import LocalToolRunner, MCPToolRunner, _decode

BUGGY = "nums = [1, 2, 3]\nfor i in range(len(nums) + 1):\n    print(nums[i])\n"


async def test_analyze_python_reports_patterns():
    out = await analyze_python(BUGGY)
    assert [p["id"] for p in out["patterns"]] == ["off_by_one_range"]


async def test_suggest_cases_for_functions():
    out = await suggest_cases("def total(nums, n):\n    return 0\n")
    case = out["cases"][0]
    assert case["function"] == "total" and "nums = []" in case["try_these"]
    assert (await suggest_cases("def (:"))["syntax_error"]


async def test_trace_python_runs_in_sandbox():
    out = await trace_python(BUGGY)
    assert out["error"]["type"] == "IndexError" and out["error"]["line"] == 3


@pytest.mark.parametrize(
    "tool,permission,expected",
    [
        ("analyze_python", "ask", "run"),
        ("suggest_cases", "deny", "run"),
        ("trace_python", "ask", "ask"),
        ("trace_python", "allow", "run"),
        ("trace_python", "deny", "skip"),
    ],
)
def test_permission_rules(tool, permission, expected):
    assert decide_permission(tool, permission) == expected


def test_decode_handles_strings_and_content_blocks():
    assert _decode('{"a": 1}') == {"a": 1}
    assert _decode([{"type": "text", "text": '{"a": 2}'}]) == {"a": 2}
    assert _decode({"a": 3}) == {"a": 3}


async def test_local_runner_dispatches():
    out = await LocalToolRunner().call("analyze_python", code=BUGGY)
    assert out["loops"] == 1


async def test_mcp_runner_talks_to_a_real_stdio_server():
    runner = MCPToolRunner()
    await runner.start()
    try:
        analysis = await runner.call("analyze_python", code=BUGGY)
        traced = await runner.call("trace_python", code=BUGGY)
    finally:
        await runner.close()
    assert analysis["patterns"][0]["id"] == "off_by_one_range"
    assert traced["error"]["type"] == "IndexError"
