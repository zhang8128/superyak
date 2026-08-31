# Engram Recall Conformance Profile

**Date:** 2026-08-30

**Status:** Approved under the standing Lighthouse build authority

**Scope:** A portable Engram adapter and an offline, falsifiable experiment for
right-turn recall and privacy leakage. All implementation lives in Lighthouse;
the Engram repository and live stores remain unchanged.

## Purpose

Lighthouse 0.1 can describe independently governed systems and make local,
purpose-bound connection decisions. It cannot yet measure the memory-shaped
case that motivated the protocol: a neighbor has a missing piece, the piece is
recalled at the useful turn, and unrelated intimate material remains private.

This increment adds the smallest boundary that can measure that behavior. An
Engram instance performs retrieval locally and exports a deterministic shadow
trace containing opaque memory references, ranks, context, and provenance.
Lighthouse does not embed, search, or rewrite the memory. A receiver chooses
which traces are admissible, fuses admitted ranks using local weights, and
evaluates the result against labels owned by the receiver rather than the
publisher.

The fixture proof is a conformance proof for the apparatus. It is not evidence
that a synthetic corpus improves production recall, and it does not advance
Engram's own shadow-mode rollout.

## Design Choice

Three boundaries were considered.

### Direct SQLite adapter

Reading `graph.db` would closely reflect today's Engram schema, but it would
couple the standard to one private storage implementation, require SQLite and
vector-extension behavior in the JavaScript kit, and make a whole-store export
the path of least resistance. It is rejected for this increment.

### Federated retrieval engine

Running embeddings and graph traversal inside Lighthouse would make the demo
look more complete, but it would create a second, uncalibrated memory engine.
It would also blur the institution boundary: local satisfaction is supposed to
remain local. It is deferred until recorded traces show what interoperability
actually needs.

### Portable shadow export

The selected design exports the result of retrieval, not the memory store or
retrieval implementation. It matches Engram's append-only, replayable shadow
posture; is implementable by other memory systems; supports deterministic
conformance; and permits data minimization. An implementation-specific exporter
can be added to Engram later without changing this profile.

## Engram Profile

The adapter profile is:

```text
id       urn:lighthouse:profile:engram-recall-trace
version  1.0.0
```

It consumes one `*.engram.json` portable export. The source document is not a
Lighthouse artifact. The adapter validates and normalizes it into a sealed
`Snapshot`.

### Source document

```ts
interface EngramExport {
  formatVersion: "1.0";
  instance: string;
  context: { id: string; path: string[] };
  memories: Array<{
    id: string;
    layer: "episode" | "semantic" | "instinct" | "skill" | "other";
    contentDigest: { algorithm: "sha256"; value: string };
    contextPath: string[];
    lane: string;
    origin: "lived" | "organic" | "external" | "direct" | "unknown";
  }>;
  edges: Array<{
    source: string;
    target: string;
    type: string;
    weight: number;
    directed: boolean;
  }>;
  recallTraces: Array<{
    turnId: string;
    queryDigest: { algorithm: "sha256"; value: string };
    contextPath: string[];
    candidates: Array<{ memoryId: string; rank: number }>;
  }>;
}
```

Raw query and memory content are intentionally absent. A digest identifies the
material for evaluation and later authorized delivery without disclosing it in
the trace. Content delivery, encryption, and remote transport remain outside
this increment.

The adapter MUST reject duplicate memory IDs, dangling edges, dangling recall
candidates, duplicate candidate memory IDs, duplicate candidate ranks,
non-contiguous ranks, non-finite or
out-of-range weights, and any memory or trace context outside the declared root.
It sorts all set-like collections with locale-independent canonical comparison
and excludes checkout paths from the sealed model so two copies produce the
same digest. Parallel edges use their complete canonical value as a total
tie-break.

### Restriction

Snapshot restriction to context `V` retains:

- memories whose context begins with `V.path`;
- edges whose two endpoints survive;
- traces whose context begins with `V.path`, with candidates filtered to
  surviving memories and ranks compacted from one.

This operation obeys restriction identity and composition. A request outside
the snapshot root returns `CONTEXT_OUTSIDE_DOMAIN`.

Claim restriction changes the claim context only when the requested context is
inside the claim's current context.

### Local satisfaction

The profile defines one initial sentence media type:

```text
application/vnd.engram.recall-rank-claim+json
```

Its sentence is `{ turnId, memoryId, maxRank }`. The Engram adapter returns:

- `satisfied` if the referenced trace ranks the memory at or above `maxRank`;
- `violated` if the trace and memory exist but the memory is absent or below
  the bound;
- `indeterminate` if the profile, sentence, trace, memory, or context cannot be
  interpreted.

This says only what the source trace recorded. It does not assert that the
memory was relevant, true, safe to disclose, or used.

## Right-Turn Experiment

The experiment lives in `packages/recall-evaluation`. Its inputs are already
projected snapshots, a local `ConnectionPolicy`, a receiver-owned manifest,
and local connection weights.

### Receiver-owned manifest

Each evaluation turn declares:

```ts
interface RecallTurnJudgment {
  turnId: string;
  context: { id: string; path: string[] };
  purpose: string;
  relevant: string[];  // publisher-qualified memory references
  forbidden: string[]; // material that must not appear at this turn
}
```

Labels cannot come from a remote publisher's trace. Keeping them receiver-owned
prevents a publisher from declaring its own memories relevant or harmless.

Each configured source has a snapshot, a role (`local` or `remote`), and a
non-negative finite local weight. Remote sources require an allow decision for:

```text
profile   urn:lighthouse:profile:engram-recall-trace
domain    memory.recall
action    recall
context   <turn context id>
claim     application/vnd.engram.recall-rank-claim+json
purpose   <turn purpose>
audience  self
```

The receiver's own source is admitted without treating self-access as a remote
grant. A denied or unmatched remote source contributes no candidates.

### Fusion

Admitted rankings are fused by weighted reciprocal rank:

```text
score(memory) = sum_source weight(source) / (60 + rank(source, memory))
```

Memory identity is publisher-qualified, so equal local IDs from different
lighthouses cannot collide. Ties break lexicographically by qualified identity.
The comparison is over canonical JSON in Unicode code-unit order, never locale
collation. The fixed constant and tie-break make replay deterministic.
Rank-only fusion avoids pretending raw scores from unrelated retrieval engines
are calibrated.

The fused result is a suggestion set. It does not call a model, mutate Engram,
increment access counts, strengthen graph edges, or inject active context.

### Modes

The reference experiment compares:

1. `local-only` — only the receiver's trace;
2. `policy-scoped` — local plus remote traces individually allowed by policy;
3. `indiscriminate-control` — all traces admitted without policy or context
   filtering, solely as a negative control for the leakage instrument.

The third mode MUST be visibly labeled unsafe and MUST NOT be exposed as a
runtime option.

### Metrics and gates

For a fixed `k`, the report records:

- `rightTurnRecallAtK`: fraction of judged relevant references present in the
  top `k`, macro-averaged across turns;
- `ndcgAtK`: normalized discounted cumulative gain using binary receiver
  relevance;
- `forbiddenExposureAtK`: number of forbidden references in the top `k`;
- `unauthorizedSelectionCount`: selected references from remote sources without
  an allow decision;
- per-turn policy decisions, fused scores, and source rank contributions.

The synthetic reference fixture passes only when:

- policy-scoped right-turn recall and nDCG exceed local-only;
- policy-scoped forbidden exposure and unauthorized selections are zero;
- the indiscriminate control produces forbidden exposure, proving the privacy
  metric is capable of failing;
- the indiscriminate control records unauthorized selections, proving bypassed
  policy is observable rather than silently normalized;
- repeating the experiment produces the same report digest;
- an otherwise identical `inject_context` request is denied even though
  `recall` is allowed.

No numerical uplift threshold is generalized beyond the fixture. A later
historical or live-shadow study must preregister its own corpus, holdout, and
confidence intervals.

## Recall Selection Receipt

Each mode emits a content-addressed local receipt containing:

- experiment and turn IDs;
- selected qualified memory references and content digests;
- source snapshot digests;
- matched policy rule IDs or explicit local-source markers;
- purpose and context;
- the `weighted-rrf-v1` transformation and connection weights;
- denied source decisions;
- per-source trace status and admission outcome, separate from authorization;
- an explicit `action: "recall"` and `injected: false`.

The receipt is a package-level evidence record, not a new Lighthouse core
artifact kind. Core promotion waits until a second profile demonstrates that
the shape is genuinely shared.

Receipt construction first clones and validates content against a strict
runtime schema, then computes the digest. Verification distinguishes malformed
structure from content tampering.

## Error Handling

- Invalid exports fail projection with stable validation messages.
- A trace with an unknown turn contributes nothing and is recorded as absent;
  absence is not authorization failure.
- Duplicate `(turnId, context.id)` judgments fail before evaluation.
- An unsupported profile or malformed rank claim evaluates to
  `indeterminate`, never `violated`.
- Invalid weights fail the experiment before ranking.
- Missing policy rules deny remote recall.
- Receipt construction is pure; a failure cannot partially mutate a source or
  active context.

## Repository Shape

```text
adapters/engram/             Portable export projection and rank evaluator
packages/recall-evaluation/  Policy admission, fusion, metrics, receipts, CLI
fixtures/engram/             Synthetic local, crew, and intimate-neighbor traces
spec/engram-recall-v0.1.md   Normative profile and experiment summary
```

The root adds `pnpm recall:proof`. The existing 15-check `pnpm proof` remains
unchanged so Lighthouse 0.1's original claim does not silently expand.

## Testing

Adapter tests cover deterministic projection, strict validation, satisfied and
violated rank claims, unknown claims, restriction identity/composition, and
out-of-domain obstruction.

Evaluation tests cover deny-by-default admission, per-source weights,
publisher-qualified identity, deterministic tie-breaking, metric definitions,
unsafe-control leakage detection, deterministic receipts, and the independent
injection denial.

The final verification runs the complete workspace check, the original proof,
the new recall proof, malformed-export negative controls, and a clean-tree
status check. No command writes under the Engram or Hyper repositories.

## Deferred Work

- A read-only Engram exporter and historical shadow-log replay.
- Authorized content delivery after opaque recall selection.
- Encryption, Starshine attestations, revocation distribution, and networking.
- Feedback receipts for attended, used, corrected, rejected, or not-applicable
  memories.
- Cross-source identity reconciliation beyond publisher-qualified references.
- Learned source weights or global reputation.
- Any automatic context injection, retention, derivation, or resharing.
