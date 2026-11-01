"""Langfuse tracing, metadata only (docs/observability.md, ADR 0009).

There is deliberately no LangChain `CallbackHandler` on the tutor graph: it records prompts and
completions, which hold learner messages, code and replies. The tutor traces through this thin
layer instead, fed by the same whitelisted summaries as the logs (observability/summaries.py),
plus model id, tier, token cap, token usage and finish reason. No observation is ever given an
input or output, and the session id is the 8-char hash, never the raw id or a learner id.

Every call into a tracer is wrapped: an error is logged at DEBUG with its type name only and the
turn carries on. The SDK exports from a background thread; nothing here waits on the network.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Protocol
from urllib.parse import urlparse

from loguru import logger

from codebuddy.config import Settings

TRACE_NAME = "tutor-turn"


class Tracer(Protocol):
    """A tracing backend. Observations are opaque values handed back to the same tracer."""

    enabled: bool

    def turn(self, turn_id: str, session_hash: str, attrs: dict) -> Any: ...

    def span(self, parent: Any, name: str, attrs: dict) -> Any: ...

    def generation(
        self, parent: Any, name: str, model: str | None, tier: str, attrs: dict
    ) -> Any: ...

    def end(self, obs: Any, attrs: dict) -> None: ...

    def score(self, obs: Any, name: str, value: float | bool) -> None: ...

    def flush(self) -> None: ...

    def shutdown(self) -> None: ...


class NoopTracer:
    """The default: tracing off. Nothing is recorded."""

    enabled = False

    def turn(self, turn_id: str, session_hash: str, attrs: dict) -> None:
        return None

    def span(self, parent: Any, name: str, attrs: dict) -> None:
        return None

    def generation(self, parent: Any, name: str, model: str | None, tier: str, attrs: dict):
        return None

    def end(self, obs: Any, attrs: dict) -> None:
        return None

    def score(self, obs: Any, name: str, value: float | bool) -> None:
        return None

    def flush(self) -> None:
        return None

    def shutdown(self) -> None:
        return None


def call(tracer: Any, method: str, *args: Any) -> Any:
    """Run one tracer method; tracing must never fail a turn."""
    try:
        return getattr(tracer, method)(*args)
    except Exception as exc:
        logger.debug("tracing call failed: {}", type(exc).__name__)
        return None


class Observation:
    """A started observation. `update` only collects attributes; they are sent once, at the
    end. Callers put whitelisted metadata here, never learner text."""

    __slots__ = ("tracer", "obs", "attrs")

    def __init__(self, tracer: Tracer | None, obs: Any):
        self.tracer, self.obs, self.attrs = tracer, obs, {}

    @property
    def recording(self) -> bool:
        return self.tracer is not None

    def update(self, **attrs: Any) -> None:
        if self.tracer is not None:
            self.attrs.update(attrs)

    def score(self, name: str, value: float | bool) -> None:
        if self.tracer is not None:
            call(self.tracer, "score", self.obs, name, value)


OFF = Observation(None, None)  # the shared handle while tracing is off
_current: ContextVar[Observation] = ContextVar("codebuddy_trace", default=OFF)


@contextmanager
def _opened(tracer: Tracer, obs: Any, current: bool) -> Generator[Observation]:
    handle = Observation(tracer, obs)
    token = _current.set(handle) if current else None
    try:
        yield handle
    finally:
        if token is not None:
            try:
                _current.reset(token)
            except ValueError:  # exited in another context; the value dies with that context
                pass
        call(tracer, "end", obs, handle.attrs)


@contextmanager
def turn(tracer: Tracer, turn_id: str, session_hash: str, **attrs: Any) -> Generator[Observation]:
    """The root `tutor-turn` observation. It is not made current, because `run_turn` is an async
    generator; it reaches the nodes through the graph config instead."""
    obs = call(tracer, "turn", turn_id, session_hash, attrs) if tracer.enabled else None
    if obs is None:
        yield OFF
        return
    with _opened(tracer, obs, current=False) as handle:
        yield handle


@contextmanager
def span(name: str, parent: Observation | None = None, **attrs: Any) -> Generator[Observation]:
    """A child of `parent` (default: the current observation), current inside the block."""
    p = parent if parent is not None else _current.get()
    obs = call(p.tracer, "span", p.obs, name, attrs) if p.tracer is not None else None
    if obs is None:
        yield OFF
        return
    with _opened(p.tracer, obs, current=True) as handle:
        yield handle


@contextmanager
def generation(name: str, *, model: str | None, tier: str, **attrs: Any) -> Generator[Observation]:
    """A model call under the current observation. Update it with `usage`, `finish_reason` and
    `outcome`; never with a prompt or a reply."""
    p = _current.get()
    obs = call(p.tracer, "generation", p.obs, name, model, tier, attrs) if p.tracer else None
    if obs is None:
        yield OFF
        return
    with _opened(p.tracer, obs, current=True) as handle:
        yield handle


async def close(tracer: Tracer) -> None:
    """At shutdown: send what is buffered, then stop the exporter (off the event loop)."""
    for step in ("flush", "shutdown"):
        await asyncio.to_thread(call, tracer, step)


class LangfuseTracer:
    """Langfuse SDK v4 adapter. Children are created from their parent observation, so no
    OpenTelemetry context is held across the graph's async boundaries."""

    enabled = True

    def __init__(self, client: Any, propagate: Any, metadata: dict[str, str]):
        self._client, self._propagate, self._metadata = client, propagate, metadata

    def turn(self, turn_id: str, session_hash: str, attrs: dict) -> tuple:
        trace = {
            "trace_name": TRACE_NAME,
            "session_id": session_hash if session_hash != "-" else None,
            "tags": [str(attrs.get("route", "turn"))],
            "metadata": self._metadata | {"turn": turn_id[:8]},
        }
        with self._propagate(**trace):
            obs = self._client.start_observation(name=TRACE_NAME, as_type="span", metadata=attrs)
        return obs, trace

    def span(self, parent: tuple, name: str, attrs: dict) -> tuple:
        obs, trace = parent
        with self._propagate(**trace):
            return obs.start_observation(name=name, as_type="span", metadata=attrs), trace

    def generation(
        self, parent: tuple, name: str, model: str | None, tier: str, attrs: dict
    ) -> tuple:
        obs, trace = parent
        params = {"max_completion_tokens": attrs["cap"]} if "cap" in attrs else None
        with self._propagate(**trace):
            child = obs.start_observation(
                name=name,
                as_type="generation",
                model=model,
                model_parameters=params,
                metadata={"tier": tier} | attrs,
            )
        return child, trace

    def end(self, obs: tuple, attrs: dict) -> None:
        span = obs[0]
        meta = dict(attrs)
        usage = meta.pop("usage", None)
        if meta or usage:
            span.update(metadata=meta or None, usage_details=usage or None)
        span.end()

    def score(self, obs: tuple, name: str, value: float | bool) -> None:
        self._client.create_score(
            name=name,
            value=float(value),
            trace_id=obs[0].trace_id,
            data_type="BOOLEAN" if isinstance(value, bool) else "NUMERIC",
        )

    def flush(self) -> None:
        self._client.flush()

    def shutdown(self) -> None:
        self._client.shutdown()


def build_tracer(settings: Settings, env: Mapping[str, str] | None = None) -> Tracer:
    """Langfuse when both keys are set, the switch is on and the `trace` extra is installed;
    otherwise the no-op tracer. Keys come from the process environment."""
    env = os.environ if env is None else env
    public, secret = env.get("LANGFUSE_PUBLIC_KEY"), env.get("LANGFUSE_SECRET_KEY")
    if not settings.tracing_enabled:
        logger.info("tracing off: CODEBUDDY_TRACING_ENABLED is false")
        return NoopTracer()
    if not (public and secret):
        logger.info("tracing off: LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are not both set")
        return NoopTracer()
    base_url = env.get("LANGFUSE_BASE_URL") or env.get("LANGFUSE_HOST") or None
    try:
        import langfuse
        from langfuse.span_filter import is_langfuse_span

        client = langfuse.Langfuse(
            public_key=public,
            secret_key=secret,
            base_url=base_url,
            sample_rate=settings.trace_sample_rate,
            should_export_span=is_langfuse_span,  # only our own spans, never other libraries'
        )
    except ImportError:
        logger.info("tracing off: langfuse is not installed (uv sync --extra trace)")
        return NoopTracer()
    except Exception as exc:
        logger.info("tracing off: Langfuse failed to start ({})", type(exc).__name__)
        return NoopTracer()
    s = settings
    metadata = {
        "prompt_version": s.prompt_version,
        "index_version": s.index_version,
        "model_fast": str(s.model_fast),
        "model_standard": str(s.model_standard),
        "model_heavy": str(s.model_heavy),
    }
    host = urlparse(base_url).hostname if base_url else "cloud.langfuse.com"
    logger.info("tracing on: Langfuse host={} sample_rate={}", host, s.trace_sample_rate)
    return LangfuseTracer(client, langfuse.propagate_attributes, metadata)
