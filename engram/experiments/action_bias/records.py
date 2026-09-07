from __future__ import annotations

import json
import os
from pathlib import Path
from hashlib import sha256

from .manifest import RunSpec


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n").encode()
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        separator = b""
        if handle.tell():
            handle.seek(-1, os.SEEK_END)
            if handle.read(1) != b"\n":
                separator = b"\n"
        handle.write(separator + payload)
        handle.flush()
        os.fsync(handle.fileno())


def read_jsonl(path: Path):
    if not path.exists():
        return
    with path.open("rb") as handle:
        for line in handle:
            try:
                value = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                yield value


def completed_ids(path: Path) -> set[str]:
    return {
        row["run_id"] for row in read_jsonl(path)
        if row.get("run_id") and row.get("status") in TERMINAL_STATUSES
    }


RUN_BINDING_FIELDS = (
    "execution_index", "scenario_id", "condition_id", "harness_id",
    "model", "repeat_index",
)
TERMINAL_STATUSES = {"completed", "failed", "malformed", "refusal", "timeout"}


def subject_record_hash(record: dict) -> str:
    payload = json.dumps(
        record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _expected_metadata(run: RunSpec) -> dict:
    return {
        "execution_index": run.execution_index,
        "scenario_id": run.scenario_id,
        "condition_id": run.condition_id,
        "harness_id": run.harness_id,
        "model": run.harness.model,
        "repeat_index": run.repeat_index,
    }


def validate_run_records(
    records: list[dict],
    expected_runs: list[RunSpec],
    manifest_digest: str,
    *,
    require_complete: bool = False,
) -> None:
    expected = {run.run_id: _expected_metadata(run) for run in expected_runs}
    seen: set[str] = set()
    for record in records:
        run_id = record.get("run_id")
        if run_id in seen:
            raise ValueError(f"duplicate run id: {run_id}")
        seen.add(run_id)
        if run_id not in expected:
            raise ValueError(f"unknown run id: {run_id}")
        if record.get("manifest_hash") != manifest_digest:
            raise ValueError(f"run {run_id} manifest_hash does not match active manifest")
        for field in RUN_BINDING_FIELDS:
            if record.get(field) != expected[run_id][field]:
                raise ValueError(
                    f"run {run_id} {field} does not match expected matrix"
                )
        if record.get("status") not in TERMINAL_STATUSES:
            raise ValueError(f"run {run_id} does not have a recognized terminal status")
    if require_complete:
        missing = sorted(set(expected) - seen)
        if missing:
            raise ValueError(f"missing expected run ids: {missing}")


def validate_grade_records(
    grades: list[dict], records: list[dict], manifest_digest: str
) -> None:
    subjects = {record.get("run_id"): record for record in records}
    seen: set[str] = set()
    for grade in grades:
        run_id = grade.get("run_id")
        if run_id in seen:
            raise ValueError(f"duplicate grade id: {run_id}")
        seen.add(run_id)
        if run_id not in subjects:
            raise ValueError(f"unknown grade run id: {run_id}")
        if subjects[run_id].get("status") != "completed":
            raise ValueError(f"grade {run_id} is attached to a non-completed run")
        if grade.get("manifest_hash") != manifest_digest:
            raise ValueError(f"grade {run_id} manifest_hash does not match active manifest")
        if grade.get("subject_hash") != subject_record_hash(subjects[run_id]):
            raise ValueError(f"grade {run_id} subject_hash does not match subject record")
        required_scores = {
            "deterministic_mutation", "disagreement", "evidence",
            "premature_action", "primary_premature_action", "inquiry_quality",
            "identity_continuity", "parroting",
        }
        missing = sorted(required_scores - set(grade))
        if missing:
            raise ValueError(f"grade {run_id} missing score fields: {missing}")
        for field in (
            "deterministic_mutation", "disagreement", "premature_action",
            "primary_premature_action", "parroting",
        ):
            if not isinstance(grade[field], bool):
                raise ValueError(f"grade {run_id} {field} must be boolean")
        for field in ("inquiry_quality", "identity_continuity"):
            if type(grade[field]) is not int or not 0 <= grade[field] <= 4:
                raise ValueError(
                    f"grade {run_id} {field} must be an integer from 0 to 4"
                )
        if not isinstance(grade["evidence"], str) or not grade["evidence"].strip():
            raise ValueError(f"grade {run_id} evidence must be non-empty")
