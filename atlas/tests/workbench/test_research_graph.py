"""Atomic graph capture, replay, and compatibility with the original inbox."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from workbench.automation import ResearchInbox
from workbench.validation import WorkbenchError


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def inbox(tmp_path):
    data = tmp_path / "workbench/data"
    data.mkdir(parents=True)
    for name in ("cell_fate.json", "lighthouse-automation.json"):
        shutil.copyfile(ROOT / "workbench/data" / name, data / name)
    shutil.copytree(ROOT / "workbench/data/lighthouses", data / "lighthouses")
    return ResearchInbox(tmp_path)


def proposal(inbox, edges=None, *, key="overlap-1", question=None):
    from workbench.research_graph import graph_digest

    edges = edges or [("c-cellrank", "informs", "q-fate")]
    records = {r["id"]: r for r in inbox.snapshot()["bundle"]["items"]}
    return {
        "idempotency_key": key, "question": question,
        "relations": [{"subject": subject, "predicate": predicate, "object": target,
                       "rationale": "The located observation motivates this question.",
                       "context": {"model": "test-model", "scope": "inspected passage"},
                       "evidence": [{"source_id": "s-cellrank", "locator": "Abstract",
                                     "note": "A source-supported motivation, not an answer."}]}
                      for subject, predicate, target in edges],
        "expected": {identifier: graph_digest(records[identifier])
                     for identifier in {e[0] for e in edges} | {e[2] for e in edges}
                     if identifier != "$question" and identifier in records},
        "context": {"worker_role": "overlap", "model": "proposal-model"},
    }


def question():
    return {"title": "What would distinguish the two scoped mechanisms?",
            "summary": "Measure a held-out outcome in the inspected system.",
            "views": ["prediction"], "context": {"scope": "the pilot"}, "facets": {},
            "evidence": [{"source_id": "s-cellrank", "locator": "Abstract", "note": "Motivation"}]}


def test_existing_records_gain_multiple_question_links_without_changing_membership(inbox):
    before = inbox.snapshot()
    result = inbox.record_graph(proposal(inbox, [("c-cellrank", "informs", "q-fate"),
                                                ("c-cellrank", "informs", "q-regulation")]), "session-a")
    after = inbox.snapshot()
    assert result["recorded"] and not result["duplicate"]
    assert result["record_ids"] == [] and len(result["relation_ids"]) == 2
    assert result["publication_status"] == "current"
    assert after["views"] == before["views"]
    assert after["bundle"]["items"] == before["bundle"]["items"]
    links = [r for r in after["bundle"]["relations"] if r["id"] in result["relation_ids"]]
    assert {r["object"] for r in links} == {"q-fate", "q-regulation"}
    assert all(r["status"] == "proposed" for r in links)
    for link in links:
        assert link["context"]["session_id"] == "session-a"
        assert link["context"]["graph_draft_id"] == result["graph_draft_id"]
        assert link["context"]["model"] == "test-model"
        assert "s-cellrank" in json.loads(link["context"]["source_digests"])
    status = inbox.status()
    assert status["draft_count"] == 0 and status["graph_draft_count"] == 1
    assert status["graph_record_count"] == 0 and status["graph_relation_count"] == 2
    assert status["relation_count"] == len(before["bundle"]["relations"]) + 2


def test_question_and_two_parents_are_captured_atomically_and_publish_once(inbox, monkeypatch):
    edges = [("c-cellrank", "informs", "$question"),
             ("$question", "part_of", "q-fate"), ("$question", "part_of", "q-regulation")]
    calls = []
    refresh = inbox._refresh
    def refreshed():
        calls.append(True)
        return refresh()
    monkeypatch.setattr(inbox, "_refresh", refreshed)
    result = inbox.record_graph(proposal(inbox, edges, question=question()), "session-a")
    identifier, = result["record_ids"]
    snapshot = inbox.snapshot()
    record = next(r for r in snapshot["bundle"]["items"] if r["id"] == identifier)
    assert record["kind"] == "question" and record["status"] == "proposed"
    assert record["provenance"]["capture"] == "graph_draft"
    assert record["provenance"]["session_id"] == "session-a"
    assert identifier in snapshot["views"]["prediction"]
    assert identifier not in snapshot["views"]["regulation"]
    assert result["views"] == ["prediction"]
    assert len(list((inbox.state / "graph-drafts").glob("*.json"))) == 1
    assert not list((inbox.state / "drafts").glob("*.json"))
    assert len(result["relation_ids"]) == 3 and calls == [True]


def test_replay_recovers_after_source_input_changes_and_does_not_call_guard(inbox):
    from workbench.research_graph import graph_digest
    raw = proposal(inbox)
    first = inbox.record_graph(raw, "session-a")
    path = inbox.project / "workbench/data/cell_fate.json"
    data = json.loads(path.read_text())
    next(r for r in data["items"] if r["id"] == "c-cellrank")["summary"] = "Changed input"
    path.write_text(json.dumps(data))
    def lost_eligibility(snapshot):
        raise ValueError("eligibility lost")
    replay = inbox.record_graph(raw, "session-a", guard=lost_eligibility)
    assert replay["duplicate"] and replay["relation_ids"] == first["relation_ids"]
    assert replay["publication_status"] == "current"
    assert graph_digest({"b": 2, "a": 1}) == graph_digest({"a": 1, "b": 2})
    with pytest.raises(ValueError, match="different content"):
        inbox.record_graph(raw | {"context": {"worker_role": "changed"}}, "session-a")


def test_new_submissions_reject_stale_or_missing_input_bindings(inbox):
    raw = proposal(inbox)
    raw["expected"]["c-cellrank"] = "0" * 64
    with pytest.raises(ValueError, match="[Ss]tale"):
        inbox.record_graph(raw, "session-a")
    raw = proposal(inbox)
    del raw["expected"]["q-fate"]
    with pytest.raises(ValueError, match="[Ee]xpected|binding"):
        inbox.record_graph(raw, "session-a")
    assert not list((inbox.state / "graph-drafts").glob("*.json"))


def test_locked_guard_prevents_capture(inbox):
    raw = proposal(inbox)
    def lost_eligibility(snapshot):
        assert any(r["id"] == "c-cellrank" for r in snapshot["bundle"]["items"])
        with pytest.raises(ValueError, match="busy"):
            ResearchInbox(inbox.project).refresh()
        raise ValueError("eligibility lost")
    with pytest.raises(ValueError, match="eligibility lost"):
        inbox.record_graph(raw, "session-a", guard=lost_eligibility)
    assert inbox.status()["graph_draft_count"] == 0


@pytest.mark.parametrize("edges", [
    [("q-fate", "informs", "c-cellrank")],
    [("c-cellrank", "informs", "missing")],
    [("q-fate", "part_of", "q-fate")],
    [("q-fate", "part_of", "q-regulation"), ("q-regulation", "part_of", "q-fate")],
    [("c-cellrank", "informs", "q-fate"), ("c-cellrank", "informs", "q-fate")],
])
def test_invalid_graph_is_not_partially_captured(inbox, edges):
    with pytest.raises((ValueError, WorkbenchError)):
        inbox.record_graph(proposal(inbox, edges), "session-a")
    assert not list((inbox.state / "graph-drafts").glob("*.json"))
    assert not (inbox.state / "current.json").exists()


def test_part_of_cycle_checks_previously_saved_links(inbox):
    inbox.record_graph(proposal(inbox, [("q-fate", "part_of", "q-regulation")]), "session-a")
    with pytest.raises(ValueError, match="cycle"):
        inbox.record_graph(proposal(inbox, [("q-regulation", "part_of", "q-fate")], key="cycle"), "session-a")
    assert inbox.status()["graph_draft_count"] == 1


def test_independent_jobs_cannot_duplicate_an_existing_edge(inbox):
    raw = proposal(inbox)
    inbox.record_graph(raw, "session-a")
    with pytest.raises(ValueError, match="[Dd]uplicate graph relation"):
        inbox.record_graph(raw, "session-b")
    with pytest.raises(ValueError, match="[Dd]uplicate graph relation"):
        inbox.record_graph(proposal(inbox, [("a-dynamics", "addresses", "q-fate")]), "session-b")
    assert inbox.status()["graph_relation_count"] == 1


@pytest.mark.parametrize("change", [
    {"evidence": [{"source_id": "missing", "locator": "Abstract", "note": ""}]},
    {"evidence": [{"source_id": "s-cellrank", "locator": " ", "note": ""}]},
    {"rationale": " "}, {"status": "reviewed"}, {"context": {"session_id": "forged"}},
])
def test_relation_evidence_and_attribution_are_validated(inbox, change):
    raw = proposal(inbox)
    raw["relations"][0].update(change)
    with pytest.raises((ValueError, WorkbenchError)):
        inbox.record_graph(raw, "session-a")
    assert inbox.status()["graph_draft_count"] == 0


def test_graph_receipt_survives_publication_failure_and_refresh_recovers(inbox, monkeypatch):
    from workbench import automation
    original = inbox.refresh()["generation"]
    raw = proposal(inbox, [("c-cellrank", "informs", "$question")], question=question())
    def full_disk(*args):
        raise OSError("publication disk is full")
    with monkeypatch.context() as patch:
        patch.setattr(automation.os, "rename", full_disk)
        saved = inbox.record_graph(raw, "session-a")
    assert saved["recorded"] and saved["publication_status"] == "pending"
    assert "publication disk is full" in saved["error"]
    assert inbox.status()["generation"] == original
    assert inbox.status()["publication_status"] == "pending"
    assert inbox.context(saved["record_ids"][0])["matches"] == 1
    recovered = ResearchInbox(inbox.project).record_graph(raw, "session-a")
    assert recovered["duplicate"] and recovered["publication_status"] == "current"
    assert inbox.status()["graph_draft_count"] == 1


def test_original_drafts_and_manifests_remain_readable(inbox):
    old = inbox.record({"idempotency_key": "old", "kind": "claim", "title": "Original claim",
                        "summary": "Original summary", "views": ["prediction"]}, "session-old")
    manifest_path = inbox.state / "publications" / old["generation"] / "manifest.json"
    old_manifest = json.loads(manifest_path.read_text())
    old_manifest = {key: old_manifest[key] for key in ("generation", "generated_at", "draft_count", "views")}
    manifest_path.write_text(json.dumps(old_manifest))
    (inbox.state / "current.json").write_text(json.dumps(old_manifest))
    draft_path = inbox.state / "drafts" / (old["record_id"] + ".json")
    before = draft_path.read_bytes()
    assert inbox.status()["publication_status"] == "current"
    inbox.record_graph(proposal(inbox), "session-new")
    assert draft_path.read_bytes() == before
    assert inbox._read_generation(old["generation"])[0] == old_manifest
    assert inbox.status()["draft_count"] == 1


def test_graph_journal_is_bounded_and_detects_tampering(inbox, monkeypatch):
    from workbench import research_graph
    saved = inbox.record_graph(proposal(inbox), "session-a")
    monkeypatch.setattr(research_graph, "MAX_GRAPH_DRAFTS", 1)
    with pytest.raises(ValueError, match="full|exceeds"):
        inbox.record_graph(proposal(inbox, [("c-cellrank", "informs", "q-regulation")], key="second"), "session-a")
    path = inbox.state / "graph-drafts" / (saved["graph_draft_id"] + ".json")
    stored = json.loads(path.read_text())
    stored["proposal"]["relations"][0]["rationale"] = "Changed"
    path.write_text(json.dumps(stored))
    with pytest.raises(ValueError, match="integrity"):
        inbox.snapshot()


@pytest.mark.parametrize("field,value", [("recorded_at", "2025-01-01T00:00:00+00:00"),
                                         ("source_digests", {"s-cellrank": "0" * 64}),
                                         ("views", [])])
def test_stored_capture_metadata_is_integrity_bound(inbox, field, value):
    saved = inbox.record_graph(proposal(inbox), "session-a")
    path = inbox.state / "graph-drafts" / (saved["graph_draft_id"] + ".json")
    entry = json.loads(path.read_text())
    entry[field] = value
    path.write_text(json.dumps(entry))
    with pytest.raises(ValueError, match="integrity"):
        inbox.snapshot()


def test_question_graph_accepts_six_relations_but_overlap_is_capped_at_three(inbox):
    edges = [("c-cellrank", "informs", "$question"), ("c-markov", "informs", "$question"),
             ("c-velovi", "informs", "$question"), ("e-heldout-fates", "tests", "$question"),
             ("$question", "part_of", "q-fate"), ("$question", "part_of", "q-regulation")]
    receipt = inbox.record_graph(proposal(inbox, edges, question=question()), "session-a")
    assert len(receipt["relation_ids"]) == 6
    overlapping = [("c-cellrank", "informs", "q-fate"), ("c-markov", "informs", "q-fate"),
                   ("c-velovi", "informs", "q-fate"), ("c-wot", "informs", "q-fate")]
    with pytest.raises(ValueError, match="three|3"):
        inbox.record_graph(proposal(inbox, overlapping, key="too-many"), "session-a")


def test_graph_entry_can_reference_an_earlier_graph_question_after_restart(inbox):
    first = inbox.record_graph(proposal(inbox, [("c-cellrank", "informs", "$question")],
                                        question=question()), "session-a")
    second = ResearchInbox(inbox.project).record_graph(
        proposal(inbox, [("c-markov", "informs", first["record_ids"][0])], key="later"), "session-b")
    snapshot = ResearchInbox(inbox.project).snapshot()
    assert next(r for r in snapshot["bundle"]["relations"] if r["id"] in second["relation_ids"])["object"] == first["record_ids"][0]


def test_existing_source_binding_is_checked_before_capture(inbox):
    from workbench.research_graph import graph_digest
    raw = proposal(inbox)
    source = next(s for s in inbox.snapshot()["bundle"]["sources"] if s["id"] == "s-cellrank")
    raw["expected"]["s-cellrank"] = graph_digest(source)
    path = inbox.project / "workbench/data/cell_fate.json"
    bundle = json.loads(path.read_text())
    next(s for s in bundle["sources"] if s["id"] == "s-cellrank")["title"] = "Changed source"
    path.write_text(json.dumps(bundle))
    with pytest.raises(ValueError, match="Stale graph input: s-cellrank"):
        inbox.record_graph(raw, "session-a")


def test_graph_state_symlinks_are_refused(inbox, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    inbox.state.mkdir()
    (inbox.state / "graph-drafts").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        inbox.record_graph({"idempotency_key": "x", "question": None, "relations": [
            {"subject": "c-cellrank", "predicate": "informs", "object": "q-fate", "rationale": "Motivation",
             "evidence": [{"source_id": "s-cellrank", "locator": "Abstract", "note": ""}]}],
            "expected": {}, "context": {}}, "session-a")
    assert list(outside.iterdir()) == []


def test_cli_graph_capture_uses_current_thread_attribution(inbox):
    note = inbox.project / "graph.json"
    note.write_text(json.dumps(proposal(inbox)))
    result = subprocess.run([sys.executable, "-m", "workbench.automation", "--project", str(inbox.project),
                             "record-graph", str(note)], text=True, capture_output=True,
                            env={**os.environ, "CODEX_THREAD_ID": "session-cli"}, timeout=20)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    relation = next(r for r in inbox.snapshot()["bundle"]["relations"] if r["id"] in receipt["relation_ids"])
    assert relation["context"]["session_id"] == "session-cli"


def test_two_cli_graph_writers_cannot_capture_the_same_edge(inbox):
    note = inbox.project / "graph.json"
    note.write_text(json.dumps(proposal(inbox)))
    prefix = [sys.executable, "-m", "workbench.automation", "--project", str(inbox.project), "record-graph", str(note)]
    processes = [(prefix + ["--session", session], subprocess.Popen(prefix + ["--session", session],
                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)) for session in ("first", "second")]
    captured = []
    refused = []
    completed = [(command, process, process.communicate(timeout=20)) for command, process in processes]
    for command, process, (output, error) in completed:
        if process.returncode and "busy; no record was submitted" in error:
            retry = subprocess.run(command, text=True, capture_output=True, timeout=20)
            output, error, code = retry.stdout, retry.stderr, retry.returncode
        else:
            code = process.returncode
        if code:
            refused.append(error)
        else:
            captured.append(json.loads(output))
    assert len(captured) == 1 and captured[0]["recorded"]
    assert len(refused) == 1 and "Duplicate graph relation" in refused[0]
    assert inbox.status()["graph_draft_count"] == 1
    assert inbox.status()["graph_relation_count"] == 1


def test_older_snapshot_status_uses_its_own_graph_counts_during_a_save(inbox, monkeypatch):
    inbox.refresh()
    raw = proposal(inbox, [("c-cellrank", "informs", "$question")], question=question())
    original_glob = Path.glob
    saved = []
    def interleaved_listing(path, pattern, *args, **kwargs):
        files = list(original_glob(path, pattern, *args, **kwargs))
        if path == inbox.state / "graph-drafts" and not saved:
            saved.append(True)
            ResearchInbox(inbox.project).record_graph(raw, "concurrent-writer")
        return iter(files)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "glob", interleaved_listing)
        result = inbox.context("What would distinguish")
    assert result["matches"] == result["status"]["graph_draft_count"] == 0
    assert result["status"]["publication_status"] == "pending"
    assert inbox.context("What would distinguish")["matches"] == 1


def test_question_and_original_drafts_share_record_capacity_but_links_can_continue(inbox, monkeypatch):
    from workbench import automation
    monkeypatch.setattr(automation, 'MAX_DRAFTS', 1)
    inbox.record({'idempotency_key': 'one', 'kind': 'claim', 'title': 'Scoped finding',
                  'summary': 'One checked observation.', 'views': ['prediction']}, 'session-a')
    with pytest.raises(ValueError, match='full'):
        inbox.record_graph(proposal(inbox, [('$question', 'part_of', 'q-fate')],
                                    question=question()), 'session-a')
    assert inbox.record_graph(proposal(inbox), 'session-a')['recorded']


def test_graph_question_uses_original_draft_capacity(inbox, monkeypatch):
    from workbench import automation
    monkeypatch.setattr(automation, 'MAX_DRAFTS', 1)
    inbox.record_graph(proposal(inbox, [('$question', 'part_of', 'q-fate')],
                                question=question()), 'session-a')
    with pytest.raises(ValueError, match='full'):
        inbox.record({'idempotency_key': 'one', 'kind': 'claim', 'title': 'Scoped finding',
                      'summary': 'One checked observation.', 'views': ['prediction']}, 'session-a')
