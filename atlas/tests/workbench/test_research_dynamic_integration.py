"""Default science calls use bounded context and retain inspectable receipts."""

from copy import deepcopy
import json

import pytest

from test_research_context import question, snapshot
from test_research_model import MODEL, completion, transport
from test_research_runner import Papers, Model, document, project
from workbench.research_context import select_context


def test_default_ollama_plan_compiles_whole_task_and_context(monkeypatch):
    from workbench.research_model import Ollama
    selected = select_context(snapshot(), question())
    requests = transport(monkeypatch, [completion({"query": "cell fate lineage tracing"})])
    model = Ollama(MODEL)
    assert model.plan(question(), selected, ["prior query"]) == "cell fate lineage tracing"
    request = json.loads(requests[0][0].data)
    data = json.loads(request["messages"][1]["content"])
    assert data["question"] == question()
    assert isinstance(data["context"], list)
    assert all(entry in selected for entry in data["context"])
    assert request["options"]["num_ctx"] == 32768
    assert model.last_context_manifest["mode"] == "dynamic"
    assert len(requests[0][0].data) == model.last_context_manifest["request_bytes"] <= 20000


def test_omitted_paper_passage_cannot_supply_an_accepted_quote(monkeypatch):
    from workbench import research_sources
    from workbench.research_model import Ollama
    import io
    doc = document()
    doc["passages"] = [{"id": f"p{i}", "locator": f"Paragraph {i}",
                        "text": f"Paragraph {i} reports a controlled synthetic observation. " + "Setup detail. " * 100}
                       for i in range(12)]
    observed = []
    def respond(request, *, timeout):
        data = json.loads(json.loads(request.data)["messages"][1]["content"])
        visible = {p["id"] for p in data["document"]["passages"]}
        assert len(visible) < len(doc["passages"])
        omitted = next(p for p in doc["passages"] if p["id"] not in visible)
        observed.append(omitted["id"])
        analysis = Model().extract(None, None, None)["analysis"]
        analysis.update(passage_id=omitted["id"], quote=" ".join(omitted["text"].split()[:8]))
        return io.BytesIO(json.dumps(completion(analysis)).encode())
    monkeypatch.setattr(research_sources, "urlopen", respond)
    with pytest.raises(ValueError, match="selected|supplied"):
        Ollama(MODEL).extract(question(), doc, select_context(snapshot(), question()))
    assert len(observed) == 1


def test_default_worker_persists_dynamic_context_and_recalls_older_findings(project, monkeypatch):
    from workbench import research_sources
    from workbench.research_service import run_worker, WorkerControl
    path = project / "workbench/data/cell_fate.json"
    bundle = json.loads(path.read_text())
    target = next(record for record in bundle["items"] if record["id"] == "q-fate")
    target.update(title="What does earlier Zebracode evidence say about fate?", summary="Recover the old Zebracode observation.")
    old = next(record for record in bundle["items"] if record["id"] == "c-cellrank")
    old.update(title="Earlier Zebracode observation", summary="Synthetic lineage ambiguity in the Zebracode assay.")
    for index in range(20):
        later = deepcopy(old)
        later.update(id=f"later-{index}", title="General cell fate update", summary="Another assay and a different limitation.")
        bundle["items"].append(later)
        bundle["relations"].append({"id": f"edge-later-{index}", "subject": later["id"], "predicate": "informs",
            "object": "q-fate", "status": "proposed", "rationale": "Synthetic test link.",
            "context": {}, "evidence": []})
    path.write_text(json.dumps(bundle))
    monkeypatch.setattr(research_sources, "EuropePMC", lambda: Papers())
    analysis = Model().extract(None, None, None)["analysis"]
    requests = transport(monkeypatch, [{"models": [{"name": MODEL, "model": MODEL}]},
        completion({"query": "cell fate lineage tracing"}), completion(analysis),
        completion(Model().review(None, None, None)["analysis"])])
    assert run_worker(project, {"cycles": 1, "batch_size": 1, "question_ids": ["q-fate"]}) == 0
    calls = [json.loads(request.data) for request, _ in requests if request.data]
    assert len(calls) == 3
    for call in calls[:2]:
        data = json.loads(call["messages"][1]["content"])
        assert "c-cellrank" in {entry["record"]["id"] for entry in data["context"]}
        assert len(call["messages"]) == 2
    assert json.loads(calls[2]["messages"][1]["content"])["context"] == []
    job = json.loads(next((project / ".atlas/research/jobs").glob("*.json")).read_text())
    assert job["receipt"]["recorded"] is True
    assert job["extraction"]["context_manifest"]["mode"] == "dynamic"
    assert job["draft"]["context"]["prompt_passage_ids"] == '["abstract:1"]'
    frontier = json.loads((project / ".atlas/research/frontier.json").read_text())
    assert frontier["frontiers"]["q-fate"]["plan_context"]["mode"] == "dynamic"
    status = WorkerControl(project).status()
    assert status["context_mode"] == "dynamic"
    assert status["context_budget"]["input_bytes"] == 20000


def test_rejected_answers_survive_restart_without_becoming_drafts(project, monkeypatch):
    from workbench.automation import ResearchInbox
    from workbench.research_model import Ollama
    from workbench.research_runner import ResearchRunner

    analysis = Model().extract(None, None, None)["analysis"]
    rejected = [analysis | {"quote": f"Copied observation from unrelated prior study {i}"} for i in range(3)]
    transport(monkeypatch, [completion({"query": "fate"}), *(completion(a) for a in rejected)])
    for attempt in range(1, 4):
        worker = ResearchRunner(project, provider=Papers(), model=Ollama(MODEL), question_ids=["q-fate"])
        result = worker.cycle()
        assert result["saved"] == 0
        job = json.loads(next((project / ".atlas/research/jobs").glob("*.json")).read_text())
        history = job.get("rejected_extractions", [])
        assert len(history) == attempt, "Keep every rejected answer across worker restarts"
        assert history[-1]["result"]["analysis"] == rejected[attempt - 1]
        assert history[-1]["attempt"] == attempt
        assert result["errors"][0]["kind"] == "invalid_analysis"
        assert job["status"] == ("failed" if attempt == 3 else "retry")
        assert "draft" not in job
    assert ResearchInbox(project).status()["draft_count"] == 0


def test_failed_analysis_recovers_once_per_revision_with_history_and_feedback(project, monkeypatch):
    from workbench.research_model import Ollama
    from workbench.research_runner import ResearchRunner

    analysis = Model().extract(None, None, None)["analysis"]
    bad = analysis | {"quote": "A quotation absent from the current paper"}
    requests = transport(monkeypatch, [*(completion(bad) for _ in range(3)), completion(analysis),
        completion(Model().review(None, None, None)["analysis"])])
    monkeypatch.setattr(Ollama, "plan", lambda *args: "fate")

    def cycle(revision):
        model = Ollama(MODEL)
        model.analysis_revision = revision
        return ResearchRunner(project, provider=Papers(), model=model, question_ids=["q-fate"]).cycle()

    for _ in range(3):
        assert cycle("before-fix")["errors"]
    path = next((project / ".atlas/research/jobs").glob("*.json"))
    failed = json.loads(path.read_text())
    assert failed["status"] == "failed"
    assert cycle("before-fix")["saved"] == 0
    recovered = cycle("after-fix")
    assert recovered["saved"] == 1, "An improved analyzer must recover exhausted older jobs automatically"
    job = json.loads(path.read_text())
    assert job["rejected_extractions"] == failed["rejected_extractions"]
    assert job["recoveries"][0]["previous_attempts"] == 3
    assert job["recoveries"][0]["analysis_revision"] == "after-fix"
    assert job["draft"]["idempotency_key"] == "paper-job:" + job["id"]
    data = json.loads(json.loads(requests[1][0].data)["messages"][1]["content"])
    assert data["previous_rejection"]["quote"] == bad["quote"]
    assert cycle("another-fix")["saved"] == 0
    assert len(list((project / ".atlas/research/jobs").glob("*.json"))) == 1


def test_analyzer_rollback_does_not_reset_an_exhausted_revision(project, monkeypatch):
    from workbench.research_model import Ollama
    from workbench.research_runner import ResearchRunner

    bad = Model().extract(None, None, None)["analysis"] | {"quote": "A quotation absent from the current paper"}
    transport(monkeypatch, [completion(bad) for _ in range(9)])
    monkeypatch.setattr(Ollama, "plan", lambda *args: "fate")
    for revision in ["v1"] * 3 + ["v2"] * 3:
        model = Ollama(MODEL)
        model.analysis_revision = revision
        ResearchRunner(project, provider=Papers(), model=model, question_ids=["q-fate"]).cycle()
    path = next((project / ".atlas/research/jobs").glob("*.json"))
    before = json.loads(path.read_text())
    assert before["status"] == "failed"
    model.analysis_revision = "v1"
    ResearchRunner(project, provider=Papers(), model=model, question_ids=["q-fate"]).cycle()
    assert json.loads(path.read_text()) == before
