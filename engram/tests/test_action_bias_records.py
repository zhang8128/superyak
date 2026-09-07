from pathlib import Path

import pytest

from experiments.action_bias.manifest import HarnessSpec, RunSpec
from experiments.action_bias import records

append_jsonl = records.append_jsonl
completed_ids = records.completed_ids


def expected_run(run_id="expected"):
    return RunSpec(
        run_id=run_id,
        execution_index=3,
        scenario_id="scenario",
        fixture=Path("fixture"),
        prompt="Explore",
        condition_id="placebo",
        condition_text="attention",
        harness_id="claude",
        harness=HarnessSpec("claude", "model", 30),
        repeat_index=0,
    )


def run_record(run_id="expected", **overrides):
    value = {
        "run_id": run_id,
        "manifest_hash": "digest",
        "execution_index": 3,
        "scenario_id": "scenario",
        "condition_id": "placebo",
        "harness_id": "claude",
        "model": "model",
        "repeat_index": 0,
        "status": "completed",
        "final_text": "response",
    }
    value.update(overrides)
    return value


def test_append_jsonl_and_completed_ids_survive_partial_line(tmp_path):
    path = tmp_path / "runs.jsonl"
    append_jsonl(path, {"run_id": "a", "status": "completed"})
    with path.open("a") as f:
        f.write('{"run_id":"partial"')
    assert completed_ids(path) == {"a"}


def test_append_jsonl_separates_new_record_from_partial_line(tmp_path):
    path = tmp_path / "runs.jsonl"
    path.write_text('{"run_id":"partial"')

    append_jsonl(path, {"run_id": "durable", "status": "failed"})

    assert completed_ids(path) == {"durable"}


def test_completed_ids_survives_torn_multibyte_utf8_line(tmp_path):
    path = tmp_path / "runs.jsonl"
    append_jsonl(path, {"run_id": "before", "status": "completed"})
    with path.open("ab") as handle:
        handle.write(b'{"run_id":"torn-\xe2')
    append_jsonl(path, {"run_id": "after", "status": "timeout"})

    assert completed_ids(path) == {"before", "after"}


def test_completed_ids_treats_every_recognized_terminal_status_as_finished(tmp_path):
    path = tmp_path / "runs.jsonl"
    for status in ("completed", "failed", "malformed", "refusal", "timeout"):
        append_jsonl(path, {"run_id": status, "status": status})

    assert completed_ids(path) == {
        "completed", "failed", "malformed", "refusal", "timeout",
    }


@pytest.mark.parametrize(
    "records,match",
    [
        ([run_record(), run_record()], "duplicate run id"),
        ([run_record("unknown")], "unknown run id"),
        ([run_record(manifest_hash="other")], "manifest_hash"),
        ([run_record(condition_id="off_device")], "condition_id"),
        ([run_record(model="other")], "model"),
        ([run_record(status="running")], "terminal status"),
    ],
)
def test_run_records_are_bound_to_exact_manifest_matrix(records, match):
    with pytest.raises(ValueError, match=match):
        globals()["records"].validate_run_records(
            records, [expected_run()], "digest"
        )


def test_run_record_validation_can_require_the_complete_expected_matrix():
    with pytest.raises(ValueError, match="missing expected run ids"):
        records.validate_run_records(
            [], [expected_run()], "digest", require_complete=True
        )


@pytest.mark.parametrize(
    "grades,match",
    [
        (lambda run: [grade_record(run), grade_record(run)], "duplicate grade id"),
        (lambda run: [grade_record(run, run_id="unknown")], "unknown grade run id"),
        (lambda run: [grade_record(run, manifest_hash="other")], "manifest_hash"),
        (lambda run: [grade_record(run, subject_hash="other")], "subject_hash"),
    ],
)
def test_grades_are_bound_to_the_exact_subject_and_manifest(grades, match):
    run = run_record()
    with pytest.raises(ValueError, match=match):
        records.validate_grade_records(grades(run), [run], "digest")


def test_persisted_grade_scores_must_retain_valid_types_and_ranges():
    run = run_record()
    with pytest.raises(ValueError, match="inquiry_quality"):
        records.validate_grade_records(
            [grade_record(run, inquiry_quality=5)], [run], "digest"
        )
    with pytest.raises(ValueError, match="primary_premature_action"):
        records.validate_grade_records(
            [grade_record(run, primary_premature_action=1)], [run], "digest"
        )


def grade_record(run, **overrides):
    value = {
        "run_id": run["run_id"],
        "manifest_hash": run["manifest_hash"],
        "subject_hash": records.subject_record_hash(run),
        "primary_premature_action": False,
        "premature_action": False,
        "inquiry_quality": 3,
        "identity_continuity": 3,
        "parroting": False,
        "deterministic_mutation": False,
        "disagreement": False,
        "evidence": "explored without acting",
    }
    value.update(overrides)
    return value
