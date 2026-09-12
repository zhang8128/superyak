"""Worker roles must leave durable, measurable outcomes for later turns."""

import json

from test_research_runner import project, runner


def test_worker_rotation_resumes_after_restart_and_counts_each_role(project, monkeypatch):
    from workbench.research_workers import WorkerRotation

    calls = []
    research = runner(project)
    rotation = WorkerRotation(research, roles=["research", "audit", "connect"])
    def perform(role):
        calls.append(role)
        return {"errors": [], "saved": int(role == "connect"), "reviewed": int(role == "audit")}
    monkeypatch.setattr(rotation, "_perform", perform)
    assert rotation.cycle()["worker_role"] == "research"
    resumed = WorkerRotation(research, roles=["research", "audit", "connect"])
    monkeypatch.setattr(resumed, "_perform", perform)
    assert resumed.cycle()["worker_role"] == "audit"
    assert resumed.cycle()["worker_role"] == "connect"
    assert calls == ["research", "audit", "connect"]
    assert resumed.metrics()["connect"]["saved"] == 1
    assert resumed.metrics()["audit"]["reviewed"] == 1
    turns = list((project / ".atlas/research/turns").glob("*.json"))
    assert len(turns) == 3
    assert all("seconds" in json.loads(p.read_text()) for p in turns)


def test_worker_failure_does_not_starve_the_next_role(project, monkeypatch):
    from workbench.research_workers import WorkerRotation

    rotation = WorkerRotation(runner(project), roles=["audit", "research"])
    monkeypatch.setattr(rotation, "_perform", lambda role: (_ for _ in ()).throw(RuntimeError("offline")))
    assert rotation.cycle()["errors"]
    resumed = WorkerRotation(rotation.research, roles=["audit", "research"])
    monkeypatch.setattr(resumed, "_perform", lambda role: {"errors": []})
    assert resumed.cycle()["worker_role"] == "research"


def test_role_configuration_defaults_to_all_five_roles_and_accepts_explicit_overrides():
    import pytest
    from workbench.research_service import _validate_options

    assert _validate_options({})["roles"] == ["research", "audit", "question", "overlap", "connect"]
    assert _validate_options({"roles": ["research"]})["roles"] == ["research"]
    assert _validate_options({"roles": ["audit", "connect"]})["roles"] == ["audit", "connect"]
    with pytest.raises(ValueError, match="role"):
        _validate_options({"roles": ["invented"]})


def test_cli_uses_default_rotation_unless_roles_are_explicit(project, monkeypatch):
    from workbench import research_service
    captured = []
    def launch(project, options):
        captured.append(research_service._validate_options(options)["roles"])
        return {"started": True}
    monkeypatch.setattr(research_service, "start", launch)
    for flags in ([], ["--role", "research"], ["--role", "connect", "--role", "audit"]):
        assert research_service.main(["--project", str(project), "start", *flags]) == 0
    assert captured == [["research", "audit", "question", "overlap", "connect"], ["research"], ["connect", "audit"]]


def test_three_malformed_audits_do_not_starve_other_records(researcher):
    from workbench.research_workers import WorkerRotation
    from workbench.research_review import SourceReviewError
    first = None
    calls = []
    review = researcher.model.review
    def audit(question, document, candidate):
        nonlocal first
        source = document["source"]["id"]
        first = first or source
        calls.append(source)
        if source == first:
            raise SourceReviewError("malformed reviewer output", {})
        return review(question, document, candidate)
    researcher.model.review = audit
    for _ in range(4):
        WorkerRotation(researcher, roles=["audit"]).cycle()
    assert calls[:3] == [first] * 3
    assert calls[3] != first


from test_research_connections import researcher


def test_default_service_runs_all_five_roles(researcher, monkeypatch):
    from workbench import research_service, research_runner, research_model
    monkeypatch.setattr(research_model.Ollama, "check", lambda self: {})
    monkeypatch.setattr(research_runner, "ResearchRunner", lambda *args, **kwargs: researcher)
    from test_research_graph_workers import GraphModel
    researcher.model = GraphModel()
    researcher.question_ids = None
    assert research_service.run_worker(researcher.project, {"cycles": 5, "interval": 1}) == 0
    status = research_service.WorkerControl(researcher.project).status()
    assert status["worker_roles"] == ["research", "audit", "question", "overlap", "connect"]
    assert status["last_cycle"]["worker_role"] == "connect"
    assert status["worker_metrics"]["audit"]["reviewed"] == 1
    assert status["worker_metrics"]["connect"]["saved"] == 1


def test_service_runs_a_selected_role_and_exposes_its_metrics(project, monkeypatch):
    from workbench.research_service import run_worker, WorkerControl
    from workbench.research_model import Ollama
    monkeypatch.setattr(Ollama, "check", lambda self: {})
    assert run_worker(project, {"roles": ["connect"], "cycles": 1}) == 0
    status = WorkerControl(project).status()
    assert status["worker_roles"] == ["connect"]
    assert status["last_cycle"]["worker_role"] == "connect"
    assert status["worker_metrics"]["connect"]["skipped"] == 1
    assert status["running"] is False


def test_new_comparison_revision_retries_previously_exhausted_audits(researcher, monkeypatch):
    from workbench import research_connections
    from workbench.research_review import SourceReviewError
    from workbench.research_workers import WorkerRotation
    assert research_connections.ConnectionWorker(researcher).cycle()["saved"] == 1
    review = researcher.model.review_connection
    researcher.model.review_connection = lambda *args: (_ for _ in ()).throw(SourceReviewError("bad review", {}))
    for _ in range(5):
        WorkerRotation(researcher, roles=["audit"]).cycle()
    assert WorkerRotation(researcher, roles=["audit"]).cycle()["exhausted"] == 1
    monkeypatch.setattr(research_connections, "CONNECTION_REVISION", "improved-comparison-review")
    researcher.model.review_connection = review
    result = WorkerRotation(researcher, roles=["audit"]).cycle()
    assert result["reviewed"] == 1 and result["exhausted"] == 0
