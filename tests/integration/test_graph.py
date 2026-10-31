import logging

from codebuddy.agent.state import Classification
from codebuddy.schemas import Intent, PcditStage
from tests.helpers import ScriptedChat


class OffTopicClassifier:
    async def classify(self, message, code, progress):
        return Classification(intent=Intent.OFF_TOPIC, stage=PcditStage.P, search_query="")


BUGGY = "nums = [1, 2, 3]\ntotal = 0\nfor i in range(len(nums) + 1):\n    total += nums[i]\n"


async def test_first_debug_turn_asks_a_diagnostic_question(make_harness):
    model = ScriptedChat(["What is the value of i on the very last pass of the loop?"])
    h = make_harness(standard=model)
    out = await h.turn("my sum crashes", code=BUGGY)
    assert out["meta"]["mode"] == "hint" and out["meta"]["level"] == 0
    assert out["text"].startswith("What is the value of i")
    assert out["state"]["progress"].hints_given == 1
    system, human = model.calls[0]
    assert "Hint level 0" in system[1]
    assert "off_by_one_range" in human[1]  # private finding reaches the model, not the learner
    assert "off_by_one_range" not in out["text"]


async def test_ladder_advances_one_level_per_turn(make_harness):
    h = make_harness(
        standard=ScriptedChat(["Q one?", "Look at the loop header.", "Q three?", "Plan."])
    )
    levels = [(await h.turn("still wrong", code=BUGGY))["meta"]["level"] for _ in range(4)]
    assert levels == [0, 1, 2, 3]


async def test_leak_guard_replaces_code_with_a_safe_question(make_harness):
    h = make_harness(
        standard=ScriptedChat(["Look closely.\nfor i in range(len(nums)):\n    pass\n"])
    )
    out = await h.turn("fix it", code=BUGGY)
    assert "range(len(nums))" not in out["text"]
    assert out["text"].startswith("Look closely.")
    assert out["state"]["guarded"] is True


async def test_answer_is_offered_after_five_hints_but_hinting_continues(make_harness):
    h = make_harness(standard=ScriptedChat([f"Hint {i}?" for i in range(8)]))
    # Different code each turn so the repeated-submission signal stays out of the way.
    metas = [(await h.turn("still stuck", code=BUGGY + f"# try {i}\n"))["meta"] for i in range(7)]
    assert [m["offer_answer"] for m in metas] == [False] * 5 + [True, True]
    assert [m["level"] for m in metas] == [0, 1, 2, 3, 3, 3, 3]  # never reveals on its own
    # Show answer is enabled from the 5th tutor turn (after 4 hints).
    assert [m["can_show_answer"] for m in metas] == [False] * 4 + [True] * 3


async def test_repeated_identical_submissions_offer_the_answer(make_harness):
    h = make_harness(standard=ScriptedChat(["Q?"] * 4))
    metas = [(await h.turn("again", code=BUGGY))["meta"] for _ in range(3)]
    assert [m["offer_answer"] for m in metas] == [False, False, True]


async def test_frustration_phrase_offers_answer_early(make_harness):
    h = make_harness(standard=ScriptedChat(["Q?", "Q?"]))
    await h.turn("why", code=BUGGY)
    out = await h.turn("I give up, this is stupid", code=BUGGY)
    assert out["meta"]["offer_answer"]


async def test_show_answer_reveals_with_code_and_resets_the_ladder(make_harness):
    heavy = ScriptedChat(["Here you go:\n```python\nfor n in nums:\n    total += n\n```\nWhy?\n"])
    h = make_harness(standard=ScriptedChat(["First question?"]), heavy=heavy)
    await h.turn("sum is wrong", code=BUGGY)
    out = await h.turn("just show me the answer", code=BUGGY)
    assert out["meta"]["mode"] == "reveal"
    assert "```python" in out["text"] and "total += n" in out["text"]
    progress = out["state"]["progress"]
    assert progress.reveals == 1 and progress.hints_given == 0


async def test_explicit_request_on_first_turn_reveals(make_harness):
    h = make_harness(heavy=ScriptedChat(["Answer: use range(len(nums))."]))
    out = await h.turn("show me the solution", code=BUGGY)
    assert out["meta"]["mode"] == "reveal"


async def test_a_model_outage_on_every_tier_gives_a_normal_question(make_harness):
    h = make_harness(standard=ScriptedChat(fail=True), fast=ScriptedChat(fail=True))
    out = await h.turn("why does my loop crash", code=BUGGY)
    assert out["state"]["degraded"] is True
    assert "tutor model" not in out["text"] and out["text"].endswith("?")
    progress = out["state"]["progress"]
    assert progress.hints_given == 0 and progress.history == []  # the turn does not count


async def test_an_outage_falls_back_to_the_next_tier(make_harness):
    h = make_harness(standard=ScriptedChat(fail=True), fast=ScriptedChat(["What is i?"]))
    out = await h.turn("why does my loop crash", code=BUGGY)
    assert out["state"]["degraded"] is False and out["text"] == "What is i?"
    assert out["state"]["progress"].hints_given == 1
    assert (await h.deps.metrics.snapshot())["tier_fallbacks"] == 1


async def test_an_empty_reply_on_every_tier_is_degraded_without_a_dump(make_harness):
    h = make_harness(standard=ScriptedChat(["", ""]), fast=ScriptedChat([""]))
    out = await h.turn("why does my loop crash", code=BUGGY)
    assert out["state"]["degraded"] is True and "tutor model" not in out["text"]
    assert "A loop repeats" not in out["text"]  # no raw course-material chunk


async def test_heavy_empty_falls_back_to_standard_with_the_reveal_cap(make_harness):
    heavy = ScriptedChat(["", ""])
    standard = ScriptedChat(["Use range(len(nums)). Why does that stop in time?"])
    h = make_harness(heavy=heavy, standard=standard)
    out = await h.turn("show me the solution", code=BUGGY)
    assert out["meta"]["mode"] == "reveal" and out["state"]["degraded"] is False
    assert out["text"].startswith("Use range")
    cap = h.deps.settings.max_tokens_reveal
    assert [k["max_completion_tokens"] for k in heavy.kwargs] == [cap, min(cap * 4, 4000)]
    assert standard.kwargs == [{"max_completion_tokens": cap}]
    snap = await h.deps.metrics.snapshot()
    assert snap["empty_replies"] == 2 and snap["tier_fallbacks"] == 1
    assert out["state"]["progress"].reveals == 1


async def test_a_degraded_reveal_keeps_the_ladder_and_says_try_again(make_harness):
    empty = dict(heavy=ScriptedChat(["", ""]), fast=ScriptedChat([""]))
    h = make_harness(standard=ScriptedChat(["Q?", ""]), **empty)
    await h.turn("sum is wrong", code=BUGGY)
    out = await h.turn("just show me the answer", code=BUGGY)
    assert out["meta"]["mode"] == "reveal" and out["state"]["degraded"] is True
    assert out["text"] == (
        "I couldn't put the full answer together just now. Press Show answer again in a moment."
    )
    progress = out["state"]["progress"]
    assert progress.reveals == 0 and progress.hints_given == 1 and progress.last_patterns
    assert len(progress.history) == 2  # only the first, real turn


async def test_a_degraded_explain_quotes_two_sentences_of_the_notes(make_harness):
    h = make_harness(standard=ScriptedChat(["", ""]), fast=ScriptedChat([""]))
    out = await h.turn("what is a loop")
    assert out["meta"]["mode"] == "explain" and out["state"]["degraded"] is True
    assert out["text"].startswith("Here is the short version from the course notes: ")
    assert "```" not in out["text"] and "#" not in out["text"]
    assert not await h.deps.answers.get(out["state"]["cache_key"])  # never cached


async def test_the_leak_guard_applies_on_the_fallback_tier(make_harness):
    fast = ScriptedChat(["Look closely.\nfor i in range(len(nums)):\n    pass\n"])
    h = make_harness(standard=ScriptedChat(fail=True), fast=fast)
    out = await h.turn("fix it", code=BUGGY)
    assert "range(len(nums))" not in out["text"]
    assert out["state"]["guarded"] is True and out["state"]["degraded"] is False


async def test_failed_tiers_log_one_line_each_without_a_traceback(make_harness, caplog):
    h = make_harness(standard=ScriptedChat(["", ""]), fast=ScriptedChat(fail=True))
    with caplog.at_level(logging.WARNING, logger="codebuddy.agent"):
        await h.turn("why does my loop crash", code=BUGGY)
    lines = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(lines) == 2 and all(r.exc_info is None for r in lines)
    assert "tier=standard" in lines[0].getMessage() and "finish_reason" in lines[0].getMessage()
    assert "tier=fast" in lines[1].getMessage() and "RuntimeError" in lines[1].getMessage()
    assert all("loop crash" not in r.getMessage() for r in caplog.records)


async def test_concept_answers_are_cached_but_hints_are_not(make_harness):
    model = ScriptedChat(["A loop repeats code [1]."])
    h = make_harness(standard=model)
    first = await h.turn("what is a loop")
    assert first["meta"]["mode"] == "explain" and not first["state"].get("cache_hit")
    second = await h.turn("What is  a LOOP")
    assert second["state"]["cache_hit"] is True and second["text"] == first["text"]
    assert second["meta"]["cached"] is True
    assert len(model.calls) == 1

    hint_model = ScriptedChat(["Q?", "Q?"])
    h2 = make_harness(standard=hint_model)
    await h2.turn("why is this wrong", code=BUGGY)
    await h2.turn("why is this wrong", code=BUGGY)
    assert len(hint_model.calls) == 2


async def test_conversation_history_reaches_the_next_prompt(make_harness):
    model = ScriptedChat(["What is i at the end?", "Good, so what next?"])
    h = make_harness(standard=model)
    await h.turn("sum is wrong", code=BUGGY)
    await h.turn("I think i is 3", code=BUGGY)
    _, human = model.calls[1]
    assert "What is i at the end?" in human[1] and "I think i is 3" in human[1]


async def test_citations_come_from_retrieval(make_harness):
    h = make_harness(standard=ScriptedChat(["Trace the loop [1]. What is i last?"]))
    out = await h.turn("off-by-one error in my for loop", code=BUGGY)
    cites = out["state"]["citations"]
    assert cites and cites[0].source == "Sample Basics"


async def test_token_cap_follows_the_mode_not_the_tier(make_harness):
    standard = ScriptedChat(["Q?", "A loop repeats code [1]."])
    heavy = ScriptedChat(["Here you go."])
    fast = ScriptedChat(["Sorry, only programming."])
    h = make_harness(standard=standard, heavy=heavy, fast=fast)
    s = h.deps.settings
    await h.turn("my sum crashes", code=BUGGY)
    await h.turn("what is a loop")
    await h.turn("show me the answer", code=BUGGY)
    h.deps.classifier = OffTopicClassifier()
    await h.turn("what is the capital of France")
    assert standard.kwargs[0] == {"max_completion_tokens": s.max_tokens_hint}
    assert standard.kwargs[1] == {"max_completion_tokens": s.max_tokens_explain}
    assert heavy.kwargs[0] == {"max_completion_tokens": s.max_tokens_reveal}
    assert fast.kwargs[0] == {"max_completion_tokens": s.max_tokens_redirect}


async def test_an_empty_reply_is_retried_once_with_a_bigger_cap(make_harness):
    model = ScriptedChat(["", "What is i on the last pass?"])
    h = make_harness(standard=model)
    out = await h.turn("why does my loop crash", code=BUGGY)
    assert out["state"]["degraded"] is False
    assert out["text"].startswith("What is i")
    assert [k["max_completion_tokens"] for k in model.kwargs] == [250, 1000]
    assert (await h.deps.metrics.snapshot())["empty_replies"] == 1


async def test_two_empty_replies_fall_down_to_the_fast_tier(make_harness):
    model, fast = ScriptedChat(["", ""]), ScriptedChat(["What is i last?"])
    h = make_harness(standard=model, fast=fast)
    out = await h.turn("why does my loop crash", code=BUGGY)
    assert out["state"]["degraded"] is False and out["text"] == "What is i last?"
    assert fast.kwargs == [{"max_completion_tokens": h.deps.settings.max_tokens_hint}]
    assert (await h.deps.metrics.snapshot())["empty_replies"] == 2


async def test_the_leak_guard_still_applies_to_the_retry(make_harness):
    h = make_harness(
        standard=ScriptedChat(["", "Look closely.\nfor i in range(len(nums)):\n    pass\n"])
    )
    out = await h.turn("fix it", code=BUGGY)
    assert "range(len(nums))" not in out["text"]
    assert out["state"]["guarded"] is True
