import pytest

from codebuddy.config import Settings
from codebuddy.pedagogy.templates import (
    EARLY_HINT_RULE,
    ERROR_TEMPLATE,
    LEVEL_RULES,
    STYLE_RULE,
    system_prompt,
)
from codebuddy.schemas import Decision, HintLevel, Mode, PcditStage


@pytest.mark.parametrize("level", [HintLevel.DIAGNOSE, HintLevel.LOCATE])
def test_early_hints_say_where_and_why_then_push_toward_the_fix(level):
    prompt = system_prompt(Decision(mode=Mode.HINT, level=level), PcditStage.I)
    assert EARLY_HINT_RULE in prompt
    assert "where the problem is" in EARLY_HINT_RULE and "what causes it" in EARLY_HINT_RULE
    assert "ONE question that pushes the learner toward the fix" in EARLY_HINT_RULE
    assert "Never write the corrected code or the exact fix" in EARLY_HINT_RULE
    assert "never state the error type" not in prompt


def test_hint_levels_add_depth_step_by_step():
    rule = LEVEL_RULES.__getitem__
    assert "line or step" in rule(HintLevel.DIAGNOSE)
    assert "specific step or value" in rule(HintLevel.LOCATE)
    assert "what to change" in rule(HintLevel.LOCATE)
    assert "Name the concept" in rule(HintLevel.NAME_CONCEPT)
    assert "pseudo-code" in rule(HintLevel.SCAFFOLD)
    assert len({rule(level) for level in LIMITS}) == 4  # each level is its own step


def test_prompt_version_was_bumped_with_the_prompt_change():
    assert Settings().prompt_version == "p4"


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


def test_confirm_prompt_is_short_plain_and_writes_no_new_code():
    prompt = system_prompt(Decision(mode=Mode.CONFIRM), PcditStage.T)
    assert STYLE_RULE in prompt and "at most 60 words" in prompt
    assert "why the fix works" in prompt and "quiz" in prompt
    assert "do not write new or corrected code" in prompt
