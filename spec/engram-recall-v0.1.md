# Lighthouse Engram Recall Profile 0.1

## Status and scope

This document specifies the portable Engram recall-trace profile and its
offline right-turn evaluation procedure. It extends the Lighthouse 0.1
reference kit without changing the Lighthouse protocol version or the original
Hyper/aDNA conformance claim.

The keywords MUST, MUST NOT, REQUIRED, SHOULD, SHOULD NOT, and MAY are to be
interpreted as requirements on conforming implementations.

The profile ID is `urn:lighthouse:profile:engram-recall-trace` and its version
is `1.0.0`. Its signature ID is
`urn:lighthouse:signature:engram-recall-trace` at version `1.0.0`.

## Portable export

An adapter consumes one JSON source document with `formatVersion` of
`"1.0"` or `"1.1"`. The document declares an instance, a non-empty root
context, memories, graph edges, and recall traces. A 1.1 document MAY also
declare `receipts`, an array of sealed `RecallReceipt` artifacts (see
"Recall receipts" below). A 1.0 document MUST NOT declare `receipts`
(`RECEIPTS_REQUIRE_1_1`). Every receipt MUST verify its digest
(`RECEIPT_DIGEST_MISMATCH`), MUST lie beneath the export root
(`CONTEXT_OUTSIDE_ROOT`), and MUST be unique per `(turnId, context.id)`
(`DUPLICATE_RECEIPT`). Restriction retains a receipt only when its context
lies beneath the requested context; receipts are never rewritten.

A memory MUST declare:

- a source-local non-empty ID;
- a layer from `episode`, `semantic`, `instinct`, `skill`, or `other`;
- a lowercase 64-hex SHA-256 content digest with algorithm label `sha256`;
- a non-empty context path beneath the export root;
- a non-empty lane;
- an origin from `lived`, `organic`, `external`, `direct`, or `unknown`.

Raw memory content MUST NOT appear in the portable profile. A trace MUST
declare a turn ID, a SHA-256 query digest, a context beneath the root, and an
ordered list of `{ memoryId, rank }` candidates. Raw query text MUST NOT appear.

Edges MUST reference two exported memories and declare a non-empty type, a
finite weight in `[0, 1]`, and directionality.

The adapter MUST reject:

- unknown object members;
- duplicate memory IDs;
- dangling edge endpoints;
- dangling recall candidates;
- duplicate candidate memory IDs within one trace;
- duplicate or non-contiguous positive candidate ranks;
- duplicate traces for one `(turnId, contextPath)` pair;
- memory or trace contexts outside the declared root;
- invalid layers, origins, weights, digests, or format versions.

Projection MUST sort set-like collections and candidate ranks. Sorts over text
or structured identity MUST compare canonical JSON strings by Unicode
code-unit order and MUST NOT use locale-sensitive collation. Parallel edges
MUST use the complete canonical edge value as a total tie-break. Filesystem
paths and directory enumeration order MUST NOT enter the snapshot. A directory
projection MUST fail unless it contains exactly one `*.engram.json` file.

## Context restriction

Restriction from context `U` to a descendant `V` MUST:

1. retain memories whose context path begins with `V.path`;
2. retain an edge only when both endpoints survive;
3. retain traces whose context path begins with `V.path`;
4. remove trace candidates whose memories do not survive;
5. compact surviving ranks from one without changing their relative order;
6. replace both the snapshot context and model root with `V`;
7. reseal the restricted snapshot.

Restriction MUST obey identity and composition. Restriction outside the
declared domain MUST return `CONTEXT_OUTSIDE_DOMAIN` rather than an empty
snapshot presented as successful.

## Rank claims and local satisfaction

The initial sentence media type is:

```text
application/vnd.engram.recall-rank-claim+json
```

Its sentence is `{ turnId, memoryId, maxRank }`, where `maxRank` is a positive
integer. The adapter evaluates the sentence as:

- `satisfied` when exactly one interpretable trace in the claim context ranks
  the known memory at or above the bound;
- `violated` when the trace and memory are known but the memory is absent or
  below the bound;
- `indeterminate` when the profile, sentence, memory, trace, or contextual
  interpretation is unknown or ambiguous.

A satisfied rank claim says what retrieval recorded. It does not establish the
memory's truth, relevance, safety, authorization, delivery, or use.

## Receiver-owned evaluation

An experiment turn declares a turn ID, context, purpose, at least one relevant
publisher-qualified memory reference, and zero or more forbidden references.
The receiver MUST own these judgments. A remote publisher MUST NOT label its
own material relevant or harmless for the receiver.

An experiment MUST reject duplicate `(turnId, context.id)` turn keys rather
than preserve caller order for ambiguous judgments.

Memory identity is the ordered pair `(publisher, source-local memoryId)`.
Equal local IDs from different publishers MUST remain distinct.

Every source declares a role (`local` or `remote`) and a finite non-negative
weight chosen locally by the receiver. A remote source contributes to scoped
recall only after an allow decision for all of:

```text
publisher     source snapshot issuer
profile       urn:lighthouse:profile:engram-recall-trace
domain        memory.recall
action        recall
context       evaluated turn context ID
claim type    application/vnd.engram.recall-rank-claim+json
purpose       evaluated turn purpose
audience      self
time          experiment timestamp
```

Missing or expired rules deny access. The receiver's own source is marked
`local:self` and is not treated as a remote grant. A remote trace MUST exactly
match the evaluated turn ID and context in scoped modes.

Each turn MUST record authorization separately from trace availability and
admission. Per-source evidence distinguishes a matched, absent, or
context-mismatched trace and an admitted, mode-excluded, policy-denied,
zero-weight, or trace-unavailable outcome. An unknown turn is recorded as
`absent`; absence MUST NOT be represented as an authorization failure.

## Rank fusion

Admitted rankings are fused using weighted reciprocal rank with fixed constant
`60`:

```text
score(m) = sum_s weight(s) / (60 + rank_s(m))
```

Fusion MUST operate on publisher-qualified identity, sum repeated
contributions to that identity, reject conflicting content digests, sort by
descending score, and break ties by canonical JSON identity. A zero-weight
source contributes no selected result.

Rank-only fusion avoids assuming raw scores from independent retrieval engines
are calibrated. Source weights are local connection preferences, not global
reputation.

## Modes

The reference evaluation computes three fixed modes:

1. `local-only` admits exact-context traces from local sources;
2. `policy-scoped` additionally admits exact-context traces from individually
   authorized remote sources;
3. `indiscriminate-control` admits every trace with the turn ID while bypassing
   policy and context filtering.

The indiscriminate mode is an explicitly unsafe negative control. It MUST NOT
be presented as a runtime configuration or recommended federation behavior.
Policy decisions are still evaluated in that mode so bypasses remain visible.

## Metrics

For cutoff `k`, a turn computes:

```text
rightTurnRecall@k = relevant references selected in top k
                    / receiver-labeled relevant references

DCG@k  = sum_i relevant(i) / log2(i + 2)
nDCG@k = DCG@k / ideal binary DCG@k
```

It also counts forbidden references in the top `k` and selected remote
references whose actual policy decision was not allow. Experiment recall and
nDCG are macro-averaged across turns; exposure and unauthorized counts are
summed.

The reference proof passes only when policy-scoped recall and nDCG exceed the
local baseline, scoped forbidden and unauthorized counts are zero, the unsafe
control triggers both counters, and input ordering does not alter the report
digest.

These fixture gates are not general performance thresholds. Historical or
live-shadow evaluation MUST preregister its own corpus, holdout, metrics, and
uncertainty procedure.

## Recall receipts

A recall receipt is the core Lighthouse artifact kind `RecallReceipt`
(`payloadMediaType` `application/vnd.lighthouse.recall-receipt+json`,
schema `schemas/recall-receipt.schema.json`). Its payload carries the turn,
context, purpose, audience `self`, action `recall`, a literal boolean
`injected`, transformation `weighted-rrf-v1`, the receiver rule that
matched, per-source records (publisher, role, local weight, store digest,
policy decision, trace outcome), the selected opaque references with
content digests, fused scores, and rank contributions, and the delivered
references with their `read` decisions.

Invariants enforced at seal time and in the generated schema:

- `injected` MUST equal whether `delivered` is non-empty
  (`RECEIPT_INJECTION_MISMATCH`);
- every delivered reference MUST appear in `selected`
  (`DELIVERED_NOT_SELECTED`);
- every delivered reference MUST carry an `allow` read decision
  (`DELIVERED_WITHOUT_ALLOW`);
- policy decision records carry explicit `null` for an absent rule id or
  code; members are never omitted.

Receipts MUST NOT contain raw query or memory content. A receipt does not
grant content delivery, injection, retention, derivation, or resharing
beyond what its `delivered` list records; those actions remain
independently authorized. The reference experiment emits receipts with
`injected: false` and records its experiment id and mode under
`extensions["lighthouse:experiment"]`.

## Labels document

A receiver labels turns in a `*.labels.json` document:
`{ formatVersion: "1.0", instance, turns: [{ turnId, context, purpose,
relevant: [{ publisher, memoryId }], forbidden: [{ publisher, memoryId }] }] }`.
Turn keys `(turnId, context.id)` MUST be unique (`DUPLICATE_LABEL_TURN`) and
`relevant` MUST be non-empty (`EMPTY_RELEVANCE_JUDGMENT`). A remote publisher
MUST NOT author this document.

## Live-shadow evaluation

`lighthouse recall shadow --preregistration <file> --export <file>
--labels <file>` replays a receiver's 1.1 export against its labels. It
MUST refuse to run without a preregistration (`PREREGISTRATION_REQUIRED`).
The preregistration declares `receiverPublisher`, the `corpusDigest`
(`sha-256` over the normalized export), `holdoutTurnIds`, `cutoff`,
`metrics: ["rightTurnRecall", "nDCG"]`, and `bootstrap: { samples, seed }`.
The export's digest MUST match (`CORPUS_DIGEST_MISMATCH`); every holdout
turn MUST be labeled (`HOLDOUT_TURN_UNLABELED`) and MUST have a local trace
in the labeled context (`HOLDOUT_TURN_MISSING_TRACE`,
`HOLDOUT_TURN_CONTEXT_MISMATCH`). A receipt whose selected scores do not
equal weighted reciprocal rank over its contributions and source weights is
rejected (`RECEIPT_SCORE_MISMATCH`).

`local-only` scores the local trace. `policy-scoped` scores the receipt's
selected list, or the local trace when no receipt exists for the turn.
The report (`RecallShadowReport`) carries macro-averaged recall and nDCG at
the cutoff with seeded bootstrap intervals, summed forbidden exposure and
unauthorized selection counts, holdout counts, the preregistration and
corpus digests, and receipt digests. It carries no content and no query
text. The shadow report is measurement, not a pass or fail gate.

## Reference proof boundary

`pnpm recall:proof` runs 14 checks over a synthetic two-turn corpus. One turn is
solved locally; one missing debugging memory is supplied by an allowed trusted
neighbor. A denied relational neighbor is weighted highly enough to win the
unsafe control, demonstrating that the privacy and policy-bypass instruments
can fail.

Passing proves deterministic projection, restriction laws, recorded rank
satisfaction, scoped policy admission, independent injection denial, metric
sensitivity, deterministic receipts, and the fixed corpus result. It does not
prove production retrieval quality, truth, authorized content delivery,
cryptographic publisher identity, revocation after disclosure, live Engram
compatibility, or network security.
