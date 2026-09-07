"""Check sibling schemas and real Engram receipts with the Lighthouse validator."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    schemas = ("connection-policy.schema.json", "recall-receipt.schema.json")
    for name in schemas:
        vendored = ROOT / "engram" / "schemas" / "lighthouse" / name
        upstream = ROOT / "lighthouse" / "schemas" / name
        if vendored.read_bytes() != upstream.read_bytes():
            raise RuntimeError(f"Engram's vendored {name} differs from Lighthouse")

    with tempfile.TemporaryDirectory(prefix="superyak-integration-") as temporary:
        output = Path(temporary) / "pilot"
        subprocess.run(
            [sys.executable, "-m", "lighthouse_pilot", "--output", str(output)],
            cwd=ROOT / "engram", check=True, timeout=60,
        )
        report = json.loads((output / "report.json").read_text())
        checks = report["checks"]
        if not checks or not all(value is True for value in checks.values()):
            raise RuntimeError("The disposable crossing did not pass every check")
        if report["synthetic"] is not True or report["humanUsefulnessEvaluated"] is not False:
            raise RuntimeError("The crossing must use only synthetic fixtures")
        scenarios = report["scenarios"]
        if set(scenarios) != {"allowed", "denied", "policy_withdrawn", "unshared"}:
            raise RuntimeError("The crossing did not exercise all four scenarios")
        for scenario in scenarios.values():
            receipt = output / scenario["receiptFile"]
            subprocess.run(
                ["pnpm", "lighthouse", "validate", str(receipt)],
                cwd=ROOT / "lighthouse", check=True, timeout=60,
            )
        print(
            f"Integration passed: {len(schemas)} matching schemas, "
            f"{len(checks)} socket checks, {len(scenarios)} validated receipts."
        )


if __name__ == "__main__":
    main()
