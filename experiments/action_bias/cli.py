from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from .grading import grade_record
from .isolation import Isolation, isolated_environment
from .manifest import (
    CONDITION_IDS,
    build_run_matrix,
    load_manifest,
    manifest_hash,
    validate_manifest,
)
from .records import (
    append_jsonl,
    completed_ids,
    read_jsonl,
    validate_grade_records,
    validate_run_records,
)
from .reporting import (
    merge_runs_and_grades,
    render_blind_review,
    render_markdown,
    summarize,
)
from .runner import execute_run


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m experiments.action_bias.cli"
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "dry-run", "run", "grade", "report"):
        command = subcommands.add_parser(name)
        command.add_argument("manifest", type=Path)
        command.add_argument("--output-root", type=Path)
        if name == "run":
            command.add_argument("--harness", choices=("claude", "codex"))
            command.add_argument("--condition", choices=CONDITION_IDS)
            command.add_argument("--limit", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    manifest = load_manifest(args.manifest)
    errors = validate_manifest(manifest, Path.cwd())
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 2

    matrix = build_run_matrix(manifest)
    if args.command == "validate":
        print(
            f"valid: {len(matrix)} runs; hash={manifest_hash(args.manifest)}"
        )
        return 0
    if args.command == "dry-run":
        for run in matrix:
            print(json.dumps({
                "execution_index": run.execution_index,
                "run_id": run.run_id,
                "scenario_id": run.scenario_id,
                "condition_id": run.condition_id,
                "harness_id": run.harness_id,
            }, sort_keys=True))
        return 0

    output_root = (
        args.output_root
        or Path(".engram/experiments/action-bias") / manifest.experiment_id
    )
    runs_path = output_root / "runs.jsonl"
    grades_path = output_root / "grades.jsonl"
    digest = manifest_hash(args.manifest)
    runs = list(read_jsonl(runs_path))
    try:
        validate_run_records(runs, matrix, digest)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.command == "run":
        selectors = (args.harness, args.condition, args.limit)
        if manifest.stage == "smoke" and any(value is None for value in selectors):
            parser.error(
                "smoke runs require --harness, --condition, and --limit"
            )
        if args.limit is not None and args.limit < 1:
            parser.error("--limit must be positive")

        selected = [
            run for run in matrix
            if (args.harness is None or run.harness_id == args.harness)
            and (args.condition is None or run.condition_id == args.condition)
        ]
        if args.limit is not None:
            selected = selected[:args.limit]
        print(
            f"selection harness={args.harness or 'all'} "
            f"condition={args.condition or 'all'} "
            f"limit={args.limit if args.limit is not None else 'all'}"
        )

        done = completed_ids(runs_path)
        live_root = Path(
            os.environ.get("ENGRAM_HOME", Path.cwd())
        ) / ".engram"
        scratch_root = (
            Path(tempfile.gettempdir())
            / "engram-action-bias"
            / manifest.experiment_id
        )
        for run in selected:
            if run.run_id in done:
                continue
            record = execute_run(
                run, digest, output_root, scratch_root, live_root
            )
            print(f"{record['run_id']} {record['status']}")
        return 0

    if args.command == "grade":
        scenario_prompts = {
            scenario.id: scenario.prompt for scenario in manifest.scenarios
        }
        grades = list(read_jsonl(grades_path))
        try:
            validate_grade_records(grades, runs, digest)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        graded = {row["run_id"] for row in grades}
        assets_root = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(prefix="engram-grader-") as raw:
            grader_root = Path(raw)
            grader_home = grader_root / "empty-engram"
            grader_home.mkdir()
            empty_mcp = grader_root / "empty-mcp.json"
            empty_mcp.write_text('{"mcpServers": {}}\n', encoding="utf-8")
            grader_env = isolated_environment(
                os.environ,
                Isolation(grader_root, grader_home, empty_mcp),
            )
            for record in runs:
                if (
                    record.get("status") != "completed"
                    or record["run_id"] in graded
                ):
                    continue
                try:
                    grade = grade_record(
                        record,
                        scenario_prompts[record["scenario_id"]],
                        manifest.grader,
                        assets_root,
                        grader_env,
                        grader_root,
                        empty_mcp,
                    )
                except (
                    OSError,
                    RuntimeError,
                    subprocess.TimeoutExpired,
                    TimeoutError,
                    ValueError,
                ) as exc:
                    append_jsonl(output_root / "grade-errors.jsonl", {
                        "run_id": record["run_id"],
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    })
                else:
                    append_jsonl(grades_path, grade)
                    graded.add(record["run_id"])
        return 0

    grades = list(read_jsonl(grades_path))
    try:
        validate_run_records(runs, matrix, digest, require_complete=True)
        validate_grade_records(grades, runs, digest)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    completed = {
        record["run_id"]
        for record in runs
        if record.get("status") == "completed"
    }
    graded = {grade["run_id"] for grade in grades}
    missing = sorted(completed - graded)
    if missing:
        print(
            f"missing grades for {len(missing)} completed runs",
            file=sys.stderr,
        )
        return 2

    unscored = [
        record for record in runs if record.get("status") != "completed"
    ]
    if manifest.stage == "confirmatory" and unscored:
        print(
            "confirmatory report cannot include unscored/non-completed "
            f"terminal outcomes: {len(unscored)}",
            file=sys.stderr,
        )
        return 2

    rows = merge_runs_and_grades(runs, grades)
    observed_cells = {
        (row["harness_id"], row["condition_id"]) for row in rows
    }
    if not observed_cells:
        print("no graded runs to report", file=sys.stderr)
        return 2

    summary = summarize(
        rows, bootstrap_seed=manifest.random_seed, stage=manifest.stage
    )
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (output_root / "report.md").write_text(
        render_markdown(summary, manifest.stage), encoding="utf-8"
    )
    grades_by_id = {grade["run_id"]: grade for grade in grades}
    review_rows = [
        {**run, **grades_by_id.get(run["run_id"], {})} for run in runs
    ]
    (output_root / "human-review-blind.md").write_text(
        render_blind_review(review_rows), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
