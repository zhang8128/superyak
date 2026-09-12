"""Command-line entry point for ``python -m deploy.stampede``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .config import ConfigError, load_config
from .launcher import Launcher, LauncherError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare and operate a Stampede3 campaign")
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="local durable run state (default: .engram/stampede/runs)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "deploy"):
        command = subparsers.add_parser(name)
        command.add_argument("--config", type=Path, required=True)
    status = subparsers.add_parser("status")
    status.add_argument("--run-id", required=True)
    resume = subparsers.add_parser("resume")
    resume.add_argument("--run-id", required=True)
    fetch = subparsers.add_parser("fetch")
    fetch.add_argument("--run-id", required=True)
    fetch.add_argument("--destination", type=Path, required=True)
    subparsers.add_parser("simulate")
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if raw_args and raw_args[0] == "simulate":
        from .simulate import main as simulate_main

        return int(simulate_main(raw_args[1:]) or 0)
    args = _parser().parse_args(raw_args)

    source_root = Path(__file__).resolve().parents[2]
    state_root = args.state_dir or source_root / ".engram/stampede/runs"
    launcher = Launcher(source_root=source_root, state_root=state_root)
    try:
        if args.command == "plan":
            result = launcher.plan(load_config(args.config))
        elif args.command == "deploy":
            result = launcher.deploy(load_config(args.config, require_launch=True))
        elif args.command == "status":
            result = launcher.status(args.run_id)
        elif args.command == "resume":
            result = launcher.resume(args.run_id)
        else:
            archive = launcher.fetch(args.run_id, args.destination)
            manifest = archive.with_name(archive.name + ".manifest.json")
            metadata = json.loads(manifest.read_text())
            result = {
                "archive": str(archive),
                "manifest": str(manifest),
                "archive_sha256": metadata["archive_sha256"],
                "export_manifest_sha256": metadata["export_manifest_sha256"],
            }
    except (ConfigError, LauncherError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
