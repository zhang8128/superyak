"""The disposable pilot exercises a real crossing without live configuration."""

import json
import sqlite3
import subprocess
import sys

import pytest

from lighthouse_protocol import canonical_json, content_digest
from lighthouse_receipts import validate_receipt


def test_pilot_cli_exercises_denial_withdrawal_and_store_integrity(tmp_path):
    output = tmp_path / "pilot"
    completed = subprocess.run(
        [sys.executable, "-m", "lighthouse_pilot", "--output", str(output)],
        capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads((output / "report.json").read_text())
    assert report["humanUsefulnessEvaluated"] is False
    assert report["checks"] and all(report["checks"].values())
    assert {
        name: scenario["deliveredCount"]
        for name, scenario in report["scenarios"].items()
    } == {"allowed": 1, "denied": 0, "policy_withdrawn": 0, "unshared": 0}
    assert report["scenarios"]["allowed"]["selectedCount"] == 1
    assert report["scenarios"]["denied"]["selectedCount"] == 1
    assert report["scenarios"]["policy_withdrawn"]["selectedCount"] == 0
    assert report["scenarios"]["unshared"]["selectedCount"] == 0

    exported = json.dumps(report)
    for name, scenario in report["scenarios"].items():
        receipt = json.loads((output / scenario["receiptFile"]).read_text())
        validate_receipt(receipt)
        assert receipt["payload"]["injected"] is (name == "allowed")
        snapshot = receipt["extensions"]["engram:traceSnapshots"][0]
        assert receipt["payload"]["sources"][0]["storeDigest"] == content_digest(
            canonical_json(snapshot)
        )
        if name == "allowed":
            assert snapshot["candidates"][0]["lane"] == "personal"
            assert snapshot["candidates"][0]["audiences"] == ["commons"]
        if name == "policy_withdrawn":
            assert snapshot["decision"]["effect"] == "deny"
        exported += json.dumps(receipt)

    with sqlite3.connect(output / "stores" / "source.db") as connection:
        contents = [row[0] for row in connection.execute("SELECT content FROM episodes")]
    assert len(contents) >= 2
    assert all(content not in exported for content in contents)
    assert "Synthetic bridge maintenance guidance" not in exported
    assert '"query":' not in exported
    assert '"content":' not in exported
    assert not list(output.rglob("*.sock"))


def test_pilot_refuses_existing_output_directory(tmp_path):
    from lighthouse_pilot import run_pilot

    sentinel = tmp_path / "keep.txt"
    sentinel.write_text("unchanged")
    with pytest.raises(FileExistsError):
        run_pilot(tmp_path)
    assert sentinel.read_text() == "unchanged"
    assert list(tmp_path.iterdir()) == [sentinel]


def test_pilot_does_not_report_success_when_crossing_fails(tmp_path, monkeypatch):
    import lighthouse_pilot

    monkeypatch.setattr(lighthouse_pilot, "neighbor_arm", lambda **kwargs: None)
    output = tmp_path / "failed"
    with pytest.raises(RuntimeError, match="CROSSING_FAILED"):
        lighthouse_pilot.run_pilot(output)
    assert not (output / "report.json").exists()


def test_pilot_detects_private_source_byte_changes(tmp_path, monkeypatch):
    import lighthouse_pilot

    output = tmp_path / "changed"
    consult = lighthouse_pilot.neighbor_arm

    def consult_then_tamper(**kwargs):
        result = consult(**kwargs)
        source = output / "stores" / "source.db"
        source.write_bytes(source.read_bytes() + b"tampered")
        return result

    monkeypatch.setattr(lighthouse_pilot, "neighbor_arm", consult_then_tamper)
    with pytest.raises(RuntimeError, match="PRIVATE_SOURCE_CHANGED"):
        lighthouse_pilot.run_pilot(output)
    assert not (output / "report.json").exists()
