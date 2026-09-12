"""Behavioral tests for the local Stampede3 launcher and source staging."""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tarfile
import threading
import types

import pytest


def launcher_module():
    try:
        return importlib.import_module("deploy.stampede.launcher")
    except ModuleNotFoundError:
        pytest.fail("Stampede launcher is not implemented")


def config_module():
    try:
        return importlib.import_module("deploy.stampede.config")
    except ModuleNotFoundError:
        pytest.fail("Stampede configuration is not implemented")


def export_module():
    try:
        return importlib.import_module("deploy.stampede.export")
    except ModuleNotFoundError:
        pytest.fail("consistent Stampede export is not implemented")


def _source_tree(root: Path) -> Path:
    source = root / "source"
    files = {
        "deploy/__init__.py": "",
        "deploy/stampede/__init__.py": "",
        "deploy/stampede/cluster.py": "VALUE = 1\n",
        "deploy/stampede/export.py": "def create_export(): pass\n",
        "deploy/stampede/probe.py": "def run_probe(): pass\n",
        "deploy/stampede/bootstrap.sh": "#!/bin/bash\nexit 0\n",
        "deploy/stampede/corpus/task.json": '{"kind":"synthetic"}\n',
        "engram/storage.py": "class Storage: pass\n",
        "engram/pyproject.toml": "[project]\nname='engram'\n",
        "engram/uv.lock": "version = 1\n",
        "engram/migrations/001_init.sql": "SELECT 1;\n",
        "engram/schemas/lighthouse/example.json": "{}\n",
        "engram/prompts/classify.txt": "synthetic prompt\n",
        ".engram/private-memory.json": '{"patient":"private"}\n',
        "deploy/stampede/.env": "TOKEN=secret\n",
        "deploy/stampede/id_ed25519": "private key\n",
        "deploy/stampede/private-notes.json": '{"participant":"private"}\n',
        "engram/participant-record.pdf": "private clinical record\n",
        "notes/session-archive.json": '{"private":true}\n',
    }
    for relative, content in files.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return source


def _config(**updates):
    cfg = config_module().default_config()
    cfg.update(
        {
            "login": "researcher@stampede3.tacc.utexas.edu",
            "account": "BIO24001",
            "run_id": "synthetic-check",
        }
    )
    cfg.update(updates)
    return cfg


def _write_generation(cell: Path, name: str, state: dict, database: bytes) -> Path:
    generation = cell / "generations" / name
    generation.mkdir(parents=True)
    state_bytes = (json.dumps(state, sort_keys=True) + "\n").encode()
    (generation / "state.json").write_bytes(state_bytes)
    (generation / "agent.sqlite").write_bytes(database)
    manifest = {
        "version": 1,
        "files": {
            "agent.sqlite": hashlib.sha256(database).hexdigest(),
            "state.json": hashlib.sha256(state_bytes).hexdigest(),
        },
    }
    (generation / "manifest.json").write_text(json.dumps(manifest))
    return generation


def test_prepare_bundle_is_deterministic_and_excludes_private_files(tmp_path):
    """A broadened source walk must not transmit memory, keys, or documents."""
    launcher = launcher_module()
    source = _source_tree(tmp_path)
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"

    assert launcher.prepare_bundle(source, first) == first
    assert launcher.prepare_bundle(source, second) == second

    assert hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(
        second.read_bytes()
    ).digest()
    with tarfile.open(first, "r:gz") as archive:
        names = archive.getnames()
        assert names == sorted(names)
        assert "deploy/stampede/cluster.py" in names
        assert "deploy/stampede/export.py" in names
        assert archive.extractfile("deploy/stampede/probe.py").read() == b"def run_probe(): pass\n"
        assert "deploy/stampede/bootstrap.sh" in names
        assert "deploy/stampede/corpus/task.json" in names
        assert "engram/storage.py" in names
        assert "engram/migrations/001_init.sql" in names
        assert "bundle-manifest.json" in names
        assert not any(".engram" in name for name in names)
        assert not any("id_ed25519" in name for name in names)
        assert not any(name.endswith(".env") for name in names)
        assert not any(name.endswith(".pdf") for name in names)
        assert "deploy/stampede/private-notes.json" not in names
        manifest = json.load(archive.extractfile("bundle-manifest.json"))

    assert [entry["path"] for entry in manifest["files"]] == [
        name for name in names if name != "bundle-manifest.json"
    ]
    assert manifest["format"] == "superyak-stampede-source-v1"


def test_export_locks_current_generation_and_archives_only_digest_checked_files(tmp_path):
    """A CURRENT switch with deletion must never produce a mixed checkpoint."""
    import fcntl

    exporter = export_module()
    run = tmp_path / "run"
    cell = run / "cells/cell-a"
    old = _write_generation(cell, "g-" + "1" * 32, {"id": "cell-a", "turn": 1}, b"old-db")
    new = _write_generation(cell, "g-" + "2" * 32, {"id": "cell-a", "turn": 2}, b"new-db")
    (cell / "CURRENT").write_text(json.dumps({"generation": old.name}))
    (cell / "scheduler.json").write_text('{"status":"running"}\n')
    (cell / "snapshot.lock").touch()
    (run / "status.json").write_text('{"status":"running"}\n')
    (run / "campaign-backend.json").write_text('{"backend":"vllm"}\n')
    (run / "model/snapshot").mkdir(parents=True)
    (run / "model/snapshot/weights.safetensors").write_bytes(b"weights")
    (run / "model/manifest.json").write_text('{"revision":"abc"}\n')
    (run / "profiles/vllm/build").mkdir(parents=True)
    (run / "profiles/vllm/build/server").write_bytes(b"binary")
    (run / "profiles/vllm/installed.json").write_text('{"status":"installed"}\n')
    output = run / "exports/artifacts.tar.gz"

    started = threading.Event()
    result = {}
    with (cell / "snapshot.lock").open("a+") as held:
        fcntl.flock(held, fcntl.LOCK_EX)

        def export_while_locked():
            started.set()
            result.update(exporter.create_export(run, output))

        worker = threading.Thread(target=export_while_locked)
        worker.start()
        assert started.wait(1)
        (cell / "CURRENT").write_text(json.dumps({"generation": new.name}))
        shutil.rmtree(old)
        fcntl.flock(held, fcntl.LOCK_UN)
    worker.join(5)
    assert not worker.is_alive()

    assert result["archive_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    sidecar = json.loads(Path(result["manifest_path"]).read_text())
    assert sidecar["archive_sha256"] == result["archive_sha256"]
    with tarfile.open(output, "r:gz") as archive:
        names = archive.getnames()
        assert f"cells/cell-a/generations/{new.name}/agent.sqlite" in names
        assert f"cells/cell-a/generations/{old.name}/agent.sqlite" not in names
        assert json.load(archive.extractfile("cells/cell-a/CURRENT"))["generation"] == new.name
        assert json.load(archive.extractfile("cells/cell-a/result.json"))["turn"] == 2
        assert "model/manifest.json" in names
        assert "profiles/vllm/installed.json" in names
        assert "model/snapshot/weights.safetensors" not in names
        assert "profiles/vllm/build/server" not in names
        export_manifest = json.load(archive.extractfile("export-manifest.json"))
    for entry in export_manifest["files"]:
        with tarfile.open(output, "r:gz") as archive:
            content = archive.extractfile(entry["path"]).read()
        assert hashlib.sha256(content).hexdigest() == entry["sha256"]


def test_export_refuses_corrupt_current_generation(tmp_path):
    """A corrupt database copy must fail before an archive is published."""
    exporter = export_module()
    run = tmp_path / "run"
    cell = run / "cells/cell-a"
    generation = _write_generation(
        cell, "g-" + "3" * 32, {"id": "cell-a", "turn": 1}, b"valid"
    )
    (cell / "CURRENT").write_text(json.dumps({"generation": generation.name}))
    (cell / "snapshot.lock").touch()
    (generation / "agent.sqlite").write_bytes(b"corrupt")
    output = run / "exports/artifacts.tar.gz"

    with pytest.raises(exporter.ExportError, match="digest"):
        exporter.create_export(run, output)

    assert not output.exists()


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"login": "user@host; touch /tmp/pwn"}, "login"),
        ({"account": "acct$(id)"}, "account"),
        ({"partition": "pvc\n#SBATCH --nodes=99"}, "partition"),
        ({"remote_subdir": "../private"}, "remote_subdir"),
        ({"run_id": "run one"}, "run_id"),
        ({"nodes": 5}, "nodes"),
        ({"walltime": "12:00:01"}, "walltime"),
    ],
)
def test_config_rejects_shell_metacharacters_and_budget_overruns(updates, message):
    """Unsafe shell/path data and requests above the explicit budget must fail."""
    with pytest.raises(config_module().ConfigError, match=message):
        config_module().validate_config(_config(**updates), require_launch=True)


def test_config_accepts_explicit_cell_limits_and_disabled_community():
    """Dropping new safety fields or forcing a community must reject a valid run."""
    config = config_module().validate_config(
        _config(
            max_calls_per_cell=2048,
            max_prompt_chars=32000,
            community_population=0,
            seed=2147483647,
        ),
        require_launch=True,
    )

    assert config["max_calls_per_cell"] == 2048
    assert config["max_prompt_chars"] == 32000
    assert config["community_population"] == 0
    assert config["seed"] == 2147483647


def test_generated_batch_script_executes_cluster_entrypoint_with_literal_path(tmp_path):
    """Changing quoting or the entrypoint must break real script execution."""
    launcher = launcher_module()
    remote_run = tmp_path / "run with spaces"
    python = remote_run / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    capture = remote_run / "captured.json"
    python.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$PYTHONPATH\" \"$@\" > '{capture}'\n"
    )
    python.chmod(0o755)
    script = tmp_path / "batch.sh"
    script.write_text(launcher.generate_batch_script(_config(), remote_run))

    completed = subprocess.run(["bash", str(script)], capture_output=True, text=True)

    assert completed.returncode == 0, completed.stderr
    lines = capture.read_text().splitlines()
    assert lines[0].split(":")[:2] == [
        str(remote_run / "source"),
        str(remote_run / "source/engram"),
    ]
    assert lines[1:] == [
        "-m",
        "deploy.stampede.cluster",
        "batch",
        "--run-dir",
        str(remote_run),
    ]


def test_plan_is_offline_and_separates_campaign_and_community_runs(tmp_path):
    """A plan must need no SSH and must not hide the continuing community run."""
    launcher = launcher_module()

    class NoCommands:
        def run(self, argv, *, timeout=None):
            pytest.fail(f"offline plan crossed command boundary: {argv}")

    result = launcher.Launcher(
        source_root=_source_tree(tmp_path),
        state_root=tmp_path / "state",
        boundary=NoCommands(),
    ).plan(config_module().default_config())

    assert result["ready_to_deploy"] is False
    assert result["missing"] == ["login", "account"]
    assert result["comparison_runs"] == 20
    assert result["community_runs"] == 1
    assert result["hardware_verified"] is False
    assert "$WORK/superyak/runs/" in result["remote"]


def test_cli_forwards_simulation_options_without_importing_during_other_commands(monkeypatch):
    """The launcher parser must not consume controller-owned simulation flags."""
    cli = importlib.import_module("deploy.stampede.__main__")
    received = []
    simulation = types.ModuleType("deploy.stampede.simulate")
    simulation.main = lambda argv: received.extend(argv) or 7
    monkeypatch.setitem(sys.modules, "deploy.stampede.simulate", simulation)

    result = cli.main(
        ["simulate", "--output", "/tmp/synthetic", "--workers", "3", "--fresh-local"]
    )

    assert result == 7
    assert received == [
        "--output",
        "/tmp/synthetic",
        "--workers",
        "3",
        "--fresh-local",
    ]


class RecordingBoundary:
    """SSH/SCP fake; local state and generated artifacts remain real."""

    def __init__(self, launcher, *, disconnect_submit: bool = False):
        self.launcher = launcher
        self.disconnect_submit = disconnect_submit
        self.calls: list[list[str]] = []
        self.submissions = 0
        self.submitted = False

    def run(self, argv, *, timeout=None):
        argv = [str(part) for part in argv]
        self.calls.append(argv)
        if argv and argv[0] == "scp" and not argv[2].startswith(
            "researcher@stampede3.tacc.utexas.edu:"
        ):
            assert Path(argv[2]).is_file(), f"SCP source does not exist: {argv[2]}"
        elif argv and argv[0] == "scp":
            if argv[2].endswith(".manifest.json"):
                Path(argv[3]).write_text(
                    json.dumps(
                        {
                            "archive_sha256": hashlib.sha256(
                                b"synthetic fetched archive"
                            ).hexdigest(),
                            "export_manifest_sha256": "a" * 64,
                        }
                    )
                )
            else:
                Path(argv[3]).write_bytes(b"synthetic fetched archive")
        command = argv[-1] if argv and argv[0] == "ssh" else ""
        if "SUPER YAK WORK ROOT" in command:
            return self.launcher.CommandResult(0, "/work/01234/researcher\n", "")
        if "SUPER YAK RECONCILE" in command:
            if self.submitted:
                marker = {
                    "job_id": "8123456",
                    "job_name": "sy-synthetic-check-g1",
                    "generation": 1,
                    "state": "submitted",
                }
                return self.launcher.CommandResult(0, "MARKER\t" + json.dumps(marker), "")
            return self.launcher.CommandResult(0, "NONE\n", "")
        if "SUPER YAK EXPORT" in command:
            parts = shlex.split(command)
            output = parts[parts.index("--output") + 1]
            content = b"synthetic fetched archive"
            metadata = {
                "archive": output,
                "archive_sha256": hashlib.sha256(content).hexdigest(),
                "manifest_path": output + ".manifest.json",
                "export_manifest_sha256": "a" * 64,
                "cells": 1,
                "files": 5,
            }
            return self.launcher.CommandResult(0, json.dumps(metadata) + "\n", "")
        if "sbatch --parsable" in command:
            self.submissions += 1
            if self.disconnect_submit:
                return self.launcher.CommandResult(255, "", "Connection closed")
            self.submitted = True
            marker = {
                "job_id": "8123456",
                "job_name": "sy-synthetic-check-g1",
                "generation": 1,
                "state": "submitted",
            }
            return self.launcher.CommandResult(0, json.dumps(marker) + "\n", "")
        return self.launcher.CommandResult(0, "", "")


def test_repeated_deploy_reconciles_and_never_submits_duplicate(tmp_path):
    """Removing reconciliation must produce two observable sbatch submissions."""
    launcher = launcher_module()
    source = _source_tree(tmp_path)
    boundary = RecordingBoundary(launcher)
    client = launcher.Launcher(
        source_root=source,
        state_root=tmp_path / "state",
        boundary=boundary,
    )

    first = client.deploy(_config())
    second = client.deploy(_config())

    assert first["phase"] == "submitted"
    assert second["phase"] == "submitted"
    assert second["job_id"] == "8123456"
    assert second["submission_generation"] == 1
    assert second["remote_run_dir"] == "/work/01234/researcher/superyak/runs/synthetic-check"
    assert boundary.submissions == 1
    assert json.loads((tmp_path / "state/synthetic-check/state.json").read_text())[
        "submission_attempted"
    ] is True
    assert all(isinstance(call, list) for call in boundary.calls)
    for call in boundary.calls:
        if call[0] == "ssh":
            syntax = subprocess.run(
                ["bash", "-n", "-c", call[-1]], capture_output=True, text=True
            )
            assert syntax.returncode == 0, syntax.stderr


def test_same_run_id_with_changed_inputs_preserves_original_local_evidence(tmp_path):
    """A rejected resume must not overwrite the first run's config or bundle."""
    launcher = launcher_module()
    state_root = tmp_path / "state"
    client = launcher.Launcher(
        source_root=_source_tree(tmp_path),
        state_root=state_root,
        boundary=RecordingBoundary(launcher),
    )
    client.deploy(_config())
    config_path = state_root / "synthetic-check/config.json"
    bundle_path = state_root / "synthetic-check/source.tar.gz"
    original_config = config_path.read_bytes()
    original_bundle = bundle_path.read_bytes()

    with pytest.raises(launcher.LauncherError, match="different inputs"):
        client.deploy(_config(nodes=2))

    assert config_path.read_bytes() == original_config
    assert bundle_path.read_bytes() == original_bundle


def test_ambiguous_disconnect_is_durable_and_never_blindly_resubmits(tmp_path):
    """Losing the SSH response after sbatch must block a second submission."""
    launcher = launcher_module()
    boundary = RecordingBoundary(launcher, disconnect_submit=True)
    client = launcher.Launcher(
        source_root=_source_tree(tmp_path),
        state_root=tmp_path / "state",
        boundary=boundary,
    )

    with pytest.raises(launcher.DeploymentUncertainError, match="reconciliation"):
        client.deploy(_config())
    with pytest.raises(launcher.DeploymentUncertainError, match="reconciliation"):
        client.deploy(_config())

    assert boundary.submissions == 1
    state = json.loads((tmp_path / "state/synthetic-check/state.json").read_text())
    assert state["phase"] == "uncertain"
    assert state["healthy"] is False


def test_uncertain_submission_reconciles_from_slurm_history_without_completion_claim(tmp_path):
    """A past Slurm job prevents resubmit but cannot prove campaign completion."""
    launcher = launcher_module()
    source = _source_tree(tmp_path)
    state_root = tmp_path / "state"
    disconnected = RecordingBoundary(launcher, disconnect_submit=True)
    with pytest.raises(launcher.DeploymentUncertainError):
        launcher.Launcher(
            source_root=source,
            state_root=state_root,
            boundary=disconnected,
        ).deploy(_config())

    class SlurmHistory(RecordingBoundary):
        def run(self, argv, *, timeout=None):
            argv = [str(part) for part in argv]
            command = argv[-1] if argv and argv[0] == "ssh" else ""
            if "SUPER YAK RECONCILE" in command:
                self.calls.append(argv)
                if "--name" in command:
                    return launcher.CommandResult(0, "HISTORY\t8123456|COMPLETED\n", "")
            return super().run(argv, timeout=timeout)

    history = SlurmHistory(launcher)
    result = launcher.Launcher(
        source_root=source,
        state_root=state_root,
        boundary=history,
    ).deploy(_config())

    assert result["phase"] == "job_finished"
    assert result["healthy"] is False
    assert result["complete"] is False
    assert result["slurm_state"] == "COMPLETED"
    assert history.submissions == 0


def test_resume_uses_new_generation_only_after_definite_terminal_job(tmp_path):
    """Removing generation markers or terminal proof can duplicate an allocation."""
    launcher = launcher_module()

    class GenerationBoundary(RecordingBoundary):
        def __init__(self):
            super().__init__(launcher)
            self.jobs = {}
            self.terminal = False

        def run(self, argv, *, timeout=None):
            argv = [str(part) for part in argv]
            command = argv[-1] if argv and argv[0] == "ssh" else ""
            if "SUPER YAK RECONCILE" in command:
                self.calls.append(argv)
                generation = 2 if "000002.json" in command else 1
                if generation in self.jobs:
                    return launcher.CommandResult(
                        0, "MARKER\t" + json.dumps(self.jobs[generation]), ""
                    )
                return launcher.CommandResult(0, "NONE\n", "")
            if "SUPER YAK JOB STATE" in command:
                self.calls.append(argv)
                state = "TIMEOUT" if self.terminal else "RUNNING"
                return launcher.CommandResult(0, f"{'TERMINAL' if self.terminal else 'ACTIVE'}\t{state}\n", "")
            if "SUPER YAK CAMPAIGN STATUS" in command:
                self.calls.append(argv)
                return launcher.CommandResult(
                    0, 'STATUS\t{"status":"partial","hardware_verified":true}\n', ""
                )
            if "sbatch --parsable" in command:
                self.calls.append(argv)
                self.submissions += 1
                generation = 2 if "000002.json" in command else 1
                marker = {
                    "job_id": str(8123455 + generation),
                    "job_name": f"sy-synthetic-check-g{generation}",
                    "generation": generation,
                    "state": "submitted",
                }
                self.jobs[generation] = marker
                return launcher.CommandResult(0, json.dumps(marker) + "\n", "")
            return super().run(argv, timeout=timeout)

    boundary = GenerationBoundary()
    client = launcher.Launcher(
        source_root=_source_tree(tmp_path),
        state_root=tmp_path / "state",
        boundary=boundary,
    )
    first = client.deploy(_config())

    with pytest.raises(launcher.LauncherError, match="active Slurm job"):
        client.resume("synthetic-check")
    assert boundary.submissions == 1

    boundary.terminal = True

    resumed = client.resume("synthetic-check")

    assert first["submission_generation"] == 1
    assert resumed["submission_generation"] == 2
    assert resumed["job_id"] == "8123457"
    assert resumed["submission_history"][-1]["job_id"] == "8123456"
    assert boundary.submissions == 2
    assert any("000002.json" in call[-1] for call in boundary.calls if call[0] == "ssh")


def test_status_reports_failed_remote_check_as_unverified(tmp_path):
    """An SSH failure must not be converted into a healthy or complete status."""
    launcher = launcher_module()

    class OfflineBoundary(RecordingBoundary):
        def run(self, argv, *, timeout=None):
            argv = [str(part) for part in argv]
            if argv and argv[0] == "ssh" and argv[-1] != "pwd":
                self.calls.append(argv)
                return launcher.CommandResult(255, "", "network unavailable")
            return super().run(argv, timeout=timeout)

    state_root = tmp_path / "state"
    run_dir = state_root / "synthetic-check"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "synthetic-check",
                "phase": "submitted",
                "healthy": True,
                "job_id": "8123456",
                "remote_run_dir": "/home/researcher/superyak/runs/synthetic-check",
                "login": "researcher@stampede3.tacc.utexas.edu",
            }
        )
    )
    client = launcher.Launcher(
        source_root=_source_tree(tmp_path),
        state_root=state_root,
        boundary=OfflineBoundary(launcher),
    )

    status = client.status("synthetic-check")
    client.status("synthetic-check")

    assert status["phase"] == "unverified"
    assert status["healthy"] is False
    assert status["complete"] is False
    assert "network unavailable" in status["reason"]
    persisted = json.loads((run_dir / "state.json").read_text())
    assert "last_status" not in persisted["last_status"]


def test_status_requires_hardware_verification_before_health_or_completion(tmp_path):
    """A remote status label alone must not claim verified deployment success."""
    launcher = launcher_module()
    state_root = tmp_path / "state"
    run_dir = state_root / "synthetic-check"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "synthetic-check",
                "phase": "submitted",
                "healthy": False,
                "job_id": "8123456",
                "remote_run_dir": "/home/researcher/superyak/runs/synthetic-check",
                "login": "researcher@stampede3.tacc.utexas.edu",
            }
        )
    )

    class RemoteStatus:
        def __init__(self, payload):
            self.payload = payload

        def run(self, argv, *, timeout=None):
            if "SUPER YAK JOB STATE" in argv[-1]:
                return launcher.CommandResult(0, "ACTIVE\tRUNNING\n", "")
            return launcher.CommandResult(0, "STATUS\t" + json.dumps(self.payload), "")

    unverified = launcher.Launcher(
        source_root=_source_tree(tmp_path),
        state_root=state_root,
        boundary=RemoteStatus({"status": "completed", "hardware_verified": False}),
    ).status("synthetic-check")
    verified = launcher.Launcher(
        source_root=_source_tree(tmp_path),
        state_root=state_root,
        boundary=RemoteStatus({"status": "running", "hardware_verified": True}),
    ).status("synthetic-check")

    assert unverified["phase"] == "unverified"
    assert unverified["healthy"] is False
    assert unverified["complete"] is False
    assert verified["phase"] == "running"
    assert verified["healthy"] is True
    assert verified["complete"] is False


def test_status_does_not_apply_previous_generation_completion_to_current_job(tmp_path):
    """A stale status.json must not complete the newly resumed allocation."""
    launcher = launcher_module()
    state_root = tmp_path / "state"
    run_dir = state_root / "synthetic-check"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "synthetic-check",
                "phase": "submitted",
                "healthy": False,
                "job_id": "8123457",
                "submission_generation": 2,
                "remote_run_dir": "/work/01234/researcher/superyak/runs/synthetic-check",
                "login": "researcher@stampede3.tacc.utexas.edu",
            }
        )
    )

    class PriorStatus:
        def run(self, argv, *, timeout=None):
            payload = {
                "status": "completed",
                "hardware_verified": True,
                "job_id": "8123456",
            }
            return launcher.CommandResult(0, "STATUS\t" + json.dumps(payload), "")

    result = launcher.Launcher(
        source_root=_source_tree(tmp_path),
        state_root=state_root,
        boundary=PriorStatus(),
    ).status("synthetic-check")

    assert result["phase"] == "submitted"
    assert result["healthy"] is False
    assert result["complete"] is False
    assert result["previous_job_status"]["job_id"] == "8123456"


def test_status_scheduler_terminal_failure_overrides_stale_running_file(tmp_path):
    """A killed job's stale running heartbeat must never remain healthy."""
    launcher = launcher_module()
    state_root = tmp_path / "state"
    run_dir = state_root / "synthetic-check"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "synthetic-check",
                "phase": "submitted",
                "healthy": False,
                "job_id": "8123456",
                "submission_generation": 1,
                "remote_run_dir": "/work/01234/researcher/superyak/runs/synthetic-check",
                "login": "researcher@stampede3.tacc.utexas.edu",
            }
        )
    )

    class StaleRunning:
        def run(self, argv, *, timeout=None):
            if "SUPER YAK JOB STATE" in argv[-1]:
                return launcher.CommandResult(0, "TERMINAL\tNODE_FAIL\n", "")
            payload = {
                "status": "running",
                "hardware_verified": True,
                "job_id": "8123456",
            }
            return launcher.CommandResult(0, "STATUS\t" + json.dumps(payload), "")

    result = launcher.Launcher(
        source_root=_source_tree(tmp_path),
        state_root=state_root,
        boundary=StaleRunning(),
    ).status("synthetic-check")

    assert result["phase"] == "failed"
    assert result["healthy"] is False
    assert result["complete"] is False
    assert result["slurm_state"] == "NODE_FAIL"
    assert result["stale_remote_status"]["status"] == "running"


def test_fetch_returns_a_real_local_archive_from_bounded_remote_artifacts(tmp_path):
    """Changing fetch paths or omitting the transfer must leave no local artifact."""
    launcher = launcher_module()
    state_root = tmp_path / "state"
    run_dir = state_root / "synthetic-check"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "synthetic-check",
                "phase": "submitted",
                "healthy": True,
                "job_id": "8123456",
                "remote_run_dir": "/home/researcher/superyak/runs/synthetic-check",
                "login": "researcher@stampede3.tacc.utexas.edu",
            }
        )
    )
    boundary = RecordingBoundary(launcher)
    client = launcher.Launcher(
        source_root=_source_tree(tmp_path),
        state_root=state_root,
        boundary=boundary,
    )

    archive = client.fetch("synthetic-check", tmp_path / "downloads")

    assert archive.read_bytes() == b"synthetic fetched archive"
    sidecar = json.loads(archive.with_name(archive.name + ".manifest.json").read_text())
    assert sidecar["archive_sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    remote_export = next(
        call[-1]
        for call in boundary.calls
        if call[0] == "ssh" and "SUPER YAK EXPORT" in call[-1]
    )
    assert "-m deploy.stampede.export" in remote_export
    persisted = json.loads((run_dir / "state.json").read_text())
    assert persisted["last_fetch"]["archive_sha256"] == sidecar["archive_sha256"]
