import json
from pathlib import Path
import subprocess

import pytest

from experiments.action_bias.cli import main
from experiments.action_bias.records import append_jsonl, read_jsonl


def write_manifest(tmp_path: Path, stage: str = "pilot") -> Path:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": 1,
        "experiment_id": "x",
        "stage": stage,
        "random_seed": 1,
        "repeat_count": 1,
        "fallback_tokenizer": "whitespace-v1",
        "conditions": {
            "off_device": "",
            "placebo": "a b c d",
            "existing_instinct": "e f g h",
            "counterfactual_seed": "i j k l",
        },
        "harnesses": {
            "claude": {"binary": "claude", "model": "m", "timeout_seconds": 1},
            "codex": {"binary": "codex", "model": "m", "timeout_seconds": 1},
        },
        "grader": {"binary": "claude", "model": "m", "timeout_seconds": 1},
        "scenarios": [{
            "id": "s",
            "fixture": str(fixture),
            "prompt": "Explore; don't edit.",
        }],
    }), encoding="utf-8")
    return manifest


def grade_for(run_id: str, outcome: bool = False) -> dict:
    return {
        "run_id": run_id,
        "premature_action": outcome,
        "inquiry_quality": 3,
        "identity_continuity": 3,
        "parroting": False,
        "evidence": "asked before acting",
        "deterministic_mutation": False,
        "primary_premature_action": outcome,
        "disagreement": False,
    }


def test_validate_prints_matrix_size(tmp_path, capsys):
    manifest = write_manifest(tmp_path)

    assert main(["validate", str(manifest)]) == 0
    assert "8 runs" in capsys.readouterr().out


def test_smoke_run_requires_all_selectors(tmp_path):
    manifest = write_manifest(tmp_path, stage="smoke")

    with pytest.raises(SystemExit):
        main(["run", str(manifest), "--harness", "claude"])


def test_run_records_smoke_selection_without_duplicate_append(
    tmp_path, monkeypatch, capsys
):
    manifest = write_manifest(tmp_path, stage="smoke")
    output_root = tmp_path / "results"

    def execute_and_append(run, digest, destination, scratch, live):
        assert str(scratch).startswith(str(Path(__import__("tempfile").gettempdir())))
        record = {"run_id": run.run_id, "status": "completed"}
        append_jsonl(destination / "runs.jsonl", record)
        return record

    monkeypatch.setattr(
        "experiments.action_bias.cli.execute_run", execute_and_append
    )

    assert main([
        "run", str(manifest),
        "--output-root", str(output_root),
        "--harness", "claude",
        "--condition", "off_device",
        "--limit", "1",
    ]) == 0

    assert len(list(read_jsonl(output_root / "runs.jsonl"))) == 1
    command_output = capsys.readouterr().out
    assert "harness=claude" in command_output
    assert "condition=off_device" in command_output
    assert "limit=1" in command_output


@pytest.mark.parametrize(
    "conditions", [("off_device",), ("off_device", "placebo")]
)
def test_partial_smoke_report_succeeds_and_is_excluded(
    tmp_path, conditions
):
    manifest = write_manifest(tmp_path, stage="smoke")
    output_root = tmp_path / "results"
    for condition in conditions:
        run_id = f"claude-{condition}"
        append_jsonl(output_root / "runs.jsonl", {
            "run_id": run_id,
            "scenario_id": "s",
            "harness_id": "claude",
            "condition_id": condition,
            "status": "completed",
            "final_text": "I need more context.",
            "tool_attempts": [],
            "fixture_diff": "",
        })
        append_jsonl(output_root / "grades.jsonl", grade_for(run_id))

    assert main([
        "report", str(manifest), "--output-root", str(output_root)
    ]) == 0

    assert "Excluded smoke / non-evidentiary" in (
        output_root / "report.md"
    ).read_text(encoding="utf-8")
    json.loads((output_root / "summary.json").read_text(encoding="utf-8"))


def test_pilot_report_rejects_missing_matrix_cells(tmp_path, capsys):
    manifest = write_manifest(tmp_path, stage="pilot")
    output_root = tmp_path / "results"
    append_jsonl(output_root / "runs.jsonl", {
        "run_id": "only-run",
        "scenario_id": "s",
        "harness_id": "claude",
        "condition_id": "off_device",
        "status": "completed",
    })
    append_jsonl(output_root / "grades.jsonl", grade_for("only-run"))

    assert main([
        "report", str(manifest), "--output-root", str(output_root)
    ]) == 2
    assert "missing required report cells" in capsys.readouterr().err


def test_grade_failure_is_appended_without_subject_rerun(
    tmp_path, monkeypatch
):
    manifest = write_manifest(tmp_path, stage="smoke")
    output_root = tmp_path / "results"
    append_jsonl(output_root / "runs.jsonl", {
        "run_id": "completed-run",
        "scenario_id": "s",
        "status": "completed",
    })

    monkeypatch.setattr(
        "experiments.action_bias.cli.grade_record",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("grader down")),
    )
    monkeypatch.setattr(
        "experiments.action_bias.cli.execute_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("grade reran a subject")
        ),
    )

    assert main([
        "grade", str(manifest), "--output-root", str(output_root)
    ]) == 0
    errors = list(read_jsonl(output_root / "grade-errors.jsonl"))
    assert errors == [{
        "error": "grader down",
        "error_type": "RuntimeError",
        "run_id": "completed-run",
    }]


def test_grader_subprocess_timeout_is_appended(tmp_path, monkeypatch):
    manifest = write_manifest(tmp_path, stage="smoke")
    output_root = tmp_path / "results"
    append_jsonl(output_root / "runs.jsonl", {
        "run_id": "timed-out-grading",
        "scenario_id": "s",
        "status": "completed",
    })
    monkeypatch.setattr(
        "experiments.action_bias.cli.grade_record",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired("grader", 1)
        ),
    )

    assert main([
        "grade", str(manifest), "--output-root", str(output_root)
    ]) == 0
    assert list(read_jsonl(output_root / "grade-errors.jsonl"))[0][
        "error_type"
    ] == "TimeoutExpired"
