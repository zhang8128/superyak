# Atlas Lighthouse Views Implementation Plan

**Goal:** Publish and inspect two scoped Lighthouse views of the Atlas research pilot.

**Architecture:** A standard-library wire/policy module and a narrow publication
adapter consume portable workbench bundles. An independent CLI shares no mutable
state or edited files with the ongoing Store/UI implementation.

**Tech Stack:** Python >=3.11, pytest, Lighthouse TypeScript development kit.

**Spec:** [Lighthouse views](../specs/2026-09-07-lighthouse-views-design.md).

## Global constraints

Runtime uses only the standard library. New work lives in `workbench/lighthouse*.py`.
Legacy Atlas, databases, vaults, and concurrent workbench changes are read-only.
Use explicit record selections, preserve source review states, and perform no
implicit network/model/service work. Policies are directional, scoped, time-bound,
and non-transitive. Existing or symlink output paths must never be overwritten.

## 1. Wire primitives and local policy

Owned files: `workbench/lighthouse_wire.py`, `tests/workbench/test_lighthouse_wire.py`.

- [x] Red: assert known canonical UTF-16 key order, exact SHA-256 fixture value,
  rejection of unsupported numbers, valid artifact round trip, digest tampering,
  and representative official policy fixtures before implementation.
- [x] Implement the five public functions declared by the spec. Envelope schema
  validation supports Descriptor/Snapshot/Claim/ConnectionPolicy; all keys and
  nested policy selectors are validated, including aware timestamps and windows.
- [x] Green: run the owned tests with the existing Superyak Python environment.
  Validate exported artifacts and policy decisions independently with TypeScript.

## 2. Publication, restriction, overlap, and CLI

Owned files: `workbench/lighthouse.py`, `tests/workbench/test_lighthouse.py`.

- [x] Red: start at `publish(bundle, config)`, asserting only selected IDs and
  referenced sources are exported and a scoped source-reported claim evaluates
  as `satisfied` for the recorded content. No biological truth claim is made.
- [x] Implement projection and sealed publication package. Reject unsupported
  bundle fields/shapes and dangling records, preserve audit/review information
  on records, and omit unrelated history.
- [x] Red/green: add tests for differing snapshots, withdrawals, malformed and
  tampered packages, restriction subset/identity/composition, no implicit grants,
  allowed overlap and denials for wrong publisher/action/context/time.
- [x] Add CLI smoke tests through subprocess with `sys.executable`: publish,
  validate, overlap, refused overwrite/symlink, malformed JSON and duplicate keys.

## 3. Atlas integration and measured demonstration

Owned files: `docs/lighthouse.md`, `docs/reports/2026-09-07-lighthouse-views.md`,
`workbench/data/lighthouses/{prediction,regulation}.json`, and dedicated
`artifacts/lighthouse/` outputs.

- [x] Coordinate through native session messages and inspect the owner's actual
  Store/export interface and pilot. Configure two local issuers with explicit
  selections and receiver rules, without inventing institutional participation.
- [x] Import the real pilot into a temporary Store, export it, and publish both
  views. Validate every artifact against the TypeScript kit; measure allowed
  overlap and denied reverse direction. Differing and withdrawn accounts remain
  synthetic regression cases; the real pilot's scientific content is unchanged.
- [x] Obtain independent standards/spec reviews of the immutable change; correct
  both findings and rerun affected tests.
- [x] Install only owned files alongside the ongoing Atlas work and verify the
  adapter against the actual pilot and Store/export boundary.
- [x] Prepare a commit containing only owned files and a concrete handoff with
  usage, measured results, and the installed commit identifier.
- [ ] Collect the Atlas owner's reply when the native queue permits delivery.
  Report pending coordination accurately; do not interrupt its active task.

The Atlas owner was still running its current turn when the setup was installed,
so its native replies were queued. No reciprocal agreement has been inferred.
