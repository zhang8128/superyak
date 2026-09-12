"""Export one cached research task, or run it against an explicit local model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def _nonblank(value):
    if not value.strip():
        raise argparse.ArgumentTypeError("A nonblank declared value is required")
    return value.strip()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command")
    export = commands.add_parser("export", help="Freeze one selected question and cached source")
    export.add_argument("--project", required=True, type=Path)
    export.add_argument("--question-id", required=True)
    export.add_argument("--job-id", required=True)
    export.add_argument("--output", required=True, type=Path, help="New packet file outside the selected project")

    run = commands.add_parser("run", help="Run or replay a frozen task in its own output directory")
    run.add_argument("--packet", required=True, type=Path)
    run.add_argument("--output", required=True, type=Path)
    run.add_argument("--backend", required=True, choices=("ollama", "completions"))
    run.add_argument("--model", required=True, type=_nonblank)
    run.add_argument("--model-revision", required=True, type=_nonblank,
                     help="Operator-declared revision or digest; server revision is not verified")
    run.add_argument("--endpoint", required=True, help="Credential-free loopback HTTP model endpoint")
    run.add_argument("--protocol", choices=("research", "kimi-k3", "glm-5.3"), default="research")
    run.add_argument("--timeout", type=float, default=120, help="Maximum seconds per model request")
    run.add_argument("--output-tokens", type=int, default=1800)
    run.add_argument("--seed", type=int, default=0, help="Completions seed; Ollama accepts only the default 0")
    run.add_argument("--reasoning-effort", choices=("low", "high", "max"),
                     help="Optional native lead protocol setting")
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    try:
        if args.command == "export":
            from .packet import export_task

            task = export_task(args.project, args.question_id, args.job_id, args.output)
            print(json.dumps({"task_id": task["task_id"], "packet": str(args.output.resolve()),
                              "packet_sha256": task["packet_sha256"], "historical_prompt_replay": False}, indent=2))
            return 0

        if args.backend == "ollama" and args.seed != 0:
            raise ValueError("Ollama research does not implement a custom seed; use --seed 0")

        from .providers import create_model
        from .runner import run_task

        model = create_model(args.backend, args.model, args.endpoint, protocol=args.protocol,
                             timeout=args.timeout, output_tokens=args.output_tokens,
                             seed=args.seed, reasoning_effort=args.reasoning_effort)
        config = {key: getattr(args, key) for key in (
            "backend", "model", "model_revision", "endpoint", "protocol", "timeout",
            "output_tokens", "seed", "reasoning_effort")}
        result = run_task(args.packet, args.output, model, config=config)
        print(json.dumps({"task_id": result["task_id"], "status": result["status"],
                          "output": str(args.output.resolve()), "model": model.model,
                          "model_revision": args.model_revision, "model_revision_verified": False,
                          "scientific_status": result["scientific_status"]}, indent=2))
        return 1 if result["status"] in {"failed", "invalid"} else 0
    except (OSError, ValueError, RuntimeError) as error:
        print(f"research-task: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
