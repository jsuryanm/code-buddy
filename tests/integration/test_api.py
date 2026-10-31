import json

import httpx
import pytest

from codebuddy.api.app import create_app
from tests.helpers import ScriptedChat

BUGGY = "total = 0\nfor i in range(len([1,2]) + 1):\n    total += i\n"


def parse(body: str) -> list[tuple[str, dict]]:
    out = []
    for block in body.strip().split("\n\n"):
        event, data = block.split("\n", 1)
        out.append((event.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


@pytest.fixture
def client_for(make_harness):
    def build(**tiers):
        h = make_harness(**tiers)
        app = create_app(h.deps)
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")

    return build


async def test_turn_streams_meta_tokens_and_done(client_for):
    client = client_for(standard=ScriptedChat(["What is i on the last pass?"]))
    async with client:
        r = await client.post("/v1/turn", json={"session_id": "a", "message": "why", "code": BUGGY})
    assert r.headers["content-type"].startswith("text/event-stream")
    events = parse(r.text)
    kinds = [k for k, _ in events if k != "step"]
    assert kinds[0] == "meta" and kinds[-1] == "done" and "token" in kinds
    assert "".join(d["text"] for k, d in events if k == "token").startswith("What is i")
    done = events[-1][1]
    assert done["hints_given"] == 1 and done["ttft_ms"] >= 0 and done["citations"]


async def test_show_answer_endpoint_reveals(client_for):
    client = client_for(
        standard=ScriptedChat(["Q?"]), heavy=ScriptedChat(["```python\nprint(1)\n```\nWhy?"])
    )
    async with client:
        await client.post("/v1/turn", json={"session_id": "b", "message": "why", "code": BUGGY})
        r = await client.post("/v1/show-answer", json={"session_id": "b", "code": BUGGY})
        meta = next(d for k, d in parse(r.text) if k == "meta")
        status = (await client.get("/v1/session/b")).json()
    assert meta["mode"] == "reveal" and "```python" in r.text
    assert status["hints_given"] == 0 and status["reveals"] == 1


async def test_session_endpoint_tracks_progress(client_for):
    client = client_for(standard=ScriptedChat(["Q?"] * 4))
    async with client:
        seen = []
        for i in range(4):
            seen.append((await client.get("/v1/session/c")).json()["can_show_answer"])
            code = BUGGY + f"# try {i}\n"
            await client.post("/v1/turn", json={"session_id": "c", "message": "why", "code": code})
        after = (await client.get("/v1/session/c")).json()
    assert seen == [False] * 4 and after["can_show_answer"] is True  # after the 4th hint


async def test_empty_message_is_rejected_and_health_works(client_for):
    client = client_for()
    async with client:
        assert (
            await client.post("/v1/turn", json={"session_id": "d", "message": " "})
        ).status_code == 422
        assert (await client.get("/healthz")).json()["status"] == "ok"
