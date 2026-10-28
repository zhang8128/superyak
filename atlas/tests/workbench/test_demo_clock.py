"""The offline pilot evaluates as of its own publication, so nothing in the demo expires on its own."""

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]


def _demo():
    spec = importlib.util.spec_from_file_location("superyak_atlas_demo", ROOT / "scripts/atlas.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def far_future(monkeypatch):
    """A wall clock long past every fixture rule: anything that still reads it shows up as an expired rule."""
    from workbench import automation
    monkeypatch.setattr(automation, "_now", lambda: "2031-01-01T00:00:00.000000+00:00")


def test_inbox_uses_its_clock_for_records_and_policy(tmp_path, far_future):
    demo = _demo()
    project = demo.seed_project(tmp_path / "pilot")
    start, clock = demo.pilot_clock(project)
    from workbench.automation import ResearchInbox

    inbox = ResearchInbox(project, clock=clock)
    inbox.refresh()
    status = inbox.status()
    assert status["policy_evaluated_at"].startswith(start.isoformat()[:19])
    assert status["overlaps"]["prediction<-regulation"]["status"] == "compared"
    assert status["overlaps"]["prediction<-regulation"]["shared_records"] > 0


def test_demo_reads_as_published_whatever_the_date(tmp_path, far_future, capsys):
    demo = _demo()
    assert demo.main(["--project", str(tmp_path / "pilot")]) == 0
    report = json.loads(capsys.readouterr().out)
    issued = max(json.loads((ROOT / "atlas" / relative).read_text())["issued_at"]
                 for relative in demo.SEED_FILES if relative.startswith("workbench/data/lighthouses/"))
    assert report["publication_status"] == "current"
    assert report["evaluated_as_of"] > issued
    assert report["overlaps"]["prediction<-regulation"] == {"status": "compared", "shared_records": 5}
    # The regulation view has no rule for prediction's records: denied by design, not by expiry.
    assert report["overlaps"]["regulation<-prediction"]["status"] == "denied"


def test_without_a_clock_the_inbox_keeps_the_wall_clock(tmp_path, far_future):
    demo = _demo()
    project = demo.seed_project(tmp_path / "pilot")
    from workbench.automation import ResearchInbox

    inbox = ResearchInbox(project)
    inbox.refresh()
    status = inbox.status()
    assert status["policy_evaluated_at"].startswith("2031-01-01")
    assert status["overlaps"]["prediction<-regulation"]["status"] == "denied"
