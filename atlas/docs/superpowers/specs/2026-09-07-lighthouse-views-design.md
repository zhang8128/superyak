# Atlas Lighthouse publication views

Kairos authorized this integration with the Atlas session: “help that session
and set it up there coordinate together”, following discussion of one research
lighthouse with overlapping, independently governed publication views.

## First usable connection

Export explicitly selected records from an Atlas workbench v1 JSON bundle as
Lighthouse 0.1 artifacts. Each view has a distinct issuer, publication context,
snapshot, descriptor, record claims, and local connection policy. Inspect two
views for shared records and differing versions after directional policy checks.
The output preserves each publisher's account. It never merges graph records,
promotes review status, or infers scientific agreement from a shared citation.

Atlas scientific context/facets remain inside the records; the Lighthouse
publication context is an explicit `{id, path}` configured by the operator.
Collection identity is an explicit stable `origin` URI, independent of category
or file path. Equal local IDs are comparable only when both views declare the
same origin. Different origins return `unmapped`, requiring a future explicit
correspondence. Equality means identical record and referenced source content,
not biological truth or independently authenticated publisher identity.

## Constraints

- Python >=3.11, standard library only at runtime; pytest for development.
- New code is in `workbench/lighthouse*.py`; never import legacy `atlas/`.
- Consume exported JSON only. Existing databases, vaults, archived code, and
  concurrent workbench files remain untouched by the adapter.
- No implicit networking, background workers, paid models, or services.
- Never change source statuses, reviewer names, timestamps, evidence, or scope.
- Explicit record IDs select each view. Include only relations whose endpoints
  are selected and only referenced sources. Report omitted relations by count
  without including their private text. Do not include export history.
- Lighthouse artifact canonicalization uses UTF-16 key ordering and SHA-256;
  this profile permits JSON safe integers and rejects floats/nonfinite values.
- Strict inputs reject duplicate JSON keys, unknown fields, malformed IDs,
  dangling references, unsupported schemas, and invalid digests.
- Writes create a new output file exclusively and reject existing/symlink paths.
  Commands print JSON to stdout and errors to stderr with nonzero status.
- Local policies match the TypeScript Lighthouse evaluator. `read` and
  `link_overlap` must both be allowed for inspecting an offered view. They grant
  no reciprocal, transitive, retain, reshare, or context-injection permission.
- Denied overlaps return decisions without foreign record or source content.

## Public interfaces

`workbench.lighthouse_wire` provides `canonical_json(value) -> str`,
`digest(value) -> dict`, `seal(kind, issuer, artifact_id, issued_at, payload) -> dict`,
`verify(artifact, kind=None) -> dict`, and `authorize(policy, request) -> dict`.
`verify` validates the supported envelope/payload shape and digest or raises
ValueError. Authorization consumes the native Lighthouse request fields and
returns `{allowed, ruleId? , code?}`.

`workbench.lighthouse` provides:

- `publish(bundle, config) -> dict`: config has `issuer`, `name`, `origin`,
  `context`, `item_ids`, `issued_at`, and optional `rules` (default empty).
  Returns an `atlas-lighthouse-publication` v1 package containing sealed
  descriptor, snapshot, claims, policy, and projection diagnostics.
- `validate_publication(package) -> dict`: verifies artifacts, references,
  profile/version, issuer consistency, and exact claim-to-snapshot binding.
- `evaluate(claim, snapshot) -> str`: `satisfied` means the declared record
  content and referenced evidence match this snapshot; unsupported sentences
  are `indeterminate`, mismatches are `violated`.
- `restrict(package, item_ids, context, issued_at) -> dict`: subset only,
  explicit descendant publication context, evidence closure, lineage retained.
  It never inherits connection grants into a newly restricted publication.
- `overlap(receiver, offered, at) -> dict`: receiver's local policy determines
  admission of the offered issuer/context for purpose `research`, audience
  `self`, domain `research`, profile `urn:lighthouse:profile:atlas-research`,
  and the profile's record sentence media type. Shared origin/ID records retain
  separate publisher-qualified entries and `identical`/`different` comparison.

The profile is `urn:lighthouse:profile:atlas-research` version `0.1.0`, signature
`urn:atlas:research-workbench` version `1.0.0`, sentence media type
`application/vnd.atlas.record-claim+json`. A sentence records origin, record ID,
and a digest over the complete item plus its referenced source records.

The standalone CLI is `python -m workbench.lighthouse publish BUNDLE CONFIG
--output FILE`, `validate FILE`, and `overlap RECEIVER OFFERED --at TIMESTAMP`.
It works alongside the other session's `python -m workbench` CLI without changing
its dispatch or Store interface. Files remain portable, with no Superyak runtime
dependency. The TypeScript kit is used only for independent development checks.

## Acceptance and coordination

Tests cover selected projection, evidence/reference closure, exact claim
evaluation, restriction identity/composition, preserved withdrawal and differing
records, cross-origin unmapped results, policy denial/expiry/non-transitivity,
tampering, Unicode digests, and output protection. Validate every exported
artifact using Superyak's TypeScript kit and compare policy decisions with its
shared fixtures. This establishes this bounded Atlas profile, not arbitrary
cross-profile translation or general sheaf gluing.

Coordinate the record IDs and demo with the Atlas owner. Generate at least two
explicitly selected overlapping views of the real local workbench pilot and
record allowed and denied overlap results. Both local issuers are operated by
Kairos; this demonstration does not claim participation by an external lab.
Provide commands and a readable verification record, then integrate only these
owned files into the Atlas branch after checking with its session.
