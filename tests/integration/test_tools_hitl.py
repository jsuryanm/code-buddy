from codebuddy.tools.runner import LocalToolRunner
from tests.helpers import ScriptedChat

BUGGY = "nums = [1, 2, 3]\ntotal = 0\nfor i in range(len(nums) + 1):\n    total += nums[i]\n"


def human_prompt(model: ScriptedChat) -> str:
    return model.calls[-1][1][1]


async def test_run_waits_for_the_learners_permission(make_harness):
    model = ScriptedChat(["What is i on the last pass?"])
    h = make_harness(standard=model, tools=LocalToolRunner())
    paused = await h.turn("my sum crashes", code=BUGGY)
    assert paused["interrupt"]["tool"] == "trace_python"
    assert paused["text"] == "" and not model.calls  # nothing generated, nothing run yet

    done = await h.resume(paused["thread_id"], approve=True)
    assert done["interrupt"] is None and done["text"].startswith("What is i")
    assert "IndexError" in human_prompt(model) and "line 4" in human_prompt(model)
    assert done["state"]["progress"].run_permission == "allow"


async def test_permission_is_remembered_for_the_session(make_harness):
    model = ScriptedChat(["Q one?", "Q two?"])
    h = make_harness(standard=model, tools=LocalToolRunner())
    first = await h.turn("it crashes", code=BUGGY)
    await h.resume(first["thread_id"], approve=True)
    second = await h.turn("still crashes", code=BUGGY + "# edit\n")
    assert second["interrupt"] is None and "IndexError" in human_prompt(model)


async def test_declining_skips_the_run_and_is_remembered(make_harness):
    model = ScriptedChat(["Q one?", "Q two?"])
    h = make_harness(standard=model, tools=LocalToolRunner())
    first = await h.turn("it crashes", code=BUGGY)
    declined = await h.resume(first["thread_id"], approve=False)
    assert declined["text"].startswith("Q one") and "IndexError" not in human_prompt(model)
    assert declined["state"]["progress"].run_permission == "deny"
    second = await h.turn("still crashes", code=BUGGY + "# edit\n")
    assert second["interrupt"] is None and "IndexError" not in human_prompt(model)


async def test_decline_without_remembering_asks_again(make_harness):
    h = make_harness(standard=ScriptedChat(["Q?", "Q?"]), tools=LocalToolRunner())
    first = await h.turn("it crashes", code=BUGGY)
    await h.resume(first["thread_id"], approve=False, remember=False)
    again = await h.turn("still crashes", code=BUGGY + "# edit\n")
    assert again["interrupt"] is not None


async def test_syntax_errors_and_reveals_never_run_code(make_harness):
    h = make_harness(
        standard=ScriptedChat(["Q?"]), heavy=ScriptedChat(["Answer."]), tools=LocalToolRunner()
    )
    broken = await h.turn("why", code="for i in range(3)\n    print(i)\n")
    assert broken["interrupt"] is None
    reveal = await h.turn("show me the answer", code=BUGGY)
    assert reveal["interrupt"] is None and reveal["meta"]["mode"] == "reveal"


async def test_problem_start_suggests_cases_without_asking(make_harness):
    from codebuddy.agent.state import Classification
    from codebuddy.schemas import Intent, PcditStage

    class StartClassifier:
        async def classify(self, message, code, progress):
            return Classification(
                intent=Intent.PROBLEM_START, stage=PcditStage.C, search_query=message
            )

    model = ScriptedChat(["Which input will you try first?"])
    h = make_harness(standard=model, tools=LocalToolRunner())
    h.deps.classifier = StartClassifier()
    out = await h.turn("I need to sum a list", code="def total(nums):\n    return 0\n")
    assert out["interrupt"] is None  # read-only tools never ask
    assert "nums = []" in human_prompt(model)
    assert out["state"]["progress"].run_permission == "ask"  # nothing was executed


async def test_violations_are_not_run(make_harness):
    model = ScriptedChat(["Q?"])
    h = make_harness(standard=model, tools=LocalToolRunner())
    evil = "import os\nprint(os.listdir('.'))\n"
    paused = await h.turn("what does this do", code=evil)
    done = await h.resume(paused["thread_id"], approve=True)
    assert done["text"].startswith("Q?")
    assert "when the code was run" not in human_prompt(model)  # refused, so no runtime facts
