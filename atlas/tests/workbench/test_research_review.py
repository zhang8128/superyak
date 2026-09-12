"""A real source quotation must not let an unsupported claim enter the graph."""

from copy import deepcopy
import json

import pytest

from test_research_runner import project, runner
from test_research_model import MODEL, completion, transport, document, analysis


def review_result(verdict="supported"):
    return {
        "model": "test-model", "metrics": {},
        "analysis": {
            "verdict": verdict,
            "reason": "The claim's method and scope do not match the source." if verdict == "unsupported"
                      else "The source directly describes this scoped observation.",
            "evidence": [{"passage_id": "abstract:1"}],
        },
        "context_manifest": {"selected_record_ids": [], "selected_passage_ids": ["abstract:1"]},
    }


@pytest.mark.parametrize("verdict", ["unsupported", "uncertain"])
def test_verbatim_quote_with_unaccepted_source_review_never_enters_graph(project, verdict):
    worker = runner(project)
    worker.model.review = lambda question, document, candidate: review_result(verdict)
    result = worker.cycle()
    assert result["saved"] == 0, "Exact quotations cannot substitute for claim-to-source support"
    assert not list((project / ".atlas/drafts").glob("*.json"))
    job = json.loads(next((project / ".atlas/research/jobs").glob("*.json")).read_text())
    assert job["status"] == "held"
    assert job["source_review"]["result"]["analysis"]["verdict"] == verdict
    assert "draft" not in job


def test_source_review_outage_cannot_capture_an_unchecked_claim(project):
    worker = runner(project)

    def offline(*args):
        raise RuntimeError("Reviewer unavailable")

    worker.model.review = offline
    result = worker.cycle()
    assert result["saved"] == 0
    assert result["errors"]
    job = json.loads(next((project / ".atlas/research/jobs").glob("*.json")).read_text())
    assert job["status"] == "retry"
    assert "draft" not in job


def test_review_uses_a_fresh_source_only_request_with_the_whole_candidate(monkeypatch, document, analysis):
    from workbench.research_model import Ollama

    decision = {"verdict": "unsupported", "reason": "The source reports an association, not the proposed mechanism.",
                "evidence": [{"passage_id": "p0001"}]}
    requests = transport(monkeypatch, [completion(decision)])
    result = Ollama(MODEL).review({"title": "What affects fate?"}, document, analysis)
    payload = json.loads(requests[0][0].data)
    data = json.loads(payload["messages"][1]["content"])
    assert data["candidate"] == analysis
    assert data["context"] == []
    assert len(payload["messages"]) == 2
    assert result["analysis"] == decision
    assert result["context_manifest"]["selected_record_ids"] == []


@pytest.mark.parametrize("change", [
    {"verdict": "reviewed"}, {"reason": ""}, {"evidence": []},
    {"evidence": [{"passage_id": "p0001", "quote": "This quotation is invented"}]},
    {"evidence": [{"passage_id": "not-supplied"}]},
])
def test_review_cannot_certify_support_with_invalid_or_missing_evidence(monkeypatch, document, analysis, change):
    from workbench.research_model import Ollama

    decision = {"verdict": "supported", "reason": "The source supports the claim.",
                "evidence": [{"passage_id": "p0001"}]} | change
    transport(monkeypatch, [completion(decision)])
    with pytest.raises(ValueError):
        Ollama(MODEL).review("What affects fate?", document, analysis)


@pytest.mark.parametrize("next_model", ["test-model", "different-model"])
def test_backlog_review_persists_across_workers_and_removes_bad_claim_from_context(project, next_model):
    from workbench import research_review

    worker = runner(project)
    first = worker.cycle()
    record_id = first["record_ids"][0]
    draft_path = project / ".atlas/drafts" / (record_id + ".json")
    original = draft_path.read_bytes()
    worker.model.review = lambda *args: review_result("unsupported")
    result = research_review.review_backlog(project, worker.model, limit=1)
    assert result["reviewed"] == 1
    assert result["verdicts"] == {"unsupported": 1}
    fresh = runner(project)
    fresh.model.model = next_model
    snapshot = fresh.inbox.snapshot()
    question = next(r for r in snapshot["bundle"]["items"] if r["id"] == "q-fate")
    assert record_id not in {r["record"]["id"] for r in fresh._context(question, snapshot)}
    assert draft_path.read_bytes() == original
    assert next(r for r in snapshot["bundle"]["items"] if r["id"] == record_id)["status"] == "proposed"

    def no_repeat(*args):
        pytest.fail("An unchanged reviewed record must not consume another model call")

    worker.model.review = no_repeat
    assert research_review.review_backlog(project, worker.model, limit=1)["reviewed"] == 0


def test_source_review_cache_is_bound_to_actual_source_and_candidate(project):
    from workbench.research_review import assess
    from test_research_runner import Model, document as runner_document

    model = Model()
    doc = runner_document()
    candidate = model.extract(None, None, None)["analysis"]
    first = assess(model, "What affects fate?", doc, candidate)
    model.review = lambda *args: review_result("unsupported")
    assert assess(model, "What affects fate?", doc, candidate, first) == first
    revised = candidate | {"summary": "An unrelated method explains these outcomes."}
    assert assess(model, "What affects fate?", doc, revised, first)["result"]["analysis"]["verdict"] == "unsupported"
    doc["passages"][0]["text"] += " This is a new source statement."
    assert assess(model, "What affects fate?", doc, candidate, first)["result"]["analysis"]["verdict"] == "unsupported"


def test_review_retry_preserves_the_candidate_instead_of_generating_another(project):
    worker = runner(project)
    worker.model.review = lambda *args: (_ for _ in ()).throw(RuntimeError("Reviewer unavailable"))
    assert worker.cycle()["saved"] == 0
    worker.model.extract = lambda *args: pytest.fail("Review retries must use the persisted candidate")
    worker.model.review = lambda *args: review_result()
    assert worker.cycle()["saved"] == 1


def test_legacy_prepared_but_uncaptured_draft_cannot_bypass_review(project, monkeypatch):
    worker = runner(project)
    original_record = worker.inbox.record
    monkeypatch.setattr(worker.inbox, "record", lambda *args: (_ for _ in ()).throw(OSError("before save")))
    assert worker.cycle()["saved"] == 0
    path = next((project / ".atlas/research/jobs").glob("*.json"))
    job = json.loads(path.read_text())
    del job["source_review"]
    path.write_text(json.dumps(job))
    monkeypatch.setattr(worker.inbox, "record", original_record)
    worker.model.review = lambda *args: review_result("unsupported")
    assert worker.cycle()["saved"] == 0
    assert not list((project / ".atlas/drafts").glob("*.json"))
    assert json.loads(path.read_text())["draft"] == job["draft"]


def test_cli_exposes_a_bounded_backlog_pass_and_reports_errors(project, monkeypatch, capsys):
    from workbench import automation, research_model, research_review

    record_id = runner(project).cycle()["record_ids"][0]
    monkeypatch.setattr(research_model.Ollama, "check", lambda self: {})
    monkeypatch.setattr(research_model.Ollama, "review", lambda *args: review_result("unsupported"))
    assert automation.main(["--project", str(project), "review-backlog", "--limit", "1", "--record", record_id]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["reviewed"] == 1
    assert result["records"][0]["record_id"] == record_id
    assert result["verdicts"] == {"unsupported": 1}


def test_rejected_review_preserves_diagnostics_without_creating_a_draft(project):
    from workbench.research_review import SourceReviewError

    worker = runner(project)
    bad = review_result() | {"analysis": review_result()["analysis"] | {"evidence": []}}
    worker.model.review = lambda *args: (_ for _ in ()).throw(SourceReviewError("Missing evidence", bad))
    result = worker.cycle()
    assert result["saved"] == 0
    job = json.loads(next((project / ".atlas/research/jobs").glob("*.json")).read_text())
    assert job["rejected_reviews"][0]["result"] == bad
    assert job["last_error_kind"] == "invalid_review"


def test_review_always_receives_the_candidates_cited_passage(monkeypatch, document, analysis):
    from workbench.research_model import Ollama
    from workbench.research_context import ContextBudget
    from workbench import research_sources
    import io

    cited = document["passages"][0]
    cited["text"] += " Observational assay detail." * 45
    document["passages"] = [{"id": f"noise-{i}", "locator": "Introduction",
                             "text": "Cells fate treatment measurement. " * 40} for i in range(6)] + [cited]
    requests = []

    def respond(request, *, timeout):
        payload = json.loads(request.data)
        data = json.loads(payload["messages"][1]["content"])
        requests.append(data)
        assert cited in data["document"]["passages"], "The reviewer must see the claim's actual cited passage"
        assert len(request.data) <= 6500
        return io.BytesIO(json.dumps(completion({"verdict": "supported", "reason": "The cited source supports it.",
            "evidence": [{"passage_id": "p0001"}]})).encode())

    monkeypatch.setattr(research_sources, "urlopen", respond)
    result = Ollama(MODEL, context_budget=ContextBudget(input_bytes=6500)).review("Cells fate treatment", document, analysis)
    assert result["analysis"]["verdict"] == "supported"
    assert len(requests) == 1


@pytest.mark.parametrize("field", ["evidence", "links", "sources"])
def test_prepared_claim_cannot_diverge_from_its_reviewed_evidence(project, monkeypatch, field):
    worker = runner(project)
    original_record = worker.inbox.record
    monkeypatch.setattr(worker.inbox, "record", lambda *args: (_ for _ in ()).throw(OSError("before save")))
    worker.cycle()
    path = next((project / ".atlas/research/jobs").glob("*.json"))
    job = json.loads(path.read_text())
    key = {"evidence": "note", "links": "rationale", "sources": "title"}[field]
    job["draft"][field][0][key] = "A different unsupported assertion"
    path.write_text(json.dumps(job))
    monkeypatch.setattr(worker.inbox, "record", original_record)
    assert worker.cycle()["saved"] == 0
    assert not list((project / ".atlas/drafts").glob("*.json"))


def test_malformed_reviewer_json_is_preserved_as_review_failure(project, monkeypatch):
    from workbench.research_model import Ollama
    from test_research_runner import Model

    worker = runner(project)
    worker.model = Ollama(MODEL)
    monkeypatch.setattr(worker.model, "plan", lambda *args: "fate")
    monkeypatch.setattr(worker.model, "extract", Model().extract)
    transport(monkeypatch, [completion({"verdict": "supported", "reason": "missing evidence field"})])
    result = worker.cycle()
    assert result["saved"] == 0
    job = json.loads(next((project / ".atlas/research/jobs").glob("*.json")).read_text())
    assert job["last_error_kind"] == "invalid_review"
    assert "missing evidence field" in job["rejected_reviews"][0]["result"]["response"]["message"]["content"]


def test_revisiting_an_older_review_input_keeps_the_new_verdict_effective(project):
    from workbench.research_review import ReviewLedger, review_backlog

    worker = runner(project)
    record_id = worker.cycle()["record_ids"][0]
    pilot = project / "workbench/data/cell_fate.json"
    original = pilot.read_text()
    worker.model.review = lambda *args: review_result("unsupported")
    review_backlog(project, worker.model, limit=1)
    changed = json.loads(original)
    next(q for q in changed["items"] if q["id"] == "q-fate")["title"] = "A different question context"
    pilot.write_text(json.dumps(changed))
    worker.model.review = lambda *args: review_result("supported")
    review_backlog(project, worker.model, limit=1)
    pilot.write_text(original)
    worker.model.review = lambda *args: review_result("unsupported")
    result = review_backlog(project, worker.model, limit=1)
    assert result["verdicts"] == {"unsupported": 1}
    assert record_id in ReviewLedger(project).excluded(worker.inbox.snapshot())


def test_question_facet_changes_do_not_block_review_of_an_unchanged_saved_claim(project):
    from workbench.research_review import review_backlog

    worker = runner(project)
    record_id = worker.cycle()["record_ids"][0]
    path = project / "workbench/data/cell_fate.json"
    bundle = json.loads(path.read_text())
    next(r for r in bundle["items"] if r["id"] == "q-fate")["facets"]["research_phase"] = ["followup"]
    path.write_text(json.dumps(bundle))
    result = review_backlog(project, worker.model, limit=1, record_ids=[record_id])
    assert not result["errors"]
    assert result["reviewed"] == 1


def test_original_source_binding_allows_an_independent_later_relation(project):
    from workbench.research_review import bound_candidate

    worker = runner(project)
    identifier = worker.cycle()["record_ids"][0]
    job = json.loads(next((worker.root / "jobs").glob("*.json")).read_text())
    snapshot = worker.inbox.snapshot()
    record = next(r for r in snapshot["bundle"]["items"] if r["id"] == identifier)
    original = next(r for r in snapshot["bundle"]["relations"] if r["subject"] == identifier)
    later = deepcopy(original) | {"id": "later-overlap-link", "object": "q-regulation",
                                  "rationale": "A separate assessment connects this finding to regulation."}
    snapshot["bundle"]["relations"].append(later)
    assert bound_candidate(snapshot, job, record)[2] == job["extraction"]["analysis"]


@pytest.mark.parametrize("change", ["removed", "substituted_id", "evidence", "context", "rationale",
                                    "subject", "object", "predicate", "status", "reviewed_by", "reviewed_at"])
def test_original_source_relation_requires_its_exact_id_and_full_content(project, change):
    from workbench.research_review import bound_candidate

    worker = runner(project)
    identifier = worker.cycle()["record_ids"][0]
    job = json.loads(next((worker.root / "jobs").glob("*.json")).read_text())
    snapshot = worker.inbox.snapshot()
    record = next(r for r in snapshot["bundle"]["items"] if r["id"] == identifier)
    relations = snapshot["bundle"]["relations"]
    original = next(r for r in relations if r["id"] == f"{identifier}:link:0")
    if change == "removed":
        relations.remove(original)
    elif change == "substituted_id":
        original["id"] = "different-edge-with-the-same-endpoints"
    elif change in {"evidence", "context"}:
        original[change] = [] if change == "evidence" else {}
    else:
        original[change] = {"rationale": "Changed assertion", "subject": "another-claim",
                            "object": "q-regulation", "predicate": "challenges", "status": "source_reported",
                            "reviewed_by": "Different reviewer", "reviewed_at": "2026-09-10T00:00:00Z"}[change]
    with pytest.raises(ValueError):
        bound_candidate(snapshot, job, record)
