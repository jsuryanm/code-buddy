import pytest

from codebuddy.config import Settings
from codebuddy.pedagogy.templates import system_prompt
from codebuddy.schemas import Decision, HintLevel, Mode, PcditStage


@pytest.mark.parametrize("level", [HintLevel.DIAGNOSE, HintLevel.LOCATE])
def test_early_hints_never_state_the_error_its_cause_or_the_failing_input(level):
    prompt = system_prompt(Decision(mode=Mode.HINT, level=level), PcditStage.I)
    assert "never state the error type, its cause, or the failing input" in prompt
    assert "run or trace a specific small input" in prompt


def test_prompt_version_was_bumped_with_the_prompt_change():
    assert Settings().prompt_version != "p1"
