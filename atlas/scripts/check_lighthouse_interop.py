"""Validate Atlas publications with the independent Lighthouse TypeScript kit."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workbench.lighthouse import PROFILE, SENTENCE, read_json, validate_publication
from workbench.lighthouse_wire import authorize, digest


NODE_CHECK = r'''
import fs from "node:fs";
import { pathToFileURL } from "node:url";
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const protocol = await import(pathToFileURL(input.root + "/packages/protocol/dist/index.js"));
const calculus = await import(pathToFileURL(input.root + "/packages/calculus/dist/index.js"));
for (const artifact of input.artifacts) {
  protocol.parseArtifact(artifact);
  if (!protocol.verifyArtifactDigest(artifact).ok) throw new Error("Native digest mismatch");
}
for (const sample of input.canonical) {
  if (protocol.canonicalize(protocol.digestJson(sample.value)) !== protocol.canonicalize(sample.digest))
    throw new Error("Canonical JSON parity failure");
}
for (const sample of input.decisions) {
  const actual = calculus.evaluateConnectionPolicy(sample.policy, sample.request);
  if (protocol.canonicalize(actual) !== protocol.canonicalize(sample.expected))
    throw new Error("Native policy disagreement");
}
console.log(JSON.stringify({passed:true, artifacts:input.artifacts.length,
  policy_checks:input.decisions.length, canonical_checks:input.canonical.length}));
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lighthouse", required=True, help="Built TypeScript Lighthouse checkout")
    parser.add_argument("--at", default=None)
    parser.add_argument("publications", nargs="+")
    args = parser.parse_args()
    packages = [validate_publication(read_json(path)) for path in args.publications]
    artifacts = [a for p in packages for a in [p["descriptor"], p["snapshot"], *p["claims"], p["policy"]]]
    at = args.at or datetime.now(timezone.utc).isoformat()
    decisions = []
    for receiver in packages:
        for offered in packages:
            for action in ("read", "link_overlap", "retain", "reshare", "inject_context"):
                request = {"publisher": offered["descriptor"]["issuer"], "profile": PROFILE["id"], "domain": "research",
                           "context": offered["snapshot"]["payload"]["context"]["id"], "claimMediaType": SENTENCE,
                           "action": action, "purpose": "research", "audience": "self", "at": at,
                           "evidence": [], "attestations": []}
                decisions.append({"policy": receiver["policy"], "request": request,
                                  "expected": authorize(receiver["policy"], request)})
    samples = [{"\ue000": "BMP key", "𐀀": "astral key", "β": "evidence", "year": 2026},
               [True, False, None, 0, -(2**53 - 1), 2**53 - 1, "\n\t🧬"]]
    data = {"root": str(Path(args.lighthouse).resolve()), "artifacts": artifacts, "decisions": decisions,
            "canonical": [{"value": value, "digest": digest(value)} for value in samples]}
    completed = subprocess.run(["node", "--input-type=module", "-e", NODE_CHECK],
                               input=json.dumps(data), text=True, capture_output=True, timeout=30)
    if completed.returncode:
        print(completed.stderr, file=sys.stderr)
        return completed.returncode
    print(completed.stdout.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
