import pytest

from codebuddy.config import Settings
from codebuddy.pedagogy.templates import ERROR_TEMPLATE, STYLE_RULE, system_prompt
from codebuddy.schemas import Decision, HintLevel, Mode, PcditStage


@pytest.mark.parametrize("level", [HintLevel.DIAGNOSE, HintLevel.LOCATE])
def test_early_hints_never_state_the_error_its_cause_or_the_failing_input(level):
    prompt = system_prompt(Decision(mode=Mode.HINT, level=level), PcditStage.I)
    assert "never state the error type, its cause, or the failing input" in prompt
    assert "run or trace a specific small input" in prompt


def test_prompt_version_was_bumped_with_the_prompt_change():
    assert Settings().prompt_version == "p3"


LIMITS = {
    HintLevel.DIAGNOSE: "at most 60 words",
    HintLevel.LOCATE: "at most 60 words",
    HintLevel.NAME_CONCEPT: "at most 90 words",
    HintLevel.SCAFFOLD: "at most 110 words",
}


@pytest.mark.parametrize("level", list(LIMITS))
def test_every_hint_level_has_the_style_rule_the_word_limit_and_one_question(level):
    prompt = system_prompt(Decision(mode=Mode.HINT, level=level), PcditStage.I)
    assert STYLE_RULE in prompt
    assert LIMITS[level] in prompt
    assert "exactly one question" in prompt


def test_explain_reveal_and_redirect_prompts_carry_style_and_limits():
    explain = system_prompt(Decision(mode=Mode.EXPLAIN), PcditStage.I)
    assert STYLE_RULE in explain and "at most 120 words" in explain
    reveal = system_prompt(Decision(mode=Mode.REVEAL), PcditStage.I)
    assert STYLE_RULE in reveal and "at most 120 words" in reveal
    assert "Show the complete corrected solution" in reveal
    redirect = system_prompt(Decision(mode=Mode.REDIRECT), PcditStage.I)
    assert STYLE_RULE in redirect and "two sentences" in redirect


def test_error_template_fits_the_name_concept_limit():
    assert "max 90 words" in ERROR_TEMPLATE


def test_token_caps_default_per_mode():
    s = Settings()
    assert (s.max_tokens_hint, s.max_tokens_explain) == (250, 320)
    assert (s.max_tokens_reveal, s.max_tokens_redirect) == (900, 90)
