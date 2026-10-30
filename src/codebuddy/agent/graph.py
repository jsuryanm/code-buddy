"""The tutor graph (spec 12.1, 14.3).

Flow: load_state, analyze_code, check_cache. A cache hit goes to emit_cached. A miss runs
classify and retrieve in parallel, then refine_retrieval and policy. After policy, route_tools
chooses generate directly, run_tools, or approve_run (a human-in-the-loop pause that asks the
learner before their code is run). generate and emit_cached both end in update_state.

Each turn runs on its own checkpoint thread, so a turn paused for approval can be resumed
later and no state leaks between turns. Learner progress lives in the session cache.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from codebuddy.agent.deps import Deps
from codebuddy.agent.nodes import TutorNodes
from codebuddy.agent.state import TutorState

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
]  # fmt: skip


def checkpoint_serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)


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
        "refine_retrieval": n.refine_retrieval,
        "policy": n.policy,
        "approve_run": n.approve_run,
        "run_tools": n.run_tools,
        "generate": n.generate,
        "update_state": n.update_state,
    }.items():
        g.add_node(name, fn)

    g.add_edge(START, "load_state")
    g.add_edge("load_state", "analyze_code")
    g.add_edge("analyze_code", "check_cache")
    g.add_conditional_edges(
        "check_cache", n.route_after_cache, ["emit_cached", "classify", "retrieve"]
    )
    g.add_edge(["classify", "retrieve"], "refine_retrieval")  # join: wait for both
    g.add_edge("refine_retrieval", "policy")
    g.add_conditional_edges("policy", n.route_tools, ["generate", "run_tools", "approve_run"])
    g.add_conditional_edges("approve_run", n.route_after_approval, ["run_tools", "generate"])
    g.add_edge("run_tools", "generate")
    g.add_edge("generate", "update_state")
    g.add_edge("emit_cached", "update_state")
    g.add_edge("update_state", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver(serde=checkpoint_serde()))


def new_turn_id() -> str:
    return uuid.uuid4().hex


async def run_turn(graph, inputs: Any, thread_id: str | None = None) -> AsyncIterator[dict]:
    """Yield stream events, then one final event.

    `inputs` is the turn input dict, or `Command(resume=...)` to continue a paused turn on the
    same `thread_id`. The final event is
    {"type": "final", "state": ..., "interrupt": payload | None, "thread_id": ...}.
    """
    thread_id = thread_id or new_turn_id()
    config = {"configurable": {"thread_id": thread_id}}
    final: dict = {}
    async for chunk in graph.astream(
        inputs, config, stream_mode=["custom", "values"], version="v2"
    ):
        if chunk["type"] == "custom":
            yield chunk["data"]
        elif chunk["type"] == "values":
            final = chunk["data"]
    snapshot = await graph.aget_state(config)
    pending = next((i.value for t in snapshot.tasks for i in t.interrupts), None)
    yield {"type": "final", "state": final, "interrupt": pending, "thread_id": thread_id}
