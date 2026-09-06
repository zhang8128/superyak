# Run a Lighthouse crossing

This milestone connects explicitly chosen local publishers to Engram recall over a Unix socket. Shared memories appear in a separate `neighbors.delivered` list, with publisher, memory ID, lane, layer, audience, content digest, and publisher read decision. Local recall results and scoring retain their usual behavior.

The feature is off by default. The build does not install live receiver settings, grant group membership, or restart running services. Cross-machine identity, discovery, authentication and usefulness in real research work remain future milestones. A digest provides integrity; it is not an identity signature.

## Try the disposable pilot

From the receiver checkout, use the project's Python environment:

```sh
cd /Users/kairos/Projects/engram/.worktrees/lighthouse-receiver
/Users/kairos/Projects/engram/.venv/bin/python -m lighthouse_pilot --output /tmp/lighthouse-pilot-demo
```

The output directory must be new. The command creates synthetic stores and policies, starts its own short-lived socket daemon, tests permitted delivery and denied/withdrawn controls, and writes `report.json` and receipt artifacts under `receipts/`. It makes no requests to the running Lighthouse daemon. Synthetic content is present only in the disposable stores; the report and receipts omit query text and memory bodies.

Validate a receipt with the sibling Lighthouse kit:

```sh
cd /Users/kairos/Projects/lighthouse
pnpm lighthouse validate /tmp/lighthouse-pilot-demo/receipts/allowed.json
```

## Choose a receiver's publishers

For an existing named Engram instance, settings live at:

```text
<ENGRAM_HOME>/.engram/instances/<receiver>/lighthouse-receiver.toml
```

An example for a receiver choosing the `lighthouse` publisher:

```toml
enabled = true
publishers = ["lighthouse"]
socket_path = "../../lighthouse.sock"
policy_path = "lighthouse-receiver-policy.json"
limit = 1
timeout_s = 2.0
```

Paths resolve relative to this file. At most eight publishers, five returned memories, and ten seconds are accepted. Defaults are one memory and two seconds. Socket exchanges share one total deadline and each frame is capped at 1 MiB; returned memory text is capped at 32 KiB in total. Slow or unavailable publishers can exhaust the shared deadline. A missing file or `enabled = false` disables the integration on the next call. A named instance falling back to the default database cannot use that instance's receiver settings.

The publisher's existing `lighthouse-policy.json` separately grants the receiver `recall` and `read`, and its audience map limits which explicit shares are visible. The receiver's policy selects the publisher and independently grants `recall`, `read`, and `inject_context`. Publisher grants and group membership alone do not enable a receiver.

Here is a minimal receiver policy generator. Adjust the names, scope and expiration intentionally, then run it from the receiver checkout. It creates a new file in the current directory for inspection; move it beside the settings only when ready to enable that choice.

```python
import json
from datetime import datetime, timezone
from lighthouse_protocol import artifact_digest

receiver, publisher = "engram", "lighthouse"
artifact = {
    "protocolVersion": "0.1",
    "kind": "ConnectionPolicy",
    "id": f"urn:policy:{receiver}-receiver",
    "issuedAt": datetime.now(timezone.utc).isoformat(),
    "issuer": f"urn:engram:{receiver}",
    "payloadMediaType": "application/vnd.lighthouse.connection-policy+json",
    "payload": {"rules": [{
        "id": "chosen-technical-neighbor",
        "effect": "allow",
        "publishers": [f"urn:engram:{publisher}"],
        "profiles": ["urn:lighthouse:profile:engram-recall-trace"],
        "domains": ["memory.recall"],
        "actions": ["recall", "read", "inject_context"],
        "contexts": ["memory/technical"],
        "claimMediaTypes": ["application/vnd.engram.recall-rank-claim+json"],
        "purposes": ["session-recall"],
        "audiences": ["self"],
        "validFrom": "2026-09-01T00:00:00Z",
        "validUntil": "2026-10-15T00:00:00Z",
        "requiredEvidence": [],
        "requiredAttestations": [],
    }]},
    "extensions": {"engram:weight": {f"urn:engram:{publisher}": 1.0}},
}
artifact["digest"] = artifact_digest(artifact)
with open("lighthouse-receiver-policy.json", "x") as stream:
    json.dump(artifact, stream, indent=2)
```

Weights are receiver preferences keyed by publisher URN in the artifact's extension; unspecified weights are 1, zero excludes a publisher's candidates from selection. There is no transitive discovery or shared reputation. Receiver policies use the unchanged Lighthouse 0.1 ConnectionPolicy schema, plus bounded validation of selectors and weights. Reseal the artifact with `artifact_digest` after edits. Replace complete policy files atomically to avoid temporarily invalid JSON.

## Recall and inspect

An MCP process started from this checkout exposes two additional recall arguments:

```text
recall(query="bridge maintenance", lighthouse_context="memory/technical",
       lighthouse_purpose="session-recall")
```

The declared context must match both policies. It is never inferred from query text. Instinct-only recall remains local. The existing `lane` argument filters local recall; explicit neighbor shares retain their published lane inside the separate envelope.

The response's `neighbors` object includes `sources`, ranked `selected` references, verified `delivered` content, `receipt_id`, and failure diagnostics. No matching receiver recall grant means no query is sent and no envelope is added. A failed neighbor adds `neighbors` to the response's `degraded` list without discarding local results. A missing or invalid receipt write suppresses neighbor content.

Receipts are stored in the receiver's `memory_log` as `lighthouse_receipt` events and retained by the existing Lighthouse export. They record response construction, not whether a model used a memory. `injected` means the receipt has a nonempty delivered set.

Each source's `storeDigest` hashes the canonical, validated trace snapshot embedded in `extensions["engram:traceSnapshots"]`. It does not hash the publisher's raw database. `engram:sourceDigestBasis` states this convention. Failed sources without a valid snapshot appear in `engram:unavailableSources`, with no fabricated digest. Receiver permissions appear in `engram:receiverDecisions`; publisher decisions are retained in the snapshots and delivered references. These are content-free records, although IDs, context and query digests still reveal metadata and should stay in the receiver's own store.

## Withdraw a connection or share

Disable the receiver's settings, remove a chosen publisher, or revoke its receiver-policy actions to prevent future consultations/delivery. Receiver policy is checked before a query, before reading content, and again after all reads before constructing delivery. The publisher reloads one strictly validated, owner-bound policy snapshot per operation for both action and audience checks; changes and invalid policy files cannot retain a cached allow. Expiration uses the publisher's clock, so callers cannot extend a grant by backdating a request. Existing `unshare` removes the published copy's eligibility while preserving its private source.

Withdrawal applies to subsequent authorization points. It cannot erase a response or a copied memory already received. Running MCP and publisher processes need a normal restart to load this build initially; configuration and policy changes then apply without a restart.

## Record human judgments

The label command records explicit judgments for a receipt's turn, context and purpose:

```sh
python -m lighthouse_label receipts/allowed.json \
  --relevant urn:engram:publisher MEMORY_ID \
  --forbidden urn:engram:publisher ANOTHER_MEMORY_ID \
  --output labels.json
```

Replace the references with the memories actually judged. Absent memories may be named so missed relevant material and correctly withheld material can be evaluated. At least one explicit relevant reference is required by the kit's LabelsDocument format. The command never infers relevance from use logs, and refuses to overwrite an existing output file. It emits `formatVersion: "1.0"` for the existing offline evaluation path; an evaluation still needs its preregistration and corresponding export.

The synthetic pilot tests mechanism only. The earlier human usefulness study, including its novel-candidate threshold, remains unfinished.
