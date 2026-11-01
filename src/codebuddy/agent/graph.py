"""The tutor graph (spec 12.1, 14.3).

Flow: load_state, analyze_code, check_cache. A cache hit goes to emit_cached. An answer to a
running quiz goes straight to policy (graded by code, no classifier or retrieval). Otherwise
classify, retrieve and recall_memory (opt-in, timed out) run in parallel, then refine_retrieval
and policy. After policy, route_tools chooses generate directly, run_tools, or approve_run (a
human-in-the-loop pause that asks the learner before their code is run). generate and
emit_cached both end in update_state.

Each turn runs on its own checkpoint thread, so a turn paused for approval can be resumed
later and no state leaks between turns. Learner progress lives in the session cache.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from loguru import logger

from codebuddy.agent.deps import Deps
from codebuddy.agent.nodes import TutorNodes
from codebuddy.agent.state import TutorState
from codebuddy.observability import tracing
from codebuddy.observability.summaries import format_summary, hash_session, safe_summary

# Types stored in checkpoints. LangGraph will refuse to load unregistered classes.
CHECKPOINT_TYPES = [
    ("codebuddy.schemas", name)
    for name in (
        "PcditStage", "Intent", "HintLevel", "Mode", "Decision", "SessionProgress", "Citation",
    )
] + [
    ("codebuddy.agent.state", "Classification"),
    ("codebuddy.agent.code_analysis", "CodeFeatures"),
    ("codebuddy.rag.rerank", "RetrievedChunk"),
    ("codebuddy.rag.retrieve", "RetrievalResult"),
    ("codebuddy.memory.types", "MemoryItem"),
    ("codebuddy.memory.types", "MemoryKind"),
]  # fmt: skip


def checkpoint_serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)


def logged(name: str, fn: Callable[[TutorState], Awaitable[dict]]):
    """Wrap a node so the flow log shows it: `-> name` (DEBUG), then `<- name  ms  summary`
    (INFO) with a whitelisted summary of its update, or the exception type when it fails.
    Every line inside the node carries turn= and sess= (a hash of the session id). With tracing
    on, the node is also a child span of the turn carrying the same summary."""

    async def node(state: TutorState, config: RunnableConfig) -> dict:
        configurable = config.get("configurable") or {}
        turn = str(configurable.get("thread_id", "-"))[:8]
        root = configurable.get("trace", tracing.OFF)
        with (
            logger.contextualize(turn=turn, sess=hash_session(state.get("session_id"))),
            tracing.span(name, parent=root) as span,
        ):
            logger.debug("-> {}", name)
            started = time.perf_counter()
            try:
                update = await fn(state)
            except GraphBubbleUp:  # an approval pause, not an error
                span.update(paused=True)
                logger.info("<- {} {:.1f} ms paused", name, (time.perf_counter() - started) * 1e3)
                raise
            except Exception as exc:
                span.update(error=type(exc).__name__)
                ms = (time.perf_counter() - started) * 1e3
                logger.info("<- {} {:.1f} ms failed: {}", name, ms, type(exc).__name__)
                raise
            if span.recording:
                span.update(**safe_summary(name, update))
            ms = (time.perf_counter() - started) * 1e3
            logger.opt(lazy=True).info(
                "<- {} {} ms {}",
                lambda: name,
                lambda: f"{ms:.1f}",
                lambda: format_summary(safe_summary(name, update)),
            )
            return update

    node.__name__ = name
    return node


def build_graph(deps: Deps, checkpointer: BaseCheckpointSaver | None = None):
    n = TutorNodes(deps)
    g = StateGraph(TutorState)
    for name, fn in {
        "load_state": n.load_state,
        "analyze_code": n.analyze_code,
        "check_cache": n.check_cache,
        "emit_cached": n.emit_cached,
        "classify": n.classify,
        "retrieve": n.retrieve,
        "recall_memory": n.recall_memory,
        "refine_retrieval": n.refine_retrieval,
        "policy": n.policy,
        "approve_run": n.approve_run,
        "run_tools": n.run_tools,
        "generate": n.generate,
        "update_state": n.update_state,
    }.items():
        g.add_node(name, logged(name, fn))

    g.add_edge(START, "load_state")
    g.add_edge("load_state", "analyze_code")
    g.add_edge("analyze_code", "check_cache")
    g.add_conditional_edges(
        "check_cache",
        n.route_after_cache,
        ["emit_cached", "policy", "classify", "retrieve", "recall_memory"],
    )
    g.add_edge(["classify", "retrieve", "recall_memory"], "refine_retrieval")  # join: wait for all
    g.add_edge("refine_retrieval", "policy")
    g.add_conditional_edges("policy", n.route_tools, ["generate", "run_tools", "approve_run"])
    g.add_conditional_edges("approve_run", n.route_after_approval, ["run_tools", "generate"])
    g.add_edge("run_tools", "generate")
    g.add_edge("generate", "update_state")
    g.add_edge("emit_cached", "update_state")
    g.add_edge("update_state", END)
    graph = g.compile(checkpointer=checkpointer or InMemorySaver(serde=checkpoint_serde()))
    # No LangChain CallbackHandler: it would record prompts and replies (tracing.py).
    graph.tracer = deps.tracer  # run_turn opens the root span with it
    return graph


def new_turn_id() -> str:
    return uuid.uuid4().hex


async def run_turn(
    graph, inputs: Any, thread_id: str | None = None, route: str | None = None
) -> AsyncIterator[dict]:
    """Yield stream events, then one final event.

    `inputs` is the turn input dict, or `Command(resume=...)` to continue a paused turn on the
    same `thread_id`. The final event is
    {"type": "final", "state": ..., "interrupt": payload | None, "thread_id": ...}.
    `route` names the entry point in the flow log (turn, show-answer, approve).
    """
    thread_id = thread_id or new_turn_id()
    config: dict = {"configurable": {"thread_id": thread_id}}
    resumed = isinstance(inputs, Command)
    route = route or ("approve" if resumed else "turn")
    sess = "-" if resumed else hash_session(inputs.get("session_id"))
    logger.bind(turn=thread_id[:8], sess=sess).info("turn start route={}", route)
    started = time.perf_counter()
    first_token_ms: float | None = None
    final: dict = {}
    tracer = getattr(graph, "tracer", None) or tracing.NoopTracer()
    with tracing.turn(tracer, thread_id, sess, route=route) as root:
        if root.recording:
            config["configurable"]["trace"] = root  # the nodes' parent span
        try:
            async for chunk in graph.astream(
                inputs, config, stream_mode=["custom", "values"], version="v2"
            ):
                if chunk["type"] == "custom":
                    if first_token_ms is None and chunk["data"].get("type") == "token":
                        first_token_ms = (time.perf_counter() - started) * 1e3
                    yield chunk["data"]
                elif chunk["type"] == "values":
                    final = chunk["data"]
            snapshot = await graph.aget_state(config)
        except Exception as exc:
            root.update(error=type(exc).__name__)
            logger.bind(turn=thread_id[:8], sess=sess).warning(
                "turn failed route={} error={}", route, type(exc).__name__
            )
            raise
        pending = next((i.value for t in snapshot.tasks for i in t.interrupts), None)
        total_ms = _log_turn_end(thread_id, final, pending, started, first_token_ms)
        if root.recording:
            _trace_turn_end(root, final, pending, total_ms, first_token_ms)
    yield {"type": "final", "state": final, "interrupt": pending, "thread_id": thread_id}


def _trace_turn_end(
    root: tracing.Observation, st: dict, pending: Any, total_ms: float, first_token_ms: float | None
) -> None:
    """Root attributes and the per-turn scores (spec 17.4): metadata only."""
    decision = st.get("decision")
    root.update(
        mode=decision.mode.value if decision else None,
        level=int(decision.level) if decision and decision.level is not None else None,
        paused=bool(pending),
    )
    if first_token_ms is not None:
        root.score("ttft_ms", round(first_token_ms, 1))
    root.score("total_ms", round(total_ms, 1))
    root.score("cache_hit", bool(st.get("cache_hit")))
    root.score("guarded", bool(st.get("guarded")))
    root.score("degraded", bool(st.get("degraded")))
    root.score("quiz", bool(st.get("quiz_turn") or (decision and decision.quiz)))


def _log_turn_end(
    thread_id: str, st: dict, pending: Any, started: float, first_token_ms: float | None
) -> float:
    total_ms = (time.perf_counter() - started) * 1e3
    decision = st.get("decision")
    logger.bind(turn=thread_id[:8], sess=hash_session(st.get("session_id"))).info(
        "turn end ttft_ms={} total_ms={} mode={} level={} cache_hit={} degraded={} guarded={}"
        " paused={}",
        round(first_token_ms) if first_token_ms is not None else None,
        round(total_ms),
        decision.mode.value if decision else None,
        int(decision.level) if decision and decision.level is not None else None,
        bool(st.get("cache_hit")),
        bool(st.get("degraded")),
        bool(st.get("guarded")),
        bool(pending),
    )
    return total_ms
