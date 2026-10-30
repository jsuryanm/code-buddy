import httpx

from codebuddy.agent.code_analysis import PATTERNS
from codebuddy.api.app import create_app
from codebuddy.tools.runner import LocalToolRunner
from tests.helpers import ScriptedChat
from tests.integration.test_api import parse

BUGGY = "nums = [1, 2, 3]\ntotal = 0\nfor i in range(len(nums) + 1):\n    total += nums[i]\n"


def steps(events: list[dict]) -> list[dict]:
    return [e for e in events if e["type"] == "step"]


def index(events: list[dict], pred) -> int:
    return next(i for i, e in enumerate(events) if pred(e))


async def test_steps_arrive_before_the_first_token(make_harness):
    h = make_harness(standard=ScriptedChat(["What is i on the last pass?"]))
    events = (await h.turn("my sum crashes", code=BUGGY))["events"]
    seen = {(s["key"], s["status"]): s for s in steps(events)}
    for key in ("analyze_code", "classify", "retrieve", "policy"):
        assert (key, "running") in seen and (key, "done") in seen
    assert ("recall_memory", "running") not in seen  # no learner id, no memory step
    assert ("check_cache", "done") not in seen
    assert seen[("retrieve", "done")]["label"] == "Searching Sample Basics"
    assert seen[("retrieve", "done")]["detail"].endswith("passages")
    assert seen[("policy", "done")]["detail"] == "Hint 1"
    first_token = index(events, lambda e: e["type"] == "token")
    generating = index(events, lambda e: e.get("key") == "generate")
    assert generating < first_token
    assert all(i < first_token for i, e in enumerate(events) if e["type"] == "step")
    assert [s["status"] for s in steps(events) if s["key"] == "generate"] == ["running"]


async def test_no_code_means_no_reading_step(make_harness):
    h = make_harness(standard=ScriptedChat(["A loop repeats [1]."]))
    events = (await h.turn("what is a loop?"))["events"]
    assert all(s["key"] != "analyze_code" for s in steps(events))
    assert {s["detail"] for s in steps(events) if s["key"] == "policy"} == {None, "Explanation"}


async def test_cached_reply_emits_one_step(make_harness):
    h = make_harness(standard=ScriptedChat(["A loop repeats code [1]."]))
    await h.turn("what is a loop?")
    events = (await h.turn("what is a loop?", session="s2"))["events"]
    assert [(s["key"], s["status"]) for s in steps(events)] == [("check_cache", "done")]
    assert steps(events)[0]["label"] == "Found a saved explanation"


async def test_memory_step_only_with_a_learner(make_harness):
    from tests.integration.test_memory import seeded

    h = make_harness(standard=ScriptedChat(["Q?"]), memory=await seeded())
    events = (await h.turn("why", code=BUGGY, learner_id="learner-1"))["events"]
    keys = {(s["key"], s["status"]) for s in steps(events)}
    assert {("recall_memory", "running"), ("recall_memory", "done")} <= keys


async def test_tool_steps_report_the_outcome(make_harness):
    h = make_harness(standard=ScriptedChat(["Q?"]), tools=LocalToolRunner())
    paused = await h.turn("it crashes", code=BUGGY)
    done = await h.resume(paused["thread_id"], approve=True)
    run = [s for s in steps(done["events"]) if s["key"] == "run_tools"]
    assert [(s["status"], s["detail"]) for s in run] == [("running", None), ("done", "finished")]
    stopped = make_harness(standard=ScriptedChat(["Q?"]), tools=LocalToolRunner())
    paused = await stopped.turn("it crashes", code=BUGGY)
    out = await stopped.resume(paused["thread_id"], approve=False)
    assert all(s["key"] != "run_tools" for s in steps(out["events"]))


async def test_steps_never_leak_findings_errors_or_code(make_harness):
    h = make_harness(standard=ScriptedChat(["Q?"]), tools=LocalToolRunner())
    paused = await h.turn("it crashes", code=BUGGY)
    done = await h.resume(paused["thread_id"], approve=True)
    text = " ".join(
        f"{s['label']} {s['detail'] or ''}" for s in steps(paused["events"]) + steps(done["events"])
    )
    assert text.strip()
    for pattern in PATTERNS.values():
        assert pattern.id not in text and pattern.symptom not in text
    assert "IndexError" not in text and "Error" not in text
    assert not any(line.strip() and line.strip() in text for line in BUGGY.splitlines())


async def test_api_forwards_step_events(make_harness):
    h = make_harness(standard=ScriptedChat(["What is i?"]))
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(h.deps)), base_url="http://t"
    )
    async with client:
        r = await client.post("/v1/turn", json={"session_id": "a", "message": "why", "code": BUGGY})
    events = parse(r.text)
    kinds = [k for k, _ in events]
    assert kinds.count("step") >= 6
    assert max(i for i, k in enumerate(kinds) if k == "step") < kinds.index("token")
    step = next(d for k, d in events if k == "step")
    assert set(step) == {"key", "label", "status", "detail"}
    assert events[-1][1]["ttft_ms"] >= 0
