"""Explicit local dataset, model, training and evaluation commands."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

from .data import (
    PURPOSES,
    bounded_read,
    canonical,
    private_write,
    read_snapshot,
    snapshot_dataset,
)
from .models import download_model, prepare_model, selected_model, verify_prepared
from .serving import DEFAULT_MODEL


def parser():
    root = argparse.ArgumentParser(
        description="Clinical and biotech dataset, evaluation, and LoRA tools"
    )
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("model", help="show the exact selected model provenance")
    p = commands.add_parser(
        "snapshot", help="freeze clinical/biotech examples and source-use grants"
    )
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--purpose", choices=sorted(PURPOSES), default="local_training")
    p = commands.add_parser(
        "download", help="download and hash-check the selected public GGUF"
    )
    p.add_argument("--output", required=True, type=Path)
    p = commands.add_parser(
        "prepare", help="materialize local text weights on a high-memory host"
    )
    p.add_argument("--gguf", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p = commands.add_parser(
        "install", help="import selected GGUF into local Ollama and record provenance"
    )
    p.add_argument("--gguf", required=True, type=Path)
    p.add_argument("--endpoint", default="http://127.0.0.1:11434")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--receipt", required=True, type=Path)
    p = commands.add_parser("train", help="train or resume a local text-attention LoRA")
    p.add_argument("--model-dir", required=True, type=Path)
    p.add_argument("--snapshot", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--device", choices=["cpu", "mps", "xpu"], default="xpu")
    p.add_argument("--max-steps", type=int, default=20)
    p.add_argument("--sequence-length", type=int, default=1024)
    p.add_argument("--rank", type=int, default=16)
    p.add_argument("--alpha", type=int, default=32)
    p.add_argument("--learning-rate", type=float, default=5e-5)
    p.add_argument("--seed", type=int, default=20260913)
    p.add_argument("--gradient-accumulation-steps", type=int, default=1)
    p.add_argument("--resume", action="store_true")
    p = commands.add_parser(
        "evaluate", help="run local clinical/biotech mechanical diagnostics"
    )
    p.add_argument("--cases", required=True, type=Path)
    p.add_argument("--endpoint", default="http://127.0.0.1:11434")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--model-receipt", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p = commands.add_parser(
        "slurm", help="write an allocated XPU training script; does not submit"
    )
    p.add_argument("--account", required=True)
    p.add_argument("--reservation")
    p.add_argument("--model-dir", required=True)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--run-dir", required=True)
    p.add_argument("--python", required=True)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--resume", action="store_true")
    return root


def slurm_script(args):
    for name in ["account", "reservation"]:
        value = getattr(args, name)
        if value is not None and not re.fullmatch(r"[a-zA-Z0-9_-]+", value):
            raise ValueError(f"invalid Slurm {name}")
    paths = {}
    for name in ("python", "model_dir", "snapshot", "run_dir"):
        value = getattr(args, name)
        if any(ord(character) < 32 for character in value):
            raise ValueError(f"invalid {name.replace('_', '-')} path")
        path = Path(value)
        if not path.is_absolute():
            raise ValueError(f"{name.replace('_', '-')} must be an absolute path")
        if ".." in path.parts:
            raise ValueError(f"invalid {name.replace('_', '-')} path")
        paths[name] = str(path)
    lines = [
        "#!/bin/bash",
        "#SBATCH --job-name=superyak-clinical-lora",
        "#SBATCH --partition=pvc",
        "#SBATCH --nodes=1",
        "#SBATCH --ntasks=1",
        "#SBATCH --time=00:30:00",
        f"#SBATCH --account={args.account}",
    ]
    if args.reservation:
        lines.append(f"#SBATCH --reservation={args.reservation}")
    command = [
        paths["python"],
        "-m",
        "superyak_tuning",
        "train",
        "--model-dir",
        paths["model_dir"],
        "--snapshot",
        paths["snapshot"],
        "--output",
        paths["run_dir"],
        "--device",
        "xpu",
    ]
    if args.resume:
        command.append("--resume")
    lines += [
        "set -eu",
        "umask 077",
        "export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1",
        shlex.join(command),
    ]
    output_parent = args.output.parent
    if not output_parent.exists():
        output_parent.mkdir(parents=True, mode=0o700)
        os.chmod(output_parent, 0o700)
    private_write(args.output, ("\n".join(lines) + "\n").encode())
    return {"status": "script_written_not_submitted", "script": str(args.output)}


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "model":
            result = selected_model()
        elif args.command == "snapshot":
            manifest = snapshot_dataset(args.input, args.output, args.purpose)
            result = {
                k: manifest[k] for k in ["digest", "purpose", "example_count", "splits"]
            }
            result["snapshot"] = str(args.output)
        elif args.command == "download":
            result = download_model(args.output)
        elif args.command == "prepare":
            lineage = prepare_model(args.gguf, args.output)
            result = {"model_dir": str(args.output), "digest": lineage["digest"]}
        elif args.command == "install":
            from .serving import install_model

            receipt = install_model(args.gguf, args.endpoint, args.model, args.receipt)
            result = {"receipt": str(args.receipt), "runtime": receipt["runtime"]}
        elif args.command == "train":
            manifest, rows = read_snapshot(args.snapshot, "local_training")
            model = verify_prepared(args.model_dir)
            from .trainer import DEFAULT_SETTINGS, run_training

            settings = {name: getattr(args, name) for name in DEFAULT_SETTINGS}
            lineage = {
                "model_digest": model["digest"],
                "source": model["source"],
                "snapshot_digest": manifest["digest"],
                "purpose": manifest["purpose"],
            }
            result = run_training(
                args.model_dir, rows, args.output, settings, lineage, resume=args.resume
            )
            private_write(
                args.output / f"receipt-{result['completed_steps']}-{os.getpid()}.json",
                canonical(result) + b"\n",
            )
        elif args.command == "evaluate":
            from .evaluation import evaluate_cases
            from .serving import read_import_receipt

            cases = json.loads(bounded_read(args.cases))
            report = evaluate_cases(
                cases,
                args.endpoint,
                args.model,
                args.output,
                read_import_receipt(args.model_receipt),
            )
            result = {
                k: report[k]
                for k in [
                    "status",
                    "case_count",
                    "mechanical_passes",
                    "refusal_flags",
                    "clinical_validation",
                ]
            }
            result["report"] = str(args.output / "results.json")
        else:
            result = slurm_script(args)
        print(json.dumps(result, sort_keys=True))
        return 0
    except json.JSONDecodeError:
        print("error: invalid JSON input", file=sys.stderr)
    except FileExistsError:
        print("error: destination already exists", file=sys.stderr)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
    except ImportError:
        print(
            "error: install the optional train dependencies for this command",
            file=sys.stderr,
        )
    except (OSError, RuntimeError, subprocess.SubprocessError):
        print(
            "error: local operation failed; inspect file access, runtime and allocated device",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
