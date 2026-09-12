"""Durable session drafts and their automatically refreshed publication views."""

import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def project(tmp_path):
    data = tmp_path / "workbench" / "data"
    data.mkdir(parents=True)
    shutil.copyfile(ROOT / "workbench/data/cell_fate.json", data / "cell_fate.json")
    shutil.copytree(ROOT / "workbench/data/lighthouses", data / "lighthouses")
    (data / "lighthouse-automation.json").write_text(json.dumps({
        "version": 1, "bundle": "workbench/data/cell_fate.json",
        "views": {
            "prediction": "workbench/data/lighthouses/prediction.json",
            "regulation": "workbench/data/lighthouses/regulation.json",
        },
    }))
    return tmp_path


@pytest.fixture
def draft():
    return {
        "idempotency_key": "cellrank-boundary-1", "kind": "claim",
        "title": "Fate prediction needs an independent outcome check",
        "summary": "Compare inferred fate probabilities with measured outcomes before transferring this result to another system.",
        "views": ["prediction"],
        "context": {"scope": "A proposed follow-up to the local CellRank pilot"},
        "evidence": [{"source_id": "s-cellrank", "locator": "Abstract",
                      "note": "Existing pilot source; this draft is not an expert assessment."}],
        "links": [{"predicate": "informs", "target": "q-fate",
                   "rationale": "Identifies a validation question for this prediction task."}],
    }


def test_record_persists_attributed_draft_and_refreshes_selected_view(project, draft):
    from workbench.automation import ResearchInbox

    inbox = ResearchInbox(project)
    source_before = (project / "workbench/data/cell_fate.json").read_bytes()
    receipt = inbox.record(draft, session_id="session-a")
    assert receipt["recorded"] is True
    assert receipt["duplicate"] is False
    assert receipt["publication_status"] == "current"
    result = inbox.context(query="Fate prediction needs", limit=5)
    item = result["records"][0]
    assert item["record"]["status"] == "proposed"
    assert item["record"]["provenance"]["session_id"] == "session-a"
    assert item["record"]["evidence"][0]["source_id"] == "s-cellrank"
    assert item["views"] == ["prediction"]
    generation = project / ".atlas/publications" / receipt["generation"]
    prediction = json.loads((generation / "prediction.json").read_text())
    regulation = json.loads((generation / "regulation.json").read_text())
    assert len(prediction["claims"]) == 12
    assert len(regulation["claims"]) == 11
    assert any(r["subject"] == receipt["record_id"] for r in prediction["snapshot"]["payload"]["model"]["relations"])
    assert (project / "workbench/data/cell_fate.json").read_bytes() == source_before
    assert ResearchInbox(project).status()["draft_count"] == 1


def test_record_receipt_survives_publication_failure_and_refresh_recovers(project, draft, monkeypatch):
    from workbench import automation

    inbox = automation.ResearchInbox(project)
    previous = inbox.refresh()["generation"]
    with monkeypatch.context() as patch:
        def full_disk(*args):
            raise OSError("publication disk is full")
        patch.setattr(automation.os, "rename", full_disk)
        receipt = inbox.record(draft, session_id="session-a")
    assert receipt["recorded"] is True
    assert receipt["publication_status"] == "pending"
    assert "publication disk is full" in receipt["error"]
    assert inbox.status()["generation"] == previous
    assert inbox.status()["publication_status"] == "pending"
    assert inbox.context(query=receipt["record_id"])["matches"] == 1
    recovered = inbox.refresh()
    assert recovered["generation"] != previous
    replay = inbox.record(draft, session_id="session-a")
    assert replay["record_id"] == receipt["record_id"]
    assert replay["duplicate"] is True
    assert replay["generation"] == recovered["generation"]
    assert inbox.status()["draft_count"] == 1


def test_cli_records_and_reads_a_draft(project, draft):
    note = project / "note.json"
    note.write_text(json.dumps(draft))
    prefix = [sys.executable, "-m", "workbench.automation", "--project", str(project)]
    saved = subprocess.run(prefix + ["record", str(note), "--session", "session-cli"],
                           text=True, capture_output=True)
    assert saved.returncode == 0, saved.stderr
    receipt = json.loads(saved.stdout)
    assert receipt["recorded"] is True
    shown = subprocess.run(prefix + ["context", receipt["record_id"]], text=True, capture_output=True)
    assert shown.returncode == 0, shown.stderr
    assert json.loads(shown.stdout)["records"][0]["record"]["provenance"]["session_id"] == "session-cli"


def test_mcp_records_with_request_session_and_returns_context(project, draft):
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def exercise():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "workbench.automation", "--project", str(project), "mcp"],
            cwd=str(ROOT), env={**os.environ, "CODEX_THREAD_ID": "wrong-server-session"},
        )
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                initialized = await client.initialize()
                assert "record" in initialized.instructions
                names = {tool.name for tool in (await client.list_tools()).tools}
                assert names == {"atlas_context", "atlas_record", "atlas_record_graph", "atlas_refresh", "atlas_status"}
                saved = await client.call_tool("atlas_record", {"draft": draft}, meta={"threadId": "actual-request-session"})
                assert saved.isError is False
                receipt = json.loads(saved.content[0].text)
                assert receipt["session_id"] == "actual-request-session"
                shown = await client.call_tool("atlas_context", {"query": receipt["record_id"]})
                assert json.loads(shown.content[0].text)["records"][0]["record"]["provenance"]["session_id"] == "actual-request-session"
                forged = await client.call_tool("atlas_record", {"draft": draft | {"session_id": "forged"}}, meta={"threadId": "actual-request-session"})
                assert forged.isError is True
                # The SDK omits None metadata fields on the wire; an explicit
                # empty identity must survive serialization and fail closed.
                missing = await client.call_tool("atlas_record", {"draft": draft}, meta={"threadId": ""})
                assert missing.isError is True
                from workbench.automation import ResearchInbox
                from workbench.research_graph import graph_digest
                records = {r["id"]: r for r in ResearchInbox(project).snapshot()["bundle"]["items"]}
                proposal = {
                    "idempotency_key": "mcp-overlap-1", "question": None,
                    "relations": [{"subject": "c-cellrank", "predicate": "informs", "object": "q-fate",
                                   "rationale": "This located observation motivates a validation question.",
                                   "context": {}, "evidence": draft["evidence"]}],
                    "expected": {key: graph_digest(records[key]) for key in ("c-cellrank", "q-fate")},
                    "context": {"model": "fixture"},
                }
                graph = await client.call_tool("atlas_record_graph", {"proposal": proposal}, meta={"threadId": "graph-request-session"})
                assert graph.isError is False
                graph_receipt = json.loads(graph.content[0].text)
                assert graph_receipt["session_id"] == "graph-request-session"
                relation = next(r for r in ResearchInbox(project).snapshot()["bundle"]["relations"]
                                if r["id"] in graph_receipt["relation_ids"])
                assert relation["context"]["session_id"] == "graph-request-session"
                forged_graph = await client.call_tool("atlas_record_graph", {"proposal": proposal | {"session_id": "forged"}},
                                                      meta={"threadId": "graph-request-session"})
                assert forged_graph.isError is True
    asyncio.run(exercise())


def test_status_checks_current_policy_time_without_renewing_grants(project, draft, monkeypatch):
    from workbench import automation

    inbox = automation.ResearchInbox(project)
    monkeypatch.setattr(automation, "_now", lambda: "2026-09-08T00:00:00+00:00")
    receipt = inbox.record(draft, "session-a")
    before = inbox.status()
    assert before["overlaps"]["prediction<-regulation"]["status"] == "compared"
    assert before["overlaps"]["regulation<-prediction"]["status"] == "denied"
    monkeypatch.setattr(automation, "_now", lambda: "2026-11-08T00:00:00+00:00")
    assert inbox.status()["overlaps"]["prediction<-regulation"]["status"] == "denied"
    assert inbox.refresh()["generation"] == receipt["generation"]


def test_status_detects_missing_publication_while_preserving_draft_context(project, draft):
    from workbench.automation import ResearchInbox

    inbox = ResearchInbox(project)
    receipt = inbox.record(draft, "session-a")
    (project / ".atlas/publications" / receipt["generation"] / "prediction.json").unlink()
    status = inbox.status()
    assert status["publication_status"] == "invalid"
    assert "prediction.json" in status["error"]
    assert inbox.context(query=receipt["record_id"])["matches"] == 1


def test_idempotency_is_per_session_and_changed_content_conflicts(project, draft):
    from workbench.automation import ResearchInbox

    inbox = ResearchInbox(project)
    first = inbox.record(draft, "session-a")
    replay = inbox.record(draft, "session-a")
    assert replay["duplicate"] is True
    assert replay["generation"] == first["generation"]
    with pytest.raises(ValueError, match="different content"):
        inbox.record(draft | {"summary": "A materially different interpretation."}, "session-a")
    independent = inbox.record(draft, "session-b")
    assert independent["record_id"] != first["record_id"]
    assert inbox.status()["draft_count"] == 2
    assert len(list((project / ".atlas/publications").iterdir())) == 2


@pytest.mark.parametrize("changes", [
    {"status": "reviewed"}, {"session_id": "forged"}, {"views": ["external"]},
    {"views": ["prediction", "prediction"]}, {"kind": "fact"},
    {"summary": "x" * 66000}, {"context": {"unsupported": 0.5}},
    {"evidence": [{"source_id": "missing", "locator": "Abstract", "note": ""}]},
    {"links": [{"predicate": "requires", "target": "q-fate", "rationale": "Claim cannot be a dependency."}]},
    {"sources": [{"id": "s-cellrank", "title": "Replacement", "url": "https://example.org", "year": 2026, "citation": ""}]},
])
def test_invalid_drafts_leave_no_record(project, draft, changes):
    from workbench.automation import ResearchInbox
    from workbench.validation import WorkbenchError

    inbox = ResearchInbox(project)
    with pytest.raises((ValueError, WorkbenchError)):
        inbox.record(draft | changes, "session-a")
    assert inbox.status()["draft_count"] == 0
    assert not (project / ".atlas/current.json").exists()


@pytest.mark.parametrize("location", [".atlas", ".atlas/drafts", ".atlas/publications", ".atlas/lock"])
def test_state_symlinks_are_refused(project, draft, tmp_path, location):
    from workbench.automation import ResearchInbox

    outside = tmp_path / "outside"
    outside.mkdir()
    target = project / location
    target.parent.mkdir(exist_ok=True)
    target.symlink_to(outside)
    with pytest.raises((ValueError, OSError)):
        ResearchInbox(project).record(draft, "session-a")
    assert list(outside.iterdir()) == []


def test_combined_export_imports_into_actual_store(project, draft):
    from workbench.automation import ResearchInbox
    from workbench.store import Store

    inbox = ResearchInbox(project)
    receipt = inbox.record(draft | {"views": ["prediction", "regulation"]}, "session-a")
    bundle = json.loads(Path(inbox.status()["bundle"]).read_text())
    with Store(project / "ordinary-workbench.db", create=True) as store:
        assert store.import_bundle(bundle) == {"sources": 6, "items": 18, "relations": 21}
        assert store.get(receipt["record_id"])["provenance"]["session_id"] == "session-a"


def test_corrupted_journal_is_detected(project, draft):
    from workbench.automation import ResearchInbox

    inbox = ResearchInbox(project)
    receipt = inbox.record(draft, "session-a")
    path = project / ".atlas/drafts" / (receipt["record_id"] + ".json")
    entry = json.loads(path.read_text())
    entry["draft"]["summary"] = "Changed without its capture receipt."
    path.write_text(json.dumps(entry))
    with pytest.raises(ValueError, match="integrity"):
        inbox.context()


def test_status_detects_changed_derived_bundle(project, draft):
    from workbench.automation import ResearchInbox

    inbox = ResearchInbox(project)
    inbox.record(draft, "session-a")
    path = Path(inbox.status()["bundle"])
    bundle = json.loads(path.read_text())
    bundle["title"] = "A different source collection"
    path.write_text(json.dumps(bundle))
    assert inbox.status()["publication_status"] == "invalid"


@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_missing_or_changed_overlap_report_invalidates_generation(project, draft, damage):
    from workbench.automation import ResearchInbox

    inbox = ResearchInbox(project)
    receipt = inbox.record(draft, "session-a")
    path = project / ".atlas/publications" / receipt["generation"] / "prediction-receives-regulation.json"
    if damage == "missing":
        path.unlink()
    else:
        report = json.loads(path.read_text())
        report["record_pairs"] = []
        path.write_text(json.dumps(report))
    assert inbox.status()["publication_status"] == "invalid"
    with pytest.raises((ValueError, OSError)):
        inbox.refresh()


def test_context_and_status_share_one_snapshot_during_a_concurrent_save(project, draft, monkeypatch):
    from workbench.automation import ResearchInbox

    reader = ResearchInbox(project)
    reader.refresh()
    original_glob = Path.glob
    written = []

    def interleaved_listing(path, pattern, *args, **kwargs):
        snapshot = list(original_glob(path, pattern, *args, **kwargs))
        if path == project / ".atlas/drafts" and not written:
            written.append(True)
            ResearchInbox(project).record(draft, "concurrent-writer")
        return iter(snapshot)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "glob", interleaved_listing)
        snapshot = reader.context(query="Fate prediction needs")
    assert written == [True]
    assert snapshot["matches"] == snapshot["status"]["draft_count"] == 0
    assert snapshot["status"]["publication_status"] == "pending"
    assert reader.context(query="Fate prediction needs")["matches"] == 1


def test_two_cli_writers_do_not_lose_or_duplicate_records(project, draft):
    prefix = [sys.executable, "-m", "workbench.automation", "--project", str(project)]
    processes = []
    for session in ("session-a", "session-b"):
        path = project / (session + ".json")
        path.write_text(json.dumps(draft))
        command = prefix + ["record", str(path), "--session", session]
        processes.append((command, subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)))
    receipts = []
    completed = [(command, process, process.communicate(timeout=15)) for command, process in processes]
    for command, process, (output, error) in completed:
        if process.returncode:
            assert "busy; no record was submitted" in error
            retry = subprocess.run(command, capture_output=True, text=True, timeout=15)
            assert retry.returncode == 0, retry.stderr
            output = retry.stdout
        receipts.append(json.loads(output))
    assert len({receipt["record_id"] for receipt in receipts}) == 2
    from workbench.automation import ResearchInbox
    assert ResearchInbox(project).status()["draft_count"] == 2
