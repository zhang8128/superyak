"""Operational scheduling remains fair, durable, and separate from scientific review."""

from copy import deepcopy
import json

import pytest

from workbench.research_agenda import QuestionAgenda


def question(identifier, *, generated=False, status="proposed"):
    return {"id": identifier, "kind": "question", "title": identifier,
            "status": status, "context": {"worker_role": "question"} if generated else {},
            "provenance": {"capture": "graph_draft" if generated else "session_draft"}}


def snapshot(*records, selected=None):
    return {"bundle": {"items": list(records), "relations": []},
            "views": {"prediction": [r["id"] for r in records] if selected is None else selected}}


def test_read_only_status_does_not_create_state_and_user_questions_are_pinned(tmp_path):
    data = snapshot(question("seed"), question("user-question"), question("new", generated=True))
    before = deepcopy(data)
    agenda = QuestionAgenda(tmp_path)
    states = agenda.status(data)
    assert states["seed"]["state"] == states["user-question"]["state"] == "active"
    assert states["user-question"]["pinned"] is True
    assert states["new"]["state"] == "queued"
    assert states["new"]["overlap_attempted"] is False
    assert states["new"]["can_generate_children"] is False
    assert not (tmp_path / ".atlas").exists()
    assert data == before


def test_generated_question_waits_for_overlap_even_when_attempt_finds_nothing(tmp_path):
    data = snapshot(question("seed"), question("new", generated=True))
    agenda = QuestionAgenda(tmp_path)
    assert [q["id"] for q in agenda.eligible(data)] == ["seed"]
    agenda.overlapped("new")
    states = QuestionAgenda(tmp_path).status(data)
    assert states["new"]["state"] == "active"
    assert states["new"]["overlap_count"] == 1
    assert states["new"]["can_generate_children"] is False
    agenda.researched("new")
    assert QuestionAgenda(tmp_path).status(data)["new"]["can_generate_children"] is True
    assert QuestionAgenda(tmp_path).status(data)["new"]["research_count"] == 1


def test_overlap_can_be_saved_before_new_question_enters_agenda(tmp_path):
    agenda = QuestionAgenda(tmp_path)
    agenda.overlapped("new")
    data = snapshot(question("new", generated=True))
    assert [q["id"] for q in QuestionAgenda(tmp_path).eligible(data)] == ["new"]


def test_graph_capture_alone_does_not_make_a_user_question_generated(tmp_path):
    user_question = question("user")
    user_question["provenance"]["capture"] = "graph_draft"
    agenda = QuestionAgenda(tmp_path)
    assert [q["id"] for q in agenda.eligible(snapshot(user_question))] == ["user"]
    assert agenda.status(snapshot(user_question))["user"]["pinned"] is True


def test_status_with_new_questions_does_not_rewrite_existing_agenda(tmp_path):
    agenda = QuestionAgenda(tmp_path)
    data = snapshot(question("seed"))
    agenda.eligible(data)
    previous = agenda.state_file.read_bytes()
    stamp = agenda.state_file.stat().st_mtime_ns
    new_data = snapshot(question("seed"), question("new", generated=True))
    assert agenda.status(new_data)["new"]["state"] == "queued"
    assert agenda.state_file.read_bytes() == previous
    assert agenda.state_file.stat().st_mtime_ns == stamp


def test_explicit_limit_is_saved_on_next_operation_and_reloaded_by_default(tmp_path):
    agenda = QuestionAgenda(tmp_path, active_limit=4)
    assert not agenda.state_file.exists()
    agenda.overlapped("new")
    assert QuestionAgenda(tmp_path).active_limit == 4
    changed = QuestionAgenda(tmp_path, active_limit=6)
    changed.eligible(snapshot(question("seed")))
    assert QuestionAgenda(tmp_path).active_limit == 6


def test_rotation_survives_restart_respects_cap_and_eventually_serves_queued_questions(tmp_path):
    data = snapshot(question("seed-a"), question("seed-b"),
                    *(question(f"generated-{i}", generated=True) for i in range(5)))
    agenda = QuestionAgenda(tmp_path, active_limit=3)
    agenda.eligible(data)
    for i in range(5):
        agenda.overlapped(f"generated-{i}")
    researched = []
    for _ in range(21):
        agenda = QuestionAgenda(tmp_path)
        assert agenda.active_limit == 3
        eligible = agenda.eligible(data)
        assert len(eligible) == 3
        assert {"seed-a", "seed-b"} <= {q["id"] for q in eligible}
        chosen = eligible[0]["id"]
        researched.append(chosen)
        agenda.researched(chosen)
    assert set(researched) == {q["id"] for q in data["bundle"]["items"]}
    counts = [s["research_count"] for s in agenda.status(data).values()]
    assert max(counts) - min(counts) <= 1


def test_explicit_selection_is_honored_without_mutating_question_status(tmp_path):
    data = snapshot(question("seed"), question("other"), question("new", generated=True))
    before = deepcopy(data)
    agenda = QuestionAgenda(tmp_path, active_limit=1)
    assert [q["id"] for q in agenda.eligible(data, ["other"])] == ["other"]
    assert agenda.status(data)["seed"]["state"] == "parked"
    assert data == before
    with pytest.raises(ValueError, match="requested question must be active and selected"):
        agenda.eligible(data, ["missing"])


def test_withdrawn_or_unselected_questions_park_without_scientific_changes(tmp_path):
    data = snapshot(question("seed"), question("withdrawn", status="withdrawn"), question("outside"),
                    selected=["seed", "withdrawn"])
    before = deepcopy(data)
    agenda = QuestionAgenda(tmp_path)
    assert [q["id"] for q in agenda.eligible(data)] == ["seed"]
    assert agenda.status(data)["withdrawn"]["state"] == "parked"
    assert agenda.status(data)["outside"]["state"] == "parked"
    assert data == before


def test_excluded_questions_need_reassessment_and_recover_only_when_exclusion_clears(tmp_path):
    data = snapshot(question("seed"), question("new", generated=True))
    before = deepcopy(data)
    agenda = QuestionAgenda(tmp_path)
    agenda.overlapped("new")
    assert [q["id"] for q in agenda.eligible(data, excluded_ids=["new", "claim-id"])] == ["seed"]
    state = QuestionAgenda(tmp_path).status(data)["new"]
    assert state["state"] == "needs_reassessment"
    assert state["can_generate_children"] is False
    assert state["overlap_count"] == 1
    assert data == before
    assert "new" in {q["id"] for q in agenda.eligible(data)}


def test_no_eligible_questions_has_existing_error_and_retains_reassessment_state(tmp_path):
    agenda = QuestionAgenda(tmp_path)
    data = snapshot(question("seed"))
    with pytest.raises(ValueError, match="no active questions in the configured research views"):
        agenda.eligible(data, excluded_ids=["seed"])
    assert QuestionAgenda(tmp_path).status(data)["seed"]["state"] == "needs_reassessment"
    with pytest.raises(ValueError, match="no active questions in the configured research views"):
        agenda.eligible(snapshot(question("new", generated=True)))


def test_limit_cannot_silently_drop_pinned_seeds(tmp_path):
    agenda = QuestionAgenda(tmp_path, active_limit=1)
    with pytest.raises(ValueError, match="active_limit.*pinned"):
        agenda.eligible(snapshot(question("a"), question("b")))


@pytest.mark.parametrize("limit", [True, 0, -1, "12", 1.5])
def test_invalid_active_limit_is_rejected(tmp_path, limit):
    with pytest.raises(ValueError, match="active_limit"):
        QuestionAgenda(tmp_path, active_limit=limit)


@pytest.mark.parametrize("corrupt", [None, {"version": 99}, {"version": True},
                                     {"version": 1, "questions": []}])
def test_invalid_saved_schema_does_not_overwrite_state(tmp_path, corrupt):
    directory = tmp_path / ".atlas/research"
    directory.mkdir(parents=True)
    path = directory / "agenda.json"
    original = json.dumps(corrupt)
    path.write_text(original)
    with pytest.raises(ValueError, match="agenda"):
        QuestionAgenda(tmp_path).status(snapshot(question("seed")))
    assert path.read_text() == original


@pytest.mark.parametrize("field,value", [("state", "reviewed"), ("pinned", 1), ("created", -1),
                                         ("last_researched", 1), ("research_count", True),
                                         ("overlap_count", 100)])
def test_invalid_saved_question_counts_and_states_fail_without_rewriting(tmp_path, field, value):
    agenda = QuestionAgenda(tmp_path)
    agenda.eligible(snapshot(question("seed")))
    state = json.loads(agenda.state_file.read_text())
    state["questions"]["seed"][field] = value
    original = json.dumps(state)
    agenda.state_file.write_text(original)
    with pytest.raises(ValueError, match="agenda"):
        QuestionAgenda(tmp_path)
    assert agenda.state_file.read_text() == original


@pytest.mark.parametrize("component", [".atlas", ".atlas/research", ".atlas/research/agenda.json"])
def test_agenda_rejects_wrong_filesystem_entry_types(tmp_path, component):
    path = tmp_path / component
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".json":
        path.mkdir()
    else:
        path.write_text("User file")
    with pytest.raises(ValueError, match="agenda"):
        QuestionAgenda(tmp_path)


@pytest.mark.parametrize("component", [".atlas", ".atlas/research", ".atlas/research/agenda.json"])
def test_agenda_never_reads_or_writes_through_symlink(tmp_path, component):
    project = tmp_path / "project"
    project.mkdir()
    external = tmp_path / "outside"
    external.mkdir()
    link = project / component
    link.parent.mkdir(parents=True, exist_ok=True)
    target = external / "missing.json" if link.suffix == ".json" else external
    link.symlink_to(target, target_is_directory=link.suffix != ".json")
    with pytest.raises(ValueError, match="symlink"):
        QuestionAgenda(project).status(snapshot(question("seed")))
    assert not list(external.iterdir())
