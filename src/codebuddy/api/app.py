"""FastAPI app: streams tutor replies over Server-Sent Events.

Run:  uv run uvicorn codebuddy.api.app:app --port 8000

Endpoints (see docs/api.md): /healthz, /v1/turn, /v1/show-answer, /v1/approve, /v1/stt,
/v1/session/{id}, /v1/metrics. Everything under /v1 honors API keys and rate limits.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langgraph.types import Command

from codebuddy.agent.deps import Deps
from codebuddy.agent.graph import build_graph, new_turn_id, run_turn
from codebuddy.api.security import (
    LearnerTokens,
    PendingApprovals,
    check_api_key,
    enforce_rate_limit,
    parse_keys,
)
from codebuddy.config import Settings, get_settings
from codebuddy.memory.store import LearnerMemory
from codebuddy.pedagogy.judge import LeakJudge, maybe_judge
from codebuddy.schemas import (
    LEARNER_TOKEN,
    ApproveRequest,
    Mode,
    ShowAnswerRequest,
    TurnRequest,
)
from codebuddy.stt.transcribe import TranscriptionError

log = logging.getLogger("codebuddy.api")

SHOW_ANSWER_MESSAGE = "Show me the full answer."
AUDIO_TYPES = ("audio/", "video/webm", "application/octet-stream")
SHUTDOWN_DRAIN_S = 5.0  # how long shutdown waits for background work such as memory writes


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def drain_background(d: Deps) -> None:
    """Let outstanding background tasks finish before resources close; cancel stragglers."""
    if not d.background:
        return
    _, pending = await asyncio.wait(set(d.background), timeout=SHUTDOWN_DRAIN_S)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
        log.warning("cancelled %d background task(s) at shutdown", len(pending))


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
                await drain_background(res.deps)
            finally:
                await res.stack.aclose()
        else:
            yield
            await drain_background(app.state.deps)

    app = FastAPI(title="CodeBuddy", version="0.2.0", lifespan=lifespan)
    app.state.background = set()  # keeps references to fire-and-forget tasks

    def _install(app: FastAPI, d: Deps, kind: str, stt: Any, jdg: Any, saver: Any) -> None:
        app.state.deps, app.state.cache_kind = d, kind
        app.state.speech, app.state.judge = stt, jdg
        app.state.graph = build_graph(d, saver)
        app.state.pending = PendingApprovals(d.cache)
        app.state.tokens = None
        if d.memory:
            secret = d.settings.memory_secret.encode()
            if not secret:
                log.warning(
                    "CODEBUDDY_MEMORY_SECRET is not set; using a random secret, so learner "
                    "tokens stop working after a restart"
                )
                secret = secrets.token_bytes(32)
            app.state.tokens = LearnerTokens(secret)

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

    async def guard(request: Request) -> str | None:
        """Authenticate, then rate limit. Runs before every /v1 route. Returns the API key."""
        d = current()
        key = check_api_key(request, d.settings)
        await enforce_rate_limit(request, d.settings, d.cache, d.metrics, key)
        return key

    def verified_learner(token: str, key: str | None) -> str:
        learner_id = app.state.tokens.verify(token, key)
        if learner_id is None:
            raise HTTPException(403, "Invalid learner token")
        return learner_id

    async def turn_learner(session_id: str, token: str | None, key: str | None) -> str | None:
        """The verified learner id for a turn (None without memory). Checked before streaming."""
        if not current().memory:
            return None
        learner_id = verified_learner(token, key) if token else None
        bound = (await current().sessions.load(session_id)).learner_id
        if bound and not (
            learner_id and secrets.compare_digest(bound.encode(), learner_id.encode())
        ):
            raise HTTPException(409, "This session belongs to another learner")
        return learner_id

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
        if learner_id:
            inputs["learner_id"] = learner_id
        return run_turn(app.state.graph, inputs, new_turn_id())

    @app.post("/v1/turn")
    async def turn(req: TurnRequest, key: str | None = Depends(guard)):
        if not req.message.strip():
            raise HTTPException(422, "message must not be empty")
        learner_id = await turn_learner(req.session_id, req.learner_id, key)
        events = turn_events(req.session_id, req.message, req.code, req.language, learner_id)
        return stream_response(events, req.session_id, req.code)

    @app.post("/v1/show-answer")
    async def show_answer(req: ShowAnswerRequest, key: str | None = Depends(guard)):
        learner_id = await turn_learner(req.session_id, req.learner_id, key)
        events = turn_events(
            req.session_id, SHOW_ANSWER_MESSAGE, req.code, req.language, learner_id
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

    # The token travels in a header so it stays out of request paths and access logs.
    LearnerToken = Header(alias="X-Learner-Token", pattern=LEARNER_TOKEN)

    def memory_store() -> LearnerMemory:
        if (memory := current().memory) is None:
            raise HTTPException(503, "Long-term memory is not enabled")
        return memory

    @app.post("/v1/memory/learners")
    async def memory_new_learner(key: str | None = Depends(guard)):
        memory_store()
        return {"learner_token": app.state.tokens.issue(key)}

    @app.get("/v1/memory")
    async def memory_list(learner_token: str = LearnerToken, key: str | None = Depends(guard)):
        memory = memory_store()
        items = await memory.all(verified_learner(learner_token, key))
        return {
            "items": [
                {"kind": i.kind.value, "text": i.text, "created_at": i.created_at} for i in items
            ]
        }

    @app.delete("/v1/memory")
    async def memory_forget(learner_token: str = LearnerToken, key: str | None = Depends(guard)):
        memory = memory_store()
        return {"deleted": await memory.forget(verified_learner(learner_token, key))}

    return app


app = create_app()
