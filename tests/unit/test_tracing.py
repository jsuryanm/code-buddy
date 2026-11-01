import sys
import types

import pytest

from codebuddy.config import Settings
from codebuddy.observability import tracing
from codebuddy.observability.tracing import LangfuseTracer, NoopTracer, build_tracer

KEYS = {"LANGFUSE_PUBLIC_KEY": "pk-lf-test", "LANGFUSE_SECRET_KEY": "sk-lf-test"}


class FakeObservation:
    def __init__(self, log: list, name: str, parent=None, **kwargs):
        self.log, self.name, self.parent = log, name, parent
        self.trace_id = parent.trace_id if parent else "t" * 32
        log.append(("start", name, kwargs))

    def start_observation(self, *, name, **kwargs):
        return FakeObservation(self.log, name, self, **kwargs)

    def update(self, **kwargs):
        self.log.append(("update", self.name, kwargs))

    def end(self):
        self.log.append(("end", self.name, {}))


class FakeLangfuse:
    instances: list = []

    def __init__(self, **kwargs):
        self.kwargs, self.log = kwargs, []
        FakeLangfuse.instances.append(self)

    def start_observation(self, *, name, **kwargs):
        return FakeObservation(self.log, name, None, **kwargs)

    def create_score(self, **kwargs):
        self.log.append(("score", kwargs["name"], kwargs))

    def flush(self):
        self.log.append(("flush", "", {}))

    def shutdown(self):
        self.log.append(("shutdown", "", {}))


@pytest.fixture
def fake_langfuse(monkeypatch):
    """A stand-in `langfuse` package, so these tests never need the extra or the network."""
    FakeLangfuse.instances = []
    propagated: list[dict] = []
    module = types.ModuleType("langfuse")
    filters = types.ModuleType("langfuse.span_filter")

    def is_langfuse_span(span) -> bool:
        return True

    class Propagate:
        def __init__(self, **kwargs):
            propagated.append(kwargs)

        def __enter__(self):
            return None

        def __exit__(self, *exc):
            return False

    filters.is_langfuse_span = is_langfuse_span
    module.Langfuse = FakeLangfuse
    module.propagate_attributes = Propagate
    module.span_filter = filters
    monkeypatch.setitem(sys.modules, "langfuse", module)
    monkeypatch.setitem(sys.modules, "langfuse.span_filter", filters)
    return module, propagated


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, model_fast="f", model_standard="s", model_heavy="h", **kw)


@pytest.mark.parametrize(
    ("env", "enabled", "expect"),
    [
        ({}, True, NoopTracer),
        ({"LANGFUSE_PUBLIC_KEY": "pk"}, True, NoopTracer),
        ({"LANGFUSE_SECRET_KEY": "sk"}, True, NoopTracer),
        (KEYS, True, LangfuseTracer),
        (KEYS, False, NoopTracer),
    ],
)
def test_build_tracer_needs_both_keys_and_the_switch(fake_langfuse, env, enabled, expect):
    tracer = build_tracer(_settings(tracing_enabled=enabled), env=env)
    assert type(tracer) is expect
    assert tracer.enabled is (expect is LangfuseTracer)


def test_build_tracer_is_off_when_the_package_is_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "langfuse", None)  # import raises ImportError
    assert type(build_tracer(_settings(), env=KEYS)) is NoopTracer


def test_build_tracer_is_off_when_the_client_fails(fake_langfuse, monkeypatch):
    def broken(**kwargs):
        raise ValueError("bad config")

    monkeypatch.setattr(fake_langfuse[0], "Langfuse", broken)
    assert type(build_tracer(_settings(), env=KEYS)) is NoopTracer


def test_build_tracer_passes_keys_host_sample_rate_and_an_export_filter(fake_langfuse):
    env = KEYS | {"LANGFUSE_HOST": "https://us.cloud.langfuse.com"}  # deprecated name
    build_tracer(_settings(trace_sample_rate=0.25), env=env)
    kwargs = FakeLangfuse.instances[-1].kwargs
    assert kwargs["public_key"] == "pk-lf-test" and kwargs["secret_key"] == "sk-lf-test"
    assert kwargs["base_url"] == "https://us.cloud.langfuse.com"
    assert kwargs["sample_rate"] == 0.25
    assert kwargs["should_export_span"] is fake_langfuse[0].span_filter.is_langfuse_span
    env["LANGFUSE_BASE_URL"] = "https://cloud.langfuse.com"  # the current name wins
    build_tracer(_settings(), env=env)
    assert FakeLangfuse.instances[-1].kwargs["base_url"] == "https://cloud.langfuse.com"


def test_langfuse_adapter_sends_metadata_and_never_input_or_output(fake_langfuse):
    _, propagated = fake_langfuse
    tracer = build_tracer(_settings(prompt_version="p9"), env=KEYS)
    client = FakeLangfuse.instances[-1]
    with tracing.turn(tracer, "turn-id", "abcd1234", route="turn") as root:
        with tracing.span("policy", parent=root) as node:
            node.update(mode="hint", level=1)
            with tracing.generation("generate", model="s", tier="standard", cap=250) as gen:
                gen.update(usage={"input": 3, "output": 4}, finish_reason="stop", outcome="ok")
        root.score("ttft_ms", 12.5)
        root.score("cache_hit", False)
    tracer.flush()
    tracer.shutdown()

    starts = [(name, kw) for kind, name, kw in client.log if kind == "start"]
    assert [name for name, _ in starts] == ["tutor-turn", "policy", "generate"]
    assert starts[2][1]["as_type"] == "generation" and starts[2][1]["model"] == "s"
    assert starts[2][1]["model_parameters"] == {"max_completion_tokens": 250}
    gen_update = next(
        kw for kind, name, kw in client.log if kind == "update" and name == "generate"
    )
    assert gen_update["usage_details"] == {"input": 3, "output": 4}
    assert gen_update["metadata"]["finish_reason"] == "stop"
    assert [kw["value"] for kind, _, kw in client.log if kind == "score"] == [12.5, 0.0]
    assert [kw["data_type"] for kind, _, kw in client.log if kind == "score"] == [
        "NUMERIC",
        "BOOLEAN",
    ]
    assert sum(1 for kind, *_ in client.log if kind == "end") == 3
    assert [kind for kind, *_ in client.log][-2:] == ["flush", "shutdown"]
    for _, _, kw in client.log:
        assert "input" not in kw and "output" not in kw
    assert propagated[0]["trace_name"] == "tutor-turn" and propagated[0]["session_id"] == "abcd1234"
    assert propagated[0]["metadata"]["prompt_version"] == "p9"
    assert all("user_id" not in p for p in propagated)


class Raising:
    enabled = True

    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise RuntimeError("tracer down")

        return fail


def test_tracer_errors_are_swallowed():
    with tracing.turn(Raising(), "t", "s") as root:
        with tracing.span("node", parent=root) as span:
            span.update(x=1)
            span.score("n", 1)
    assert root is tracing.OFF and span is tracing.OFF


def test_tracer_errors_at_the_end_do_not_hide_the_body(monkeypatch):
    class EndFails(NoopTracer):
        enabled = True

        def turn(self, *args):
            return object()

        def span(self, *args):
            return object()

        def end(self, obs, attrs):
            raise RuntimeError("export down")

    with tracing.turn(EndFails(), "t", "s") as root:
        with pytest.raises(KeyError):
            with tracing.span("node", parent=root):
                raise KeyError("body error")  # the body's own error still propagates


def test_noop_tracer_yields_the_shared_off_handle():
    with tracing.turn(NoopTracer(), "t", "s") as root:
        with tracing.span("node", parent=root) as span:
            assert span is tracing.OFF and not span.recording
        with tracing.generation("g", model="m", tier="fast") as gen:
            assert gen is tracing.OFF


async def test_close_flushes_once_then_shuts_down():
    calls = []

    class Counting(NoopTracer):
        def flush(self):
            calls.append("flush")

        def shutdown(self):
            calls.append("shutdown")

    await tracing.close(Counting())
    assert calls == ["flush", "shutdown"]
