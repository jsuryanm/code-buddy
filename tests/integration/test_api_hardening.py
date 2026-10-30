import asyncio
import json

import httpx
import pytest

from codebuddy.api.app import create_app
from codebuddy.pedagogy.judge import LeakJudge, Verdict
from codebuddy.stt.transcribe import SpeechToText, Transcript, TranscriptionError
from codebuddy.tools.runner import LocalToolRunner
from tests.helpers import ScriptedChat

BUGGY = "nums = [1, 2, 3]\ntotal = 0\nfor i in range(len(nums) + 1):\n    total += nums[i]\n"
WAV = b"RIFF" + b"\x00" * 64


def parse(body: str) -> list[tuple[str, dict]]:
    out = []
    for block in body.strip().split("\n\n"):
        event, data = block.split("\n", 1)
        out.append((event.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


class FakeTranscriber:
    name = "fake"

    def __init__(self, text="why is my loop off by one", fail=False):
        self.text, self.fail = text, fail

    async def transcribe(self, audio, filename):
        if self.fail:
            raise RuntimeError("down")
        return self.text


@pytest.fixture
def build(make_harness):
    def _build(settings_update=None, speech=None, judge=None, **tiers):
        h = make_harness(**tiers)
        if settings_update:
            h.deps.settings = h.deps.settings.model_copy(update=settings_update)
        app = create_app(h.deps, speech=speech, judge=judge)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        return client, h

    return _build


async def test_api_key_is_required_when_configured(build):
    client, _ = build({"api_keys": "secret-1, secret-2"})
    body = {"session_id": "a", "message": "what is a loop"}
    async with client:
        assert (await client.get("/healthz")).status_code == 200  # health stays open
        assert (await client.post("/v1/turn", json=body)).status_code == 401
        bad = await client.post("/v1/turn", json=body, headers={"Authorization": "Bearer nope"})
        assert bad.status_code == 401
        good = await client.post(
            "/v1/turn", json=body, headers={"Authorization": "Bearer secret-2"}
        )
        assert good.status_code == 200
        header = await client.post("/v1/turn", json=body, headers={"X-API-Key": "secret-1"})
        assert header.status_code == 200
        assert (await client.get("/v1/metrics")).status_code == 401
        assert (await client.get("/healthz")).json()["auth_required"] is True


async def test_rate_limit_returns_429_with_retry_after(build):
    client, h = build({"rate_limit_per_minute": 2})
    async with client:
        codes = [(await client.get("/v1/session/x")).status_code for _ in range(3)]
        limited = await client.get("/v1/session/x")
    assert codes == [200, 200, 429]
    assert "retry-after" in limited.headers and int(limited.headers["retry-after"]) <= 60
    assert (await h.deps.metrics.snapshot())["rate_limited"] == 2


async def test_rate_limit_zero_disables_it(build):
    client, _ = build({"rate_limit_per_minute": 0})
    async with client:
        codes = [(await client.get("/v1/session/x")).status_code for _ in range(40)]
    assert set(codes) == {200}


async def test_approval_flow_over_http(build):
    client, h = build(standard=ScriptedChat(["What is i on the last pass?"]))
    h.deps.tools = LocalToolRunner()
    async with client:
        first = await client.post(
            "/v1/turn", json={"session_id": "s", "message": "it crashes", "code": BUGGY}
        )
        events = parse(first.text)
        kinds = [k for k, _ in events if k != "step"]
        assert kinds == ["meta", "approval", "done"] or kinds == ["approval", "done"]
        approval = next(d for k, d in events if k == "approval")
        done = events[-1][1]
        assert done["awaiting_approval"] is True and approval["tool"] == "trace_python"
        assert "token" not in kinds  # nothing was said before the learner decided

        wrong = await client.post(
            "/v1/approve",
            json={"session_id": "other", "turn_id": approval["turn_id"], "approve": True},
        )
        assert wrong.status_code == 404  # another session cannot answer for this learner

        ok = await client.post(
            "/v1/approve",
            json={"session_id": "s", "turn_id": approval["turn_id"], "approve": True},
        )
        resumed = parse(ok.text)
        assert "".join(d["text"] for k, d in resumed if k == "token").startswith("What is i")
        assert resumed[-1][1]["awaiting_approval"] is False

        again = await client.post(
            "/v1/approve",
            json={"session_id": "s", "turn_id": approval["turn_id"], "approve": True},
        )
        assert again.status_code == 404  # an approval can be used only once
        status = (await client.get("/v1/session/s")).json()
    assert status["run_permission"] == "allow"
    counts = await h.deps.metrics.snapshot()
    assert counts["approvals_requested"] == 1 and counts["approvals_granted"] == 1


async def test_speech_to_text_endpoint(build):
    speech = SpeechToText([FakeTranscriber("why does i plus plus fail")])
    client, h = build(speech=speech)
    async with client:
        ok = await client.post("/v1/stt", files={"audio": ("a.wav", WAV, "audio/wav")})
        assert ok.status_code == 200
        assert ok.json() == {
            "text": "why does i++ fail",
            "provider": "fake",
        }  # spoken symbols fixed
        assert (await client.get("/healthz")).json()["stt_configured"] is True
        bad_type = await client.post("/v1/stt", files={"audio": ("a.txt", b"hi", "text/plain")})
        assert bad_type.status_code == 415
        assert (
            await client.post("/v1/stt", files={"audio": ("a.wav", b"", "audio/wav")})
        ).status_code == 422
    assert (await h.deps.metrics.snapshot())["stt_requests"] == 1


async def test_speech_to_text_limits_and_failures(build):
    client, h = build({"stt_max_bytes": 100}, speech=SpeechToText([FakeTranscriber(fail=True)]))
    async with client:
        big = await client.post("/v1/stt", files={"audio": ("a.wav", b"x" * 101, "audio/wav")})
        assert big.status_code == 413
        failed = await client.post("/v1/stt", files={"audio": ("a.wav", WAV, "audio/wav")})
        assert failed.status_code == 502
    assert (await h.deps.metrics.snapshot())["stt_failures"] == 1


async def test_speech_to_text_not_configured_is_503(build):
    client, _ = build()
    async with client:
        r = await client.post("/v1/stt", files={"audio": ("a.wav", WAV, "audio/wav")})
    assert r.status_code == 503


async def test_fallback_transcriber_is_used_when_primary_fails():
    class Boom:
        name = "groq"

        async def transcribe(self, audio, filename):
            raise RuntimeError("rate limited")

    class Fine:
        name = "openai"

        async def transcribe(self, audio, filename):
            return "equals equals"

    result = await SpeechToText([Boom(), Fine()]).transcribe(WAV)
    assert result == Transcript("==", "openai")
    with pytest.raises(TranscriptionError):
        await SpeechToText([Boom()]).transcribe(WAV)


async def test_metrics_and_health_report_state(build):
    client, h = build(standard=ScriptedChat(["Q?"]))
    h.deps.tools = LocalToolRunner()
    async with client:
        await client.post("/v1/turn", json={"session_id": "m", "message": "hi", "code": None})
        counts = (await client.get("/v1/metrics")).json()
        health = (await client.get("/healthz")).json()
    assert counts["turns"] == 1
    assert health["tools"] == "local" and "sandbox_network_isolated" in health


async def test_judge_samples_hint_replies_in_the_background(build):
    chain_calls = []

    class Chain:
        async def ainvoke(self, messages):
            chain_calls.append(messages)
            return Verdict(leaks_answer=True, reason="says the fix")

    client, h = build(
        {"judge_sample_rate": 1.0},
        judge=LeakJudge(Chain()),
        standard=ScriptedChat(["Change the plus one."]),
    )
    async with client:
        await client.post("/v1/turn", json={"session_id": "j", "message": "why", "code": "x = 1\n"})
        for _ in range(20):  # the judge runs after the response, wait for it
            if chain_calls:
                break
            await asyncio.sleep(0.02)
    await asyncio.sleep(0.05)
    counts = await h.deps.metrics.snapshot()
    assert counts["judge_checked"] == 1 and counts["judge_flagged"] == 1
