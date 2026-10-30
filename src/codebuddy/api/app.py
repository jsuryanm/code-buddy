"""FastAPI app: streams tutor replies over Server-Sent Events.

Run:  uv run uvicorn codebuddy.api.app:app --port 8000

Endpoints (see docs/api.md): /healthz, /v1/turn, /v1/show-answer, /v1/approve, /v1/stt,
/v1/session/{id}, /v1/metrics. Everything under /v1 honors API keys and rate limits.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Path, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langgraph.types import Command

from codebuddy.agent.deps import Deps
from codebuddy.agent.graph import build_graph, new_turn_id, run_turn
from codebuddy.api.security import (
    PendingApprovals,
    check_api_key,
    enforce_rate_limit,
    parse_keys,
)
from codebuddy.config import Settings, get_settings
from codebuddy.memory.store import LearnerMemory
from codebuddy.pedagogy.judge import LeakJudge, maybe_judge
from codebuddy.schemas import ApproveRequest, Mode, ShowAnswerRequest, TurnRequest
from codebuddy.stt.transcribe import TranscriptionError

log = logging.getLogger("codebuddy.api")

SHOW_ANSWER_MESSAGE = "Show me the full answer."
AUDIO_TYPES = ("audio/", "video/webm", "application/octet-stream")


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def create_app(
    deps: Deps | None = None,
    cache_kind: str = "injected",
    *,
    speech: Any = None,
    judge: LeakJudge | None = None,
    checkpointer: Any = None,
) -> FastAPI:
    """Build the app. Pass `deps` (tests, demo) or leave empty to build from the environment."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if getattr(app.state, "graph", None) is None:
            from codebuddy.api.wiring import build_resources

            res = await build_resources(get_settings())
            try:
                _install(app, res.deps, res.cache_kind, res.speech, res.judge, res.checkpointer)
                yield
            finally:
                await res.stack.aclose()
        else:
            yield

    app = FastAPI(title="CodeBuddy", version="0.2.0", lifespan=lifespan)
    app.state.background = set()  # keeps references to fire-and-forget tasks

    def _install(app: FastAPI, d: Deps, kind: str, stt: Any, jdg: Any, saver: Any) -> None:
        app.state.deps, app.state.cache_kind = d, kind
        app.state.speech, app.state.judge = stt, jdg
        app.state.graph = build_graph(d, saver)
        app.state.pending = PendingApprovals(d.cache)

    if deps is not None:
        _install(app, deps, cache_kind, speech, judge, checkpointer)

    settings: Settings = deps.settings if deps is not None else get_settings()
    if origins := [o.strip() for o in settings.cors_origins.split(",") if o.strip()]:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )

    def current() -> Deps:
        return app.state.deps

    async def guard(request: Request) -> None:
        """Authenticate, then rate limit. Runs before every /v1 route."""
        d = current()
        key = check_api_key(request, d.settings)
        await enforce_rate_limit(request, d.settings, d.cache, d.metrics, key)

    # -- health and metrics ----------------------------------------------------------

    @app.get("/healthz")
    async def healthz():
        from codebuddy.sandbox.runner import network_isolated

        d = getattr(app.state, "deps", None)
        s = d.settings if d else settings
        tools = type(d.tools).__name__ if d and d.tools else None
        return {
            "status": "ok",
            "cache": getattr(app.state, "cache_kind", "not started"),
            "models_configured": all((s.model_fast, s.model_standard, s.model_heavy)),
            "stt_configured": getattr(app.state, "speech", None) is not None,
            "tools": {"MCPToolRunner": "mcp", "LocalToolRunner": "local"}.get(tools or "", "off"),
            "sandbox_network_isolated": network_isolated(),
            "memory_enabled": bool(d and d.memory),
            "auth_required": bool(parse_keys(s.api_keys)),
        }

    @app.get("/v1/metrics", dependencies=[Depends(guard)])
    async def metrics():
        return await current().metrics.snapshot()

    # -- streaming -------------------------------------------------------------------

    async def emit(
        events: AsyncIterator[dict], session_id: str, code: str | None
    ) -> AsyncIterator[str]:
        d = current()
        started = time.perf_counter()
        first_token_ms: float | None = None
        level: int | None = None
        try:
            async for event in events:
                kind = event["type"]
                if kind == "meta":
                    level = event.get("level") if event.get("mode") == Mode.HINT.value else None
                    yield sse("meta", event)
                elif kind == "token":
                    if first_token_ms is None:
                        first_token_ms = (time.perf_counter() - started) * 1000
                    yield sse("token", {"text": event["text"]})
                elif kind == "final":
                    st, pending = event["state"], event["interrupt"]
                    turn_id = event["thread_id"]
                    total_ms = (time.perf_counter() - started) * 1000
                    if pending:
                        await app.state.pending.add(turn_id, session_id)
                        await d.metrics.incr("approvals_requested")
                        yield sse("approval", {"turn_id": turn_id, **pending})
                    progress = st.get("progress")
                    done = {
                        "turn_id": turn_id,
                        "awaiting_approval": bool(pending),
                        "citations": [c.model_dump() for c in st.get("citations", [])],
                        "degraded": bool(st.get("degraded")),
                        "guarded": bool(st.get("guarded")),
                        "cache_hit": bool(st.get("cache_hit")),
                        "stage": progress.stage.value if progress else None,
                        "hints_given": progress.hints_given if progress else 0,
                        "ttft_ms": round(first_token_ms or total_ms),
                        "total_ms": round(total_ms),
                    }
                    log.info("turn session=%s %s", session_id, done)
                    yield sse("done", done)
                    if not pending and st.get("reply"):
                        _audit(session_id, code, st["reply"], level)
        except Exception:
            log.exception("turn failed")
            yield sse("error", {"message": "Something went wrong. Please try again."})

    def _audit(session_id: str, code: str | None, reply: str, level: int | None) -> None:
        d = current()
        task = asyncio.create_task(
            maybe_judge(
                app.state.judge,
                d.metrics,
                d.settings.judge_sample_rate,
                session_id=session_id,
                code=code,
                reply=reply,
                level=level,
            )
        )
        app.state.background.add(task)
        task.add_done_callback(app.state.background.discard)

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

    def stream_response(events: AsyncIterator[dict], session_id: str, code: str | None):
        return StreamingResponse(
            emit(events, session_id, code), media_type="text/event-stream", headers=headers
        )

    def turn_events(
        session_id: str, message: str, code: str | None, language: str, learner_id: str | None
    ):
        inputs = {"session_id": session_id, "message": message, "code": code, "language": language}
        if learner_id and current().memory:
            inputs["learner_id"] = learner_id
        return run_turn(app.state.graph, inputs, new_turn_id())

    @app.post("/v1/turn", dependencies=[Depends(guard)])
    async def turn(req: TurnRequest):
        if not req.message.strip():
            raise HTTPException(422, "message must not be empty")
        events = turn_events(req.session_id, req.message, req.code, req.language, req.learner_id)
        return stream_response(events, req.session_id, req.code)

    @app.post("/v1/show-answer", dependencies=[Depends(guard)])
    async def show_answer(req: ShowAnswerRequest):
        events = turn_events(
            req.session_id, SHOW_ANSWER_MESSAGE, req.code, req.language, req.learner_id
        )
        return stream_response(events, req.session_id, req.code)

    @app.post("/v1/approve", dependencies=[Depends(guard)])
    async def approve(req: ApproveRequest):
        """Resume a turn that paused to ask permission to run the learner's code."""
        if not await app.state.pending.take(req.turn_id, req.session_id):
            raise HTTPException(404, "No pending approval for this session and turn")
        await current().metrics.incr("approvals_granted" if req.approve else "approvals_declined")
        command = Command(resume={"approve": req.approve, "remember": req.remember})
        return stream_response(
            run_turn(app.state.graph, command, req.turn_id), req.session_id, None
        )

    # -- speech and session ----------------------------------------------------------

    @app.post("/v1/stt", dependencies=[Depends(guard)])
    async def stt(audio: UploadFile):
        stt_service = getattr(app.state, "speech", None)
        if stt_service is None:
            raise HTTPException(503, "Speech-to-text is not configured (set GROQ_API_KEY)")
        s = current().settings
        content_type = audio.content_type or ""
        if not content_type.startswith(AUDIO_TYPES):
            raise HTTPException(415, f"Unsupported content type: {content_type or 'none'}")
        data = await audio.read(s.stt_max_bytes + 1)
        if len(data) > s.stt_max_bytes:
            raise HTTPException(413, f"Audio larger than {s.stt_max_bytes} bytes")
        if not data:
            raise HTTPException(422, "Empty audio")
        await current().metrics.incr("stt_requests")
        try:
            transcript = await stt_service.transcribe(data, audio.filename or "speech.wav")
        except TranscriptionError as exc:
            await current().metrics.incr("stt_failures")
            log.warning("transcription failed: %s", exc)
            raise HTTPException(502, "Transcription failed; please type your question") from exc
        return {"text": transcript.text, "provider": transcript.provider}

    @app.get("/v1/session/{session_id}", dependencies=[Depends(guard)])
    async def session(session_id: str):
        progress = await current().sessions.load(session_id)
        return {
            "stage": progress.stage.value,
            "hints_given": progress.hints_given,
            "reveals": progress.reveals,
            "can_show_answer": progress.hints_given >= 1,
            "run_permission": progress.run_permission,
        }

    # -- learner memory (privacy) ----------------------------------------------------

    LearnerId = Path(pattern=r"^[A-Za-z0-9_-]{16,64}$")

    def memory_store() -> LearnerMemory:
        if (memory := current().memory) is None:
            raise HTTPException(503, "Long-term memory is not enabled")
        return memory

    @app.get("/v1/memory/{learner_id}", dependencies=[Depends(guard)])
    async def memory_list(learner_id: str = LearnerId):
        items = await memory_store().all(learner_id)
        return {
            "items": [
                {"kind": i.kind.value, "text": i.text, "created_at": i.created_at} for i in items
            ]
        }

    @app.delete("/v1/memory/{learner_id}", dependencies=[Depends(guard)])
    async def memory_forget(learner_id: str = LearnerId):
        return {"deleted": await memory_store().forget(learner_id)}

    return app


app = create_app()
