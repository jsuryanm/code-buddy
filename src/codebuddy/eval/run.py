"""Offline evals for the pedagogy rules and retrieval (spec 16).

    uv run python -m codebuddy.eval.run            # fake models, no keys, deterministic
    uv run python -m codebuddy.eval.run --json     # machine-readable output

Metrics (fake mode checks the machinery; they are not a quality score for a real model):
  leak_rate           share of hint-level replies that still contain code after the guard
  guard_trigger_rate  share of scripted "leaky" replies the guard stopped (should be 100%)
  pattern_recall      bug patterns the static analysis found
  escalation_ok       the answer is offered after three hints and never revealed unasked
  fix_detection       fixed code gets a confirmation; "I fixed it" with unchanged code does not
  retrieval_recall    queries whose expected text appears in the top results (tutor query path)
Exit code is 1 when a threshold fails, so CI can gate on it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

from langchain_core.embeddings import DeterministicFakeEmbedding
from qdrant_client import QdrantClient

from codebuddy.agent.code_analysis import analyze
from codebuddy.agent.deps import Deps, HeuristicClassifier
from codebuddy.agent.graph import build_graph, run_turn
from codebuddy.cache.layers import AnswerCache, SessionStore
from codebuddy.cache.memory import InMemoryCache
from codebuddy.config import Settings
from codebuddy.llm import Tiers
from codebuddy.pedagogy.guard import LeakDetected, StreamGuard
from codebuddy.pedagogy.quiz import BANK
from codebuddy.rag.fakes import HashSparse, ScriptedChat
from codebuddy.rag.ingest import ingest_file
from codebuddy.rag.manifest import Manifest
from codebuddy.rag.query import build_query, rrf_merge
from codebuddy.rag.retrieve import Retriever
from codebuddy.rag.store import get_store

GOLDEN = Path(__file__).parent / "golden"
SAMPLE = Path(__file__).parents[3] / "data" / "sample"
THRESHOLDS = {
    "leak_rate": ("<=", 0.02),
    "guard_trigger_rate": (">=", 1.0),
    "pattern_recall": (">=", 1.0),
    "escalation_ok": (">=", 1.0),
    "fix_detection": (">=", 1.0),
    "retrieval_recall": (">=", 0.75),
}


def _load(name: str) -> list[dict]:
    return [json.loads(line) for line in (GOLDEN / name).read_text().splitlines() if line.strip()]


def _contains_code(text: str) -> bool:
    guard = StreamGuard(enforce=True)
    try:
        guard.feed(text)
        guard.flush()
    except LeakDetected:
        return True
    return False


def _offline_deps(replies: list[str]) -> tuple[Deps, ScriptedChat]:
    settings = Settings(
        _env_file=None,
        model_fast="f",
        model_standard="s",
        model_heavy="h",
        relevance_threshold=0.0,
        qdrant_path=tempfile.mkdtemp(),
    )
    embeddings, sparse, client = (
        DeterministicFakeEmbedding(size=32),
        HashSparse(),
        QdrantClient(":memory:"),
    )
    stores = {"fundamentals": get_store("fundamentals", client, embeddings, sparse, settings)}
    ingest_file(
        SAMPLE / "python_basics.md",
        corpus="fundamentals",
        store=stores["fundamentals"],
        manifest=Manifest(Path(settings.qdrant_path) / "m.json"),
        settings=settings,
        title="Sample Basics",
    )
    cache = InMemoryCache()
    standard = ScriptedChat(replies)
    deps = Deps(
        settings=settings,
        tiers=Tiers(fast=ScriptedChat(), standard=standard, heavy=ScriptedChat()),
        classifier=HeuristicClassifier(),
        retriever=Retriever(stores, settings, allowed={"fundamentals"}),
        sessions=SessionStore(cache, ttl=600),
        answers=AnswerCache(cache, ttl=600),
    )
    return deps, standard


async def _turns(graph, session: str, message: str, code: str | None) -> dict:
    events = [
        e async for e in run_turn(graph, {"session_id": session, "message": message, "code": code})
    ]
    return {
        "meta": next((e for e in events if e["type"] == "meta"), {}),
        "text": "".join(e["text"] for e in events if e["type"] == "token"),
        "final": next(e["state"] for e in events if e["type"] == "final"),
    }


async def evaluate() -> dict[str, float]:
    cases = _load("cases.jsonl")

    # 1. Leak guard: a model that tries to leak on every case must be stopped.
    leaks = triggered = total = 0
    for case in cases:
        deps, _ = _offline_deps([case["leaky_reply"]])
        out = await _turns(build_graph(deps), case["id"], case["message"], case["code"])
        total += 1
        triggered += bool(out["final"].get("guarded"))
        leaks += _contains_code(out["text"])

    # 2. Static analysis recall on labeled bugs.
    labeled = [c for c in cases if c["pattern"]]
    found = sum(c["pattern"] in analyze(c["code"]).patterns for c in labeled)

    # 3. Escalation: offer after three hints, never reveal without a request.
    deps, _ = _offline_deps([f"Think about step {i}?" for i in range(6)])
    graph = build_graph(deps)
    metas = []
    for i in range(5):
        code = cases[0]["code"] + f"# try {i}\n"
        metas.append((await _turns(graph, "esc", "still stuck", code))["meta"])
    escalation_ok = [m["offer_answer"] for m in metas] == [False, False, False, True, True] and all(
        m["mode"] == "hint" for m in metas
    )

    # 4. Fix detection: the first quiz snippet of each pattern, then its stored solution.
    fix_ok = 0
    for pattern, items in BANK.items():
        graph = build_graph(_offline_deps([])[0])
        await _turns(graph, pattern, "why is this wrong", items[0].snippet)
        claimed = await _turns(graph, pattern, "I fixed it, it works now", items[0].snippet)
        fixed = await _turns(graph, pattern, "is this right?", items[0].solution)
        fix_ok += claimed["meta"]["mode"] == "hint" and fixed["meta"]["mode"] == "confirm"

    # 5. Retrieval recall on the sample corpus, through the tutor's query path. A case with
    # `search_query` (what the classifier would resolve from `history`) also runs the fusion.
    deps, _ = _offline_deps([])
    queries = _load("retrieval.jsonl")
    hits = 0
    for q in queries:
        features = analyze(q.get("code"))
        chunks = (await deps.retriever.retrieve(build_query(q["query"], features))).chunks
        if q.get("search_query"):
            query = build_query(q["search_query"], features, q.get("concepts", []))
            second = await deps.retriever.retrieve(query)
            chunks = rrf_merge([chunks, second.chunks], deps.settings.rerank_top)
        hits += any(q["expect"].lower() in c.text.lower() for c in chunks)

    return {
        "leak_rate": leaks / total,
        "guard_trigger_rate": triggered / total,
        "pattern_recall": found / len(labeled),
        "escalation_ok": float(escalation_ok),
        "fix_detection": fix_ok / len(BANK),
        "retrieval_recall": hits / len(queries),
    }


def check(metrics: dict[str, float]) -> list[str]:
    failures = []
    for name, (op, limit) in THRESHOLDS.items():
        value = metrics[name]
        ok = value <= limit if op == "<=" else value >= limit
        if not ok:
            failures.append(f"{name}={value:.2f} (need {op} {limit})")
    return failures


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--json", action="store_true", help="print metrics as JSON")
    args = ap.parse_args(argv)
    metrics = asyncio.run(evaluate())
    failures = check(metrics)
    if args.json:
        print(json.dumps({"metrics": metrics, "failures": failures}, indent=2))
    else:
        for name, value in metrics.items():
            op, limit = THRESHOLDS[name]
            print(f"{name:20s} {value:5.2f}   (need {op} {limit})")
        print("PASS" if not failures else "FAIL: " + "; ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
