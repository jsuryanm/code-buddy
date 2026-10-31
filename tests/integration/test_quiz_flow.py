import json

import httpx
import pytest

from codebuddy.agent.state import Classification
from codebuddy.api.app import create_app
from codebuddy.pedagogy.guard import StreamGuard
from codebuddy.pedagogy.quiz import BANK, DIFFERENT, NUDGE
from codebuddy.schemas import Intent, PcditStage
from tests.helpers import ScriptedChat

BUGGY = "nums = [1, 2, 3]\ntotal = 0\nfor i in range(len(nums) + 1):\n    total += nums[i]\n"
FIXED = "nums = [1, 2, 3]\ntotal = 0\nfor i in range(len(nums)):\n    total += nums[i]\n"
QUIZ = BANK["off_by_one_range"]


def parse(body: str) -> list[tuple[str, dict]]:
    out = []
    for block in body.strip().split("\n\n"):
        event, data = block.split("\n", 1)
        out.append((event.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def meta_and_text(body: str) -> tuple[dict, str]:
    events = parse(body)
    meta = next(d for k, d in events if k == "meta")
    return meta, "".join(d["text"] for k, d in events if k == "token")


# -- fix detection in the graph ----------------------------------------------------------


async def test_fixed_code_gets_a_confirmation_that_resets_the_ladder(make_harness):
    model = ScriptedChat(["Q one?", "Q two?", "You fixed the loop bound. Why does it work?"])
    h = make_harness(standard=model)
    await h.turn("my sum crashes", code=BUGGY)
    await h.turn("still crashes", code=BUGGY + "# try\n")
    out = await h.turn("is this right now?", code=FIXED)
    meta = out["meta"]
    assert meta["mode"] == "confirm" and meta["offer_quiz"] is True
    assert meta["quiz_concept"] == "loop bounds" and meta["can_show_answer"] is False
    progress = out["state"]["progress"]
    assert progress.hints_given == 0 and progress.started_at == 0.0
    assert progress.quiz_offer == "off_by_one_range" and progress.last_patterns == []
    system, human = model.calls[-1]
    assert "The learner fixed the bug" in system[1] and "fixed now:" in human[1]


async def test_saying_it_is_fixed_without_changing_the_code_is_another_hint(make_harness):
    h = make_harness(standard=ScriptedChat(["Q one?", "Q two?"]))
    await h.turn("my sum crashes", code=BUGGY)
    out = await h.turn("I fixed it, it works now", code=BUGGY)
    assert out["meta"]["mode"] == "hint" and out["meta"]["offer_quiz"] is False


async def test_a_syntax_error_in_between_does_not_hide_the_fix(make_harness):
    h = make_harness(standard=ScriptedChat(["Q?", "Q?", "Fixed."]))
    await h.turn("my sum crashes", code=BUGGY)
    await h.turn("now what", code="for i in range(3)\n    pass\n")
    assert (await h.turn("how about now", code=FIXED))["meta"]["mode"] == "confirm"


async def test_pasting_the_revealed_solution_is_not_praised_as_a_fix(make_harness):
    h = make_harness(standard=ScriptedChat(["Q?", "Q?"]), heavy=ScriptedChat(["Fixed code."]))
    await h.turn("my sum crashes", code=BUGGY)
    out = await h.turn("show me the answer", code=BUGGY)
    assert out["meta"]["mode"] == "reveal"
    progress = out["state"]["progress"]
    assert progress.last_patterns == [] and progress.last_shape is None
    assert (await h.turn("like this?", code=FIXED))["meta"]["mode"] == "hint"


@pytest.mark.parametrize("code", ["# nothing\n", "pass\n", "print(1)\n"])
async def test_deleting_or_replacing_the_code_is_not_a_fix(make_harness, code):
    h = make_harness(standard=ScriptedChat(["Q?", "Q?"]))
    await h.turn("my sum crashes", code=BUGGY)
    assert (await h.turn("fixed?", code=code))["meta"]["mode"] == "hint"


async def test_the_quiz_offer_persists_and_the_reflection_is_acknowledged(make_harness):
    model = ScriptedChat(["Q?", "You fixed it. Why?", "Right, and the quiz is still there."])
    h = make_harness(standard=model)
    await h.turn("my sum crashes", code=BUGGY)
    assert (await h.turn("is this right now?", code=FIXED))["meta"]["mode"] == "confirm"
    out = await h.turn("because range stops before len", code=FIXED)
    meta = out["meta"]
    assert meta["mode"] == "confirm" and meta["level"] is None
    assert meta["offer_quiz"] is True and meta["quiz_concept"] == "loop bounds"
    assert "The learner already fixed the bug" in model.calls[-1][0][1]
    progress = out["state"]["progress"]
    assert progress.hints_given == 0 and progress.quiz_offer == "off_by_one_range"
    concept = await h.turn("what is a list?")  # another kind of reply still offers the quiz
    assert concept["meta"]["mode"] == "explain" and concept["meta"]["offer_quiz"] is True


async def test_new_buggy_code_or_a_new_problem_withdraws_the_quiz_offer(make_harness):
    h = make_harness(standard=ScriptedChat(["Q?", "Fixed.", "Q?"]))
    await h.turn("my sum crashes", code=BUGGY)
    await h.turn("now?", code=FIXED)
    out = await h.turn("new one", code="list = [1]\nprint(list)\n")
    assert out["meta"]["mode"] == "hint" and out["meta"]["offer_quiz"] is False
    assert out["state"]["progress"].quiz_offer == ""


async def test_a_new_problem_withdraws_the_quiz_offer(make_harness):
    h = make_harness(standard=ScriptedChat(["Q?", "Fixed.", "Q?"]))
    await h.turn("my sum crashes", code=BUGGY)
    await h.turn("now?", code=FIXED)

    async def problem_start(message, code, progress):
        return Classification(intent=Intent.PROBLEM_START, stage=PcditStage.P, search_query=message)

    h.deps.classifier.classify = problem_start
    out = await h.turn("new exercise: reverse a string")
    assert out["meta"]["offer_quiz"] is False and out["state"]["progress"].quiz_offer == ""


# -- the quiz over HTTP ------------------------------------------------------------------


@pytest.fixture
def quiz_client(make_harness):
    def build(standard=None, **settings_update):
        h = make_harness(standard=standard or ScriptedChat(["Q?", "Fixed. Why?"]))
        if settings_update:
            h.deps.settings = h.deps.settings.model_copy(update=settings_update)
        app = create_app(h.deps)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        return client, h

    return build


async def fix_then_quiz(client, sid="q") -> httpx.Response:
    await client.post("/v1/turn", json={"session_id": sid, "message": "why", "code": BUGGY})
    await client.post("/v1/turn", json={"session_id": sid, "message": "now?", "code": FIXED})
    return await client.post("/v1/quiz", json={"session_id": sid})


async def answer(client, code, message="here is my fix", sid="q") -> httpx.Response:
    return await client.post("/v1/turn", json={"session_id": sid, "message": message, "code": code})


async def test_quiz_is_refused_before_a_fix(quiz_client):
    client, _ = quiz_client()
    async with client:
        r = await client.post("/v1/quiz", json={"session_id": "none"})
    assert r.status_code == 404  # not 409: the UI reads 409 as "another learner's session"


async def test_quiz_sends_question_one_without_a_model_call(quiz_client):
    model = ScriptedChat(["Q?", "Fixed. Why?"])
    client, h = quiz_client(standard=model)
    async with client:
        r = await fix_then_quiz(client)
    assert r.status_code == 200
    meta, text = meta_and_text(r.text)
    assert meta["mode"] == "quiz" and meta["quiz_code"] == QUIZ[0].snippet
    assert meta["quiz"] == {"index": 0, "total": 5, "difficulty": "easy", "score": 0}
    assert "Quiz 1 of 5 (easy)" in text and QUIZ[0].snippet in text
    assert "off_by_one_range" not in r.text and QUIZ[0].solution not in text
    assert parse(r.text)[-1][0] == "done" and len(model.calls) == 2
    progress = await h.deps.sessions.load("q")
    assert progress.quiz["index"] == 0 and progress.hints_given == 0


async def test_a_correct_answer_says_correct_and_streams_the_next_question(quiz_client):
    model = ScriptedChat(["Q?", "Fixed. Why?"])
    client, _ = quiz_client(standard=model)
    async with client:
        await fix_then_quiz(client)
        meta, text = meta_and_text((await answer(client, QUIZ[0].solution)).text)
    assert text.startswith("Correct.") and "Quiz 2 of 5 (easy)" in text
    assert meta["mode"] == "quiz" and meta["quiz"]["index"] == 1 and meta["quiz"]["score"] == 1
    assert meta["quiz_code"] == QUIZ[1].snippet and len(model.calls) == 2


async def test_a_wrong_answer_gets_one_guarded_hint_then_the_solution(quiz_client):
    model = ScriptedChat(["Q?", "Fixed. Why?", "What is i on the last pass?"])
    client, h = quiz_client(standard=model)
    async with client:
        await fix_then_quiz(client)
        meta, text = meta_and_text((await answer(client, QUIZ[0].snippet + "# hm\n")).text)
        assert meta["mode"] == "hint" and meta["level"] == 0 and meta["quiz"]["index"] == 0
        assert meta["can_show_answer"] is False and text == "What is i on the last pass?"
        assert "Hint level 0" in model.calls[-1][0][1]
        meta, text = meta_and_text((await answer(client, QUIZ[0].snippet + "# hm2\n")).text)
    assert QUIZ[0].solution in text and "Quiz 2 of 5" in text
    assert meta["quiz"] == {"index": 1, "total": 5, "difficulty": "easy", "score": 0}
    assert (await h.deps.sessions.load("q")).hints_given == 0  # no ladder inside the quiz


async def test_the_quiz_hint_is_guarded(quiz_client, monkeypatch):
    fed = []
    real = StreamGuard.__init__

    def spy(self, enforce=True, allow_pseudocode=False):
        fed.append(enforce)
        real(self, enforce=enforce, allow_pseudocode=allow_pseudocode)

    monkeypatch.setattr(StreamGuard, "__init__", spy)
    client, _ = quiz_client(standard=ScriptedChat(["Q?", "Fixed.", "Hint?"]))
    async with client:
        await fix_then_quiz(client)
        await answer(client, QUIZ[0].snippet + "# hm\n")
    assert fed[-1] is True


async def test_unchanged_question_code_gets_a_nudge_without_a_model_call(quiz_client):
    model = ScriptedChat(["Q?", "Fixed. Why?"])
    client, h = quiz_client(standard=model)
    async with client:
        await fix_then_quiz(client)
        meta, text = meta_and_text((await answer(client, QUIZ[0].snippet, "done")).text)
    assert text == NUDGE and meta["mode"] == "quiz" and len(model.calls) == 2
    quiz = (await h.deps.sessions.load("q")).quiz
    assert quiz["index"] == 0 and quiz["tries"] == 0 and quiz["results"] == []


async def test_quiz_turns_skip_the_classifier_and_retrieval(quiz_client, monkeypatch):
    client, h = quiz_client()
    calls = []

    async def classify(*args, **kwargs):
        calls.append("classify")

    async def retrieve(*args, **kwargs):
        calls.append("retrieve")

    async with client:
        await fix_then_quiz(client)
        monkeypatch.setattr(h.deps.classifier, "classify", classify)
        monkeypatch.setattr(h.deps.retriever, "retrieve", retrieve)
        for code, message in [
            (QUIZ[0].solution, "done"),  # correct
            (QUIZ[1].snippet, "hm"),  # unchanged: nudge
            (QUIZ[1].snippet + "# x\n", "try"),  # wrong: one model hint
            ("", "skip"),
            ("", "stop quiz"),
        ]:
            assert (await answer(client, code, message)).status_code == 200
    assert calls == []


async def test_skip_and_stop(quiz_client):
    client, h = quiz_client()
    async with client:
        await fix_then_quiz(client)
        meta, text = meta_and_text((await answer(client, QUIZ[0].snippet, "skip")).text)
        assert QUIZ[0].solution in text and meta["quiz"]["index"] == 1
        meta, text = meta_and_text((await answer(client, QUIZ[1].snippet, "stop quiz")).text)
    assert meta["quiz"] is None and "Quiz stopped" in text
    assert (await h.deps.sessions.load("q")).quiz is None


async def test_five_answers_end_in_a_summary_and_clear_the_quiz(quiz_client):
    client, h = quiz_client()
    async with client:
        await fix_then_quiz(client)
        for item in QUIZ[:4]:
            await answer(client, item.solution)
        await answer(client, "", "skip")  # the hard one
        progress = await h.deps.sessions.load("q")
    assert progress.quiz is None and progress.hints_given == 0
    assert progress.history[-1]["text"].startswith("Here is one way")
    assert "4 of 5" in progress.history[-1]["text"] and "hard" in progress.history[-1]["text"]


async def test_quiz_needs_the_api_key_when_configured(quiz_client):
    client, _ = quiz_client(api_keys="secret")
    async with client:
        assert (await client.post("/v1/quiz", json={"session_id": "q"})).status_code == 401


async def test_quiz_again_while_one_runs_resends_the_current_question(quiz_client):
    client, h = quiz_client()
    async with client:
        await fix_then_quiz(client)
        await answer(client, QUIZ[0].solution)  # now on question 2
        r = await client.post("/v1/quiz", json={"session_id": "q"})
    meta, text = meta_and_text(r.text)
    assert meta["quiz"]["index"] == 1 and meta["quiz"]["score"] == 1
    assert meta["quiz_code"] == QUIZ[1].snippet and "Quiz 2 of 5" in text
    progress = await h.deps.sessions.load("q")
    assert progress.quiz["index"] == 1 and progress.quiz_offer == ""


async def test_starting_a_quiz_withdraws_the_offer(quiz_client):
    client, h = quiz_client()
    async with client:
        await fix_then_quiz(client)
        assert (await h.deps.sessions.load("q")).quiz_offer == ""
        await answer(client, "", "stop quiz")
        r = await client.post("/v1/quiz", json={"session_id": "q"})
    assert r.status_code == 404


async def test_a_degraded_quiz_hint_does_not_use_up_the_try(quiz_client):
    client, h = quiz_client()
    async with client:
        await fix_then_quiz(client)
        h.tiers.standard.fail = True
        r = await answer(client, QUIZ[0].snippet + "# hm\n")
    assert "can't reach the tutor model" in r.text
    assert (await h.deps.sessions.load("q")).quiz["tries"] == 0


async def test_different_code_is_not_graded_over_http(quiz_client):
    client, h = quiz_client()
    async with client:
        await fix_then_quiz(client)
        meta, text = meta_and_text((await answer(client, "pass\n")).text)
    assert text == DIFFERENT and meta["mode"] == "quiz"
    assert (await h.deps.sessions.load("q")).quiz["tries"] == 0


async def test_a_question_about_unchanged_quiz_code_gets_one_hint(quiz_client):
    model = ScriptedChat(["Q?", "Fixed. Why?", "What is the last index?"])
    client, h = quiz_client(standard=model)
    async with client:
        await fix_then_quiz(client)
        meta, text = meta_and_text((await answer(client, QUIZ[0].snippet, "what is wrong?")).text)
    assert meta["mode"] == "hint" and meta["level"] == 0 and text == "What is the last index?"
    assert (await h.deps.sessions.load("q")).quiz["tries"] == 0


async def test_skip_and_stop_buttons_send_an_action(quiz_client):
    client, h = quiz_client()
    async with client:
        await fix_then_quiz(client)
        body = {"session_id": "q", "message": "Skip this question.", "code": QUIZ[0].snippet}
        r = await client.post("/v1/turn", json={**body, "action": "skip"})
        assert QUIZ[0].solution in meta_and_text(r.text)[1]
        bad = await client.post("/v1/turn", json={**body, "action": "restart"})
        assert bad.status_code == 422
        await client.post("/v1/turn", json={**body, "message": "Stop.", "action": "stop"})
    assert (await h.deps.sessions.load("q")).quiz is None
