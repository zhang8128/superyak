import json
import os
from pathlib import Path

from experiments.action_bias.manifest import HarnessSpec, RunSpec
from experiments.action_bias.runner import execute_run, fixture_diff


def make_stub(tmp_path: Path, body: str) -> Path:
    stub = tmp_path / "stub.py"
    stub.write_text("#!/usr/bin/env python3\n" + body)
    stub.chmod(0o755)
    return stub


def spec(fixture: Path, binary: Path, timeout: int = 5) -> RunSpec:
    return RunSpec(
        run_id="run-1", execution_index=0, scenario_id="scenario", fixture=fixture,
        prompt="Explore; do not edit.", condition_id="off_device", condition_text="",
        harness_id="claude",
        harness=HarnessSpec(binary=str(binary), model="stub", timeout_seconds=timeout),
        repeat_index=0,
    )


def test_execute_run_preserves_output_and_isolation(tmp_path, monkeypatch):
    fixture = tmp_path / "source"
    fixture.mkdir()
    (fixture / "x.py").write_text("VALUE = 1\n")
    stub = make_stub(
        tmp_path,
        "import json; print(json.dumps({'type':'result','result':'I will explore first'}))\n",
    )
    monkeypatch.setattr(
        "experiments.action_bias.runner.build_subject_command",
        lambda run, iso: [str(stub)],
    )
    record = execute_run(
        spec(fixture, stub),
        "digest",
        tmp_path / "out",
        tmp_path / "scratch",
        tmp_path / "live",
    )
    assert record["status"] == "completed"
    assert record["final_text"] == "I will explore first"
    assert record["manifest_hash"] == "digest"
    assert list((tmp_path / "scratch").glob("*/fixture")) == []


def test_execute_run_records_timeout_without_retry(tmp_path, monkeypatch):
    fixture = tmp_path / "source"
    fixture.mkdir()
    stub = make_stub(tmp_path, "import time; time.sleep(2)\n")
    monkeypatch.setattr(
        "experiments.action_bias.runner.build_subject_command",
        lambda run, iso: [str(stub)],
    )
    record = execute_run(
        spec(fixture, stub, timeout=1),
        "digest",
        tmp_path / "out",
        tmp_path / "scratch",
        tmp_path / "live",
    )
    assert record["status"] == "timeout"
    assert record["exit_code"] is None


def test_fixture_diff_reports_mutation(tmp_path):
    os.system(f"git -C {tmp_path} init -q")
    (tmp_path / "x.txt").write_text("before")
    os.system(f"git -C {tmp_path} add x.txt")
    os.system(f"git -C {tmp_path} -c user.name=t -c user.email=t@x commit -qm init")
    (tmp_path / "x.txt").write_text("after")
    assert "x.txt" in fixture_diff(tmp_path)
