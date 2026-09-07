import json
from pathlib import Path
import tarfile

import pytest

from scripts.context_compaction_followup import initialize, prepare, project_summary, report
from scripts.context_continuity_pilot import _records


@pytest.fixture
def parent(tmp_path):
    archive = Path(__file__).resolve().parents[1] / "docs/reports/2026-09-06-context-continuity-evidence.tar.gz"
    with tarfile.open(archive) as handle:
        handle.extractall(tmp_path / "parent", filter="data")
    return tmp_path / "parent/continuity-capture"


def test_import_preserves_success_and_checks_the_exact_failed_request(parent, tmp_path):
    destination = tmp_path / "followup"
    config = initialize(parent, destination)
    assert config["continuation_request_digest"] == "84e2ba5e08ff6bcc24aebc7b943397a42f1d9511a733c292f0d4ecd1f5b0de01"
    assert config["compaction_timeout_seconds"] == 300
    imported = _records(destination / "compactions.jsonl")
    assert len(imported) == 1 and imported[0]["imported_from"]
    assert imported[0]["summary"] == _records(parent / "compactions.jsonl")[0]["summary"]
    assert not (destination / "compaction-dispatches.jsonl").exists()
    initialize(parent, destination)
    assert _records(destination / "compactions.jsonl") == imported


def test_changed_parent_evidence_is_rejected_before_new_dispatch(parent, tmp_path):
    (parent / "compactions.jsonl").write_text("[]\n")
    with pytest.raises(ValueError, match="fingerprint"):
        initialize(parent, tmp_path / "followup")


def test_changed_followup_profile_is_rejected_on_resume(parent, tmp_path):
    destination = tmp_path / "followup"
    initialize(parent, destination)
    config = json.loads((destination / "configuration.json").read_text())
    config["compaction_timeout_seconds"] = 900
    (destination / "configuration.json").write_text(json.dumps(config))
    with pytest.raises(ValueError, match="configuration"):
        initialize(parent, destination)


def test_new_compaction_failure_is_preserved_and_never_replayed(parent, tmp_path):
    destination = tmp_path / "followup"
    calls = []

    class Timeout:
        def generate(self, payload):
            calls.append(payload)
            raise RuntimeError("second profile timeout")
        def close(self):
            pass

    cells = prepare(parent, destination, compactor_factory=Timeout)
    assert len(calls) == 1
    assert len(cells) == 100 and all(c.get("preparation_error") for c in cells)
    assert prepare(parent, destination, compactor_factory=lambda: pytest.fail("must not replay")) == cells
    stats = report(parent, destination)
    assert stats["compaction_dispatches"] == 1
    assert stats["compaction_usage_and_timing"]["captured"] == 1
    assert stats["imported_compaction_usage_and_timing"]["captured"] == 1
    assert stats["historical_arms"]["dynamic"]["captured"] == 100
    assert not (destination / "answers.jsonl").exists()


def test_success_builds_only_new_comparator_cells_without_changing_parent(parent, tmp_path):
    destination = tmp_path / "followup"
    before = (parent / "answers.jsonl").read_bytes()

    class Compactor:
        def generate(self, payload):
            raw = json.dumps({"summary": []})
            return {"output": [{"type": "message", "content": [{"type": "output_text", "text": raw}]}]}
        def close(self):
            pass

    cells = prepare(parent, destination, compactor_factory=Compactor)
    assert len(cells) == 100
    assert {c["arm"] for c in cells} == {"append_compact_300s_followup"}
    assert not any(c.get("preparation_error") for c in cells)
    assert (parent / "answers.jsonl").read_bytes() == before
    assert not (destination / "dispatches.jsonl").exists()


def test_summary_projection_preserves_whole_entries_and_has_a_hard_byte_cap():
    rows = [{"text": "λ" * 1600, "source_ids": ["ev-first"]},
            {"text": "second fact" * 300, "source_ids": ["ev-second"]}]
    selected = project_summary(rows, {"ev-first", "ev-second"})
    assert selected == rows[:1]
    assert project_summary(selected, {"ev-first"}) == selected
    assert rows[1]["source_ids"] == ["ev-second"]


def test_projection_rejects_invented_sources_even_in_omitted_entries():
    rows = [{"text": "x" * 5990, "source_ids": []},
            {"text": "x", "source_ids": ["invented"]}]
    with pytest.raises(ValueError, match="source"):
        project_summary(rows, set())


def test_bounded_profile_cannot_resume_a_different_profile(parent, tmp_path):
    destination = tmp_path / "bounded"
    config = initialize(parent, destination, bounded=True)
    assert config["summary_admission"] == "whole_entry_prefix"
    assert config["compaction_reasoning_effort"] == "low"
    with pytest.raises(ValueError, match="configuration"):
        initialize(parent, destination)
