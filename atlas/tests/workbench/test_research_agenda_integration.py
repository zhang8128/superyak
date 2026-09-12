"""Scheduling, audit eligibility, and service behavior across durable role turns."""

import pytest

from test_research_graph_audit import recorded_graph
from test_research_graph_workers import GraphModel, researcher
from test_research_runner import project


def test_generated_question_gets_a_fair_research_turn_after_overlap_and_restart(researcher):
    from workbench.research_agenda import QuestionAgenda
    from workbench.research_overlap import OverlapWorker
    from workbench.research_runner import ResearchRunner
    job = recorded_graph(researcher, "question")
    identifier = job["receipt"]["record_ids"][0]
    assert QuestionAgenda(researcher.project).status(researcher.inbox.snapshot())[identifier]["state"] == "queued"
    OverlapWorker(researcher).cycle()
    researcher.provider.search = lambda *args, **kwargs: {"papers": [], "next_cursor": None}
    selected = []
    for _ in range(3):
        resumed = ResearchRunner(researcher.project, provider=researcher.provider, model=GraphModel(), question_ids=None)
        result = resumed.cycle()
        assert not result["errors"], result
        selected.append(result["question_id"])
    assert set(selected) == {"q-fate", "q-regulation", identifier}
    status = QuestionAgenda(researcher.project).status(researcher.inbox.snapshot())
    assert status[identifier]["research_count"] == 1
    assert status[identifier]["can_generate_children"]


def test_no_eligible_question_is_a_noop_while_waiting_for_overlap(researcher):
    job = recorded_graph(researcher, "question")
    identifier = job["receipt"]["record_ids"][0]
    researcher.question_ids = [identifier]
    researcher.model.plan = lambda *args: pytest.fail("Queued questions cannot start research")
    result = researcher.cycle()
    assert result["skipped"] == 1 and result["errors"] == [], result
    assert result["question_agenda"][identifier]["state"] == "queued"


def test_later_graph_question_rejection_suspends_agenda_and_context(researcher):
    from workbench.research_agenda import QuestionAgenda
    from workbench.research_graph_audit import audit_graph
    job = recorded_graph(researcher, "question")
    identifier = job["receipt"]["record_ids"][0]
    QuestionAgenda(researcher.project).overlapped(identifier)
    assert identifier in {q["id"] for q in researcher._questions(researcher.inbox.snapshot())}
    review = researcher.model.review_question
    def reject(*args):
        result = review(*args)
        result["analysis"]["verdict"] = "unsupported"
        result["analysis"]["reason"] = "The measurement does not resolve the stated motivation."
        return result
    researcher.model.review_question = reject
    assert audit_graph(researcher)["verdicts"] == {"unsupported": 1}
    snapshot = researcher.inbox.snapshot()
    assert identifier not in {q["id"] for q in researcher._questions(snapshot)}
    assert QuestionAgenda(researcher.project).status(snapshot)[identifier]["state"] == "needs_reassessment"
    anchor = next(q for q in snapshot["bundle"]["items"] if q["id"] == "q-fate")
    assert identifier not in {item["record"]["id"] for item in researcher._context(anchor, snapshot)}
    assert researcher.inbox.context(identifier)["records"][0]["record"]["status"] == "proposed"


def test_rejected_graph_link_leaves_its_original_finding_in_research_context(researcher):
    from workbench.research_graph_audit import audit_graph
    job = recorded_graph(researcher)
    identifier = job["receipt"]["relation_ids"][0]
    finding = job["packet"]["records"][0]["id"]
    anchor = job["question"]
    before = researcher._context(anchor, researcher.inbox.snapshot())
    assert identifier in {r["id"] for entry in before for r in entry["relations"]}
    review = researcher.model.review_overlap
    def reject(*args):
        result = review(*args)
        result["analysis"]["decisions"][0]["verdict"] = "unsupported"
        return result
    researcher.model.review_overlap = reject
    assert audit_graph(researcher)["held"] == 1
    context = researcher._context(anchor, researcher.inbox.snapshot())
    assert identifier not in {r["id"] for entry in context for r in entry["relations"]}
    assert finding in {entry["record"]["id"] for entry in context}


def test_all_five_real_roles_resume_across_process_reconstruction(researcher):
    from workbench.research_runner import ResearchRunner
    from workbench.research_workers import WorkerRotation, ROLES
    researcher.model = GraphModel()
    researcher.question_ids = None
    researcher.provider.search = lambda *args, **kwargs: {"papers": [], "next_cursor": None}
    turns = []
    for _ in range(10):
        resumed = ResearchRunner(researcher.project, provider=researcher.provider, model=GraphModel(), question_ids=None)
        rotation = WorkerRotation(resumed, roles=list(ROLES))
        result = rotation.cycle()
        assert not result["errors"], result
        turns.append(result["worker_role"])
    assert turns == list(ROLES) * 2
    assert {role: value["turns"] for role, value in rotation.metrics().items()} == {role: 2 for role in ROLES}


def test_malformed_graph_audit_is_classified_without_service_backoff(researcher, monkeypatch):
    from workbench import research_model, research_runner, research_service
    from workbench.research_review import review_backlog
    recorded_graph(researcher, count=1)
    assert review_backlog(researcher.project, researcher.model, limit=2)["reviewed"] == 2
    researcher.model.review_overlap = lambda *args: {"analysis": {"decisions": []}}
    clock = [1000.0]
    monkeypatch.setattr(research_service.time, "time", lambda: clock[0])
    monkeypatch.setattr(research_service.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(research_service.threading.Event, "wait", lambda self, timeout: clock.__setitem__(0, clock[0] + timeout))
    monkeypatch.setattr(research_model.Ollama, "check", lambda self: {})
    monkeypatch.setattr(research_runner, "ResearchRunner", lambda *args, **kwargs: researcher)
    updates = []
    original_update = research_service.WorkerControl.update
    def observe(self, values):
        if values.get("next_cycle_at_epoch", 0) > clock[0]:
            updates.append(values["next_cycle_at_epoch"] - clock[0])
        original_update(self, values)
    monkeypatch.setattr(research_service.WorkerControl, "update", observe)
    assert research_service.run_worker(researcher.project, {"cycles": 3, "interval": 60, "roles": ["audit"]}) == 2
    status = research_service.WorkerControl(researcher.project).status()
    assert status["last_cycle"]["errors"][0]["kind"] == "invalid_review"
    assert updates == [60, 60]
