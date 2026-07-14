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
from .records import append_jsonl, completed_ids


def fixture_diff(root: Path) -> str:
    result = subprocess.run(
        ["git", "diff", "--no-ext-diff", "--binary", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout


def execute_run(
    run: RunSpec,
    manifest_digest: str,
    output_root: Path,
    scratch_root: Path,
    live_root: Path,
    base_env: dict[str, str] | None = None,
) -> dict:
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
        events_path = output_root / "events" / f"{run.run_id}.jsonl"
        events_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.write_text(stdout, encoding="utf-8")
    return {
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
    done = completed_ids(records_path)
    digest = manifest_hash(manifest.source_path)
    produced: list[dict] = []
    for run in build_run_matrix(manifest):
        if run.run_id in done:
            continue
        record = execute_run(run, digest, output_root, scratch_root, live_root)
        append_jsonl(records_path, record)
        produced.append(record)
    return produced
