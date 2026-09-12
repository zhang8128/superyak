"""Graph assessments remain independent and capture rechecks every chosen parent."""

from copy import deepcopy
import json

import pytest

from test_research_graph_audit import recorded_graph
from test_research_graph_workers import researcher, setup
from test_research_runner import project

from workbench.research_graph_review import GraphReviewLedger, exclusions
from workbench.research_graph import graph_digest


def test_graph_review_ledger_rejects_a_file_in_place_of_its_directory(tmp_path):
    directory = tmp_path / ".atlas/research"
    directory.mkdir(parents=True)
    (directory / "graph-reviews").write_text("Unexpected state file")
    with pytest.raises(ValueError, match="director"):
        GraphReviewLedger(tmp_path).current({"bundle": {"items": [], "relations": []}})


def saved_review(project):
    record = {"id": "test-record", "summary": "A stable scoped record"}
    ledger = GraphReviewLedger(project)
    result = {"analysis": {"verdict": "supported", "reason": "The supplied observation supports the scoped account."},
              "audit_input_digest": "a" * 64, "details": {"attempts": [1, 2]}}
    entry = ledger.store(record, result, model="test-model")
    return ledger, record, entry


def test_ledger_accepts_project_strings_and_preserves_full_result_without_read_writes(tmp_path):
    ledger, record, entry = saved_review(str(tmp_path))
    path = ledger.root / (graph_digest(entry) + ".json")
    before, stamp = path.read_bytes(), path.stat().st_mtime_ns
    current = GraphReviewLedger(str(tmp_path)).current({"bundle": {"items": [record], "relations": []}})
    assert current[record["id"]] == entry
    assert current[record["id"]]["result"]["audit_input_digest"] == "a" * 64
    assert current[record["id"]]["result"]["details"] == {"attempts": [1, 2]}
    assert path.read_bytes() == before and path.stat().st_mtime_ns == stamp


def test_latest_review_uses_timestamp_order_across_timezone_offsets(tmp_path, monkeypatch):
    from workbench import research_graph_review

    times = iter(("2026-09-09T14:30:00+02:00", "2026-09-09T13:00:00Z"))
    monkeypatch.setattr(research_graph_review, "_now", lambda: next(times))
    ledger, record, _ = saved_review(tmp_path)
    ledger.store(record, {"verdict": "unsupported", "reason": "A later independent review rejected the transfer."},
                 model="later-reviewer")
    current = ledger.current({"bundle": {"items": [record], "relations": []}})
    assert current[record["id"]]["verdict"] == "unsupported"


@pytest.mark.parametrize("field,value", [("version", True), ("stage", "manual"), ("verdict", "useful"),
                                         ("model", ""), ("reason", " "), ("record_id", ""),
                                         ("record_digest", "not-a-digest"), ("checked_at", "today"),
                                         ("checked_at", "2026-09-09T12:00:00"), ("result", [])])
def test_ledger_rejects_invalid_entries_even_with_matching_content_filename(tmp_path, field, value):
    ledger, record, entry = saved_review(tmp_path)
    original_path = ledger.root / (graph_digest(entry) + ".json")
    entry[field] = value
    original_path.unlink()
    path = ledger.root / (graph_digest(entry) + ".json")
    path.write_text(json.dumps(entry))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="[Gg]raph review"):
        ledger.current({"bundle": {"items": [record], "relations": []}})
    assert path.read_bytes() == before


@pytest.mark.parametrize("change", ["missing", "extra", "changed-content"])
def test_ledger_rejects_missing_unknown_or_unbound_saved_fields(tmp_path, change):
    ledger, record, entry = saved_review(tmp_path)
    path = ledger.root / (graph_digest(entry) + ".json")
    if change == "missing":
        del entry["reason"]
    elif change == "extra":
        entry["unexpected"] = True
    else:
        entry["reason"] = "Changed explanation inside an existing journal entry."
    path.write_text(json.dumps(entry))
    with pytest.raises(ValueError, match="[Gg]raph review"):
        ledger.current({"bundle": {"items": [record], "relations": []}})


@pytest.mark.parametrize("operation", ["current", "store"])
def test_existing_ledger_object_rechecks_parent_symlinks_before_access(tmp_path, operation):
    project, outside = tmp_path / "project", tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    ledger = GraphReviewLedger(project)
    (project / ".atlas").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        if operation == "current":
            ledger.current({"bundle": {"items": [], "relations": []}})
        else:
            ledger.store({"id": "record"}, {"verdict": "supported", "reason": "Source checked."}, model="test")
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("field,value", [("model", ""), ("reason", ""), ("stage", "unexpected")])
def test_invalid_review_store_creates_no_state(tmp_path, field, value):
    ledger = GraphReviewLedger(tmp_path)
    arguments = {"model": "test-model", "reason": "Source checked.", "stage": "audit", field: value}
    with pytest.raises(ValueError, match="[Gg]raph review"):
        ledger.store({"id": "record"}, {"verdict": "supported", "reason": "Source checked."}, **arguments)
    assert not (tmp_path / ".atlas").exists()


@pytest.mark.parametrize("changed", ["source", "endpoint"])
def test_changed_binding_excludes_only_affected_graph_edges(researcher, changed):
    job = recorded_graph(researcher, count=1)
    original = researcher.inbox.snapshot()
    snapshot = deepcopy(original)
    if changed == "source":
        identifier = job["packet"]["sources"][0]["id"]
        next(r for r in snapshot["bundle"]["sources"] if r["id"] == identifier)["title"] += " corrected"
    else:
        identifier = job["question"]["id"]
        next(r for r in snapshot["bundle"]["items"] if r["id"] == identifier)["summary"] += " changed scope"
    rejected = exclusions(researcher.project, snapshot)
    assert rejected == set(job["receipt"]["relation_ids"])
    assert job["packet"]["records"][0]["id"] not in rejected
    assert researcher.inbox.snapshot() == original


@pytest.mark.parametrize("field", ["input_digests", "source_digests"])
@pytest.mark.parametrize("invalid", [[], None, {"record": 42}, {"record": "not-a-digest"}])
def test_malformed_digest_maps_exclude_only_the_affected_overlap_edge(researcher, field, invalid):
    job = recorded_graph(researcher)
    original = researcher.inbox.snapshot()
    changed = deepcopy(original)
    relation = next(r for r in changed["bundle"]["relations"] if r["id"] == job["receipt"]["relation_ids"][0])
    relation["context"][field] = json.dumps(invalid)
    assert exclusions(researcher.project, changed) == {relation["id"]}
    assert researcher.inbox.snapshot() == original


def test_replaying_capture_does_not_override_a_later_negative_audit(researcher):
    from workbench.research_graph_work import GraphWork

    job = recorded_graph(researcher, count=1)
    snapshot = researcher.inbox.snapshot()
    relation = next(r for r in snapshot["bundle"]["relations"] if r["id"] in job["receipt"]["relation_ids"])
    ledger = GraphReviewLedger(researcher.project)
    ledger.store(relation, {"analysis": {"verdict": "unsupported", "reason": "The target scope does not match."}},
                 model="independent-reviewer", stage="audit")
    before = {path.name: path.read_bytes() for path in ledger.root.glob("*.json")}
    GraphWork(researcher, "overlap").submit(job, {"errors": []})
    current = ledger.current(snapshot)[relation["id"]]
    assert current["stage"] == "audit" and current["verdict"] == "unsupported"
    assert {path.name: path.read_bytes() for path in ledger.root.glob("*.json")} == before
    assert exclusions(researcher.project, snapshot) == {relation["id"]}


def test_rejected_initial_evidence_link_suspends_question_without_rejecting_source_claims(researcher):
    job = recorded_graph(researcher, "question")
    snapshot = researcher.inbox.snapshot()
    question_id = job["receipt"]["record_ids"][0]
    initial = next(r for r in snapshot["bundle"]["relations"]
                   if r["id"] in job["receipt"]["relation_ids"] and r["predicate"] == "raises_question")
    GraphReviewLedger(researcher.project).store(initial, {
        "analysis": {"verdict": "unsupported", "reason": "This observation does not motivate the proposed gap."}},
        model="independent-reviewer")
    rejected = exclusions(researcher.project, snapshot)
    assert question_id in rejected
    assert set(job["receipt"]["relation_ids"]) <= rejected
    assert not ({r["id"] for r in job["packet"]["records"]} & rejected)
    assert researcher.inbox.snapshot() == snapshot


def test_question_parent_rejected_during_review_cannot_be_captured(researcher):
    from workbench.research_questions import QuestionWorker

    worker = setup(researcher)
    review = worker.model.review_question
    rejected_parents = []

    def reject_other_parent(anchor, packet, candidate, questions, views):
        result = review(anchor, packet, candidate, questions, views)
        parent_id = next(identifier for identifier in candidate["parents"] if identifier != anchor["id"])
        parent = next(r for r in worker.inbox.snapshot()["bundle"]["items"] if r["id"] == parent_id)
        GraphReviewLedger(worker.project).store(parent, {
            "analysis": {"verdict": "unsupported", "reason": "Parent premises require reassessment."}},
            model="independent-reviewer")
        rejected_parents.append(parent_id)
        return result

    worker.model.review_question = reject_other_parent
    result = QuestionWorker(worker).cycle()
    assert rejected_parents
    assert result["saved"] == 0, result
    assert result["links_added"] == 0
    assert not [r for r in worker.inbox.snapshot()["bundle"]["items"]
                if r["context"].get("worker_role") == "question"]
