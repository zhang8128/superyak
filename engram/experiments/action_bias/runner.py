from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import time

from .harnesses import build_subject_command, parse_subject_output
from .isolation import isolated_environment, isolated_fixture
from .manifest import (
    Manifest,
    RunSpec,
    build_run_matrix,
    manifest_hash,
    validate_manifest,
)
from .records import (
    append_jsonl, completed_ids, read_jsonl, validate_run_records,
)


def fixture_diff(root: Path) -> str:
    subprocess.run(
        ["git", "add", "--intent-to-add", "--", "."],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    result = subprocess.run(
        ["git", "diff", "--no-ext-diff", "--binary", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout


def _write_new_durable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(content.encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def execute_run(
    run: RunSpec,
    manifest_digest: str,
    output_root: Path,
    scratch_root: Path,
    live_root: Path,
    base_env: dict[str, str] | None = None,
) -> dict:
    events_path = output_root / "events" / f"{run.run_id}.jsonl"
    if events_path.exists():
        raise FileExistsError(f"refusing to overwrite event artifact: {events_path}")
    started = datetime.now(timezone.utc).isoformat()
    monotonic = time.monotonic()
    source = run.fixture if run.fixture.is_absolute() else Path.cwd() / run.fixture
    status, exit_code, stdout, stderr = "failed", None, "", ""
    parsed, diff = None, ""
    with isolated_fixture(source, scratch_root, live_root) as isolation:
        cmd = build_subject_command(run, isolation)
        env = isolated_environment(base_env or os.environ, isolation)
        try:
            proc = subprocess.run(
                cmd,
                cwd=isolation.fixture_root,
                env=env,
                text=True,
                capture_output=True,
                timeout=run.harness.timeout_seconds,
                check=False,
            )
            stdout, stderr, exit_code = proc.stdout, proc.stderr, proc.returncode
            parsed = parse_subject_output(run.harness_id, stdout)
            status = "completed" if proc.returncode == 0 and parsed.final_text else "failed"
        except subprocess.TimeoutExpired as exc:
            status = "timeout"
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            parsed = parse_subject_output(run.harness_id, stdout)
        diff = fixture_diff(isolation.fixture_root)
        _write_new_durable(events_path, stdout)
        record = {
            "run_id": run.run_id,
            "manifest_hash": manifest_digest,
            "execution_index": run.execution_index,
            "scenario_id": run.scenario_id,
            "condition_id": run.condition_id,
            "harness_id": run.harness_id,
            "model": run.harness.model,
            "repeat_index": run.repeat_index,
            "started_at": started,
            "duration_seconds": round(time.monotonic() - monotonic, 3),
            "status": status,
            "exit_code": exit_code,
            "final_text": parsed.final_text if parsed else "",
            "tool_attempts": list(parsed.tool_attempts) if parsed else [],
            "fixture_diff": diff,
            "stderr": stderr,
            "events_path": str(events_path),
        }
        append_jsonl(output_root / "runs.jsonl", record)
    return record


def run_pending(
    manifest: Manifest,
    output_root: Path,
    scratch_root: Path,
    live_root: Path,
) -> list[dict]:
    errors = validate_manifest(manifest, Path.cwd())
    if errors:
        raise ValueError("; ".join(errors))
    records_path = output_root / "runs.jsonl"
    digest = manifest_hash(manifest.source_path)
    matrix = build_run_matrix(manifest)
    validate_run_records(list(read_jsonl(records_path)), matrix, digest)
    done = completed_ids(records_path)
    produced: list[dict] = []
    for run in matrix:
        if run.run_id in done:
            continue
        record = execute_run(run, digest, output_root, scratch_root, live_root)
        produced.append(record)
    return produced
