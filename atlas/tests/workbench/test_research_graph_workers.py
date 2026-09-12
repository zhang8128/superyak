"""Fresh question and overlap passes must grow shared evidence without copies."""

import json

import pytest

from test_research_connections import researcher, ConnectorModel
from test_research_runner import project


class GraphModel(ConnectorModel):
    def overlap(self, question, packet, *, record_kinds=None):
        links = []
        for source in packet["sources"]:
            passage = next(p for p in packet["document"]["passages"] if p["id"] in source["passage_ids"])
            links.append({"record_id": source["record_id"], "rationale": "This measured mismatch motivates a scoped outcome check.",
                          "predicate": {"claim": "informs", "approach": "addresses", "experiment": "tests"}[
                              (record_kinds or {}).get(source["record_id"], "claim")], "answer_scope": "", "remaining": "",
                          "evidence": [{"passage_id": passage["id"], "quote": " ".join(passage["text"].split()[:8])}]})
        return {"model": self.model, "analysis": {"links": links, "reason": "Each source informs the question."}}

    def review_overlap(self, question, packet, candidate):
        return {"model": self.model, "analysis": {"decisions": [
            {"record_id": link["record_id"], "predicate": link.get("predicate", "informs"),
             "verdict": "supported", "reason": "The scoped observation is relevant.",
             "evidence": [{"passage_id": entry["passage_id"]} for entry in link["evidence"]]}
            for link in candidate["links"]]}}

    def propose_question(self, anchor, packet, questions, views):
        return {"model": self.model, "analysis": {
            "useful": True, "title": "Which independent measurement resolves the observed prediction mismatch?",
            "summary": "Identify the measured outcome needed to compare these predictions.",
            "scope": "The supplied mouse systems.", "limitations": "Abstract evidence only.",
            "motivation": "The supplied sources report mismatched outcomes.",
            "advance": "A measured lineage outcome held out from fitting.", "duplicate_of": "",
            "parents": [q["id"] for q in questions if q.get("eligible_parent")][:2], "views": list(views),
            "premises": [r["id"] for r in packet["records"]],
            "evidence": [{"passage_id": p["id"], "quote": " ".join(p["text"].split()[:8])}
                         for p in packet["document"]["passages"]]}}

    def review_question(self, anchor, packet, candidate, questions, views, *, premise_predicate="raises_question"):
        owners = {source["record_id"]: set(source["passage_ids"]) for source in packet["sources"]}
        evidence = [{"passage_id": entry["passage_id"]} for entry in candidate["evidence"]]
        relations = [{"kind": "parent", "record_id": identifier, "verdict": "supported",
                      "reason": f"The scoped measurement resolves a specific subproblem of {identifier}.",
                      "evidence": evidence} for identifier in candidate["parents"]]
        relations += [{"kind": "premise", "record_id": identifier, "verdict": "supported",
                       "reason": f"The original observation in {identifier} motivates the requested measurement.",
                       "evidence": [entry for entry in evidence if entry["passage_id"] in owners[identifier]]}
                      for identifier in candidate["premises"]]
        return {"model": self.model, "analysis": {"verdict": "useful", "reason": "Specific grounded measurement question.",
            "duplicate_of": "", "evidence": evidence, "relations": relations}}


def setup(researcher):
    researcher.model = GraphModel()
    researcher.question_ids = None
    return researcher


def test_overlap_links_existing_findings_to_another_question_without_copies(researcher):
    from workbench.research_overlap import OverlapWorker
    from workbench.research_evidence import eligible_inputs
    worker = setup(researcher)
    before = worker.inbox.snapshot()
    result = OverlapWorker(worker).cycle()
    assert result["links_added"] == 2, result
    after = worker.inbox.snapshot()
    assert len(after["bundle"]["items"]) == len(before["bundle"]["items"])
    assert len(eligible_inputs(worker, after)) == 2
    for identifier in eligible_inputs(worker, after):
        questions = {r["object"] for r in after["bundle"]["relations"] if r["subject"] == identifier and r["predicate"] == "informs"}
        assert questions == {"q-fate", "q-regulation"}
    assert OverlapWorker(worker).cycle()["links_added"] == 0


def test_question_has_multiple_parents_and_existing_evidence_then_gets_researched(researcher):
    from workbench.research_questions import QuestionWorker
    from workbench.research_overlap import OverlapWorker
    from workbench.research_agenda import QuestionAgenda
    worker = setup(researcher)
    result = QuestionWorker(worker).cycle()
    assert result["saved"] == 1, result
    identifier = result["record_ids"][0]
    snapshot = worker.inbox.snapshot()
    parents = {r["object"] for r in snapshot["bundle"]["relations"] if r["subject"] == identifier and r["predicate"] == "part_of"}
    assert parents == {"q-fate", "q-regulation"}
    assert len([r for r in snapshot["bundle"]["relations"] if r["object"] == identifier and r["predicate"] == "raises_question"]) == 2
    agenda = QuestionAgenda(worker.project)
    assert identifier not in {q["id"] for q in agenda.eligible(snapshot)}
    OverlapWorker(worker).cycle()
    assert identifier in {q["id"] for q in agenda.eligible(worker.inbox.snapshot())}


def test_overlap_review_can_accept_one_link_and_hold_another(researcher):
    from workbench.research_overlap import OverlapWorker
    worker = setup(researcher)
    review = worker.model.review_overlap
    def partial(*args):
        result = review(*args)
        result["analysis"]["decisions"][1].update(verdict="uncertain", evidence=[])
        return result
    worker.model.review_overlap = partial
    result = OverlapWorker(worker).cycle()
    assert result["links_added"] == 1 and result["held"] == 1, result


def test_question_duplicate_review_creates_no_new_record(researcher):
    from workbench.research_questions import QuestionWorker
    worker = setup(researcher)
    worker.model.review_question = lambda *args: {"analysis": {"verdict": "duplicate", "reason": "Same measurement question.",
                                                            "duplicate_of": "q-fate", "evidence": [], "relations": []}, "model": worker.model.model}
    before = worker.inbox.snapshot()
    result = QuestionWorker(worker).cycle()
    assert result["saved"] == 0 and result["skipped"] == 1, result
    assert worker.inbox.snapshot() == before


def test_overlap_reuses_candidate_after_review_outage(researcher):
    from workbench.research_overlap import OverlapWorker
    worker = setup(researcher)
    review = worker.model.review_overlap
    worker.model.review_overlap = lambda *args: (_ for _ in ()).throw(RuntimeError("offline"))
    assert OverlapWorker(worker).cycle()["errors"]
    worker.model.review_overlap = review
    worker.model.overlap = lambda *args: pytest.fail("Candidate must survive restart")
    assert OverlapWorker(worker).cycle()["links_added"] == 2


def test_capture_receipt_loss_replays_without_duplicate_question(researcher, monkeypatch):
    from workbench.research_questions import QuestionWorker
    worker = setup(researcher)
    record = worker.inbox.record_graph
    def lost(*args, **kwargs):
        record(*args, **kwargs)
        raise OSError("receipt lost")
    monkeypatch.setattr(worker.inbox, "record_graph", lost)
    assert QuestionWorker(worker).cycle()["errors"]
    monkeypatch.setattr(worker.inbox, "record_graph", record)
    worker.model.propose_question = lambda *args: pytest.fail("Captured proposal must be replayed")
    result = QuestionWorker(worker).cycle()
    assert result["replayed"] == 1 and result["saved"] == 0, result
    assert len([r for r in worker.inbox.snapshot()["bundle"]["items"] if r["context"].get("worker_role") == "question"]) == 1


def test_question_capture_retains_each_initial_relations_own_reason_and_evidence(researcher):
    from workbench.research_questions import QuestionWorker
    worker = setup(researcher)
    result = QuestionWorker(worker).cycle()
    assert result["saved"] == 1 and not result["errors"], result
    job = json.loads(next((worker.root / "graph-jobs").glob("*.json")).read_text())
    decisions = {(r["kind"], r["record_id"]): r for r in job["review"]["analysis"]["relations"]}
    passages = {p["id"]: p for p in job["packet"]["document"]["passages"]}
    relations = {r["id"]: r for r in worker.inbox.snapshot()["bundle"]["relations"]}
    for identifier in result["relation_ids"]:
        relation = relations[identifier]
        key = ("parent", relation["object"]) if relation["predicate"] == "part_of" else ("premise", relation["subject"])
        decision = decisions[key]
        assert relation["rationale"] == relation["context"]["review_reason"] == decision["reason"]
        assert relation["context"]["review_verdict"] == "supported"
        assert {(e["source_id"], e["locator"]) for e in relation["evidence"]} == {
            (passages[e["passage_id"]]["source_id"], passages[e["passage_id"]]["locator"]) for e in decision["evidence"]}
    assert len({relations[identifier]["rationale"] for identifier in result["relation_ids"]}) == len(result["relation_ids"])


@pytest.mark.parametrize("kind,verdict", [("parent", "unsupported"), ("premise", "uncertain")])
def test_one_unsafe_initial_relation_holds_the_whole_question(researcher, kind, verdict):
    from workbench.research_questions import QuestionWorker
    worker = setup(researcher)
    review = worker.model.review_question
    def reject(*args):
        result = review(*args)
        decision = next(r for r in result["analysis"]["relations"] if r["kind"] == kind)
        decision.update(verdict=verdict, reason="The scoped relation lacks support.")
        return result
    worker.model.review_question = reject
    before = worker.inbox.snapshot()
    result = QuestionWorker(worker).cycle()
    assert result["saved"] == 0 and result["held"] == 1 and not result["errors"], result
    assert worker.inbox.snapshot() == before


def test_overlap_classifies_existing_generic_pairs_once_without_upgrading_original_links(researcher):
    from workbench.research_overlap import OverlapWorker
    worker = setup(researcher)
    worker.question_ids = ["q-fate"]
    original = worker.model.overlap
    def answer(*args, **kwargs):
        result = original(*args, **kwargs)
        for link in result["analysis"]["links"]:
            link.update(predicate="partially_answers", answer_scope="Observed lineage outcomes in the supplied mouse system.",
                        remaining="The supplied excerpts do not establish transfer to other systems.")
        return result
    worker.model.overlap = answer
    before = worker.inbox.snapshot()
    result = OverlapWorker(worker).cycle()
    assert result["links_added"] == 2 and not result["errors"], result
    after = worker.inbox.snapshot()
    by_id = {r["id"]: r for r in after["bundle"]["relations"]}
    assert all(by_id[r["id"]] == r for r in before["bundle"]["relations"])
    assert len(after["bundle"]["items"]) == len(before["bundle"]["items"])
    for identifier in result["relation_ids"]:
        edge = by_id[identifier]
        assert edge["predicate"] == "partially_answers" and edge["status"] == "proposed"
        assert edge["context"]["answer_scope"] and edge["context"]["remaining"]
    worker.model.overlap = lambda *args, **kwargs: pytest.fail("Already classified pairs must be skipped")
    assert OverlapWorker(worker).cycle()["links_added"] == 0


def test_overlap_skips_duplicate_generic_fallback_and_keeps_other_reviewed_links(researcher):
    from workbench.research_overlap import OverlapWorker
    worker = setup(researcher)
    worker.question_ids = ["q-fate"]
    original = worker.model.overlap
    def mixed(*args, **kwargs):
        result = original(*args, **kwargs)
        result["analysis"]["links"][1].update(predicate="raises_question", remaining="Which independent lineage readout resolves this mismatch?")
        return result
    worker.model.overlap = mixed
    result = OverlapWorker(worker).cycle()
    assert result["links_added"] == 1 and result["skipped"] == 1 and not result["errors"], result
    edge = next(r for r in worker.inbox.snapshot()["bundle"]["relations"] if r["id"] == result["relation_ids"][0])
    assert edge["predicate"] == "raises_question"
    assert OverlapWorker(worker).cycle()["links_added"] == 0


def test_overlap_new_jobs_bind_record_kinds_without_changing_original_packets(researcher):
    from workbench.research_overlap import OverlapWorker
    worker = setup(researcher)
    job = OverlapWorker(worker).select()
    assert job["revision"] == "question-overlap-v3"
    assert job["record_kinds"] == {r["id"]: "claim" for r in job["packet"]["records"]}
    assert all("kind" not in record for record in job["packet"]["records"])


@pytest.mark.parametrize("reviewed", [False, True])
def test_legacy_pending_overlap_keeps_raw_candidate_and_generic_capture_semantics(researcher, reviewed):
    from copy import deepcopy
    from workbench.research_overlap import OverlapWorker
    worker = setup(researcher)
    connector = OverlapWorker(worker)
    job = connector.select()
    job["revision"] = "question-overlap-v2"
    job.pop("record_kinds", None)
    job["candidate"] = worker.model.overlap(job["question"], job["packet"])
    for link in job["candidate"]["analysis"]["links"]:
        for field in ("predicate", "answer_scope", "remaining"):
            link.pop(field)
    original = deepcopy(job["candidate"])
    original_review = None
    if reviewed:
        job["review"] = worker.model.review_overlap(job["question"], job["packet"], job["candidate"]["analysis"])
        for decision in job["review"]["analysis"]["decisions"]:
            decision.pop("predicate")
        original_review = deepcopy(job["review"])
    connector.save(job)
    review = worker.model.review_overlap
    def inspect(question, packet, candidate):
        assert not reviewed, "The saved legacy review must replay unchanged"
        assert all(link["predicate"] == "informs" for link in candidate["links"])
        return review(question, packet, candidate)
    worker.model.review_overlap = inspect
    worker.model.overlap = lambda *args, **kwargs: pytest.fail("Legacy candidates must survive the revision")
    result = connector.cycle()
    assert result["links_added"] == 2 and not result["errors"], result
    saved = json.loads((connector.root / (job["id"] + ".json")).read_text())
    assert saved["candidate"] == original and "record_kinds" not in saved
    if reviewed:
        assert saved["review"] == original_review
    edges = {r["id"]: r for r in worker.inbox.snapshot()["bundle"]["relations"]}
    assert all(edges[i]["predicate"] == "informs" and "answer_scope" not in edges[i]["context"] for i in result["relation_ids"])


@pytest.mark.parametrize("revision", ["question-overlap-v1", "question-overlap-v2"])
def test_legacy_pending_question_retains_generic_premise_links(researcher, revision):
    from workbench.research_questions import QuestionWorker
    worker = setup(researcher)
    questions = QuestionWorker(worker)
    job = questions.select()
    job["revision"] = revision
    review = worker.model.review_question
    def inspect(*args, **kwargs):
        assert kwargs == {"premise_predicate": "informs"}
        return review(*args, **kwargs)
    worker.model.review_question = inspect
    if revision.endswith("v1"):
        job["candidate"] = questions.generate(job)
        job["review"] = questions.review(job)
        del job["review"]["analysis"]["relations"]
    questions.save(job)
    result = questions.cycle()
    assert result["saved"] == 1 and not result["errors"], result
    edges = {r["id"]: r for r in worker.inbox.snapshot()["bundle"]["relations"]}
    assert {edges[i]["predicate"] for i in result["relation_ids"]} == {"part_of", "informs"}
    if revision.endswith("v1"):
        assert all(edges[i]["rationale"] == job["candidate"]["analysis"]["motivation"] for i in result["relation_ids"])
