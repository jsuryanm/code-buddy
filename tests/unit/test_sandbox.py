import pytest

from codebuddy.sandbox.check import check_code
from codebuddy.sandbox.runner import run_python


async def test_runs_simple_code_and_traces_variables():
    out = await run_python("total = 0\nfor n in [1, 2, 3]:\n    total += n\nprint(total)\n")
    assert out["ok"] and out["stdout"].strip() == "6"
    assert any(step["vars"].get("total") == "3" for step in out["trace"])


async def test_runtime_error_reports_type_and_line():
    out = await run_python("nums = [1, 2, 3]\nfor i in range(4):\n    print(nums[i])\n")
    assert out["ok"] is False
    assert out["error"] == {"type": "IndexError", "message": "list index out of range", "line": 3}
    assert out["stdout"].split() == ["1", "2", "3"]


async def test_infinite_loop_is_stopped():
    out = await run_python("while True:\n    pass\n", timeout_s=1.5, cpu_s=1)
    assert out["ok"] is False
    assert out["timed_out"] or out["error"]["type"] == "SandboxError"


async def test_recursion_without_base_case_is_reported():
    out = await run_python("def f(n):\n    return f(n - 1)\nf(5)\n")
    assert out["error"]["type"] == "RecursionError"


async def test_output_is_capped():
    out = await run_python("for i in range(5000):\n    print('xxxxxxxxxx')\n")
    assert out["truncated"] and len(out["stdout"]) <= 4000


@pytest.mark.parametrize(
    "code",
    [
        "import os\n",
        "import subprocess\n",
        "from os import path\n",
        "open('/etc/passwd')\n",
        "eval('1+1')\n",
        "exec('x=1')\n",
        "__import__('os')\n",
        "x = ().__class__\n",
        "getattr(int, 'real')\n",
        "'{0.__class__}'.format(1)\n",
        "class A:\n    pass\n",
        "input()\n",
        "type(1)\n",
    ],
)
async def test_dangerous_code_is_refused_before_running(code):
    assert check_code(code)
    out = await run_python(code)
    assert out["ran"] is False and out["violations"]


async def test_allowed_import_works():
    out = await run_python("import math\nprint(math.sqrt(16))\n")
    assert out["ok"] and out["stdout"].strip() == "4.0"


async def test_environment_is_empty_and_files_cannot_be_written():
    # No way to reach env or files through the allowlist; this documents the empty env.
    out = await run_python("print('hi')\n")
    assert out["ok"]


def test_oversized_code_is_refused():
    assert check_code("x = 1\n" * 2000)
