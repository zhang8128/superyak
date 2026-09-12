"""Explicit answer edges preserve source identity and exact review semantics."""

from copy import deepcopy
import json

import pytest

from test_research_graph_audit import recorded_graph
from test_research_graph_workers import researcher
from test_research_runner import project
from workbench.research_evidence import eligible_inputs, question_links
from workbench.research_graph_audit import audit_graph
from workbench.research_graph_review import exclusions


@pytest.mark.parametrize("predicate", ["answers", "partially_answers", "raises_question"])
def test_typed_neighbors_and_negative_edge_audit_preserve_original_claim(researcher, predicate):
    original_inputs = eligible_inputs(researcher, researcher.inbox.snapshot())
    job = recorded_graph(researcher, predicate=predicate, count=1)
    identifier = job["packet"]["records"][0]["id"]
    snapshot = researcher.inbox.snapshot()
    assert question_links(snapshot, identifier) == {"q-fate", "q-regulation"}
    review = researcher.model.review_overlap

    def reject(*args):
        result = review(*args)
        decision, = result["analysis"]["decisions"]
        assert decision["predicate"] == predicate
        decision.update(verdict="unsupported", reason="This source does not establish this target relationship.")
        return result

    researcher.model.review_overlap = reject
    outcome = audit_graph(researcher)
    assert outcome["verdicts"] == {"unsupported": 1} and not outcome["errors"], outcome
    rejected = exclusions(researcher.project, snapshot)
    assert rejected == set(job["receipt"]["relation_ids"])
    assert question_links(snapshot, identifier, excluded_relations=rejected) == {"q-fate"}
    assert eligible_inputs(researcher, snapshot) == original_inputs


def test_fresh_audit_cannot_replace_an_answer_with_a_weaker_predicate(researcher):
    job = recorded_graph(researcher, predicate="answers", count=1)
    review = researcher.model.review_overlap

    def weaken(*args):
        result = review(*args)
        result["analysis"]["decisions"][0]["predicate"] = "informs"
        return result

    researcher.model.review_overlap = weaken
    outcome = audit_graph(researcher)
    assert outcome["reviewed"] == outcome["held"] == 0
    assert outcome["errors"][0]["kind"] == "invalid_review"
    assert exclusions(researcher.project, researcher.inbox.snapshot()) == set()


def test_unlinked_packet_record_kind_change_does_not_invalidate_an_answer(researcher):
    from workbench.research_graph_audit import _bind_job
    job = recorded_graph(researcher, predicate="partially_answers", links_count=1)
    snapshot = deepcopy(researcher.inbox.snapshot())
    unrelated = job["packet"]["records"][1]["id"]
    next(r for r in snapshot["bundle"]["items"] if r["id"] == unrelated)["kind"] = "approach"
    record = next(r for r in snapshot["bundle"]["relations"] if r["id"] == job["receipt"]["relation_ids"][0])
    entry = next(e for e in researcher.inbox._graph_entries(snapshot["views"])
                 if e["id"] == job["receipt"]["graph_draft_id"])
    assert _bind_job(researcher, snapshot, record, entry) == job


@pytest.mark.parametrize("change", ["kind", "missing-map"])
def test_kind_map_is_bound_to_capture_and_checked_against_current_records(researcher, change):
    from workbench.research_graph_work import GraphWork
    job = recorded_graph(researcher, count=1)
    work = GraphWork(researcher, "overlap")
    altered = deepcopy(job)
    if change == "kind":
        altered["record_kinds"][job["packet"]["records"][0]["id"]] = "experiment"
        with pytest.raises(ValueError, match="changed|kind"):
            work.guard(altered, researcher.inbox.snapshot())
    else:
        del altered["record_kinds"]
    work.save(altered)
    researcher.model.review_overlap = lambda *args: pytest.fail("Changed captured kinds must not reach the model")
    outcome = audit_graph(researcher)
    assert outcome["verdicts"] == {"uncertain": 1} and outcome["held"] == 1


@pytest.mark.parametrize("revision", ["question-overlap-v1", "question-overlap-v2"])
@pytest.mark.parametrize("role", ["question", "overlap"])
def test_old_jobs_replay_exactly_and_receive_fresh_current_reviews(researcher, revision, role):
    from workbench.research_graph_work import GraphWork
    job = recorded_graph(researcher, role, revision=revision, count=1)
    before = deepcopy(job)
    snapshot = researcher.inbox.snapshot()
    assert job["proposal"]["context"]["worker_revision"] == revision
    assert "record_kinds_digest" not in job["proposal"]["context"]
    if role == "question":
        review = researcher.model.review_question
        def inspect(*args, **kwargs):
            assert kwargs == {"premise_predicate": "informs"}
            return review(*args, **kwargs)
        researcher.model.review_question = inspect
    outcome = audit_graph(researcher, limit=len(job["receipt"]["record_ids"] + job["receipt"]["relation_ids"]))
    assert not outcome["errors"] and outcome["held"] == 0, outcome
    assert outcome["reviewed"] == len(job["receipt"]["record_ids"] + job["receipt"]["relation_ids"])
    assert json.loads((researcher.root / "graph-jobs" / (job["id"] + ".json")).read_text()) == before
    result = {"errors": []}
    GraphWork(researcher, role).submit(job, result)
    assert result["replayed"] == 1 and result["saved"] == result["links_added"] == 0
    assert researcher.inbox.snapshot() == snapshot


@pytest.mark.parametrize("predicate", ["answers", "partially_answers", "raises_question"])
def test_reuse_recognizes_existing_typed_link_without_another_proposal(project, predicate):
    from test_research_reuse import first_claim, job_for
    from workbench.research_reuse import reuse_claim
    from workbench.research_graph import graph_digest
    worker, identifier = first_claim(project)
    before = worker.inbox.snapshot()
    claim = next(r for r in before["bundle"]["items"] if r["id"] == identifier)
    worker.inbox.record_graph({"idempotency_key": "typed-reuse:" + predicate, "question": None,
        "relations": [{"subject": identifier, "predicate": predicate, "object": "q-regulation",
                       "rationale": "A separately reviewed connection to the target question.",
                       "evidence": claim["evidence"], "context": {}}],
        "expected": {r["id"]: graph_digest(r) for kind in ("items", "sources") for r in before["bundle"][kind]
                     if r["id"] in {identifier, "q-regulation", *(e["source_id"] for e in claim["evidence"]) }},
        "context": {}}, "test-answer-reuse")
    original = job_for(worker, "q-fate")
    job = deepcopy(original) | {"id": "reuse-typed-test", "question_id": "q-regulation", "status": "pending"}
    job.pop("receipt")
    snapshot = worker.inbox.snapshot()
    question = next(r for r in snapshot["bundle"]["items"] if r["id"] == "q-regulation")
    calls_before = list(worker.model.calls)
    result = {"held": 0, "errors": []}
    assert reuse_claim(worker, job, question, snapshot, original["extraction"]["analysis"], result)
    assert job["status"] == "linked" and job["reuse"]["existing"]
    assert result["links_added"] == 0 and result["reused_record_ids"] == [identifier]
    assert worker.model.calls == calls_before
