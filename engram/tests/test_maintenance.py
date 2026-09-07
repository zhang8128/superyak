"""Tests for the sleep-maintenance pain channel."""

from pathlib import Path

import pytest

from maintenance import MaintenanceReport
from storage import Storage

MIGRATIONS_DIR = str(Path(__file__).parent.parent / "migrations")


@pytest.fixture
def storage(tmp_path):
    s = Storage(str(tmp_path / "test.db"), migrations_dir=MIGRATIONS_DIR)
    yield s
    s.close()


def test_step_records_success():
    r = MaintenanceReport()
    with r.step("decay"):
        pass
    assert [s["name"] for s in r.steps] == ["decay"]
    assert r.steps[0]["ok"] is True
    assert r.failures == []


def test_step_swallows_and_records_failure():
    r = MaintenanceReport()
    with r.step("auto-compress"):
        raise ValueError("poisoned context")
    # Execution continues past the failed step — nothing propagates.
    assert len(r.failures) == 1
    f = r.failures[0]
    assert f["name"] == "auto-compress"
    assert "poisoned context" in f["error"]


def test_note_attaches_counts():
    r = MaintenanceReport()
    with r.step("prune"):
        pass
    r.note("prune", pruned=3)
    assert r.steps[0]["pruned"] == 3


def test_save_and_load_last_roundtrip(storage):
    r = MaintenanceReport()
    with r.step("decay"):
        pass
    with r.step("auto-compress"):
        raise RuntimeError("boom")
    r.save(storage.conn)

    loaded = MaintenanceReport.load_last(storage.conn)
    assert loaded is not None
    assert loaded["ok"] is False
    assert loaded["at"]
    names = [f["name"] for f in loaded["failures"]]
    assert names == ["auto-compress"]
    assert "boom" in loaded["failures"][0]["error"]


def test_load_last_returns_most_recent(storage):
    bad = MaintenanceReport()
    with bad.step("decay"):
        raise RuntimeError("old failure")
    bad.save(storage.conn)

    good = MaintenanceReport()
    with good.step("decay"):
        pass
    good.save(storage.conn)

    loaded = MaintenanceReport.load_last(storage.conn)
    assert loaded["ok"] is True


def test_load_last_none_when_absent(storage):
    assert MaintenanceReport.load_last(storage.conn) is None
