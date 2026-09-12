"""Research capture must survive replay and preserve source boundaries."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from workbench.automation import ResearchInbox


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def project(tmp_path):
    data = tmp_path / "workbench/data"
    data.mkdir(parents=True)
    shutil.copyfile(ROOT / "workbench/data/cell_fate.json", data / "cell_fate.json")
    shutil.copytree(ROOT / "workbench/data/lighthouses", data / "lighthouses")
    shutil.copyfile(ROOT / "workbench/data/lighthouse-automation.json", data / "lighthouse-automation.json")
    return tmp_path


def document():
    return {
        "source": {"id": "epmc:MED:123", "title": "A controlled fate study", "url": "https://europepmc.org/article/MED/123",
                   "year": 2026, "citation": "Example authors. A controlled fate study. 2026."},
        "passages": [{"id": "abstract:1", "locator": "Abstract, paragraph 1",
                      "text": "Measured lineage outcomes differed from predicted cell fates in this mouse system."}],
        "coverage": "abstract_only", "retrieved_at": "2026-09-07T18:00:00+00:00",
        "content_sha256": hashlib.sha256(b"test source").hexdigest(),
        "document_url": "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=EXT_ID:123",
    }


class Papers:
    def search(self, query, cursor="*", limit=5):
        return {"papers": [{"key": "MED:123", "doi": "10.example/123"}], "next_cursor": None}

    def read(self, paper):
        return document()


class Model:
    model = "test-model"

    def plan(self, question, context, prior_queries):
        return '"cell fate" AND "lineage tracing"'

    def extract(self, question, doc, context):
        return {"model": self.model, "metrics": {"seconds": 0.1}, "analysis": {
            "relevant": True, "title": "Lineage outcomes can check fate predictions",
            "summary": "The study reports a mismatch between predicted fates and observed lineage outcomes.",
            "scope": "The mouse system described in the abstract.",
            "limitations": "Only the abstract was read; applicability to other systems is not established.",
            "passage_id": "abstract:1", "quote": "Measured lineage outcomes differed from predicted cell fates",
            "rationale": "Provides a scoped outcome check for the prediction question.",
        }}

    def review(self, question, doc, candidate):
        return {"model": self.model, "metrics": {}, "analysis": {
            "verdict": "supported", "reason": "The abstract reports this scoped mismatch.",
            "evidence": [{"passage_id": "abstract:1"}],
        }, "context_manifest": {"selected_record_ids": [], "selected_passage_ids": ["abstract:1"]}}


def runner(project, **kwargs):
    from workbench.research_runner import ResearchRunner
    return ResearchRunner(project, provider=Papers(), model=Model(), question_ids=["q-fate"], **kwargs)


def test_cycle_adds_sourced_claim_links_question_and_renders_live_graph(project):
    result = runner(project).cycle()
    assert result["saved"] == 1
    inbox = ResearchInbox(project)
    snapshot = inbox.snapshot()
    claims = [r for r in snapshot["bundle"]["items"] if r["provenance"].get("capture") == "session_draft"]
    assert len(claims) == 1
    claim = claims[0]
    assert claim["status"] == "proposed"
    assert claim["context"]["source_coverage"] == "abstract_only"
    assert claim["context"]["model"] == "test-model"
    assert claim["evidence"][0]["source_id"] == "epmc:MED:123"
    assert "Measured lineage outcomes differed" in claim["evidence"][0]["note"]
    assert {name for name, ids in snapshot["views"].items() if claim["id"] in ids} == {"prediction", "regulation"}
    link = next(r for r in snapshot["bundle"]["relations"] if r["subject"] == claim["id"])
    assert (link["predicate"], link["object"], link["status"]) == ("informs", "q-fate", "proposed")
    assert claim["title"] in (project / ".atlas/research/index.html").read_text()
    jobs = list((project / ".atlas/research/jobs").glob("*.json"))
    assert len(jobs) == 1
    job = json.loads(jobs[0].read_text())
    assert job["document"] == document()
    assert job["receipt"]["recorded"] is True
    assert result["research_views"]["status"] == "current"
    assert claim["title"] in Path(result["research_views"]["home"]).read_text()
    assert claim["title"] in Path(result["research_views"]["canvas"]).read_text()


def test_repeated_search_and_new_worker_resume_do_not_generate_duplicate_drafts(project):
    runner(project).cycle()
    result = runner(project).cycle()
    assert result["saved"] == 0
    assert ResearchInbox(project).status()["draft_count"] == 1


def test_capture_then_crash_replays_exact_prepared_draft(project, monkeypatch):
    worker = runner(project)
    original = worker.inbox.record

    def interrupted(draft, session_id):
        original(draft, session_id)
        raise OSError("simulated crash after capture")

    monkeypatch.setattr(worker.inbox, "record", interrupted)
    first = worker.cycle()
    assert first["errors"]
    assert worker.inbox.status()["draft_count"] == 1
    recovered = runner(project).cycle()
    assert not recovered["errors"]
    assert ResearchInbox(project).status()["draft_count"] == 1
    job = json.loads(next((project / ".atlas/research/jobs").glob("*.json")).read_text())
    assert job["receipt"]["duplicate"] is True


@pytest.mark.parametrize("change", [
    {"quote": "An invented result absent from the source"},
    {"passage_id": "invented-section"}, {"relevant": "true"},
    {"status": "reviewed"}, {"limitations": ""},
])
def test_invalid_model_claims_never_enter_graph(project, change):
    worker = runner(project)
    original = worker.model.extract
    worker.model.extract = lambda *args: original(*args) | {"analysis": original(*args)["analysis"] | change}
    result = worker.cycle()
    assert result["errors"]
    assert worker.inbox.status()["draft_count"] == 0


def test_irrelevant_paper_is_remembered_without_recording_a_claim(project):
    worker = runner(project)
    worker.model.extract = lambda *args: {"model": "test-model", "metrics": {}, "analysis": {"relevant": False}}
    assert worker.cycle()["skipped"] == 1
    assert runner(project).cycle()["saved"] == 0
    assert ResearchInbox(project).status()["draft_count"] == 0


def test_pending_publication_keeps_record_and_recovers_without_regeneration(project, monkeypatch):
    worker = runner(project)
    refresh = worker.inbox._refresh
    monkeypatch.setattr(worker.inbox, "_refresh", lambda: (_ for _ in ()).throw(OSError("publication disk error")))
    result = worker.cycle()
    assert result["saved"] == 1
    assert result["publication_status"] == "pending"
    assert result["errors"]
    monkeypatch.setattr(worker.inbox, "_refresh", refresh)
    result = runner(project).cycle()
    assert result["publication_status"] == "current"
    assert ResearchInbox(project).status()["draft_count"] == 1


def test_stop_between_fetch_and_analysis_prevents_capture(project):
    stopped = False
    worker = runner(project, should_stop=lambda: stopped)
    def fetch(paper):
        nonlocal stopped
        stopped = True
        return document()
    worker.provider.read = fetch
    worker.cycle()
    assert worker.inbox.status()["draft_count"] == 0


def test_existing_source_metadata_is_reused_by_canonical_url(project):
    worker = runner(project)
    original_doc = document()
    pilot = json.loads((project / "workbench/data/cell_fate.json").read_text())
    existing = pilot["sources"][0]
    original_doc["source"] = deepcopy(existing) | {"id": "epmc:MED:123", "title": "Different metadata rendering"}
    worker.provider.read = lambda paper: original_doc
    worker.cycle()
    snapshot = worker.inbox.snapshot()["bundle"]
    assert len(snapshot["sources"]) == len(pilot["sources"])
    claim = next(i for i in snapshot["items"] if i["provenance"].get("capture"))
    assert claim["evidence"][0]["source_id"] == existing["id"]


def test_full_inbox_stops_research_before_more_model_work(project, monkeypatch):
    from workbench import research_runner
    worker = runner(project)
    worker.cycle()
    monkeypatch.setattr(research_runner, "MAX_DRAFTS", 1)
    result = worker.cycle()
    assert "capacity" in str(result["errors"])
    assert worker.inbox.status()["draft_count"] == 1


def test_transient_outage_does_not_permanently_discard_the_paper(project):
    worker = runner(project)
    successful_read = worker.provider.read
    def unavailable(paper):
        raise RuntimeError("temporary provider outage")
    worker.provider.read = unavailable
    for _ in range(4):
        assert worker.cycle()["errors"]
    worker.provider.read = successful_read
    recovered = worker.cycle()
    assert recovered["saved"] == 1
    assert worker.inbox.status()["draft_count"] == 1


def test_capacity_still_allows_saved_publication_to_recover(project, monkeypatch):
    from workbench import research_runner
    worker = runner(project)
    refresh = worker.inbox._refresh
    monkeypatch.setattr(worker.inbox, "_refresh", lambda: (_ for _ in ()).throw(OSError("publication disk error")))
    assert worker.cycle()["saved"] == 1
    monkeypatch.setattr(worker.inbox, "_refresh", refresh)
    monkeypatch.setattr(research_runner, "MAX_DRAFTS", 1)
    result = worker.cycle()
    assert result["publication_status"] == "current"
    assert (project / ".atlas/research/index.html").exists()
    assert worker.inbox.status()["draft_count"] == 1
