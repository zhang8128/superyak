"""Shared records and question neighborhoods stay readable without changing research state."""

from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest

from workbench.automation import ResearchInbox
from workbench.research_agenda import QuestionAgenda
from workbench.research_monitor import format_event, monitor
from workbench.research_views import export_research
from test_research_graph_workers import researcher


@pytest.fixture
def project(tmp_path):
    shutil.copytree(Path(__file__).resolve().parents[2] / "workbench/data", tmp_path / "workbench/data")
    return tmp_path


def add_question(snapshot, identifier, title):
    item = deepcopy(next(r for r in snapshot["bundle"]["items"] if r["kind"] == "question"))
    item.update(id=identifier, title=title, context={"worker_role": "question", "scope": "A scoped unresolved gap"})
    snapshot["bundle"]["items"].append(item)
    snapshot["views"]["prediction"].append(identifier)
    return item


def add_relation(snapshot, subject, predicate, target, rationale, *, context=None):
    relation = {"id": f"test-relation-{len(snapshot['bundle']['relations'])}", "subject": subject,
                "predicate": predicate, "object": target, "rationale": rationale, "status": "proposed",
                "context": context or {}, "evidence": [], "reviewed_by": "", "reviewed_at": ""}
    snapshot["bundle"]["relations"].append(relation)
    return relation


def note(project, identifier):
    paths = [path for path in (project / "Research/Records").glob("*.md")
             if f"> Record ID: {identifier}\n" in path.read_text()]
    assert len(paths) == 1
    return paths[0]


@pytest.mark.parametrize("kind,predicate", [("claim", "informs"), ("approach", "addresses"), ("experiment", "tests")])
def test_shared_record_lists_all_questions_once_with_each_reason_and_one_note(project, kind, predicate):
    snapshot = ResearchInbox(project).snapshot()
    record = next(r for r in snapshot["bundle"]["items"] if r["kind"] == kind)
    questions = [add_question(snapshot, f"q-shared-{i}", f"Shared question {i}") for i in range(2)]
    for index, question in enumerate(questions):
        add_relation(snapshot, record["id"], predicate, question["id"], f"Independent reason {index}")
    result = export_research(project, snapshot, "test")
    assert result["status"] == "current", result["errors"]
    path = note(project, record["id"])
    visible = path.read_text().split("> [!info]- Technical details")[0]
    assert "### Related questions" in visible
    for index, question in enumerate(questions):
        assert visible.count(f"|{question['title']}]]") == 1
        assert f"Independent reason {index}" in visible
        question_text = note(project, question["id"]).read_text()
        assert f"[[{path.stem}|" in question_text
    assert len(list((project / "Research/Records").glob("*.md"))) == len(snapshot["bundle"]["items"])


def test_question_lists_multiple_parents_subquestions_and_relevant_record_kinds(project):
    snapshot = ResearchInbox(project).snapshot()
    child = add_question(snapshot, "q-child", "Which measurement narrows this gap?")
    grandchild = add_question(snapshot, "q-grandchild", "Which control checks that measurement?")
    for parent in ("q-fate", "q-regulation"):
        add_relation(snapshot, child["id"], "part_of", parent, f"A distinct scoped part of {parent}")
    add_relation(snapshot, grandchild["id"], "part_of", child["id"], "A more specific control question")
    neighbors = []
    for kind, predicate in (("claim", "informs"), ("approach", "addresses"), ("experiment", "tests")):
        record = next(r for r in snapshot["bundle"]["items"] if r["kind"] == kind)
        add_relation(snapshot, record["id"], predicate, child["id"], f"Relevant {kind} rationale")
        neighbors.append(record)
    assert export_research(project, snapshot, "test")["status"] == "current"
    visible = note(project, child["id"]).read_text().split("> [!info]- Technical details")[0]
    for heading in ("Broader questions", "Subquestions", "Relevant findings", "Methods", "Experiments"):
        assert f"### {heading}" in visible
    for identifier in ("q-fate", "q-regulation", grandchild["id"], *(r["id"] for r in neighbors)):
        assert visible.count(f"[[{note(project, identifier).stem}|") == 1
    assert "## Research agenda" in visible
    assert "**Queued**" in visible
    assert "Waiting for an overlap attempt" in visible
    assert not (project / ".atlas/research/agenda.json").exists()


def test_agenda_rendering_preserves_state_personal_notes_and_record_filename(project):
    snapshot = ResearchInbox(project).snapshot()
    child = add_question(snapshot, "q-child", "A new scoped question")
    agenda = QuestionAgenda(project)
    agenda.eligible(snapshot, excluded_ids=[child["id"]])
    state_bytes = agenda.state_file.read_bytes()
    state_stamp = agenda.state_file.stat().st_mtime_ns
    assert export_research(project, snapshot, "first")["status"] == "current"
    path = note(project, child["id"])
    with path.open("a") as stream:
        stream.write("\nMy personal question annotation.\n")
    before = deepcopy(snapshot)
    assert export_research(project, snapshot, "second")["status"] == "current"
    assert note(project, child["id"]) == path
    assert "My personal question annotation." in path.read_text()
    assert "**Needs reassessment**" in path.read_text()
    assert "needs_reassessment" not in path.read_text().split("> [!info]- Technical details")[0]
    assert agenda.state_file.read_bytes() == state_bytes
    assert agenda.state_file.stat().st_mtime_ns == state_stamp
    assert snapshot == before


def test_link_review_reason_is_visible_and_other_connections_remain_available(project):
    snapshot = ResearchInbox(project).snapshot()
    claims = [r for r in snapshot["bundle"]["items"] if r["kind"] == "claim"]
    child = add_question(snapshot, "q-review", "Question with separately assessed relevance")
    add_relation(snapshot, claims[0]["id"], "informs", child["id"], "The observed outcome bears on this question.",
                 context={"review_verdict": "supported", "review_reason": "The comparison uses the same measured outcome.",
                          "input_digest": "private-technical-digest"})
    add_relation(snapshot, claims[0]["id"], "supports", claims[1]["id"], "A separate claim comparison.")
    assert export_research(project, snapshot, "test")["status"] == "current"
    text = note(project, claims[0]["id"]).read_text()
    visible, technical = text.split("> [!info]- Technical details")
    assert "The comparison uses the same measured outcome." in visible
    assert "supported" in visible.lower()
    assert "proposed" in visible
    assert "> [!info]- Other connections" in visible
    assert "A separate claim comparison." in visible
    assert "private-technical-digest" not in visible
    assert "private-technical-digest" in technical


def test_damaged_agenda_does_not_prevent_exporting_current_research(project):
    snapshot = ResearchInbox(project).snapshot()
    directory = project / ".atlas/research"
    directory.mkdir(parents=True)
    agenda = directory / "agenda.json"
    agenda.write_text('{"version":99}')
    before = agenda.read_bytes()
    result = export_research(project, snapshot, "test")
    assert result["status"] == "pending"
    assert any("Question agenda unavailable" in error for error in result["errors"])
    assert "Scheduling state is unavailable." in note(project, "q-fate").read_text()
    assert agenda.read_bytes() == before


def test_latest_link_audit_is_visible_without_rejecting_the_source_finding(researcher):
    from test_research_graph_audit import recorded_graph
    from workbench.research_evidence import eligible_inputs
    from workbench.research_graph_review import GraphReviewLedger, exclusions

    job = recorded_graph(researcher, count=1)
    snapshot = researcher.inbox.snapshot()
    relation = next(r for r in snapshot["bundle"]["relations"] if r["id"] in job["receipt"]["relation_ids"])
    reason = "The measured population does not match this question's population."
    GraphReviewLedger(researcher.project).store(relation, {"analysis": {
        "verdict": "unsupported", "reason": reason}}, model="later-reviewer", stage="audit")
    assert export_research(researcher.project, snapshot, "latest-audit")["status"] == "current"
    text = note(researcher.project, relation["subject"]).read_text()
    visible, technical = text.split("> [!info]- Technical details")
    assert "Link review: **Unsupported**" in visible
    assert reason in visible
    assert "Fresh source-grounded proposal review accepted this addition." not in visible
    assert "later-reviewer" in technical
    assert exclusions(researcher.project, snapshot) == {relation["id"]}
    assert relation["subject"] in eligible_inputs(researcher, snapshot)
    assert researcher.inbox.snapshot() == snapshot


def test_monitor_and_events_show_agenda_counts_without_initializing_state(tmp_path, capsys):
    agenda = {"a": {"state": "active", "research_count": 2, "overlap_count": 0},
              "b": {"state": "queued", "research_count": 0, "overlap_count": 1},
              "c": {"state": "parked", "research_count": 0, "overlap_count": 0},
              "d": {"state": "needs_reassessment", "research_count": 1, "overlap_count": 1}}

    class Control:
        def status(self):
            return {"running": False, "project": str(tmp_path), "live_graph": "Research/index.html",
                    "log": str(tmp_path / "worker.log"), "question_agenda": agenda}

        def _check_paths(self):
            pass

    assert monitor(Control(), follow=False) == 0
    output = capsys.readouterr().out
    for value in ("Question agenda", "1 active", "1 queued", "1 parked", "1 needs reassessment"):
        assert value in output
        assert value in "\n".join(format_event(json.dumps({"question_agenda": agenda})))
    assert "3 research attempts" in output
    assert list(tmp_path.iterdir()) == []


def test_old_monitor_events_do_not_acquire_agenda_output():
    output = "\n".join(format_event('{"phase":"reading","paper":"Existing publication"}'))
    assert output == "Reading: Existing publication"
    assert "Question agenda" not in output
