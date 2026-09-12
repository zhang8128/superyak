# Lighthouse views of Atlas research

Atlas can publish selected research records through Lighthouse and inspect
overlapping views from explicitly admitted publishers. Every account keeps its
issuer, scientific context, evidence locators, review status, and source metadata.
The adapter consumes a workbench JSON export and uses only Python's standard
library. It runs alongside the ordinary workbench CLI.

## Public cell-fate views

The cell-fate pilot has two configured local views: **prediction** and
**regulation**. Each selects 11 records, with five records in common. The
prediction view may inspect the regulation view; the reverse direction has no
grant. These are two views operated locally, not external institutions.

`make atlas-demo` from the Superyak root generates the project's current
publications; `make atlas ATLAS_ARGS='status'` reports their paths. To reproduce
separate seed publications in a temporary directory, use Python 3.11 or later
and run from `atlas/`:

```sh
ATLAS_VIEW_DIR="$(mktemp -d)"
python3 -m workbench.lighthouse publish workbench/data/cell_fate.json workbench/data/lighthouses/prediction.json --output "$ATLAS_VIEW_DIR/prediction.json"
python3 -m workbench.lighthouse publish workbench/data/cell_fate.json workbench/data/lighthouses/regulation.json --output "$ATLAS_VIEW_DIR/regulation.json"
python3 -m workbench.lighthouse validate "$ATLAS_VIEW_DIR/prediction.json"
python3 -m workbench.lighthouse validate "$ATLAS_VIEW_DIR/regulation.json"
python3 -m workbench.lighthouse overlap "$ATLAS_VIEW_DIR/prediction.json" "$ATLAS_VIEW_DIR/regulation.json" --at 2026-09-07T17:14:07+00:00
```

Selections and rules live in
[`prediction.json`](../workbench/data/lighthouses/prediction.json) and
[`regulation.json`](../workbench/data/lighthouses/regulation.json). The original
generated artifact collection was excluded from the source import; these
commands reproduce the public views from bundled inputs. No database,
background service, or external checkout is required. Remaining low-level
commands in this guide also run from `atlas/`.

The example grant expires on **2026-10-07 at 17:14:07 UTC**. The fixed `--at`
above reproduces the original evaluation. Omit it to evaluate current policy.
To publish an updated view, revise the selection, issue time, and policy window
deliberately, then write to a new output filename.

## Publish a view

Export a workbench database with `python -m workbench --db PATH export`, or use
the portable pilot bundle directly. Create a configuration with explicit item
IDs from that bundle:

```json
{
  "issuer": "urn:atlas:my-research",
  "name": "My research view",
  "origin": "urn:atlas:my-workbench",
  "context": {"id": "research/cell-fate", "path": ["research", "cell-fate"]},
  "item_ids": ["REPLACE_WITH_AN_EXISTING_ITEM_ID"],
  "issued_at": "2026-09-07T12:00:00Z",
  "rules": []
}
```

The issuer identifies the publishing participant. The origin identifies the
source collection across its publication views; keep it stable when records
are regrouped. Independently built collections need distinct origins even if
some local IDs happen to match. Publication context is separate from the
biological context and multiple facets already attached to each record.

```sh
python -m workbench.lighthouse publish bundle.json my-view-config.json --output my-view.json
python -m workbench.lighthouse validate my-view.json
```

An output path must be new. The adapter atomically creates it and refuses to
overwrite existing files or symlinks, including source bundles and databases.
For a new version, choose a new filename. Input JSON is limited to 32 MiB and
rejects duplicate keys, malformed references, unsupported schemas, and floats.
This profile's structured records use strings, booleans, null, lists, objects,
and integers in JavaScript's safe integer range.

The publication contains sealed Lighthouse descriptor, snapshot, record claims,
and connection policy artifacts. Selection includes only the requested items,
relations with both endpoints selected, and their referenced sources. Unrelated
records and audit history are excluded. Review fields and existing scientific
context are preserved. Omitted relations are counted without copying their text.

## Admit an overlapping view

Each publication starts with an empty local connection policy. To inspect an
offered view, the receiver needs explicit `read` and `link_overlap` grants for
the offered publisher, profile, publication context, purpose, audience, and time.
For example, add this rule to the receiver's `rules` before publishing it:

```json
{
  "id": "inspect-chosen-peer",
  "effect": "allow",
  "publishers": ["urn:atlas:chosen-peer"],
  "profiles": ["urn:lighthouse:profile:atlas-research"],
  "domains": ["research"],
  "actions": ["read", "link_overlap"],
  "contexts": ["research/cell-fate"],
  "claimMediaTypes": ["application/vnd.atlas.record-claim+json"],
  "purposes": ["research"],
  "audiences": ["self"],
  "validFrom": "2026-09-07T00:00:00Z",
  "validUntil": "2026-10-07T00:00:00Z",
  "requiredEvidence": [],
  "requiredAttestations": []
}
```

```sh
python -m workbench.lighthouse overlap my-view.json offered-view.json
```

`--at TIMESTAMP` makes the policy evaluation reproducible; the default is current
UTC time. Update policy windows deliberately when they expire. `compared` means
the receiver admitted inspection. `denied` returns decisions without foreign
records. `unmapped` means the collections declare different origins and need
an explicit correspondence that this first adapter does not implement.

For a shared origin and record ID, the output retains two publisher-qualified
accounts. `identical` means equal item and directly referenced source content;
`different` preserves both versions for inspection. Incident relations and all
their source metadata accompany each account. Different selections can include
different relations, so item equality does not imply equal surrounding graphs.
No record is merged, upgraded, or written into the receiver's database.

Admission is directional and non-transitive. The offered publisher's rules
cannot grant itself access to the receiver. Reading and linking overlaps do
not grant retaining, resharing, or context injection. Offline artifacts are
already disclosed files; this tool cannot retract copies or control later
actions by their recipient. Digests check integrity, while issuer identifiers
remain declared identities, not verified signatures.

## What is verified

The profile's claim means “this snapshot records this item with this evidence
and review state.” `satisfied` checks that recorded-content binding. It does
not certify scientific truth, source support, expert review identity, or
cross-profile equivalence. Unsupported scientific sentences evaluate as
`indeterminate`.

The Python API also supports `restrict(publication, item_ids, context, issued_at)`.
Restriction to the same context is identity. A changed selection requires an
explicit descendant context; expansion and renaming the same context fail.
New restrictions retain snapshot lineage and receive no inherited connection
grants. Identity/composition checks apply to projected content and scope;
different publication histories retain their distinct provenance digests.

From the Superyak root, `make check-atlas` runs the local tests and
`make check-integration` includes independent TypeScript validation of the
pilot after `make setup`. For the temporary publications above, from `atlas/`:

```sh
uv run --locked --extra dev python -m pytest tests/workbench/test_lighthouse.py tests/workbench/test_lighthouse_wire.py -q
python3 scripts/check_lighthouse_interop.py --lighthouse ../lighthouse "$ATLAS_VIEW_DIR/prediction.json" "$ATLAS_VIEW_DIR/regulation.json" --at 2026-09-07T17:14:07+00:00
```

The TypeScript checkout must have its packages built. The check validates every
sealed artifact, verifies Python/JavaScript digests including Unicode ordering,
and compares policy decisions for inspection and ungranted actions. It does not
execute code named by received artifacts. Exit codes are 0 for success, 1 for
input/operational errors, and 2 for a denied or unmapped overlap.

Session messaging can be used to ask another researcher about a particular
record or source. This adapter performs no messaging, networking, autonomous
research, or model calls itself.

The [research recording interface](research-recording.md) adds a durable local
draft inbox and automatically refreshes selected Lighthouse views after a
session records a finding. Its versioned outputs are separate from the fixed
demonstration publications above.
