"""Two bounded text calls against an already-running local model service.

This probes conversation-state handling and a fictional source correction. It
does not download models, launch servers, submit jobs, or measure research quality.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time

from .cluster import atomic_json
from .provider import LocalModel, LocalModelError


SYSTEM = (
    "This is a fictional protocol test. Use only the supplied observation. "
    "Return one JSON object with exactly these fields: source_id (string), "
    "observed (integer), total (integer), causal_effect_established (boolean), "
    "supersedes (string or null). A corrected source replaces the old count. "
    "An uncontrolled observation alone does not establish a causal effect. "
    "Put only the JSON object in your final answer."
)
TASKS = (
    ("Source probe-observation-v1: In a fictional uncontrolled bench observation, "
     "6 of 10 wells fluoresced. This is the first version; it supersedes nothing.",
     {"source_id": "probe-observation-v1", "observed": 6, "total": 10,
      "causal_effect_established": False, "supersedes": None}),
    ("Correction, source probe-observation-v2: The count was transcribed incorrectly. "
     "2 of 10 wells fluoresced. This version supersedes probe-observation-v1. "
     "The observation is still uncontrolled. Revise your answer using this version.",
     {"source_id": "probe-observation-v2", "observed": 2, "total": 10,
      "causal_effect_established": False, "supersedes": "probe-observation-v1"}),
)


def run_probe(model: LocalModel, output: Path, *, revision: str, deployment: str,
              max_tokens: int = 4096, timeout_s: float = 120) -> dict:
    """Record a fresh probe; never overwrite or automatically retry a prior run."""
    if not isinstance(revision, str) or not re.fullmatch(r"(?:[0-9a-fA-F]{40}|sha256:[0-9a-fA-F]{64})", revision):
        raise ValueError("Revision must be an exact 40-character commit or sha256 model digest")
    if not isinstance(deployment, str) or not deployment.strip() or len(deployment) > 1024:
        raise ValueError("Describe the serving backend, precision, and hardware in deployment")
    if type(max_tokens) is not int or not 1 <= max_tokens <= 32768:
        raise ValueError("Output token limit must be between 1 and 32768")
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or not math.isfinite(timeout_s) or not 0 < timeout_s <= 3600:
        raise ValueError("Request timeout must be positive, finite, and at most 3600 seconds")
    output = Path(output)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    report = {
        "version": 1, "synthetic": True, "purpose": "text_protocol_and_correction",
        "status": "running", "model": model.model, "protocol": model.protocol,
        "declared_revision": revision, "declared_deployment": deployment,
        "server_revision_verified": False,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "max_output_tokens": max_tokens, "request_timeout_s": timeout_s,
        "reasoning_effort": None if model.protocol == "synthetic" else model.reasoning_effort,
        "seed": model.seed, "temperature": 0.6, "turns": [],
    }
    atomic_json(output / "report.json", report)
    messages = [{"role": "system", "content": SYSTEM}]
    for number, (prompt, expected) in enumerate(TASKS, 1):
        messages.append({"role": "user", "content": prompt})
        request = {"messages": messages, "max_tokens": max_tokens, "timeout_s": timeout_s}
        turn = {"turn": number, "checks_passed": False}
        started = time.monotonic()
        try:
            response = model.generate(messages, max_tokens=max_tokens, timeout_s=timeout_s)
        except (LocalModelError, ValueError) as error:
            turn.update(elapsed_s=time.monotonic() - started, error=str(error))
            atomic_json(output / f"turn-{number}.json", {"request": request, "error": str(error)})
            report["turns"].append(turn)
            break
        turn.update(elapsed_s=time.monotonic() - started,
                    input_tokens=response["input_tokens"], output_tokens=response["output_tokens"])
        try:
            answer = json.loads(response["text"])
        except (ValueError, TypeError):
            answer = None
            turn["check_failure"] = "invalid_json"
        turn["checks_passed"] = (
            isinstance(answer, dict) and answer == expected
            and all(type(answer[key]) is type(value) for key, value in expected.items())
        )
        if not turn["checks_passed"]:
            turn.setdefault("check_failure", "unexpected_answer")
        artifact = output / f"turn-{number}.json"
        atomic_json(artifact, {"request": request, "response": response})
        turn.update(artifact=artifact.name, artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest())
        report["turns"].append(turn)
        atomic_json(output / "report.json", report)
        messages.append(response.get("assistant_message", {"role": "assistant", "content": response["text"]}))
    report["status"] = "passed" if len(report["turns"]) == 2 and all(
        turn["checks_passed"] for turn in report["turns"]) else "failed"
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    atomic_json(output / "report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True, help="already-running loopback HTTP service at /v1")
    parser.add_argument("--model", required=True, help="exact served model name")
    parser.add_argument("--protocol", required=True, choices=["synthetic", "kimi-k3", "glm-5.3"])
    parser.add_argument("--revision", required=True, help="loaded checkpoint commit or sha256 digest")
    parser.add_argument("--deployment", required=True, help="backend/version, precision, and hardware description")
    parser.add_argument("--output", required=True, type=Path, help="new private local results directory")
    parser.add_argument("--reasoning-effort", choices=["low", "high", "max"], default=None)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args(argv)
    try:
        model = LocalModel(args.endpoint, args.model, protocol=args.protocol,
                           reasoning_effort=args.reasoning_effort)
        result = run_probe(model, args.output, revision=args.revision, deployment=args.deployment,
                           max_tokens=args.max_tokens, timeout_s=args.timeout)
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
