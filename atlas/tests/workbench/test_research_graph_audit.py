"""Later graph audits bind the captured job and assess each relationship separately."""

import json

import pytest

from test_research_graph_workers import GraphModel, researcher
from test_research_runner import project


def recorded_graph(researcher, role="overlap", *, count=2, reverse_premises=False,
                   predicate="informs", revision=None, links_count=None):
    from workbench.research_graph import graph_digest
    from workbench.research_graph_work import GraphWork, graph_inputs, question_catalog, evidence
    from workbench.research_evidence import make_packet

    researcher.model = GraphModel()
    researcher.question_ids = None
    snapshot = researcher.inbox.snapshot()
    inputs = list(graph_inputs(researcher, snapshot).values())[:count]
    packet = make_packet(inputs)
    anchor = next(r for r in snapshot["bundle"]["items"] if r["id"] == "q-regulation")
    questions = [{"id": r["id"], "title": r["title"], "summary": r["summary"], "eligible_parent": True}
                 for r in snapshot["bundle"]["items"] if r["kind"] == "question"]
    work = GraphWork(researcher, role)
    extra = {"questions": questions, "views": list(snapshot["views"]), "question_catalog": question_catalog(snapshot)} if role == "question" else {}
    if role == "overlap" and revision not in {"question-overlap-v1", "question-overlap-v2"}:
        extra["record_kinds"] = {item["record"]["id"]: item["record"]["kind"] for item in inputs}
    if revision:
        extra["revision"] = revision
    job = work.new_job(anchor, packet, **extra)
    if role == "overlap":
        job["candidate"] = researcher.model.overlap(anchor, packet)
        candidate = job["candidate"]["analysis"]
        if links_count is not None:
            candidate["links"] = candidate["links"][:links_count]
        for link in candidate["links"]:
            link.update(predicate=predicate,
                        answer_scope="The measured mouse cell population." if predicate in {"answers", "partially_answers"} else "",
                        remaining="Independent validation in the target population is still needed."
                        if predicate in {"partially_answers", "raises_question"} else "")
        job["review"] = researcher.model.review_overlap(anchor, packet, candidate)
        question = None
        relations = [{"subject": link["record_id"], "predicate": link["predicate"], "object": anchor["id"],
                      "rationale": link["rationale"],
                      "context": {"review_verdict": decision["verdict"], "review_reason": decision["reason"],
                                  "answer_scope": link["answer_scope"], "remaining": link["remaining"]},
                      "evidence": evidence(link["evidence"], packet)}
                     for link, decision in zip(candidate["links"], job["review"]["analysis"]["decisions"])]
        if revision in {"question-overlap-v1", "question-overlap-v2"}:
            for link, decision, relation in zip(candidate["links"], job["review"]["analysis"]["decisions"], relations):
                for field in ("predicate", "answer_scope", "remaining"):
                    link.pop(field)
                decision.pop("predicate", None)
                for field in ("answer_scope", "remaining"):
                    relation["context"].pop(field)
    else:
        from workbench.research_questions import _reviewed_relations
        job["candidate"] = researcher.model.propose_question(anchor, packet, questions, list(snapshot["views"]))
        candidate = job["candidate"]["analysis"]
        if reverse_premises:
            candidate["premises"].reverse()
        job["review"] = researcher.model.review_question(anchor, packet, candidate, questions, list(snapshot["views"]))
        question = {"title": candidate["title"], "summary": candidate["summary"], "views": candidate["views"],
                    "context": {key: candidate[key] for key in ("scope", "limitations", "motivation", "advance")} | {
                        "worker_role": "question", "derived_from": json.dumps(candidate["premises"])},
                    "facets": {}, "evidence": evidence(candidate["evidence"], packet)}
        if revision == "question-overlap-v1":
            job["review"]["analysis"].pop("relations")
        relations = _reviewed_relations(candidate, job["review"]["analysis"], packet,
            premise_predicate="informs" if revision in {"question-overlap-v1", "question-overlap-v2"} else "raises_question",
            legacy=revision == "question-overlap-v1")
    job["proposal"] = work.proposal(job, snapshot, question=question, relations=relations)
    for field, value in {"candidate": job["candidate"], "packet": packet, "anchor": anchor,
                         "questions": job.get("questions", []), "views": job.get("views", [])}.items():
        job["proposal"]["context"][field + "_digest"] = graph_digest(value)
    work.submit(job, {"errors": []})
    return job


def test_graph_audit_reviews_one_link_with_its_own_original_passage_ids(researcher):
    from workbench.research_graph_audit import audit_graph
    from workbench.research_graph_review import GraphReviewLedger
    job = recorded_graph(researcher)
    calls = []
    review = researcher.model.review_overlap
    def inspect(question, packet, candidate):
        calls.append((packet, candidate))
        assert len(packet["records"]) == len(candidate["links"]) == 1
        assert set(p["id"] for p in packet["document"]["passages"]) <= {
            p["id"] for p in job["packet"]["document"]["passages"]}
        return review(question, packet, candidate)
    researcher.model.review_overlap = inspect
    original = researcher.inbox.snapshot()
    result = audit_graph(researcher)
    assert result["reviewed"] == 1 and result["held"] == 0 and not result["errors"]
    assert result["record_ids"] == job["receipt"]["relation_ids"][:1]
    assert result["verdicts"] == {"supported": 1}
    assert researcher.inbox.snapshot() == original
    assert GraphReviewLedger(researcher.project).current(original)[result["record_ids"][0]]["stage"] == "audit"
    assert audit_graph(researcher)["record_ids"] == job["receipt"]["relation_ids"][1:]
    assert audit_graph(researcher)["reviewed"] == 0
    assert len(calls) == 2


def test_rejected_overlap_edge_does_not_reject_original_finding_or_other_link(researcher):
    from workbench.research_graph_audit import audit_graph
    from workbench.research_graph_review import exclusions
    job = recorded_graph(researcher)
    review = researcher.model.review_overlap
    def reject(*args):
        result = review(*args)
        result["analysis"]["decisions"][0]["verdict"] = "unsupported"
        return result
    researcher.model.review_overlap = reject
    result = audit_graph(researcher)
    assert result["held"] == 1 and result["verdicts"] == {"unsupported": 1}
    assert exclusions(researcher.project, researcher.inbox.snapshot()) == {job["receipt"]["relation_ids"][0]}


def test_unrelated_rejected_premise_does_not_invalidate_an_overlap_link(researcher):
    from workbench.research_graph_audit import audit_graph
    from workbench.research_review import review_backlog
    job = recorded_graph(researcher)
    unrelated = job["packet"]["records"][1]["id"]
    source_review = researcher.model.review
    def reject(*args):
        result = source_review(*args)
        result["analysis"]["verdict"] = "unsupported"
        return result
    researcher.model.review = reject
    review_backlog(researcher.project, researcher.model, record_ids=[unrelated], limit=1)
    assert audit_graph(researcher)["verdicts"] == {"supported": 1}
    researcher.model.review_overlap = lambda *args: pytest.fail("Rejected premises require no model call")
    result = audit_graph(researcher)
    assert result["verdicts"] == {"uncertain": 1} and result["held"] == 1


def test_question_audit_uses_all_premises_and_excludes_itself_from_duplicates(researcher):
    from workbench.research_graph_audit import audit_graph
    job = recorded_graph(researcher, "question")
    identifier = job["receipt"]["record_ids"][0]
    review = researcher.model.review_question
    def inspect(anchor, packet, candidate, questions, views):
        assert identifier not in {q["id"] for q in questions}
        assert candidate["premises"] == job["candidate"]["analysis"]["premises"]
        assert candidate["parents"] == job["candidate"]["analysis"]["parents"]
        return review(anchor, packet, candidate, questions, views)
    researcher.model.review_question = inspect
    result = audit_graph(researcher)
    assert result["record_ids"] == [identifier] and result["verdicts"] == {"supported": 1}


def test_question_duplicate_audit_is_uncertain_and_preserves_the_question(researcher):
    from workbench.research_graph_audit import audit_graph
    job = recorded_graph(researcher, "question")
    researcher.model.review_question = lambda *args: {"model": "test-model", "analysis": {
        "verdict": "duplicate", "reason": "The same scoped measurement was already requested.",
        "duplicate_of": "q-fate", "evidence": [], "relations": []}}
    result = audit_graph(researcher)
    assert result["verdicts"] == {"uncertain": 1} and result["held"] == 1
    assert researcher.inbox.context(job["receipt"]["record_ids"][0])["matches"] == 1


@pytest.mark.parametrize("field", ["candidate", "packet", "review", "proposal", "question", "questions", "views"])
def test_changed_graph_job_is_held_without_trusting_its_model_candidate(researcher, field):
    from workbench.research_graph_audit import audit_graph
    job = recorded_graph(researcher, "question")
    path = researcher.root / "graph-jobs" / (job["id"] + ".json")
    changed = json.loads(path.read_text())
    if field == "packet":
        changed[field]["document"]["passages"][0]["text"] = "An invented passage."
    elif field == "proposal":
        changed[field]["relations"][0]["rationale"] = "Changed rationale."
    elif field in {"candidate", "review"}:
        changed[field]["analysis"]["reason" if field == "review" else "motivation"] = "Changed model content."
    elif field == "question":
        changed[field]["summary"] = "Changed anchor."
    else:
        changed[field] = []
    path.write_text(json.dumps(changed))
    researcher.model.review_question = lambda *args: pytest.fail("A changed job cannot authorize a fresh model verdict")
    result = audit_graph(researcher)
    assert result["verdicts"] == {"uncertain": 1} and result["held"] == 1


def test_model_outage_appends_no_negative_assessment_and_retries(researcher):
    from workbench.research_graph_audit import audit_graph
    from workbench.research_graph_review import GraphReviewLedger
    job = recorded_graph(researcher, count=1)
    review = researcher.model.review_overlap
    researcher.model.review_overlap = lambda *args: (_ for _ in ()).throw(RuntimeError("model offline"))
    first = audit_graph(researcher)
    assert first["errors"] and first["reviewed"] == first["held"] == 0
    entry = GraphReviewLedger(researcher.project).current(researcher.inbox.snapshot())[job["receipt"]["relation_ids"][0]]
    assert entry["stage"] == "initial" and entry["verdict"] == "supported"
    researcher.model.review_overlap = review
    assert audit_graph(researcher)["verdicts"] == {"supported": 1}


def test_malformed_reviews_stop_after_three_attempts_for_unchanged_inputs(researcher):
    from workbench.research_graph_audit import audit_graph
    from workbench.research_graph_review import GraphReviewLedger
    job = recorded_graph(researcher, count=1)
    calls = []
    def malformed(*args):
        calls.append(True)
        return {"analysis": {"decisions": []}}
    researcher.model.review_overlap = malformed
    for _ in range(3):
        assert audit_graph(researcher)["errors"]
    assert audit_graph(researcher)["reviewed"] == 0
    assert len(calls) == 3
    assert GraphReviewLedger(researcher.project).current(researcher.inbox.snapshot())[job["receipt"]["relation_ids"][0]]["stage"] == "initial"


def test_stopped_graph_audit_makes_no_model_calls(researcher):
    from workbench.research_graph_audit import audit_graph
    recorded_graph(researcher)
    researcher.should_stop = lambda: True
    researcher.model.review_overlap = lambda *args: pytest.fail("Stop checkpoint ignored")
    assert audit_graph(researcher)["reviewed"] == 0


def test_question_premise_order_does_not_change_attributed_source_binding(researcher):
    from workbench.research_graph_audit import audit_graph
    recorded_graph(researcher, "question", reverse_premises=True)
    assert audit_graph(researcher)["verdicts"] == {"supported": 1}


def test_source_rejected_during_model_call_is_held_before_assessment_save(researcher):
    from workbench.research_graph_audit import audit_graph
    from workbench.research_review import review_backlog
    job = recorded_graph(researcher, count=1)
    review = researcher.model.review_overlap
    source_review = researcher.model.review
    def reject_source(*args):
        result = source_review(*args)
        result["analysis"]["verdict"] = "unsupported"
        return result
    researcher.model.review = reject_source
    def changed_during_call(*args):
        result = review(*args)
        review_backlog(researcher.project, researcher.model, limit=1,
                       record_ids=[job["packet"]["records"][0]["id"]])
        return result
    researcher.model.review_overlap = changed_during_call
    result = audit_graph(researcher)
    assert result["verdicts"] == {"uncertain": 1} and result["held"] == 1


@pytest.mark.parametrize("role", ["question", "overlap"])
def test_graph_audit_accepts_jobs_from_the_actual_workers(researcher, role):
    from workbench.research_graph_audit import audit_graph
    from workbench.research_questions import QuestionWorker
    from workbench.research_overlap import OverlapWorker
    researcher.model = GraphModel()
    researcher.question_ids = None
    worker = QuestionWorker(researcher) if role == "question" else OverlapWorker(researcher)
    saved = worker.cycle()
    assert saved["saved"] + saved["links_added"] > 0 and not saved["errors"], saved
    audited = audit_graph(researcher)
    assert audited["verdicts"] == {"supported": 1} and not audited["errors"], audited


def test_question_edges_are_audited_with_their_own_parent_or_premise(researcher):
    from workbench.research_graph_audit import audit_graph
    job = recorded_graph(researcher, "question")
    assert audit_graph(researcher)["record_ids"] == job["receipt"]["record_ids"]
    review = researcher.model.review_question
    candidates = []
    def inspect(anchor, packet, candidate, questions, views):
        candidates.append(candidate)
        return review(anchor, packet, candidate, questions, views)
    researcher.model.review_question = inspect
    for identifier in job["receipt"]["relation_ids"]:
        result = audit_graph(researcher)
        assert result["record_ids"] == [identifier] and result["verdicts"] == {"supported": 1}
    assert [len(c["parents"]) for c in candidates[:2]] == [1, 1]
    assert [len(c["premises"]) for c in candidates[2:]] == [1, 1]


def test_new_duplicate_comparison_during_review_gets_a_fresh_audit(researcher):
    from workbench.research_graph_audit import audit_graph
    recorded_graph(researcher, "question")
    review = researcher.model.review_question
    calls = []
    def new_question(*args):
        calls.append(True)
        if len(calls) == 1:
            researcher.inbox.record({"idempotency_key": "another-question", "kind": "question",
                                     "title": "A newly captured measurement question", "summary": "Compare the same scoped measurement.",
                                     "views": ["prediction"]}, "concurrent-session")
        return review(*args)
    researcher.model.review_question = new_question
    first = audit_graph(researcher)
    assert first["verdicts"] == {"uncertain": 1}
    second = audit_graph(researcher)
    assert second["record_ids"] == first["record_ids"] and second["verdicts"] == {"supported": 1}
    assert len(calls) == 2


def test_question_overlap_and_audit_accept_real_shaped_model_timings(researcher):
    from workbench.research_graph_audit import audit_graph
    from workbench.research_questions import QuestionWorker
    from workbench.research_overlap import OverlapWorker
    from workbench.research_graph_review import GraphReviewLedger

    class TimedModel(GraphModel):
        def propose_question(self, *args):
            return super().propose_question(*args) | {"metrics": {"wall_time_seconds": 0.125, "eval_count": 77}}

        def review_question(self, *args):
            return super().review_question(*args) | {"metrics": {"wall_time_seconds": 0.25, "eval_count": 31}}

        def overlap(self, *args, **kwargs):
            return super().overlap(*args, **kwargs) | {"metrics": {"wall_time_seconds": 0.375, "eval_count": 29}}

        def review_overlap(self, *args):
            return super().review_overlap(*args) | {"metrics": {"wall_time_seconds": 0.5, "eval_count": 17}}

    researcher.model = TimedModel()
    researcher.question_ids = None
    question = QuestionWorker(researcher).cycle()
    assert question["saved"] == 1 and not question["errors"], question
    overlap = OverlapWorker(researcher).cycle()
    assert overlap["links_added"] == 2 and not overlap["errors"], overlap
    expected = set(question["record_ids"] + question["relation_ids"] + overlap["relation_ids"])
    audited = audit_graph(researcher, limit=len(expected))
    assert set(audited["record_ids"]) == expected and not audited["errors"], audited
    assert audited["verdicts"] == {"supported": len(expected)}
    entries = GraphReviewLedger(researcher.project).current(researcher.inbox.snapshot())
    assert all(entries[identifier]["result"]["metrics"]["wall_time_seconds"] > 0 for identifier in expected)


@pytest.mark.parametrize("kind", ["parent", "premise"])
def test_later_question_edge_uses_its_own_negative_decision_despite_useful_overall_verdict(researcher, kind):
    from workbench.research_graph_audit import audit_graph
    from workbench.research_graph_review import GraphReviewLedger
    job = recorded_graph(researcher, "question")
    assert audit_graph(researcher)["verdicts"] == {"supported": 1}
    if kind == "premise":
        assert audit_graph(researcher, limit=2)["reviewed"] == 2
    review = researcher.model.review_question
    def reject_one(*args):
        result = review(*args)
        decision = next(r for r in result["analysis"]["relations"] if r["kind"] == kind)
        decision.update(verdict="unsupported", reason="This particular relation exceeds the source scope.")
        return result
    researcher.model.review_question = reject_one
    result = audit_graph(researcher)
    assert result["verdicts"] == {"unsupported": 1} and result["held"] == 1
    identifier = result["record_ids"][0]
    assert identifier in job["receipt"]["relation_ids"]
    assert GraphReviewLedger(researcher.project).current(researcher.inbox.snapshot())[identifier]["reason"] == "This particular relation exceeds the source scope."


@pytest.mark.parametrize("kind,expected", [("premise", "unsupported"), ("parent", "supported")])
def test_question_audit_distinguishes_a_bad_premise_from_an_independent_parent(researcher, kind, expected):
    from workbench.research_graph_audit import audit_graph
    recorded_graph(researcher, "question")
    review = researcher.model.review_question
    def reject_one(*args):
        result = review(*args)
        decision = next(r for r in result["analysis"]["relations"] if r["kind"] == kind)
        decision.update(verdict="unsupported", reason="This specific relation is not grounded.")
        return result
    researcher.model.review_question = reject_one
    assert audit_graph(researcher)["verdicts"] == {expected: 1}
