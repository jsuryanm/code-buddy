import asyncio

import httpx

from codebuddy.api.app import create_app
from codebuddy.memory.store import InMemoryLearnerMemory
from codebuddy.memory.types import MemoryItem, MemoryKind
from tests.helpers import ScriptedChat

LEARNER = "learner-0123456789ab"
BUGGY = "nums = [1, 2, 3]\nfor i in range(len(nums) + 1):\n    print(nums[i])\n"


def prompt_of(model: ScriptedChat) -> str:
    return model.calls[-1][1][1]


async def seeded(text="Struggles with off by one loop bounds") -> InMemoryLearnerMemory:
    memory = InMemoryLearnerMemory()
    memory._items[LEARNER] = [MemoryItem(MemoryKind.SEMANTIC, text)]
    return memory


async def drain(h) -> None:
    while h.deps.background:
        await asyncio.gather(*list(h.deps.background))


class SlowMemory(InMemoryLearnerMemory):
    async def recall(self, learner_id, query, limit=5):
        await asyncio.sleep(5)
        return []


class FailingWrites(InMemoryLearnerMemory):
    async def remember(self, learner_id, history, episode):
        raise RuntimeError("boom")


async def test_recalled_items_appear_in_the_prompt(make_harness):
    model = ScriptedChat(["Q?"])
    h = make_harness(standard=model, memory=await seeded())
    await h.turn("why is my loop wrong", code=BUGGY, learner_id=LEARNER)
    assert "<memory>" in prompt_of(model)
    assert "- [semantic] Struggles with off by one loop bounds" in prompt_of(model)
    assert (await h.deps.metrics.snapshot())["memory_recalls"] == 1


async def test_no_learner_id_means_no_recall(make_harness):
    model = ScriptedChat(["Q?"])
    h = make_harness(standard=model, memory=await seeded())
    await h.turn("why is my loop wrong", code=BUGGY)
    assert "<memory>" not in prompt_of(model)
    assert (await h.deps.metrics.snapshot())["memory_recalls"] == 0


async def test_slow_recall_times_out_and_the_turn_still_replies(make_harness):
    h = make_harness(standard=ScriptedChat(["Q?"]), memory=SlowMemory())
    h.deps.settings = h.deps.settings.model_copy(update={"memory_recall_timeout_s": 0.05})
    out = await h.turn("why is my loop wrong", code=BUGGY, learner_id=LEARNER)
    assert out["text"] == "Q?"
    assert (await h.deps.metrics.snapshot())["memory_failures"] == 1


async def test_memory_does_not_change_the_decision(make_harness):
    plain = make_harness(standard=ScriptedChat(["Q?"]))
    with_memory = make_harness(standard=ScriptedChat(["Q?"]), memory=await seeded())
    a = await plain.turn("why is my loop wrong", code=BUGGY)
    b = await with_memory.turn("why is my loop wrong", code=BUGGY, learner_id=LEARNER)
    assert a["state"]["decision"] == b["state"]["decision"]


async def test_opted_in_learner_bypasses_the_answer_cache(make_harness):
    model = ScriptedChat(["A loop repeats [1].", "A loop repeats again [1]."])
    h = make_harness(standard=model, memory=InMemoryLearnerMemory())
    await h.turn("what is a loop", learner_id=LEARNER)
    second = await h.turn("what is a loop", session="s2", learner_id=LEARNER)
    assert not second["state"].get("cache_hit")
    assert len(model.calls) == 2


async def test_writes_on_reveal_and_every_fourth_hint(make_harness):
    memory = InMemoryLearnerMemory()
    h = make_harness(memory=memory)
    for n in range(1, 4):
        await h.turn("why is my loop wrong", code=BUGGY, learner_id=LEARNER)
        await drain(h)
        assert await memory.all(LEARNER) == [], f"hint {n}"
    await h.turn("why is my loop wrong", code=BUGGY, learner_id=LEARNER)
    await drain(h)
    assert await memory.all(LEARNER)
    assert (await h.deps.metrics.snapshot())["memory_writes"] == 1

    other = "learner-other-0123456"
    out = await h.turn("show me the answer", code=BUGGY, session="s2", learner_id=other)
    assert out["meta"]["mode"] == "reveal"
    await drain(h)
    assert any(i.kind is MemoryKind.PROCEDURAL for i in await memory.all(other))


async def test_a_failing_write_does_not_break_the_turn(make_harness):
    h = make_harness(memory=FailingWrites())
    out = await h.turn("show me the answer", code=BUGGY, learner_id=LEARNER)
    await drain(h)
    assert out["text"]
    assert (await h.deps.metrics.snapshot())["memory_failures"] == 1


async def test_reply_that_followed_earlier_turns_is_not_cached(make_harness):
    model = ScriptedChat(["Variables hold values [1].", "A loop repeats [1].", "Fresh [1]."])
    h = make_harness(standard=model)
    first = await h.turn("what is a variable")
    assert first["state"]["cache_key"]
    await h.turn("what is a loop")  # answered with history in the prompt: must not be stored
    fresh = await h.turn("what is a loop", session="s2")
    assert not fresh["state"].get("cache_hit")
    assert fresh["text"] == "Fresh [1]."
    again = await h.turn("what is a loop", session="s3")
    assert again["state"]["cache_hit"] is True  # a first-turn answer is stored


def client_for(h, **settings_update):
    if settings_update:
        h.deps.settings = h.deps.settings.model_copy(update=settings_update)
    app = create_app(h.deps)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_memory_endpoints_round_trip(make_harness):
    h = make_harness(memory=await seeded())
    async with client_for(h) as client:
        got = await client.get(f"/v1/memory/{LEARNER}")
        item = got.json()["items"][0]
        assert item["kind"] == "semantic" and "off by one" in item["text"] and "created_at" in item
        assert (await client.delete(f"/v1/memory/{LEARNER}")).json() == {"deleted": 1}
        assert (await client.get(f"/v1/memory/{LEARNER}")).json() == {"items": []}
        assert (await client.get("/v1/memory/short")).status_code == 422
        assert (await client.delete("/v1/memory/bad!id")).status_code == 422
        bad = await client.post(
            "/v1/turn", json={"session_id": "a", "message": "hi", "learner_id": "x"}
        )
        assert bad.status_code == 422
        health = await client.get("/healthz")
        assert health.json()["memory_enabled"] is True


async def test_memory_endpoints_when_disabled_or_unauthenticated(make_harness):
    h = make_harness()
    async with client_for(h) as client:
        for call in (client.get, client.delete):
            r = await call(f"/v1/memory/{LEARNER}")
            assert r.status_code == 503 and "not enabled" in r.json()["detail"]
        assert (await client.get("/healthz")).json()["memory_enabled"] is False
    h = make_harness(memory=InMemoryLearnerMemory())
    async with client_for(h, api_keys="secret") as client:
        assert (await client.get(f"/v1/memory/{LEARNER}")).status_code == 401
        assert (await client.delete(f"/v1/memory/{LEARNER}")).status_code == 401
        ok = await client.get(f"/v1/memory/{LEARNER}", headers={"Authorization": "Bearer secret"})
        assert ok.status_code == 200
