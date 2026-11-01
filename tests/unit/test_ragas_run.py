import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from codebuddy.agent.nodes import PASSAGE_CHARS
from codebuddy.eval import ragas_run as rr
from codebuddy.rag.rerank import RetrievedChunk
from codebuddy.schemas import Decision, Mode

SAMPLE_TEXT = (Path(rr.SAMPLE) / "python_basics.md").read_text()


def _write(tmp_path, lines) -> Path:
    path = tmp_path / "golden.jsonl"
    path.write_text("\n".join(json.dumps(x) if isinstance(x, dict) else x for x in lines))
    return path


# -- dataset ---------------------------------------------------------------------------------


def test_golden_set_loads_and_every_section_exists_in_the_sample():
    items = rr.load_dataset(rr.DATASET)
    assert len(items) >= 20
    assert all(not it.get("auto_generated") for it in items)
    for it in items:
        assert f"# {it['expected_section']}" in SAMPLE_TEXT, it


@pytest.mark.parametrize(
    "lines, message",
    [
        ([], "no items"),
        (["not json"], "line 1"),
        ([{"question": "q"}], "reference"),
        ([{"question": " ", "reference": "r"}], "question"),
        ([{"question": "q", "reference": "r", "typo": 1}], "typo"),
        ([{"question": "q", "reference": "r", "auto_generated": "yes"}], "auto_generated"),
        ([{"question": "q", "reference": "r"}, {"question": "q", "reference": "s"}], "duplicate"),
    ],
)
def test_load_dataset_rejects_bad_files(tmp_path, lines, message):
    with pytest.raises(ValueError, match=message):
        rr.load_dataset(_write(tmp_path, lines))


def test_load_dataset_skips_blank_lines(tmp_path):
    path = _write(tmp_path, [{"question": "q", "reference": "r"}, "", "  "])
    assert rr.load_dataset(path) == [{"question": "q", "reference": "r"}]


# -- samples from a graph run ------------------------------------------------------------------


def _events(chunks, reply="An accumulator collects a result.", mode=Mode.EXPLAIN):
    final = {
        "retrieval": SimpleNamespace(chunks=chunks),
        "reply": reply,
        "decision": Decision(mode=mode),
    }
    return [
        (1.0, {"type": "step", "key": "retrieve", "status": "running"}),
        (1.2, {"type": "step", "key": "retrieve", "status": "done"}),
        (1.5, {"type": "step", "key": "generate", "status": "running"}),
        (1.6, {"type": "meta", "mode": "explain"}),
        (1.7, {"type": "token", "text": reply}),
        (2.5, {"type": "final", "state": final, "interrupt": None}),
    ]


def test_build_sample_takes_the_prompt_contexts_and_the_reply():
    long = "x" * (PASSAGE_CHARS + 50)
    chunks = [
        RetrievedChunk(long, 0.9, {"title": "Sample Basics", "section": "Basics › Accumulators"}),
        RetrievedChunk("short", 0.5, {"title": "Sample Basics", "section": "Basics › Loops"}),
    ]
    item = {"question": "What is an accumulator?", "reference": "r", "expected_section": "Loops"}
    s = rr.build_sample(item, _events(chunks), started=0.5)
    assert s.contexts == ["x" * PASSAGE_CHARS, "short"]
    assert s.response == "An accumulator collects a result."
    assert s.question == item["question"] and s.reference == "r"
    assert s.mode == "explain" and s.section_hit is True
    assert s.sources == [
        {"title": "Sample Basics", "section": "Basics › Accumulators"},
        {"title": "Sample Basics", "section": "Basics › Loops"},
    ]
    assert s.retrieval_ms == pytest.approx(500) and s.generate_ms == pytest.approx(1000)
    assert s.total_ms == pytest.approx(2000)


def test_build_sample_without_chunks_or_section():
    s = rr.build_sample({"question": "q", "reference": "r"}, _events([]), started=1.0)
    assert s.contexts == [] and s.section_hit is None


async def test_concept_classifier_pins_the_intent():
    from codebuddy.agent.deps import HeuristicClassifier
    from codebuddy.schemas import Intent, SessionProgress

    cls = await rr.ConceptClassifier(HeuristicClassifier()).classify(
        "why is this wrong", "x = 1", SessionProgress(session_id="s")
    )
    assert cls.intent is Intent.CONCEPT_QUESTION


async def test_item_deps_bypass_caches_memory_tools_and_tracing(settings):
    from codebuddy.cache.layers import AnswerCache, SessionStore
    from codebuddy.cache.memory import InMemoryCache

    shared = InMemoryCache()
    deps = SimpleNamespace(
        settings=settings,
        classifier=object(),
        answers=AnswerCache(shared, 60),
        sessions=SessionStore(shared, 60),
        semantic=object(),
        memory=object(),
        tools=object(),
        cache=shared,
    )
    out = rr.item_deps(rr.Deps(**vars(deps), tiers=None, retriever=None))
    assert out.semantic is None and out.memory is None and out.tools is None
    assert out.cache is not shared and out.answers._cache is out.cache
    assert isinstance(out.classifier, rr.ConceptClassifier)
    assert type(out.tracer).__name__ == "NoopTracer"


async def test_real_graph_run_gives_explain_reply_and_contexts():
    """The pipeline's graph wiring on the offline sample store: a concept answer, no cache."""
    from codebuddy.agent.graph import build_graph
    from codebuddy.eval.run import _offline_deps

    deps, _ = _offline_deps(["An accumulator collects a result.", "Second reply."])
    item = {"question": "What is an accumulator?", "reference": "r"}
    first = await rr.run_item(build_graph(rr.item_deps(deps)), item)
    again = await rr.run_item(build_graph(rr.item_deps(deps)), item)
    assert first.mode == "explain" and first.contexts
    assert first.response == "An accumulator collects a result."
    assert again.response == "Second reply."  # no answer cache hit across items


# -- scoring, aggregation, output --------------------------------------------------------------


def _sample(q="q1", contexts=("c",), response="a", reference="r"):
    return rr.Sample(
        question=q,
        reference=reference,
        expected_section=None,
        contexts=list(contexts),
        sources=[],
        response=response,
        mode="explain",
        degraded=False,
        guarded=False,
        section_hit=None,
        retrieval_ms=1.0,
        generate_ms=2.0,
        total_ms=3.0,
    )


def test_means_ignore_missing_scores():
    scores = [
        {"faithfulness": 1.0, "context_recall": None},
        {"faithfulness": 0.5, "context_recall": 0.25},
    ]
    assert rr.means(scores, ["faithfulness", "context_recall", "answer_relevancy"]) == {
        "faithfulness": 0.75,
        "context_recall": 0.25,
        "answer_relevancy": None,
    }


def test_report_json_has_config_items_and_means(tmp_path):
    config = {"index_version": "sample", "prompt_version": "p5"}
    path = rr.write_report(
        tmp_path / "out" / "r.json", config, [_sample()], [{"faithfulness": 0.5}], ["faithfulness"]
    )
    data = json.loads(path.read_text())
    assert data["config"] == config
    assert data["means"] == {"faithfulness": 0.5}
    item = data["items"][0]
    assert item["question"] == "q1" and item["contexts"] == ["c"] and item["response"] == "a"
    assert item["scores"] == {"faithfulness": 0.5}


def test_run_config_has_versions_models_and_k(settings):
    config = rr.run_config(settings, "real", ["faithfulness"], Path("golden.jsonl"))
    assert config["index_version"] == settings.index_version
    assert config["prompt_version"] == settings.prompt_version
    assert config["models"]["judge"] == settings.model_standard
    assert config["models"]["embeddings"] == settings.embed_model
    assert (
        config["retrieve_k"] == settings.retrieve_k and config["rerank_top"] == settings.rerank_top
    )
    assert config["passage_chars"] == PASSAGE_CHARS and config["git_sha"]
    assert "api_key" not in json.dumps(config).lower()


def test_table_prints_rows_and_means(capsys):
    rr.print_table([_sample("What is a loop?")], [{"faithfulness": 0.5}], ["faithfulness"])
    out = capsys.readouterr().out
    assert "What is a loop?" in out and "0.50" in out and "mean" in out


# -- Langfuse ------------------------------------------------------------------------------


class FakeObservation:
    def __init__(self, log, name, parent, **kwargs):
        self.log, self.name, self.kwargs = log, name, kwargs
        self.trace_id = parent.trace_id if parent else f"trace-{len(log)}"
        self.id = f"obs-{len(log)}"
        self.ended = False
        log.append(("observation", name, self.trace_id, kwargs))

    def start_observation(self, *, name, **kwargs):
        return FakeObservation(self.log, name, self, **kwargs)

    def end(self):
        self.ended = True


class FakeLangfuse:
    def __init__(self, dataset_exists=False):
        self.log = []
        self.dataset_exists = dataset_exists
        self.api = SimpleNamespace(
            dataset_run_items=SimpleNamespace(create=lambda **kw: self.log.append(("run", kw)))
        )

    def create_dataset(self, **kwargs):
        if self.dataset_exists:
            raise RuntimeError("exists")
        self.log.append(("dataset", kwargs))

    def create_dataset_item(self, **kwargs):
        self.log.append(("item", kwargs))
        return SimpleNamespace(id=kwargs["id"])

    def start_observation(self, *, name, **kwargs):
        return FakeObservation(self.log, name, None, **kwargs)

    def create_score(self, **kwargs):
        self.log.append(("score", kwargs))

    def flush(self):
        self.log.append(("flush",))


@pytest.mark.parametrize("exists", [False, True])
def test_push_langfuse_records_items_traces_and_scores(exists):
    client = FakeLangfuse(dataset_exists=exists)
    samples = [_sample("q1"), _sample("q2", contexts=("c2",))]
    scores = [{"faithfulness": 0.5, "context_recall": None}, {"faithfulness": 1.0}]
    rr.push_langfuse(
        client, "p5-sample-20261102T000000Z", {"prompt_version": "p5"}, samples, scores
    )

    log = client.log
    assert (
        ("dataset", {"name": rr.LANGFUSE_DATASET, "description": rr.DATASET_DESCRIPTION}) in log
    ) != exists
    items = [e[1] for e in log if e[0] == "item"]
    assert [i["input"] for i in items] == [{"question": "q1"}, {"question": "q2"}]
    assert all(i["dataset_name"] == rr.LANGFUSE_DATASET for i in items)
    assert items[0]["expected_output"] == {"reference": "r"}
    assert items[0]["id"] == rr.item_id("q1") != rr.item_id("q2")

    obs = [e for e in log if e[0] == "observation"]
    roots = [e for e in obs if e[1] == "ragas-item"]
    assert len(roots) == 2
    for root in roots:
        names = [e[1] for e in obs if e[2] == root[2] and e is not root]
        assert names == ["retrieve", "generate"]
    retrieve = next(e for e in obs if e[1] == "retrieve" and e[2] == roots[1][2])
    assert retrieve[3]["output"]["contexts"] == ["c2"]
    generate = next(e for e in obs if e[1] == "generate" and e[2] == roots[0][2])
    assert generate[3]["output"] == "a" and generate[3]["as_type"] == "generation"

    runs = [e[1] for e in log if e[0] == "run"]
    assert [r["run_name"] for r in runs] == ["p5-sample-20261102T000000Z"] * 2
    assert [r["trace_id"] for r in runs] == [roots[0][2], roots[1][2]]
    assert [r["dataset_item_id"] for r in runs] == [rr.item_id("q1"), rr.item_id("q2")]

    got = [(e[1]["name"], e[1]["value"], e[1]["trace_id"]) for e in log if e[0] == "score"]
    assert got == [
        ("faithfulness", 0.5, roots[0][2]),
        ("faithfulness", 1.0, roots[1][2]),
    ]  # a missing score is not pushed
    assert log[-1] == ("flush",)


def test_build_langfuse_needs_both_keys_and_the_switch():
    assert rr.build_langfuse({}, enabled=True) is None
    assert rr.build_langfuse({"LANGFUSE_PUBLIC_KEY": "p"}, enabled=True) is None
    keys = {"LANGFUSE_PUBLIC_KEY": "p", "LANGFUSE_SECRET_KEY": "s"}
    assert rr.build_langfuse(keys, enabled=False) is None


def test_build_langfuse_without_the_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "langfuse", None)  # import fails
    keys = {"LANGFUSE_PUBLIC_KEY": "p", "LANGFUSE_SECRET_KEY": "s"}
    assert rr.build_langfuse(keys, enabled=True) is None


# -- draft generation --------------------------------------------------------------------------


class StubDraftModel:
    def __init__(self):
        self.prompts = []

    async def ainvoke(self, messages):
        self.prompts.append(messages)
        return rr.DraftQA(question=f"Q{len(self.prompts)}?", reference=f"A{len(self.prompts)}.")


async def test_draft_items_are_marked_auto_generated():
    chunks = [
        {"text": "A list holds items.", "section": "Lists", "title": "Think Python"},
        {"text": "A dict maps keys.", "section": "Dicts", "title": "Think Python"},
    ]
    model = StubDraftModel()
    items = await rr.draft_items(chunks, model)
    assert items == [
        {
            "question": "Q1?",
            "reference": "A1.",
            "expected_section": "Lists",
            "source": "Think Python",
            "auto_generated": True,
        },
        {
            "question": "Q2?",
            "reference": "A2.",
            "expected_section": "Dicts",
            "source": "Think Python",
            "auto_generated": True,
        },
    ]
    assert "A list holds items." in str(model.prompts[0])


def test_write_draft_round_trips_through_the_loader(tmp_path, capsys):
    items = [{"question": "q", "reference": "r", "expected_section": "s", "auto_generated": True}]
    path = rr.write_draft(tmp_path / "d.jsonl", items)
    assert rr.load_dataset(path) == items
    assert "review" in capsys.readouterr().out.lower()


# -- CLI -------------------------------------------------------------------------------------


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    """No .env is read; keys and model ids come only from what each test sets."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(rr, "load_dotenv", lambda *a, **k: False)
    monkeypatch.setattr(rr, "setup_logging", lambda *a, **k: None)  # no sink outlives capsys
    for name in (
        "OPENAI_API_KEY",
        "CODEBUDDY_MODEL_FAST",
        "CODEBUDDY_MODEL_STANDARD",
        "CODEBUDDY_MODEL_HEAVY",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _keys(env):
    env.setenv("OPENAI_API_KEY", "sk-test")
    for tier in ("FAST", "STANDARD", "HEAVY"):
        env.setenv(f"CODEBUDDY_MODEL_{tier}", tier.lower())


def test_cli_refuses_without_openai_key(cli_env, capsys):
    called = []
    assert rr.main(["--index", "sample"], pipeline=lambda *a: called.append(a)) == 1
    assert "OPENAI_API_KEY" in capsys.readouterr().err and not called


def test_cli_refuses_without_model_ids(cli_env, capsys):
    cli_env.setenv("OPENAI_API_KEY", "sk-test")
    assert rr.main(["--index", "sample"], pipeline=lambda *a: None) == 1
    assert "CODEBUDDY_MODEL_STANDARD" in capsys.readouterr().err


def test_cli_rejects_bad_fail_under(cli_env):
    with pytest.raises(SystemExit):
        rr.main(["--fail-under", "faithfulness"])
    with pytest.raises(SystemExit):
        rr.main(["--fail-under", "nope=0.5"])


def _run_cli(env, tmp_path, extra, value=0.6):
    _keys(env)
    seen = {}

    async def pipeline(settings, index, items):
        seen["index"], seen["items"] = index, items
        return [_sample(it["question"]) for it in items]

    async def scorer(samples, metrics):
        seen["metrics"] = metrics
        return [dict.fromkeys(metrics, value) for _ in samples]

    out = tmp_path / "report.json"
    code = rr.main(
        ["--index", "sample", "--limit", "2", "--no-langfuse", "--out", str(out), *extra],
        pipeline=pipeline,
        scorer=scorer,
    )
    return code, seen, out


def test_cli_runs_with_injected_pipeline_and_scorer(cli_env, tmp_path, capsys):
    code, seen, out = _run_cli(cli_env, tmp_path, ["--metrics", "faithfulness,context_recall"])
    assert code == 0
    assert seen["index"] == "sample" and len(seen["items"]) == 2
    assert seen["metrics"] == ["faithfulness", "context_recall"]
    data = json.loads(out.read_text())
    assert data["means"] == {"faithfulness": 0.6, "context_recall": 0.6}
    assert data["config"]["index"] == "sample"
    assert "mean" in capsys.readouterr().out


@pytest.mark.parametrize(
    "gates, code",
    [
        (["faithfulness=0.5"], 0),
        (["faithfulness=0.7"], 2),
        (["faithfulness=0.5", "context_recall=0.9"], 2),
        (["answer_relevancy=0.1"], 2),  # not measured in this run: fails the gate
    ],
)
def test_cli_fail_under_sets_exit_code(cli_env, tmp_path, gates, code):
    extra = ["--metrics", "faithfulness,context_recall"]
    for gate in gates:
        extra += ["--fail-under", gate]
    assert _run_cli(cli_env, tmp_path, extra)[0] == code


def test_cli_fails_when_every_score_is_missing(cli_env, tmp_path):
    code, _, out = _run_cli(cli_env, tmp_path, [], value=None)
    assert code == 1 and out.exists()  # the report is still written


def test_cli_rejects_unknown_metric(cli_env):
    with pytest.raises(SystemExit):
        rr.main(["--metrics", "faithfulness,bleu"])


def test_cli_without_ragas_installed_says_how_to_get_it(cli_env, capsys, monkeypatch):
    _keys(cli_env)
    monkeypatch.setattr(rr, "ragas_available", lambda: False)
    called = []
    assert rr.main(["--index", "sample"], pipeline=lambda *a: called.append(a)) == 1
    assert "evals/setup.sh" in capsys.readouterr().err and not called


def test_importing_the_runner_does_not_import_ragas_or_langfuse():
    code = (
        "import sys, codebuddy.eval.ragas_run; "
        "print(sorted(m for m in ('ragas', 'langfuse', 'openai.AsyncOpenAI') if m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
