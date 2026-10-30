import pytest

from codebuddy.pedagogy.guard import LeakDetected, StreamGuard


def stream(guard: StreamGuard, text: str, size: int = 3) -> str:
    out = ""
    for i in range(0, len(text), size):
        out += guard.feed(text[i : i + size])
    return out + guard.flush()


def test_prose_passes_unchanged():
    text = "What value does `total` hold after the second pass?\nTrace it by hand."
    assert stream(StreamGuard(), text) == text


def test_prose_is_released_before_the_line_ends():
    g = StreamGuard()
    assert g.feed("What") == ""  # first word not finished yet
    assert g.feed(" is the value of i") == "What is the value of i"


def test_inline_code_is_allowed():
    text = "Check the condition in `range(len(nums) + 1)` again."
    assert stream(StreamGuard(), text) == text


@pytest.mark.parametrize(
    "text",
    [
        "Try this:\n```python\nfor i in range(len(nums)):\n    total += nums[i]\n```\n",
        "Fix it:\nfor i in range(len(nums)):\n",
        "Use this:\ntotal = 0\n",
        "Then:\ntotal += nums[i]\n",
        "Finally:\nreturn total\n",
        "Add:\nimport math\n",
    ],
)
def test_code_is_blocked(text):
    with pytest.raises(LeakDetected):
        stream(StreamGuard(), text)


def test_text_before_a_violation_was_already_safe():
    g = StreamGuard()
    shown = g.feed("Look at your loop.\n")
    assert shown == "Look at your loop.\n"
    with pytest.raises(LeakDetected):
        g.feed("total = 0\n")


def test_comparison_is_not_an_assignment():
    text = "Is nums == [] ever true here?\n"
    assert stream(StreamGuard(), text) == text


def test_lowercase_prose_starting_with_keyword_is_fine():
    text = "for example, imagine the list has one item.\n"
    assert stream(StreamGuard(), text) == text


def test_pseudocode_fence_allowed_at_scaffold_level():
    text = "Plan:\n```text\nstart total at zero\nadd each item\n```\n"
    assert stream(StreamGuard(allow_pseudocode=True), text) == text


def test_python_fence_blocked_even_at_scaffold_level():
    with pytest.raises(LeakDetected):
        stream(StreamGuard(allow_pseudocode=True), "```python\nx = 1\n```\n")


def test_guard_off_passes_code():
    text = "```python\nfor i in range(3):\n    print(i)\n```\n"
    assert stream(StreamGuard(enforce=False), text) == text
