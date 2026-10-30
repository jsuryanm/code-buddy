"""Graph nodes. Each takes the state and returns a partial state update.

Custom stream events (via LangGraph's stream writer):
    {"type": "meta", ...}   decision info, sent before the first token
    {"type": "token", "text": ...}   text already approved by the leak guard
"""

from __future__ import annotations

import asyncio
import hashlib
import logging

from langgraph.config import get_stream_writer
from langgraph.types import interrupt

from codebuddy.agent.code_analysis import PATTERNS, analyze
from codebuddy.agent.deps import Deps
from codebuddy.agent.state import TutorState
from codebuddy.cache import keys
from codebuddy.cache.layers import CachedAnswer, is_answer_cacheable
from codebuddy.memory.types import Episode
from codebuddy.pedagogy.frustration import detect_signals
from codebuddy.pedagogy.guard import LeakDetected, StreamGuard
from codebuddy.pedagogy.policy import decide_mode
from codebuddy.pedagogy.templates import fallback_text, system_prompt, user_prompt
from codebuddy.rag.retrieve import RetrievalResult
from codebuddy.schemas import Citation, Decision, HintLevel, Intent, Mode
from codebuddy.tools.policy import decide_permission

log = logging.getLogger("codebuddy.agent")

MAX_MESSAGE = 4000
MAX_CODE = 8000
HISTORY_TURNS = 6
HISTORY_CHARS = 500
LOCK_WAIT_SECONDS = 1.5
SHORT_FOLLOWUP_WORDS = 8  # short messages with history are rewritten before retrieval


def _text(chunk) -> str:
    content = chunk.content
    if isinstance(content, str):
        return content
    return "".join(p.get("text", "") for p in content if isinstance(p, dict))


def runtime_findings(runtime: dict | None, cases: list[dict]) -> list[str]:
    """Private notes for the model from running the code and from suggested cases."""
    notes: list[str] = []
    if runtime and runtime.get("ran"):
        err = runtime.get("error")
        if err:
            where = f" at line {err['line']}" if err.get("line") else ""
            notes.append(f"when the code was run: {err['type']}: {err['message']}{where}")
        else:
            notes.append(
                f"the code ran without error; output was {runtime.get('stdout', '')[:200]!r}"
            )
        trace = runtime.get("trace") or []
        if trace:
            last = trace[-1]
            shown = ", ".join(f"{k}={v}" for k, v in list(last["vars"].items())[:6])
            notes.append(f"variables at the last traced step (line {last['line']}): {shown}")
    for case in cases[:3]:
        if case.get("try_these"):
            notes.append(
                f"small inputs the learner could work by hand for {case['function']}(): "
                + "; ".join(case["try_these"][:4])
            )
    return notes


class TutorNodes:
    def __init__(self, deps: Deps):
        self.d = deps

    # -- input ---------------------------------------------------------------------

    async def load_state(self, state: TutorState) -> dict:
        progress = await self.d.sessions.load(state["session_id"])
        message = state["message"].strip()[:MAX_MESSAGE]
        code = (state.get("code") or "").strip()[:MAX_CODE]
        if code:
            digest = hashlib.sha1(keys.normalize(code).encode()).hexdigest()
            if digest == progress.last_submission_hash:
                progress.repeated_submissions += 1
            else:
                progress.repeated_submissions = 0
                progress.last_submission_hash = digest
        update = {"progress": progress, "message": message, "code": code or None}
        if learner_id := state.get("learner_id"):
            if progress.learner_id is None:
                progress.learner_id = learner_id  # the API refuses other learners from now on
                progress.history = []  # turns made before binding never reach this memory
            elif progress.learner_id != learner_id:  # lost a race with the API check
                log.warning("session is bound to another learner; memory is off for this turn")
                update["learner_id"] = None
        return update

    async def analyze_code(self, state: TutorState) -> dict:
        lang = state.get("language", "python")
        return {"features": analyze(state.get("code") if lang == "python" else None)}

    async def _semantic_lookup(self, message: str) -> CachedAnswer | None:
        if not (self.d.semantic and self.d.semantic.enabled and self.d.embeddings):
            return None
        vector = await self.d.embeddings.aembed_query(message)  # also warms the L3 cache
        near = await self.d.semantic.find(vector)
        hit = await self.d.answers.get(near) if near else None
        if hit:
            await self.d.metrics.incr("semantic_hits")
        return hit

    async def check_cache(self, state: TutorState) -> dict:
        """L1 (exact) then optional L2 (semantic). Only concept answers without code are stored."""
        if state.get("code"):
            return {"cache_key": None}
        if self.d.memory and state.get("learner_id"):
            return {"cache_key": None}  # personalized answers must not be shared or stored
        s = self.d.settings
        key = keys.answer_key(
            state["message"],
            mode=Mode.EXPLAIN.value,
            hint_level=None,
            learner_level="beginner",
            index_version=s.index_version,
            prompt_version=s.prompt_version,
            model_id=s.model_standard or "",
        )
        hit = await self.d.answers.get(key)
        if hit is None:
            hit = await self._semantic_lookup(state["message"])
        locked = False
        if hit is None:
            if await self.d.answers.try_lock(key):
                locked = True
            else:
                hit = await self.d.answers.wait_for(key, LOCK_WAIT_SECONDS)
        if hit:
            await self.d.metrics.incr("cache_hits")
            return {
                "cache_key": key,
                "cached_reply": hit.text,
                "citations": [Citation(**c) for c in hit.citations],
                "cache_hit": True,
            }
        return {"cache_key": key, "cache_locked": locked}

    def route_after_cache(self, state: TutorState):
        return (
            "emit_cached"
            if state.get("cached_reply")
            else ["classify", "retrieve", "recall_memory"]
        )

    async def emit_cached(self, state: TutorState) -> dict:
        writer = get_stream_writer()
        progress = state["progress"]
        decision = Decision(
            mode=Mode.EXPLAIN,
            can_show_answer=progress.hints_given >= 1,
            reasons=["answer cache hit"],
        )
        writer(self._meta(decision, progress.stage.value, cached=True))
        writer({"type": "token", "text": state["cached_reply"]})
        return {"decision": decision, "reply": state["cached_reply"]}

    # -- understanding ---------------------------------------------------------------

    async def classify(self, state: TutorState) -> dict:
        progress = state["progress"]
        cls = await self.d.classifier.classify(state["message"], state.get("code"), progress)
        if cls.intent is Intent.PROBLEM_START:  # new problem: restart the ladder
            progress.hints_given = 0
            progress.started_at = 0.0
            progress.repeated_submissions = 0
        return {"classification": cls, "progress": progress}

    def _query(self, text: str, state: TutorState) -> str:
        features = state.get("features")
        concepts = [PATTERNS[p].concept for p in (features.patterns if features else [])]
        return " ".join([text, *concepts])

    async def retrieve(self, state: TutorState) -> dict:
        try:
            result = await self.d.retriever.retrieve(self._query(state["message"], state))
        except Exception:
            log.warning("retrieval failed", exc_info=True)
            result = RetrievalResult([], grounded=False)
        return {"retrieval": result}

    async def recall_memory(self, state: TutorState) -> dict:
        learner_id = state.get("learner_id")
        if not (self.d.memory and learner_id):
            return {"memories": []}
        s = self.d.settings
        try:
            items = await asyncio.wait_for(
                self.d.memory.recall(learner_id, state["message"], s.memory_recall_limit),
                timeout=s.memory_recall_timeout_s,
            )
        except Exception:
            log.warning("memory recall failed", exc_info=True)
            await self.d.metrics.incr("memory_failures")
            return {"memories": []}
        await self.d.metrics.incr("memory_recalls")
        return {"memories": items}

    async def refine_retrieval(self, state: TutorState) -> dict:
        """Short follow-ups ("and what about that?") retrieve badly. Re-run retrieval with the
        classifier's standalone query, only in that case, so most turns pay nothing."""
        cls = state["classification"]
        message = state["message"]
        query = cls.search_query.strip()
        short = len(message.split()) <= SHORT_FOLLOWUP_WORDS
        if not (short and state["progress"].history and query):
            return {}
        if keys.normalize(query) == keys.normalize(message):
            return {}
        try:
            result = await self.d.retriever.retrieve(self._query(query, state))
        except Exception:
            log.warning("refined retrieval failed", exc_info=True)
            return {}
        return {"retrieval": result} if result.chunks else {}

    async def policy(self, state: TutorState) -> dict:
        s = self.d.settings
        progress = state["progress"]
        decision = decide_mode(
            state["classification"].intent,
            progress,
            detect_signals(state["message"], progress),
            self.d.clock(),
            max_turns=s.ladder_max_turns,
            max_seconds=s.ladder_max_seconds,
        )
        return {"decision": decision, "tool_plan": self._plan_tools(state, decision)}

    # -- tools and human approval ----------------------------------------------------

    def _plan_tools(self, state: TutorState, decision: Decision) -> list[str]:
        """Which tools to use this turn. Chosen by rules, not by the model."""
        features = state.get("features")
        if not (self.d.tools and state.get("code") and features and not features.parse_error):
            return []
        if state.get("language", "python") != "python":
            return []
        intent = state["classification"].intent
        if intent is Intent.DEBUG_HELP and decision.mode is Mode.HINT:
            return ["trace_python"]
        if intent is Intent.PROBLEM_START:
            return ["suggest_cases"]
        return []

    def route_tools(self, state: TutorState) -> str:
        plan = state.get("tool_plan") or []
        if not plan:
            return "generate"
        verdicts = {decide_permission(t, state["progress"].run_permission) for t in plan}
        if "ask" in verdicts:
            return "approve_run"
        return "run_tools" if "run" in verdicts else "generate"

    async def approve_run(self, state: TutorState) -> dict:
        """Pause for the learner's permission to run their code (human in the loop).

        Resumed with {"approve": bool, "remember": bool}. This node holds nothing but the
        interrupt, because LangGraph re-runs the whole node on resume.
        """
        answer = interrupt(
            {
                "type": "approval",
                "tool": "trace_python",
                "message": "Run your code in a safe sandbox to see what happens?",
                "code": (state.get("code") or "")[:600],
            }
        )
        approved = bool(answer.get("approve"))
        progress = state["progress"]
        if answer.get("remember", True):
            progress.run_permission = "allow" if approved else "deny"
        return {"progress": progress, "approved": approved}

    def route_after_approval(self, state: TutorState) -> str:
        return "run_tools" if state.get("approved") else "generate"

    async def run_tools(self, state: TutorState) -> dict:
        update: dict = {}
        timeout = self.d.settings.sandbox_timeout_s + 5
        for name in state.get("tool_plan") or []:
            if decide_permission(name, state["progress"].run_permission) != "run":
                continue
            try:
                result = await asyncio.wait_for(
                    self.d.tools.call(name, code=state["code"]), timeout=timeout
                )
            except Exception:
                log.warning("tool %s failed", name, exc_info=True)
                continue
            await self.d.metrics.incr("tool_runs")
            if name == "trace_python":
                update["runtime"] = result
            elif name == "suggest_cases":
                update["cases"] = result.get("cases", [])
        return update

    # -- generation ------------------------------------------------------------------

    def _tier(self, decision: Decision):
        t = self.d.tiers
        if decision.mode is Mode.REVEAL:
            return t.heavy
        if decision.mode is Mode.REDIRECT:
            return t.fast
        return t.standard

    @staticmethod
    def _meta(decision: Decision, stage: str, cached: bool = False) -> dict:
        return {
            "type": "meta",
            "mode": decision.mode.value,
            "level": None if decision.level is None else int(decision.level),
            "stage": stage,
            "can_show_answer": decision.can_show_answer,
            "offer_answer": decision.offer_answer,
            "cached": cached,
        }

    async def generate(self, state: TutorState) -> dict:
        writer = get_stream_writer()
        decision: Decision = state["decision"]
        cls = state["classification"]
        retrieval: RetrievalResult = state["retrieval"]
        progress = state["progress"]
        features = state.get("features")
        writer(self._meta(decision, cls.stage.value))

        context = [(i + 1, c.text[:1200]) for i, c in enumerate(retrieval.chunks)]
        findings: list[str] = []
        if features:
            findings += [f"{PATTERNS[p].id}: {PATTERNS[p].symptom}" for p in features.patterns]
            if features.parse_error:
                findings.append(f"syntax error: {features.parse_error}")
        findings += runtime_findings(state.get("runtime"), state.get("cases") or [])
        messages = [
            ("system", system_prompt(decision, cls.stage)),
            (
                "human",
                user_prompt(
                    state["message"],
                    state.get("code"),
                    context,
                    findings,
                    progress.history,
                    state.get("memories"),
                    self.d.settings.memory_recall_limit,
                ),
            ),
        ]

        enforce = decision.mode is Mode.HINT and (decision.level or 0) < HintLevel.REVEAL
        guard = StreamGuard(enforce=enforce, allow_pseudocode=decision.level is HintLevel.SCAFFOLD)
        parts: list[str] = []
        guarded = degraded = False

        def emit(text: str) -> None:
            if text:
                parts.append(text)
                writer({"type": "token", "text": text})

        try:
            async for chunk in self._tier(decision).astream(messages):
                emit(guard.feed(_text(chunk)))
            emit(guard.flush())
        except LeakDetected as leak:
            log.info("leak guard stopped a reply: %s", leak.reason)
            guarded = True
            await self.d.metrics.incr("guard_stops")
            concept = cls.concepts[0] if cls.concepts else None
            emit(("\n\n" if parts else "") + fallback_text(cls.stage, concept))
        except Exception:
            log.warning("generation failed, degrading", exc_info=True)
            degraded = True
            await self.d.metrics.incr("degraded")
            snippet = retrieval.chunks[0].text[:600] if retrieval.chunks else ""
            emit(
                ("\n\n" if parts else "")
                + "I can't reach the tutor model right now, so here is what the course "
                "material says instead."
                + (f"\n\n{snippet}" if snippet else " Please try again in a moment.")
            )

        citations = [
            Citation(source=c.source, section=c.section, corpus=c.corpus) for c in retrieval.chunks
        ]
        return {
            "reply": "".join(parts),
            "citations": citations,
            "guarded": guarded,
            "degraded": degraded,
        }

    # -- output ----------------------------------------------------------------------

    async def _remember(
        self, state: TutorState, decision: Decision, progress, hints_before: int
    ) -> None:
        learner_id = state.get("learner_id")
        if not (self.d.memory and learner_id and progress.learner_id == learner_id):
            return
        every = self.d.settings.memory_write_every
        revealed = decision.mode is Mode.REVEAL
        if not (revealed or (decision.mode is Mode.HINT and progress.hints_given % every == 0)):
            return
        episode = Episode(
            state["session_id"],
            progress.stage.value,
            hints_before,
            "revealed" if revealed else "in_progress",
        )
        since = self.d.memory.generation(learner_id)  # a Forget from now on drops this write
        history = progress.history
        try:
            forgot = await self.d.cache.get(keys.forgot_key(learner_id))
        except Exception as exc:  # fail closed: without the marker, older turns might be re-written
            # No traceback: a cache error can quote the key, which holds the learner id.
            log.warning(
                "could not read forget marker (%s); skipping memory write", type(exc).__name__
            )
            await self.d.metrics.incr("memory_failures")
            return
        if forgot:
            # Turns from before Forget me stay in the session; never write them again.
            history = [h for h in history if float(h.get("at", 0)) > float(forgot)]
        self.d.spawn(self._write_memory(learner_id, history, episode, since))

    async def _write_memory(
        self, learner_id: str, history: list[dict], episode: Episode, since: int
    ) -> None:
        try:
            await self.d.memory.remember(learner_id, history, episode, since=since)
        except Exception:
            log.warning("memory write failed", exc_info=True)
            await self.d.metrics.incr("memory_failures")
        else:
            await self.d.metrics.incr("memory_writes")

    async def update_state(self, state: TutorState) -> dict:
        progress = state["progress"]
        decision: Decision = state["decision"]
        reply = state.get("reply", "")
        if cls := state.get("classification"):
            progress.stage = cls.stage

        had_history = bool(progress.history)  # the prompt depended on earlier turns
        hints_before = progress.hints_given
        if decision.mode is Mode.HINT:
            progress.hints_given += 1
            progress.started_at = progress.started_at or self.d.clock()
        elif decision.mode is Mode.REVEAL:
            progress.reveals += 1
            progress.hints_given = 0
            progress.started_at = 0.0
            progress.repeated_submissions = 0

        at = str(self.d.clock())  # lets a later write skip turns from before Forget me
        progress.history = [
            *progress.history,
            {"role": "learner", "text": state["message"][:HISTORY_CHARS], "at": at},
            {"role": "tutor", "text": reply[:HISTORY_CHARS], "at": at},
        ][-HISTORY_TURNS:]
        await self.d.sessions.save(progress)
        await self.d.metrics.incr("turns")
        await self._remember(state, decision, progress, hints_before)

        key = state.get("cache_key")
        retrieval = state.get("retrieval")
        if (
            key
            and not state.get("cache_hit")
            and not state.get("degraded")
            and not state.get("guarded")
            and not had_history  # the key ignores history, so only first-turn replies are shared
            and retrieval is not None
            and retrieval.grounded
            and is_answer_cacheable(decision, bool(state.get("code")))
        ):
            await self.d.answers.put(
                key,
                CachedAnswer(reply, [c.model_dump() for c in state.get("citations", [])]),
            )
            if self.d.semantic and self.d.semantic.enabled and self.d.embeddings:
                vector = await self.d.embeddings.aembed_query(state["message"])
                await self.d.semantic.add(vector, key)
        if key and state.get("cache_locked"):
            await self.d.answers.unlock(key)
        return {"progress": progress}
