import itertools

import httpx
from pydantic import SecretStr

from codebuddy.agent.graph import build_graph
from codebuddy.api.app import create_app
from codebuddy.memory.store import InMemoryLearnerMemory
from codebuddy.observability.summaries import hash_session
from codebuddy.observability.tracing import NoopTracer
from codebuddy.tools.runner import LocalToolRunner
from tests.helpers import ScriptedChat

MSG = "SENTINELMSG why does my loop crash"
CODE_MARK = "SENTINELCODE"
REPLY = "SENTINELREPLY"
SESSION = "SENTINELSESSION-raw-id"
BUGGY = (
    f"{CODE_MARK} = [1, 2, 3]\nfor i in range(len({CODE_MARK}) + 1):\n    print({CODE_MARK}[i])\n"
)


class RecordingTracer:
    """Keeps every observation and score in memory, in the order they were made."""

    enabled = True

    def __init__(self):
        self.ids = itertools.count(1)
        self.spans: dict[int, dict] = {}
        self.scores: list[tuple[int, str, object]] = []
        self.flushes = self.shutdowns = 0

    def _start(self, kind, parent, name, attrs) -> int:
        oid = next(self.ids)
        self.spans[oid] = {"kind": kind, "parent": parent, "name": name, "attrs": dict(attrs)}
        return oid

    def turn(self, turn_id, session_hash, attrs):
        oid = self._start("turn", None, "tutor-turn", attrs)
        self.spans[oid] |= {"session": session_hash, "turn_id": turn_id}
        return oid

    def span(self, parent, name, attrs):
        return self._start("span", parent, name, attrs)

    def generation(self, parent, name, model, tier, attrs):
        return self._start("generation", parent, name, attrs | {"model": model, "tier": tier})

    def end(self, obs, attrs):
        self.spans[obs]["attrs"] |= attrs
        self.spans[obs]["ended"] = True

    def score(self, obs, name, value):
        self.scores.append((obs, name, value))

    def flush(self):
        self.flushes += 1

    def shutdown(self):
        self.shutdowns += 1

    def named(self, name: str) -> list[dict]:
        return [s for s in self.spans.values() if s["name"] == name]


def traced(h, tracer):
    h.deps.tracer = tracer
    h.graph = build_graph(h.deps)
    return h


async def test_a_turn_records_a_root_node_spans_a_generation_and_scores(make_harness):
    rec = RecordingTracer()
    h = traced(make_harness(standard=ScriptedChat(["What is i?"])), rec)
    await h.turn("why does my loop crash", code=BUGGY, session="s9")

    roots = rec.named("tutor-turn")
    assert len(roots) == 1 and roots[0]["session"] == hash_session("s9")
    root_id = next(i for i, s in rec.spans.items() if s["kind"] == "turn")
    nodes = [s for s in rec.spans.values() if s["kind"] == "span"]
    names = [s["name"] for s in nodes]
    assert names[:3] == ["load_state", "analyze_code", "check_cache"]
    assert {"classify", "retrieve", "policy", "generate", "update_state"} <= set(names)
    assert all(s["parent"] == root_id for s in nodes)
    assert all(s.get("ended") for s in rec.spans.values())
    policy = rec.named("policy")[0]["attrs"]
    assert policy["mode"] == "hint" and policy["level"] == 0
    gen_node = next(i for i, s in rec.spans.items() if s["name"] == "generate")
    gens = [s for s in rec.spans.values() if s["kind"] == "generation"]
    assert len(gens) == 1 and gens[0]["parent"] == gen_node
    assert gens[0]["attrs"]["model"] == "standard" and gens[0]["attrs"]["tier"] == "standard"
    assert gens[0]["attrs"]["outcome"] == "ok" and gens[0]["attrs"]["cap"] == 250
    assert roots[0]["attrs"]["mode"] == "hint" and roots[0]["attrs"]["route"] == "turn"
    scores = {name: value for obs, name, value in rec.scores if obs == root_id}
    assert set(scores) == {"ttft_ms", "total_ms", "cache_hit", "guarded", "degraded", "quiz"}
    assert scores["cache_hit"] is False and scores["total_ms"] >= scores["ttft_ms"] >= 0


async def test_tier_fallbacks_and_tool_calls_are_recorded(make_harness):
    rec = RecordingTracer()
    h = traced(
        make_harness(
            standard=ScriptedChat(fail=True),
            fast=ScriptedChat(["Q?"]),
            tools=LocalToolRunner(),
        ),
        rec,
    )
    paused = await h.turn("it crashes", code=BUGGY)
    await h.resume(paused["thread_id"], approve=True)
    roots = rec.named("tutor-turn")
    assert [r["attrs"]["route"] for r in roots] == ["turn", "approve"]
    assert roots[0]["attrs"]["paused"] is True
    assert rec.named("approve_run")[0]["attrs"].get("paused") is True
    tool = rec.named("tool:trace_python")
    assert len(tool) == 1 and tool[0]["attrs"]["ok"] is True
    run_tools = next(i for i, s in rec.spans.items() if s["name"] == "run_tools")
    assert tool[0]["parent"] == run_tools
    gens = [s["attrs"] for s in rec.spans.values() if s["kind"] == "generation"]
    assert [(g["tier"], g["outcome"]) for g in gens] == [("standard", "error"), ("fast", "ok")]


async def test_tracer_failures_do_not_change_the_turn(make_harness):
    class Broken(RecordingTracer):
        def __getattribute__(self, name):
            if name in {"turn", "span", "generation", "end", "score"}:
                raise RuntimeError("tracer down")
            return super().__getattribute__(name)

    plain = make_harness(standard=ScriptedChat(["What is i?"]))
    broken = traced(make_harness(standard=ScriptedChat(["What is i?"])), Broken())
    a = await plain.turn("why does my loop crash", code=BUGGY)
    b = await broken.turn("why does my loop crash", code=BUGGY)
    assert a["text"] == b["text"] == "What is i?"
    assert a["meta"] == b["meta"]


async def test_no_learner_text_code_reply_token_or_raw_session_reaches_a_trace(make_harness):
    rec = RecordingTracer()
    leaky = f"{REPLY} first\nfor {REPLY}_x in range(3):\n    pass\n"  # stopped by the guard
    h = traced(
        make_harness(
            standard=ScriptedChat([f"{REPLY} what is i?", leaky]),
            heavy=ScriptedChat(fail=True),
            fast=ScriptedChat([f"{REPLY} answer"]),
            memory=InMemoryLearnerMemory(),
        ),
        rec,
    )
    h.deps.settings = h.deps.settings.model_copy(
        update={"memory_secret": SecretStr("s" * 32), "memory_write_every": 1}
    )
    app = create_app(h.deps)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        token = (await client.post("/v1/memory/learners")).json()["learner_token"]
        learner_id = app.state.tokens.verify(token, None)
        body = {"session_id": SESSION, "message": MSG, "code": BUGGY, "learner_id": token}
        for _ in range(2):
            assert (await client.post("/v1/turn", json=body)).status_code == 200
        show = {"session_id": SESSION, "code": BUGGY, "learner_id": token}
        assert (await client.post("/v1/show-answer", json=show)).status_code == 200
    recorded = repr(rec.spans) + repr(rec.scores)
    assert len(rec.named("tutor-turn")) == 3 and hash_session(SESSION) in recorded
    assert any(s["attrs"].get("outcome") == "guarded" for s in rec.spans.values())
    for secret in ("SENTINELMSG", CODE_MARK, REPLY, SESSION, token, learner_id):
        assert secret not in recorded, secret


async def test_healthz_reports_tracing_and_shutdown_flushes_once(make_harness):
    rec = RecordingTracer()
    h = traced(make_harness(), rec)
    app = create_app(h.deps)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as client:
            assert (await client.get("/healthz")).json()["tracing_enabled"] is True
    assert (rec.flushes, rec.shutdowns) == (1, 1)

    off = create_app(make_harness().deps)
    assert isinstance(off.state.deps.tracer, NoopTracer)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=off), base_url="http://t"
    ) as client:
        assert (await client.get("/healthz")).json()["tracing_enabled"] is False
