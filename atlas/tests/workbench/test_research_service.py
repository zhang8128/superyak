"""Worker ownership and stopping must not depend on an unchecked PID."""

import json
import subprocess
import sys

import pytest


def test_lock_ownership_drives_status_and_duplicate_launch_is_idempotent(tmp_path):
    from workbench.research_service import WorkerControl, start
    control = WorkerControl(tmp_path)
    with control.lease("worker"):
        control.update({"token": "test-run", "pid": 999999, "phase": "waiting"})
        assert control.status()["running"] is True
        result = start(tmp_path, {})
        assert result["already_running"] is True
        assert result["token"] == "test-run"
        with pytest.raises(ValueError, match="running"):
            with control.lease("worker"):
                pytest.fail("A second worker entered the lease")
    assert control.status()["running"] is False
    assert control.status()["phase"] == "not_running"


def test_stop_request_applies_only_to_current_worker_token(tmp_path):
    from workbench.research_service import WorkerControl
    control = WorkerControl(tmp_path)
    assert control.stop()["stop_requested"] is False
    with control.lease("worker"):
        control.update({"token": "first", "phase": "analyzing"})
        assert control.stop()["stop_requested"] is True
        assert control.should_stop("first") is True
        assert control.should_stop("second") is False
        control.update({"token": "second", "phase": "starting"})
        assert control.should_stop("second") is False


def test_read_only_status_and_stop_do_not_initialize_a_fresh_project(tmp_path):
    from workbench.research_service import WorkerControl
    control = WorkerControl(tmp_path)
    assert control.status()["running"] is False
    assert control.stop()["stop_requested"] is False
    assert not (tmp_path / ".atlas").exists()


def test_launcher_routes_research_status_and_stop_from_any_cwd(tmp_path):
    from pathlib import Path
    script = Path(__file__).resolve().parents[2] / "scripts/atlas_research.py"
    prefix = [sys.executable, str(script), "--project", str(tmp_path)]
    for command in ("research-status", "stop"):
        result = subprocess.run(prefix + [command], cwd=tmp_path, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["running"] is False
    assert not (tmp_path / ".atlas").exists()


def test_controller_refuses_symlink_state(tmp_path):
    from workbench.research_service import WorkerControl
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / ".atlas").symlink_to(elsewhere, target_is_directory=True)
    control = WorkerControl(tmp_path)
    with pytest.raises(ValueError, match="symlink"):
        with control.lease("worker"):
            pass
    assert list(elsewhere.iterdir()) == []


def test_finite_run_reports_cycle_failure_in_exit_code(tmp_path, monkeypatch):
    from pathlib import Path
    import shutil
    from workbench.research_model import Ollama
    from workbench.research_service import run_worker, WorkerControl
    root = Path(__file__).resolve().parents[2]
    shutil.copytree(root / "workbench/data", tmp_path / "workbench/data")
    monkeypatch.setattr(Ollama, "check", lambda self: {"model": self.model})
    def offline(*args):
        raise RuntimeError("controlled model outage")
    monkeypatch.setattr(Ollama, "plan", offline)
    assert run_worker(tmp_path, {"cycles": 1, "interval": 1}) == 2
    status = WorkerControl(tmp_path).status()
    assert status["running"] is False
    assert "controlled model outage" in str(status["last_cycle"]["errors"])


@pytest.mark.parametrize("errors, saved, expected_delays", [
    ([{"kind": "invalid_analysis", "error": "quote mismatch"}], 0, [60, 60]),
    ([{"kind": "invalid_analysis", "error": "quote mismatch"}], 2, [60, 60]),
    ([{"error": "provider unavailable"}], 0, [60, 120]),
    ([{"kind": "invalid_analysis", "error": "quote mismatch"}, {"error": "publication failed"}], 1, [60, 120]),
])
def test_only_operational_failures_slow_the_whole_worker(tmp_path, monkeypatch, errors, saved, expected_delays):
    from workbench import research_model, research_runner, research_service

    class Cycles:
        def __init__(self, *args, **kwargs):
            pass

        def cycle(self):
            return {"errors": errors, "saved": saved}

    clock = [1000.0]
    monkeypatch.setattr(research_service.time, "time", lambda: clock[0])
    monkeypatch.setattr(research_service.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(research_service.threading.Event, "wait", lambda self, timeout: clock.__setitem__(0, clock[0] + timeout))
    monkeypatch.setattr(research_model.Ollama, "check", lambda self: {})
    monkeypatch.setattr(research_runner, "ResearchRunner", Cycles)
    delays = []
    original_update = research_service.WorkerControl.update

    def observe(self, values):
        if values.get("next_cycle_at_epoch", 0) > clock[0]:
            delays.append(values["next_cycle_at_epoch"] - clock[0])
        original_update(self, values)

    monkeypatch.setattr(research_service.WorkerControl, "update", observe)
    assert research_service.run_worker(tmp_path, {"cycles": 3, "interval": 60, "roles": ["research"]}) == 2
    assert delays == expected_delays


def test_explicit_stop_disables_automatic_restart_even_after_a_crash(tmp_path, monkeypatch):
    from workbench.research_service import WorkerControl, start
    from workbench.research_model import Ollama

    control = WorkerControl(tmp_path)
    control.root.mkdir(parents=True)
    desired = control.root / "supervision.json"
    desired.write_text(json.dumps({"enabled": True, "options": {"interval": 60}}))
    control.update({"token": "crashed-worker", "phase": "analyzing", "options": {"interval": 60}})
    assert control.stop()["running"] is False
    assert json.loads(desired.read_text())["enabled"] is False
    monkeypatch.setattr(Ollama, "check", lambda self: pytest.fail("A stopped worker must not be restarted"))
    assert start(tmp_path, {}, supervised=True)["running"] is False


def test_supervision_uses_existing_worker_and_manual_start_resumes_it(tmp_path):
    from workbench.research_service import WorkerControl, start

    control = WorkerControl(tmp_path)
    with control.lease("worker"):
        options = {"model": "existing-model", "interval": 123, "batch_size": 2, "cycles": None}
        control.update({"token": "current-worker", "phase": "waiting", "options": options})
        desired = control.root / "supervision.json"
        desired.write_text(json.dumps({"enabled": False, "options": options}))
        assert start(tmp_path, {})["already_running"] is True
        assert json.loads(desired.read_text()) == {"enabled": True, "options": options}
        assert start(tmp_path, {}, supervised=True)["already_running"] is True


def test_supervision_without_configuration_does_not_start_research(tmp_path):
    from workbench.research_service import start
    assert start(tmp_path, {}, supervised=True)["running"] is False


def test_installed_launcher_routes_supervision_without_initializing_a_project(tmp_path):
    from pathlib import Path
    script = Path(__file__).resolve().parents[2] / "scripts/atlas_research.py"
    result = subprocess.run([sys.executable, str(script), "--project", str(tmp_path), "supervise"],
                            cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["running"] is False
    assert not (tmp_path / ".atlas").exists()


def test_stop_during_a_supervisor_health_check_persists_pause(tmp_path, monkeypatch):
    from workbench.research_service import WorkerControl, start
    from workbench.research_model import Ollama

    control = WorkerControl(tmp_path)
    control.root.mkdir(parents=True)
    (control.root / "supervision.json").write_text(json.dumps({"enabled": True, "options": {}}))
    monkeypatch.setattr(Ollama, "check", lambda self: control.stop())
    result = start(tmp_path, {}, supervised=True)
    assert result["running"] is False
    assert result["started"] is False
    assert control.supervision()["enabled"] is False


def test_managed_child_observes_stop_arriving_during_launch(tmp_path, monkeypatch):
    from workbench.research_service import WorkerControl, run_worker
    from workbench.research_model import Ollama

    control = WorkerControl(tmp_path)
    control.root.mkdir(parents=True)
    (control.root / "supervision.json").write_text(json.dumps({"enabled": False, "options": {}}))
    monkeypatch.setattr(Ollama, "check", lambda self: pytest.fail("Paused child must not start model work"))
    assert run_worker(tmp_path, {}, supervised=True) == 0
    assert control.status()["cycles"] == 0


@pytest.mark.parametrize("supervised, expected_code, expected_passes", [(True, 1, 5), (False, 2, 6)])
def test_repeated_operational_failures_recycle_only_a_supervised_worker(tmp_path, monkeypatch, supervised, expected_code, expected_passes):
    from workbench import research_model, research_runner, research_service

    class Stalled:
        def __init__(self, *args, **kwargs):
            pass

        def cycle(self):
            return {"errors": [{"error": "Previous HTTP request is still finishing; one request may be in flight"}]}

    control = research_service.WorkerControl(tmp_path)
    control.root.mkdir(parents=True)
    if supervised:
        (control.root / "supervision.json").write_text(json.dumps({"enabled": True, "options": {}}))
    clock = [1000.0]
    monkeypatch.setattr(research_service.time, "time", lambda: clock[0])
    monkeypatch.setattr(research_service.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(research_service.threading.Event, "wait", lambda self, timeout: clock.__setitem__(0, clock[0] + timeout))
    monkeypatch.setattr(research_model.Ollama, "check", lambda self: {})
    monkeypatch.setattr(research_runner, "ResearchRunner", Stalled)
    assert research_service.run_worker(tmp_path, {"cycles": 6, "interval": 60, "roles": ["research"]}) == expected_code
    assert control.status()["cycles"] == expected_passes
    assert control.status()["running"] is False
