"""Graph nodes. Each takes the state and returns a partial state update.

Custom stream events (via LangGraph's stream writer):
    {"type": "meta", ...}   decision info, sent before the first token
    {"type": "token", "text": ...}   text already approved by the leak guard
    {"type": "step", "key", "label", "status", "detail"}   progress shown to the learner
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
from codebuddy.agent.steps import emit_step, short_title
from codebuddy.cache import keys
from codebuddy.cache.layers import CachedAnswer, is_answer_cacheable
from codebuddy.memory.types import Episode
from codebuddy.pedagogy.frustration import detect_signals
from codebuddy.pedagogy.guard import LeakDetected, StreamGuard
from codebuddy.pedagogy.policy import SHOW_AFTER_HINTS, decide_mode, fixed_it, shape
from codebuddy.pedagogy.quiz import advance, quiz_meta
from codebuddy.pedagogy.templates import fallback_text, system_prompt, user_prompt
from codebuddy.rag.query import build_query, rrf_merge
from codebuddy.rag.retrieve import RetrievalResult
from codebuddy.schemas import Citation, Decision, HintLevel, Intent, Mode
from codebuddy.tools.policy import decide_permission

log = logging.getLogger("codebuddy.agent")

MAX_MESSAGE = 4000
MAX_CODE = 8000
HISTORY_TURNS = 6
HISTORY_CHARS = 500
LOCK_WAIT_SECONDS = 1.5


def _text(chunk) -> str:
    content = chunk.content
    if isinstance(content, str):
        return content
    return "".join(p.get("text", "") for p in content if isinstance(p, dict))


def submission_hash(code: str) -> str:
    return hashlib.sha1(keys.normalize(code).encode()).hexdigest()


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


def _ignore_result(task: asyncio.Task) -> None:
    """A background search we stopped waiting for: read its outcome so nothing is reported."""
    if not task.cancelled():
        task.exception()


class TutorNodes:
    def __init__(self, deps: Deps):
        self.d = deps

    # -- input ---------------------------------------------------------------------

    async def load_state(self, state: TutorState) -> dict:
        progress = await self.d.sessions.load(state["session_id"])
        message = state["message"].strip()[:MAX_MESSAGE]
        code = (state.get("code") or "").strip()[:MAX_CODE]
        changed = False
        if code:
            digest = submission_hash(code)
            if digest == progress.last_submission_hash:
                progress.repeated_submissions += 1
            else:
                changed = True
                progress.repeated_submissions = 0
                progress.last_submission_hash = digest
        update = {
            "progress": progress,
            "message": message,
            "code": code or None,
            "code_changed": changed,
        }
        learner_id = state.get("learner_id")
        if learner_id and progress.learner_id is None:
            progress.learner_id = learner_id  # the API refuses other learners from now on
            progress.history = []  # turns made before binding never reach this memory
        elif progress.learner_id is not None and progress.learner_id != learner_id:
            # Lost a race with the API check (another learner, or none): the turn still gets a
            # reply, but it neither reads nor adds to the bound learner's history or memory.
            log.warning("session is bound to another learner; memory and history are off")
            update["learner_id"] = None
            update["foreign"] = True
        return update

    async def analyze_code(self, state: TutorState) -> dict:
        lang = state.get("language", "python")
        if not state.get("code"):
            return {"features": analyze(None)}
        writer = get_stream_writer()
        emit_step(writer, "analyze_code", "running")
        features = analyze(state.get("code") if lang == "python" else None)
        emit_step(writer, "analyze_code", "done")
        return {"features": features}

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
        if state.get("code") or state["progress"].quiz:  # a quiz turn is graded, never cached
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

    @staticmethod
    def _quiz_step(state: TutorState):
        """The grading of a running quiz for this turn, or None when it is not a quiz answer."""
        quiz = state["progress"].quiz
        if quiz is None:
            return None
        return advance(
            quiz, state["message"], state.get("features"), state.get("code"), state.get("action")
        )

    def route_after_cache(self, state: TutorState):
        if state.get("cached_reply"):
            return "emit_cached"
        if self._quiz_step(state) is not None:
            return "policy"  # a quiz answer is graded by code: no classifier, no retrieval
        return ["classify", "retrieve", "recall_memory"]

    async def emit_cached(self, state: TutorState) -> dict:
        writer = get_stream_writer()
        progress = state["progress"]
        decision = Decision(
            mode=Mode.EXPLAIN,
            can_show_answer=progress.hints_given >= SHOW_AFTER_HINTS,
            reasons=["answer cache hit"],
        )
        emit_step(writer, "check_cache", "done")
        writer(self._meta(decision, progress.stage.value, cached=True))
        writer({"type": "token", "text": state["cached_reply"]})
        return {"decision": decision, "reply": state["cached_reply"]}

    # -- understanding ---------------------------------------------------------------

    async def classify(self, state: TutorState) -> dict:
        progress = state["progress"]
        writer = get_stream_writer()
        emit_step(writer, "classify", "running")
        seen = progress.model_copy(update={"history": []}) if state.get("foreign") else progress
        cls = await self.d.classifier.classify(state["message"], state.get("code"), seen)
        emit_step(writer, "classify", "done")
        if cls.intent is Intent.PROBLEM_START:  # new problem: restart the ladder
            progress.hints_given = 0
            progress.started_at = 0.0
            progress.repeated_submissions = 0
            progress.quiz_offer = ""  # a quiz on the last bug is no longer on offer
        return {"classification": cls, "progress": progress}

    def _query(self, text: str, state: TutorState, concepts: list[str] | None = None) -> str:
        return build_query(text, state.get("features"), concepts or [])

    async def retrieve(self, state: TutorState) -> dict:
        writer = get_stream_writer()
        emit_step(writer, "retrieve", "running")
        try:
            result = await self.d.retriever.retrieve(self._query(state["message"], state))
        except Exception:
            log.warning("retrieval failed", exc_info=True)
            result = RetrievalResult([], grounded=False)
        n = len(result.chunks)
        title = short_title(result.chunks[0].source) if n else ""
        emit_step(
            writer,
            "retrieve",
            "done",
            f"{n} passage{'' if n == 1 else 's'}",
            label=f"Searching {title}" if title else None,
        )
        return {"retrieval": result}

    async def recall_memory(self, state: TutorState) -> dict:
        learner_id = state.get("learner_id")
        if not (self.d.memory and learner_id):
            return {"memories": []}
        s = self.d.settings
        writer = get_stream_writer()
        emit_step(writer, "recall_memory", "running")
        try:
            items = await asyncio.wait_for(
                self.d.memory.recall(learner_id, state["message"], s.memory_recall_limit),
                timeout=s.memory_recall_timeout_s,
            )
        except Exception as exc:  # no traceback: it can quote the learner id
            log.warning("memory recall failed (%s)", type(exc).__name__)
            await self.d.metrics.incr("memory_failures")
            emit_step(writer, "recall_memory", "done")
            return {"memories": []}
        await self.d.metrics.incr("memory_recalls")
        emit_step(writer, "recall_memory", "done")
        return {"memories": items}

    async def refine_retrieval(self, state: TutorState) -> dict:
        """Follow-ups ("and why is that?") and vague messages retrieve badly on their own. Search
        again with the classifier's standalone query and concepts, then fuse both result lists
        (reciprocal rank fusion) so neither query's best passages are lost. Skipped when the
        second query would be the same as the first, and for foreign turns."""
        cls = state["classification"]
        if state.get("foreign") or not cls.search_query.strip():
            return {}
        query = self._query(cls.search_query.strip(), state, cls.concepts)
        if keys.normalize(query) == keys.normalize(self._query(state["message"], state)):
            return {}
        # Shielded and tracked: on a timeout the search keeps running in the background, so it
        # still warms the L3 and L4 caches, and shutdown waits for it.
        task = self.d.spawn(self.d.retriever.retrieve(query))
        try:
            second = await asyncio.wait_for(
                asyncio.shield(task), timeout=self.d.settings.refine_timeout_s
            )
        except TimeoutError:
            task.add_done_callback(_ignore_result)
            log.debug("refined retrieval timed out, keeping the first result")
            await self.d.metrics.incr("refine_timeouts")
            return {}
        except Exception:
            log.warning("refined retrieval failed", exc_info=True)
            return {}
        if not second.chunks:
            return {}
        first = state["retrieval"]
        chunks = rrf_merge([first.chunks, second.chunks], self.d.settings.rerank_top)
        best = max(c.score for c in chunks)
        grounded = best >= self.d.settings.relevance_threshold
        cache_hit = first.cache_hit and second.cache_hit
        return {"retrieval": RetrievalResult(chunks, grounded, cache_hit=cache_hit)}

    async def policy(self, state: TutorState) -> dict:
        s = self.d.settings
        progress = state["progress"]
        writer = get_stream_writer()
        emit_step(writer, "policy", "running")
        features = state.get("features")
        update: dict = {"progress": progress}
        step = self._quiz_step(state)
        if step is not None:
            # A quiz answer: graded by code. Only a first wrong try reaches the model, as one
            # guarded level-0 hint; everything else is written by code (pedagogy/quiz.py).
            update["quiz_prior"] = progress.quiz  # restored if the one hint degrades
            progress.quiz = step.quiz
            update |= {"quiz_turn": True, "scripted": step.text, "quiz_code": step.code}
            if step.text is None:
                decision = Decision(
                    mode=Mode.HINT, level=HintLevel.DIAGNOSE, reasons=["quiz: one hint"]
                )
            else:
                decision = Decision(mode=Mode.QUIZ, reasons=["quiz: graded"])
        else:
            changed = bool(state.get("code_changed"))
            if changed and features and features.patterns:
                progress.quiz_offer = ""  # new code with a new bug: the old quiz offer is gone
            fixed = fixed_it(progress, features, changed)
            # After a fix, the learner's answer to "why does it work?" comes with the same code.
            after_fix = bool(progress.quiz_offer) and progress.quiz is None and not changed
            decision = decide_mode(
                state["classification"].intent,
                progress,
                detect_signals(state["message"], progress, fixed=fixed, after_fix=after_fix),
                self.d.clock(),
                max_turns=s.ladder_max_turns,
                max_seconds=s.ladder_max_seconds,
            )
        if progress.quiz is not None:
            decision.quiz, decision.can_show_answer = quiz_meta(progress.quiz), False
        emit_step(writer, "policy", "done", self._decision_detail(decision))
        plan = [] if step is not None else self._plan_tools(state, decision)  # no runs in a quiz
        update |= {"decision": decision, "tool_plan": plan}
        return update

    @staticmethod
    def _decision_detail(decision: Decision) -> str:
        if decision.mode is Mode.HINT and decision.level is not None:
            return f"Hint {int(decision.level) + 1}"
        return {
            Mode.EXPLAIN: "Explanation",
            Mode.REVEAL: "Full answer",
            Mode.REDIRECT: "Staying on programming",
            Mode.CONFIRM: "You fixed it",
            Mode.QUIZ: "Quiz",
        }.get(decision.mode, "")

    # -- tools and human approval ----------------------------------------------------

    def _plan_tools(self, state: TutorState, decision: Decision) -> list[str]:
        """Which tools to use this turn. Chosen by rules, not by the model."""
        features = state.get("features")
        if not (self.d.tools and state.get("code") and features and not features.parse_error):
            return []
        if state.get("language", "python") != "python" or state["progress"].quiz is not None:
            return []  # nothing runs during a quiz
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
        writer = get_stream_writer()
        emit_step(writer, "run_tools", "running")
        ran = False
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
            ran = True
            await self.d.metrics.incr("tool_runs")
            if name == "trace_python":
                update["runtime"] = result
            elif name == "suggest_cases":
                update["cases"] = result.get("cases", [])
        emit_step(writer, "run_tools", "done", "finished" if ran else "stopped")
        return update

    # -- generation ------------------------------------------------------------------

    def _tier(self, decision: Decision):
        t = self.d.tiers
        if decision.mode is Mode.REVEAL:
            return t.heavy
        if decision.mode is Mode.REDIRECT:
            return t.fast
        return t.standard

    def _max_tokens(self, decision: Decision) -> int:
        s = self.d.settings
        return {
            Mode.HINT: s.max_tokens_hint,
            Mode.CONFIRM: s.max_tokens_hint,
            Mode.EXPLAIN: s.max_tokens_explain,
            Mode.REVEAL: s.max_tokens_reveal,
            Mode.REDIRECT: s.max_tokens_redirect,
        }[decision.mode]

    @staticmethod
    def _meta(
        decision: Decision, stage: str, cached: bool = False, quiz_code: str | None = None
    ) -> dict:
        return {
            "type": "meta",
            "mode": decision.mode.value,
            "level": None if decision.level is None else int(decision.level),
            "stage": stage,
            "can_show_answer": decision.can_show_answer,
            "offer_answer": decision.offer_answer,
            "offer_quiz": decision.offer_quiz,
            "quiz_concept": decision.quiz_concept,
            "quiz": decision.quiz,
            "quiz_code": quiz_code,  # a new quiz question's snippet, for the code box
            "cached": cached,
        }

    async def generate(self, state: TutorState) -> dict:
        writer = get_stream_writer()
        decision: Decision = state["decision"]
        cls = state.get("classification")  # quiz answers skip classify and retrieval
        retrieval: RetrievalResult = state.get("retrieval") or RetrievalResult([], grounded=False)
        progress = state["progress"]
        stage = cls.stage if cls else progress.stage
        features = state.get("features")
        emit_step(writer, "generate", "running")
        writer(self._meta(decision, stage.value, quiz_code=state.get("quiz_code")))
        if (scripted := state.get("scripted")) is not None:
            writer({"type": "token", "text": scripted})  # quiz text written by code, no model
            return {"reply": scripted, "citations": [], "guarded": False, "degraded": False}

        context = [(i + 1, c.text[:1200]) for i, c in enumerate(retrieval.chunks)]
        findings: list[str] = []
        if features:
            findings += [f"{PATTERNS[p].id}: {PATTERNS[p].symptom}" for p in features.patterns]
            if features.parse_error:
                findings.append(f"syntax error: {features.parse_error}")
        if decision.mode is Mode.CONFIRM:
            findings += [f"fixed now: {PATTERNS[p].symptom}" for p in progress.last_patterns]
        findings += runtime_findings(state.get("runtime"), state.get("cases") or [])
        messages = [
            ("system", system_prompt(decision, stage)),
            (
                "human",
                user_prompt(
                    state["message"],
                    state.get("code"),
                    context,
                    findings,
                    [] if state.get("foreign") else progress.history,
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
            # Per-call kwarg: RunnableWithFallbacks passes it to every tier, so fallbacks keep it.
            cap = {"max_completion_tokens": self._max_tokens(decision)}
            async for chunk in self._tier(decision).astream(messages, **cap):
                emit(guard.feed(_text(chunk)))
            emit(guard.flush())
            if not parts:  # e.g. a reasoning model spent the whole token cap on reasoning
                raise RuntimeError("the model returned an empty reply")
        except LeakDetected as leak:
            log.info("leak guard stopped a reply: %s", leak.reason)
            guarded = True
            await self.d.metrics.incr("guard_stops")
            concept = cls.concepts[0] if cls and cls.concepts else None
            emit(("\n\n" if parts else "") + fallback_text(stage, concept))
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
        if state.get("quiz_turn"):
            return  # quiz answers are practice, not progress on the learner's problem
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
        except Exception as exc:  # no traceback: it can quote the learner id
            log.warning("memory write failed (%s)", type(exc).__name__)
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
        if state.get("quiz_turn"):
            # The ladder stays reset during a quiz; the quiz has its own one hint. A hint that
            # degraded (model unavailable) does not use up the learner's try.
            if state.get("degraded"):
                progress.quiz = state.get("quiz_prior")
        elif decision.mode is Mode.HINT:
            progress.hints_given += 1
            progress.started_at = progress.started_at or self.d.clock()
        elif decision.mode in (Mode.REVEAL, Mode.CONFIRM):
            if decision.mode is Mode.REVEAL:
                progress.reveals += 1
            else:  # solved: a quiz on that bug is now on offer
                progress.quiz_offer = next(iter(progress.last_patterns), progress.quiz_offer)
            progress.hints_given = 0
            progress.started_at = 0.0
            progress.repeated_submissions = 0
        features = state.get("features")
        if (
            state.get("code")
            and features
            and not features.parse_error
            and not state.get("quiz_turn")
        ):
            progress.last_patterns = features.patterns  # what the next fix is judged against
            progress.last_shape = shape(features) if features.patterns else None
        if decision.mode is Mode.REVEAL:  # pasting the revealed solution is not a fix
            progress.last_patterns, progress.last_shape = [], None

        at = str(self.d.clock())  # lets a later write skip turns from before Forget me
        if not state.get("foreign"):
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
