"""Publication reuse retains distinct assertions and original capture ownership."""

from copy import deepcopy
import json

import pytest

from test_research_graph_workers import GraphModel
from test_research_runner import Papers, document, project
from workbench.research_runner import ResearchRunner


class CachedPapers(Papers):
    def __init__(self):
        self.reads = 0
        self.paper = {"key": "doi:10.1000/shared", "doi": "10.1000/shared",
                      "provider_source": "MED", "provider_id": "123", "pmcid": "PMC456"}

    def search(self, *args, **kwargs):
        return {"papers": [deepcopy(self.paper)], "next_cursor": None}

    def read(self, paper):
        self.reads += 1
        return document()


class ReuseModel(GraphModel):
    def __init__(self):
        self.calls = []
        self.change = {}

    def extract(self, *args):
        self.calls.append("extract")
        result = super().extract(*args)
        result["analysis"].update(self.change)
        return result

    def review(self, *args):
        self.calls.append("review")
        return super().review(*args)

    def overlap(self, question, packet, **kwargs):
        self.calls.append("overlap")
        assert len(packet["records"]) == 1
        assert question["id"] == "q-regulation"
        return super().overlap(question, packet, **kwargs)

    def review_overlap(self, *args):
        self.calls.append("review_overlap")
        return super().review_overlap(*args)


def first_claim(project):
    worker = ResearchRunner(project, provider=CachedPapers(), model=ReuseModel(), question_ids=["q-fate"])
    result = worker.cycle()
    assert result["saved"] == 1, result
    worker.question_ids = ["q-regulation"]
    return worker, result["record_ids"][0]


def job_for(worker, question):
    return next(json.loads(path.read_text()) for path in (worker.root / "jobs").glob("*.json")
                if json.loads(path.read_text())["question_id"] == question)


def withdraw_questions(project):
    path = project / "workbench/data/cell_fate.json"
    bundle = json.loads(path.read_text())
    for item in bundle["items"]:
        if item["kind"] == "question":
            item["status"] = "withdrawn"
    path.write_text(json.dumps(bundle))


@pytest.mark.parametrize("paper", [
    {"key": "alternate-doi", "doi": "10.1000/SHARED"},
    {"key": "europepmc:MED:123", "provider_source": "MED", "provider_id": "123"},
    {"key": "pmcid:PMC456", "pmcid": "PMC456"},
])
def test_canonical_paper_uses_cached_document_and_links_existing_assertion(project, paper):
    from workbench.research_evidence import eligible_inputs
    worker, identifier = first_claim(project)
    original = job_for(worker, "q-fate")
    before = worker.inbox.snapshot()
    worker.provider.paper = paper
    result = worker.cycle()
    assert result["saved"] == 0 and result["links_added"] == 1, result
    assert result["record_ids"] == [] and result["reused_record_ids"] == [identifier]
    assert worker.provider.reads == 1
    assert worker.model.calls == ["extract", "review", "extract", "review", "overlap", "review_overlap"]
    job = job_for(worker, "q-regulation")
    assert job["status"] == "linked" and "draft" not in job
    assert job["document"] == original["document"]
    assert job["document_reused_from"] == original["id"]
    assert "record_id" not in job["receipt"]
    assert job_for(worker, "q-fate") == original
    after = worker.inbox.snapshot()
    assert len(after["bundle"]["items"]) == len(before["bundle"]["items"])
    assert set(eligible_inputs(worker, after)) == {identifier}
    assert {r["object"] for r in after["bundle"]["relations"]
            if r["subject"] == identifier and r["predicate"] == "informs"} == {"q-fate", "q-regulation"}
    worker.cycle()
    assert worker.provider.reads == 1 and worker.model.calls.count("overlap") == 1


@pytest.mark.parametrize("change", [
    {"summary": "The study reports observed lineage outcomes in this mouse system."},
    {"summary": "THE STUDY REPORTS A MISMATCH BETWEEN PREDICTED FATES AND OBSERVED LINEAGE OUTCOMES."},
    {"scope": "A distinct population within the mouse system described in the abstract."},
    {"quote": "lineage outcomes differed from predicted cell fates"},
])
def test_same_publication_preserves_distinct_assertions_scopes_and_evidence(project, change):
    worker, original = first_claim(project)
    worker.model.change = change
    result = worker.cycle()
    assert result["saved"] == 1 and result["record_ids"] != [original], result
    assert worker.provider.reads == 1
    assert "overlap" not in worker.model.calls
    assert job_for(worker, "q-regulation")["status"] == "recorded"


def test_reuse_normalizes_whitespace(project):
    worker, identifier = first_claim(project)
    original = job_for(worker, "q-fate")["extraction"]["analysis"]
    worker.model.change = {key: "  " + value.replace(" ", "  ") + " "
                           for key, value in original.items() if key in {"summary", "scope"}}
    result = worker.cycle()
    assert result["saved"] == 0 and result["reused_record_ids"] == [identifier], result


def test_matching_words_in_distinct_publications_remain_separate_claims(project):
    worker, original = first_claim(project)
    worker.provider.paper = {"key": "europepmc:MED:789", "provider_source": "MED", "provider_id": "789"}
    def read_another(paper):
        worker.provider.reads += 1
        doc = document()
        doc["source"].update(id="epmc:MED:789", url="https://europepmc.org/article/MED/789")
        return doc
    worker.provider.read = read_another
    result = worker.cycle()
    assert result["saved"] == 1 and result["record_ids"] != [original], result
    assert worker.provider.reads == 2
    assert "overlap" not in worker.model.calls


def test_new_publication_alias_does_not_rebind_an_original_source(project):
    from workbench.research_evidence import eligible_inputs
    provider = CachedPapers()
    def read(paper):
        doc = document()
        doc["source"]["url"] = "https://europepmc.org/articles/PMC456"
        return doc
    provider.read = read
    worker = ResearchRunner(project, provider=provider, model=ReuseModel(), question_ids=["q-fate"])
    result = worker.cycle()
    assert result["saved"] == 1, result
    identifier = result["record_ids"][0]
    snapshot = worker.inbox.snapshot()
    original = next(s for s in snapshot["bundle"]["sources"] if s["id"] == "epmc:MED:123")
    snapshot["bundle"]["sources"].insert(0, original | {
        "id": "older-pmc-alias", "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC456/"})
    assert identifier in eligible_inputs(worker, snapshot)


def test_overlap_rejection_holds_duplicate_without_capturing_another_claim(project):
    worker, identifier = first_claim(project)
    review = worker.model.review_overlap
    def reject(*args):
        result = review(*args)
        result["analysis"]["decisions"][0].update(verdict="uncertain", reason="Relevance is unclear.", evidence=[])
        return result
    worker.model.review_overlap = reject
    result = worker.cycle()
    assert result["saved"] == 0 and result["held"] == 1, result
    job = job_for(worker, "q-regulation")
    assert job["status"] == "held" and "draft" not in job
    graph = json.loads((worker.root / "graph-jobs" / (job["reuse"]["graph_job_id"] + ".json")).read_text())
    assert graph["review"]["analysis"]["decisions"][0]["verdict"] == "uncertain"
    assert len(list((project / ".atlas/drafts").glob("*.json"))) == 1


def test_overlap_review_outage_keeps_candidate_and_resumes_after_restart(project):
    worker, identifier = first_claim(project)
    worker.model.review_overlap = lambda *args: (_ for _ in ()).throw(RuntimeError("review offline"))
    result = worker.cycle()
    assert result["errors"] and result["saved"] == 0, result
    assert job_for(worker, "q-regulation")["status"] == "retry"
    model = ReuseModel()
    model.extract = model.review = model.overlap = lambda *args: pytest.fail("Retain the saved source and overlap candidates")
    restarted = ResearchRunner(project, provider=worker.provider, model=model, question_ids=["q-regulation"])
    result = restarted.cycle()
    assert result["links_added"] == 1 and result["reused_record_ids"] == [identifier], result
    assert model.calls == ["review_overlap"]
    assert job_for(restarted, "q-regulation")["status"] == "linked"


def test_reuse_capture_receipt_loss_replays_exact_proposal(project, monkeypatch):
    worker, identifier = first_claim(project)
    record = worker.inbox.record_graph
    def lost(*args, **kwargs):
        record(*args, **kwargs)
        raise OSError("graph receipt lost")
    monkeypatch.setattr(worker.inbox, "record_graph", lost)
    result = worker.cycle()
    assert result["errors"] and result["saved"] == 0, result
    pending = job_for(worker, "q-regulation")
    graph_path = worker.root / "graph-jobs" / (pending["reuse"]["graph_job_id"] + ".json")
    proposal = json.loads(graph_path.read_text())["proposal"]
    restarted = ResearchRunner(project, provider=worker.provider, model=ReuseModel(), question_ids=["q-regulation"])
    restarted.model.extract = restarted.model.review = restarted.model.overlap = restarted.model.review_overlap = lambda *args: pytest.fail("Replay the captured proposal")
    result = restarted.cycle()
    assert result["replayed"] == 1 and result["links_added"] == 0, result
    assert json.loads(graph_path.read_text())["proposal"] == proposal
    assert job_for(restarted, "q-regulation")["status"] == "linked"
    assert len(list((project / ".atlas/graph-drafts").glob("*.json"))) == 1
    assert len(list((project / ".atlas/drafts").glob("*.json"))) == 1


def test_reuse_pending_publication_retries_saved_graph_receipt(project, monkeypatch):
    worker, identifier = first_claim(project)
    monkeypatch.setattr(worker.inbox, "_refresh", lambda: (_ for _ in ()).throw(ValueError("publication unavailable")))
    result = worker.cycle()
    assert result["errors"], result
    pending = job_for(worker, "q-regulation")
    assert pending["status"] == "retry" and pending["receipt"]["recorded"]
    assert pending["receipt"]["publication_status"] == "pending" and "record_id" not in pending["receipt"]
    restarted = ResearchRunner(project, provider=worker.provider, model=ReuseModel(), question_ids=["q-regulation"])
    result = restarted.cycle()
    assert result["replayed"] == 1 and not restarted.model.calls, result
    assert job_for(restarted, "q-regulation")["status"] == "linked"


def test_already_linked_assertion_does_not_propose_duplicate_relation(project):
    worker, identifier = first_claim(project)
    result = worker.cycle()
    assert result["links_added"] == 1, result
    worker.provider.paper = {"key": "pmid-alias", "provider_source": "MED", "provider_id": "123"}
    result = worker.cycle()
    assert result["saved"] == 0 and result["links_added"] == 0, result
    assert result["reused_record_ids"] == [identifier]
    assert worker.model.calls.count("overlap") == 1
    assert len(list((project / ".atlas/graph-drafts").glob("*.json"))) == 1


def test_negative_existing_link_holds_rediscovery_without_duplicate_capture(project):
    from workbench.research_graph_review import GraphReviewLedger
    worker, identifier = first_claim(project)
    result = worker.cycle()
    assert result["links_added"] == 1, result
    edge = next(r for r in worker.inbox.snapshot()["bundle"]["relations"] if r["id"] == result["relation_ids"][0])
    GraphReviewLedger(project).store(edge, {"verdict": "unsupported", "reason": "The comparison does not apply."}, model="changed-reviewer")
    worker.provider.paper = {"key": "pmid-alias", "provider_source": "MED", "provider_id": "123"}
    result = worker.cycle()
    assert result["saved"] == 0 and result["held"] == 1, result
    assert worker.model.calls.count("overlap") == 1
    assert len(list((project / ".atlas/drafts").glob("*.json"))) == 1


def test_captured_reuse_recovers_with_no_active_questions_at_capacity(project, monkeypatch):
    from workbench import research_runner
    worker, identifier = first_claim(project)
    record = worker.inbox.record_graph
    def lost(*args, **kwargs):
        record(*args, **kwargs)
        raise OSError("receipt lost")
    monkeypatch.setattr(worker.inbox, "record_graph", lost)
    assert worker.cycle()["errors"]
    withdraw_questions(project)
    monkeypatch.setattr(research_runner, "MAX_DRAFTS", 1)
    restarted = ResearchRunner(project, provider=worker.provider, model=ReuseModel(), question_ids=["q-regulation"])
    result = restarted.cycle()
    assert result["replayed"] == 1 and not result["errors"], result
    assert not restarted.model.calls
    assert job_for(restarted, "q-regulation")["status"] == "linked"
    assert restarted.state["frontiers"]["q-regulation"]["pending"] == []


def test_original_capture_recovers_with_no_active_questions_at_capacity(project, monkeypatch):
    from workbench import research_runner
    worker = ResearchRunner(project, provider=CachedPapers(), model=ReuseModel(), question_ids=["q-fate"])
    record = worker.inbox.record
    def lost(*args, **kwargs):
        record(*args, **kwargs)
        raise OSError("receipt lost")
    monkeypatch.setattr(worker.inbox, "record", lost)
    assert worker.cycle()["errors"]
    withdraw_questions(project)
    monkeypatch.setattr(research_runner, "MAX_DRAFTS", 1)
    restarted = ResearchRunner(project, provider=worker.provider, model=ReuseModel(), question_ids=["q-fate"])
    result = restarted.cycle()
    assert result["replayed"] == 1 and not result["errors"], result
    assert not restarted.model.calls
    assert job_for(restarted, "q-fate")["status"] == "recorded"
    assert restarted.state["frontiers"]["q-fate"]["pending"] == []


@pytest.mark.parametrize("graph", [False, True])
def test_uncaptured_prepared_submission_does_not_bypass_withdrawn_question(project, monkeypatch, graph):
    if graph:
        worker, identifier = first_claim(project)
        operation, question = "record_graph", "q-regulation"
    else:
        worker = ResearchRunner(project, provider=CachedPapers(), model=ReuseModel(), question_ids=["q-fate"])
        operation, question = "record", "q-fate"
    monkeypatch.setattr(worker.inbox, operation, lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("capture unavailable")))
    assert worker.cycle()["errors"]
    withdraw_questions(project)
    restarted = ResearchRunner(project, provider=worker.provider, model=ReuseModel(), question_ids=[question])
    result = restarted.cycle()
    assert result["saved"] == 0 and result["replayed"] == 0, result
    assert not restarted.model.calls
    assert not list((project / ".atlas/graph-drafts").glob("*.json"))
    assert len(list((project / ".atlas/drafts").glob("*.json"))) == int(graph)
    assert job_for(restarted, question)["status"] == ("held" if graph else "retry")
