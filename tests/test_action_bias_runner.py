from dataclasses import replace
import json
import os
from pathlib import Path

import pytest

from experiments.action_bias.manifest import (
    GraderSpec,
    HarnessSpec,
    Manifest,
    RunSpec,
    Scenario,
)
from experiments.action_bias.records import append_jsonl, completed_ids
from experiments.action_bias.runner import execute_run, fixture_diff, run_pending


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


def make_manifest(tmp_path: Path) -> Manifest:
    fixture = tmp_path / "manifest-fixture"
    fixture.mkdir()
    source_path = tmp_path / "manifest.json"
    source_path.write_text("{}")
    harness = HarnessSpec(binary="/bin/true", model="stub", timeout_seconds=5)
    return Manifest(
        schema_version=1,
        experiment_id="test",
        stage="smoke",
        random_seed=1,
        repeat_count=1,
        fallback_tokenizer="whitespace-v1",
        conditions={
            "off_device": "",
            "placebo": "same",
            "existing_instinct": "same",
            "counterfactual_seed": "same",
        },
        harnesses={"claude": harness, "codex": harness},
        grader=GraderSpec(binary="/bin/true", model="stub", timeout_seconds=5),
        scenarios=(Scenario(id="scenario", fixture=fixture, prompt="Explore"),),
        source_path=source_path,
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


@pytest.mark.parametrize("mode,expected,mutated", [
    ("clean", "completed", False),
    ("mutation", "completed", True),
    ("timeout", "timeout", False),
    ("malformed", "failed", False),
])
def test_stubbed_end_to_end_modes(
    mode, expected, mutated, tmp_path, monkeypatch
):
    fixture = tmp_path / "source"
    fixture.mkdir()
    (fixture / "x.py").write_text("VALUE = 1\n")
    bodies = {
        "clean": (
            "import json; "
            "print(json.dumps({'type':'result','result':'I will examine the ambiguity'}))\n"
        ),
        "mutation": (
            "import json; from pathlib import Path; "
            "Path('x.py').write_text('VALUE = 2\\n'); "
            "print(json.dumps({'type':'result','result':'I changed it'}))\n"
        ),
        "timeout": "import time; time.sleep(2)\n",
        "malformed": "print('not json')\n",
    }
    stub = make_stub(tmp_path, bodies[mode])
    monkeypatch.setattr(
        "experiments.action_bias.runner.build_subject_command",
        lambda run, isolation: [str(stub)],
    )
    timeout = 1 if mode == "timeout" else 5
    record = execute_run(
        spec(fixture, stub, timeout=timeout),
        "digest",
        tmp_path / "out",
        tmp_path / "scratch",
        tmp_path / "live",
    )
    assert record["status"] == expected
    assert bool(record["fixture_diff"].strip()) is mutated
    assert (tmp_path / "out" / "events" / "run-1.jsonl").exists()


def test_execute_run_appends_terminal_record_before_isolation_cleanup(
    tmp_path, monkeypatch
):
    fixture = tmp_path / "source"
    fixture.mkdir()
    stub = make_stub(
        tmp_path,
        "import json; print(json.dumps({'type':'result','result':'done'}))\n",
    )
    scratch = tmp_path / "scratch"
    append_observations = []

    monkeypatch.setattr(
        "experiments.action_bias.runner.build_subject_command",
        lambda run, iso: [str(stub)],
    )

    def append_while_isolated(path, record):
        append_observations.append(bool(list(scratch.glob("*/fixture"))))
        append_jsonl(path, record)

    monkeypatch.setattr(
        "experiments.action_bias.runner.append_jsonl", append_while_isolated
    )

    execute_run(
        spec(fixture, stub),
        "digest",
        tmp_path / "out",
        scratch,
        tmp_path / "live",
    )

    assert append_observations == [True]
    assert completed_ids(tmp_path / "out" / "runs.jsonl") == {"run-1"}
    assert list(scratch.glob("*/fixture")) == []


def test_fixture_diff_reports_mutation(tmp_path):
    os.system(f"git -C {tmp_path} init -q")
    (tmp_path / "x.txt").write_text("before")
    os.system(f"git -C {tmp_path} add x.txt")
    os.system(f"git -C {tmp_path} -c user.name=t -c user.email=t@x commit -qm init")
    (tmp_path / "x.txt").write_text("after")
    assert "x.txt" in fixture_diff(tmp_path)


def test_fixture_diff_reports_untracked_file_content(tmp_path):
    os.system(f"git -C {tmp_path} init -q")
    os.system(
        f"git -C {tmp_path} -c user.name=t -c user.email=t@x "
        "commit --allow-empty -qm init"
    )
    (tmp_path / "created.txt").write_text("subject-created content\n")

    diff = fixture_diff(tmp_path)

    assert "created.txt" in diff
    assert "subject-created content" in diff


def test_run_pending_validates_before_subject_execution(tmp_path, monkeypatch):
    manifest = replace(make_manifest(tmp_path), schema_version=2)
    invocation_count = 0

    def unexpected_execute(*args, **kwargs):
        nonlocal invocation_count
        invocation_count += 1
        raise AssertionError("invalid manifest reached subject execution")

    monkeypatch.setattr("experiments.action_bias.runner.execute_run", unexpected_execute)

    with pytest.raises(ValueError, match="schema_version must be 1"):
        run_pending(
            manifest,
            tmp_path / "out",
            tmp_path / "scratch",
            tmp_path / "live",
        )

    assert invocation_count == 0


def test_run_pending_skips_all_terminal_ids_without_duplicate_append(
    tmp_path, monkeypatch
):
    manifest = make_manifest(tmp_path)
    records_path = tmp_path / "out" / "runs.jsonl"
    for run_id, status in (
        ("completed-id", "completed"),
        ("failed-id", "failed"),
        ("timeout-id", "timeout"),
    ):
        append_jsonl(records_path, {"run_id": run_id, "status": status})
    runs = [
        replace(
            spec(manifest.scenarios[0].fixture, Path("/bin/true")),
            run_id=run_id,
            execution_index=index,
        )
        for index, run_id in enumerate(
            ("completed-id", "failed-id", "timeout-id", "pending-id")
        )
    ]
    invoked = []

    monkeypatch.setattr(
        "experiments.action_bias.runner.build_run_matrix", lambda candidate: runs
    )

    def execute_and_append(run, digest, output_root, scratch_root, live_root):
        invoked.append(run.run_id)
        record = {"run_id": run.run_id, "status": "completed"}
        append_jsonl(output_root / "runs.jsonl", record)
        return record

    monkeypatch.setattr(
        "experiments.action_bias.runner.execute_run", execute_and_append
    )

    produced = run_pending(
        manifest,
        tmp_path / "out",
        tmp_path / "scratch",
        tmp_path / "live",
    )

    assert invoked == ["pending-id"]
    assert produced == [{"run_id": "pending-id", "status": "completed"}]
    assert len(records_path.read_text().splitlines()) == 4
