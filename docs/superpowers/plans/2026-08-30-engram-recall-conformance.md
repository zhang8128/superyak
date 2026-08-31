# Engram Recall Conformance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic Engram shadow-trace adapter and an offline experiment that measures right-turn recall improvement and forbidden-memory exposure under local Lighthouse policy.

**Architecture:** Engram remains the retrieval authority and exports opaque ranked traces rather than a database or raw memory content. Lighthouse projects those traces into sealed snapshots, authorizes each remote source, fuses permitted rankings with locally weighted reciprocal rank, and evaluates the result against receiver-owned labels while emitting non-injection receipts.

**Tech Stack:** TypeScript 7, Node.js 24, pnpm workspaces, Zod 4, Vitest 4, Lighthouse protocol/calculus packages.

**Spec:** `docs/superpowers/specs/2026-08-30-engram-recall-conformance-design.md`

## Global Constraints

- All implementation and documentation changes MUST be under `/Users/kairos/Projects/lighthouse`; the Engram and Hyper repositories are read-only references.
- The source format version is exactly `"1.0"`; the Lighthouse protocol version remains exactly `"0.1"`.
- The profile ID is `urn:lighthouse:profile:engram-recall-trace` at version `1.0.0`.
- Portable traces contain content and query SHA-256 digests, never raw query or memory text.
- Remote admission is deny-by-default and evaluates `recall` independently from `inject_context`, `retain`, `derive`, and `reshare`.
- Fusion is rank-only `weight / (60 + rank)` with deterministic canonical-reference tie-breaking.
- The unsafe indiscriminate mode exists only inside the proof harness as a labeled negative control.
- No code may call a model, open a live Engram database, mutate memory, or inject active context.
- The original `pnpm proof` and its 15 checks remain unchanged; the new entry point is `pnpm recall:proof`.
- Each task follows red-green-refactor and ends in a focused commit.

---

## File Structure

### Engram adapter

- `adapters/engram/package.json` — workspace package metadata and dependencies.
- `adapters/engram/tsconfig.json` — production TypeScript compilation.
- `adapters/engram/tsconfig.test.json` — Vitest type checking.
- `adapters/engram/src/export.ts` — strict source schema, semantic validation, deterministic normalization.
- `adapters/engram/src/adapter.ts` — projection, restriction, model access, and local rank evaluation.
- `adapters/engram/src/claims.ts` — rank-claim sentence parsing and sealed claim construction.
- `adapters/engram/src/index.ts` — public exports only.
- `adapters/engram/test/export.test.ts` — invalid-input and normalization tests.
- `adapters/engram/test/adapter.test.ts` — projection, laws, and satisfaction tests.

### Recall evaluation

- `packages/recall-evaluation/package.json` — package metadata, proof script, dependencies.
- `packages/recall-evaluation/tsconfig.json` — production compilation.
- `packages/recall-evaluation/tsconfig.test.json` — test type checking.
- `packages/recall-evaluation/src/types.ts` — receiver judgments, sources, candidates, reports, and checks.
- `packages/recall-evaluation/src/fusion.ts` — context selection and pure weighted reciprocal-rank fusion.
- `packages/recall-evaluation/src/metrics.ts` — recall, nDCG, forbidden exposure, and unauthorized-selection metrics.
- `packages/recall-evaluation/src/receipt.ts` — deterministic package-level recall receipts.
- `packages/recall-evaluation/src/experiment.ts` — policy admission and three-mode experiment orchestration.
- `packages/recall-evaluation/src/reference.ts` — fixed fixture corpus, policy, gates, and proof report.
- `packages/recall-evaluation/src/cli.ts` — JSON proof entry point.
- `packages/recall-evaluation/src/index.ts` — public exports only.
- `packages/recall-evaluation/test/fusion.test.ts` — fusion identity, weights, context, and tie behavior.
- `packages/recall-evaluation/test/metrics.test.ts` — exact metric examples.
- `packages/recall-evaluation/test/experiment.test.ts` — policy, unsafe control, receipt, and determinism behavior.
- `packages/recall-evaluation/test/reference.test.ts` — end-to-end proof gates.

### Fixtures and documentation

- `fixtures/engram/local.engram.json` — receiver-local traces.
- `fixtures/engram/trusted-crew.engram.json` — allowed debugging neighbor.
- `fixtures/engram/intimate-neighbor.engram.json` — denied relational material for the negative control.
- `fixtures/engram/invalid-dangling.engram.json` — malformed candidate reference.
- `spec/engram-recall-v0.1.md` — normative profile and measurement contract.
- `README.md` — command, repository map, and claim boundary.
- `package.json` — root `recall:proof` script.

---

### Task 1: Strict portable Engram export

**Files:**
- Create: `adapters/engram/package.json`
- Create: `adapters/engram/tsconfig.json`
- Create: `adapters/engram/tsconfig.test.json`
- Create: `adapters/engram/src/export.ts`
- Create: `adapters/engram/src/index.ts`
- Create: `adapters/engram/test/export.test.ts`

**Interfaces:**
- Consumes: `Digest` and `ContextRef` types from `@lighthouse/protocol`; Zod strict schemas.
- Produces: `EngramExport`, `EngramMemory`, `EngramEdge`, `EngramRecallTrace`, `EngramModel`, `parseEngramExport(input: unknown): EngramModel`, and `contextStartsWith(parent: string[], child: string[]): boolean`.

- [ ] **Step 1: Scaffold the package and write failing source-validation tests**

Use the existing adapter package scripts and TypeScript configs. In `export.test.ts`, define one valid document with two memories, one edge, and one two-candidate trace, then assert:

```ts
const parsed = parseEngramExport(validExport);
expect(parsed.memories.map(({ id }) => id)).toEqual(["memory-a", "memory-b"]);
expect(parsed.recallTraces[0]?.candidates).toEqual([
  { memoryId: "memory-b", rank: 1 },
  { memoryId: "memory-a", rank: 2 },
]);
```

Add separate cases that expect stable thrown messages containing these codes:

```ts
expect(() => parseEngramExport(withDuplicateMemory)).toThrow("DUPLICATE_MEMORY_ID");
expect(() => parseEngramExport(withDanglingEdge)).toThrow("DANGLING_EDGE");
expect(() => parseEngramExport(withDanglingCandidate)).toThrow("DANGLING_CANDIDATE");
expect(() => parseEngramExport(withDuplicateRank)).toThrow("DUPLICATE_CANDIDATE_RANK");
expect(() => parseEngramExport(withRankGap)).toThrow("NON_CONTIGUOUS_RANKS");
expect(() => parseEngramExport(withOutsideContext)).toThrow("CONTEXT_OUTSIDE_ROOT");
expect(() => parseEngramExport(withUnknownMember)).toThrow();
```

- [ ] **Step 2: Run the source tests and verify red**

Run: `pnpm --filter @lighthouse/adapter-engram test -- export.test.ts`

Expected: FAIL because the package or `parseEngramExport` does not exist.

- [ ] **Step 3: Implement strict parsing and normalization**

Define strict Zod schemas with literal `formatVersion: "1.0"`, SHA-256 digests, non-empty paths, finite weights in `[0, 1]`, positive integer ranks, and the enumerated layers/origins from the design. Parse first, then run semantic checks in this order so failures are stable:

```ts
const memoryIds = new Set<string>();
for (const memory of parsed.memories) {
  if (memoryIds.has(memory.id)) fail("DUPLICATE_MEMORY_ID", memory.id);
  memoryIds.add(memory.id);
  if (!contextStartsWith(parsed.context.path, memory.contextPath)) {
    fail("CONTEXT_OUTSIDE_ROOT", memory.id);
  }
}
```

Validate edge endpoints and every trace candidate against `memoryIds`. For each trace, reject duplicate ranks and require sorted ranks to equal `[1, 2, ..., n]`. Normalize with:

```ts
return {
  formatVersion: parsed.formatVersion,
  instance: parsed.instance,
  context: parsed.context,
  memories: parsed.memories.toSorted((a, b) => a.id.localeCompare(b.id)),
  edges: parsed.edges.toSorted((a, b) =>
    `${a.source}\u0000${a.target}\u0000${a.type}`.localeCompare(
      `${b.source}\u0000${b.target}\u0000${b.type}`,
    ),
  ),
  recallTraces: parsed.recallTraces
    .map((trace) => ({ ...trace, candidates: trace.candidates.toSorted((a, b) => a.rank - b.rank) }))
    .toSorted((a, b) => `${a.turnId}\u0000${a.contextPath.join("/")}`.localeCompare(
      `${b.turnId}\u0000${b.contextPath.join("/")}`,
    )),
};
```

Reject duplicate `(turnId, contextPath)` traces so evaluation never depends on input order.

- [ ] **Step 4: Run adapter source tests and type checking**

Run: `pnpm --filter @lighthouse/adapter-engram test -- export.test.ts && pnpm --filter @lighthouse/adapter-engram typecheck`

Expected: all source tests PASS and both TypeScript configs report no errors.

- [ ] **Step 5: Commit the portable export boundary**

```bash
git add adapters/engram
git commit -m "feat: define portable Engram recall export"
```

---

### Task 2: Engram projection, restriction, and rank satisfaction

**Files:**
- Create: `adapters/engram/src/adapter.ts`
- Create: `adapters/engram/src/claims.ts`
- Modify: `adapters/engram/src/index.ts`
- Create: `adapters/engram/test/adapter.test.ts`

**Interfaces:**
- Consumes: `EngramModel` and `parseEngramExport` from Task 1; `InstitutionAdapter` and restriction laws from `@lighthouse/calculus`; artifacts from `@lighthouse/protocol`.
- Produces: `ENGRAM_PROFILE`, `ENGRAM_SIGNATURE`, `ENGRAM_RECALL_RANK_CLAIM_MEDIA_TYPE`, `engramAdapter`, `engramModel(snapshot: Snapshot): EngramModel | undefined`, `EngramRankClaimInput`, and `createEngramRankClaim(snapshot: Snapshot, input: EngramRankClaimInput): Claim`.

- [ ] **Step 1: Write failing projection and evaluator tests**

Build the source document in a temporary directory named `sample.engram.json`. Project identical copies and assert equal model and digest. Add these law and satisfaction assertions:

```ts
expect(await checkRestrictionIdentity(engramAdapter, snapshot)).toEqual({ passed: true });
expect(
  await checkRestrictionComposition(
    engramAdapter,
    snapshot,
    { id: "memory/debugging", path: ["memory", "debugging"] },
    { id: "memory/debugging/mcp", path: ["memory", "debugging", "mcp"] },
  ),
).toEqual({ passed: true });

expect(await engramAdapter.evaluate(snapshot, createEngramRankClaim(snapshot, {
  turnId: "turn-1", memoryId: "memory-b", maxRank: 1,
}))).toBe("satisfied");
expect(await engramAdapter.evaluate(snapshot, createEngramRankClaim(snapshot, {
  turnId: "turn-1", memoryId: "memory-a", maxRank: 1,
}))).toBe("violated");
```

Also assert `indeterminate` for an unknown media type, unknown turn, unknown memory, and a trace outside the claim context. Assert honest obstruction for `path: ["workflow"]`.

- [ ] **Step 2: Run the adapter behavior tests and verify red**

Run: `pnpm --filter @lighthouse/adapter-engram test -- adapter.test.ts`

Expected: FAIL because adapter and claim exports do not exist.

- [ ] **Step 3: Implement deterministic projection and restrictions**

Resolve the request root as either a file or a directory containing exactly one lexically sorted `*.engram.json`; zero or multiple files must fail. Seal a snapshot with:

```ts
payload: {
  profile: ENGRAM_PROFILE,
  signature: ENGRAM_SIGNATURE,
  context: model.context,
  model: model as unknown as JsonValue,
  lineage: [],
}
```

Restriction keeps memories beneath the requested context, keeps edges only when both endpoints survive, keeps traces beneath the requested context, removes non-surviving candidates, and reassigns candidate ranks from one in their prior order. Reseal after removing the old digest and attestations.

Implement claim restriction with the same `isSubcontext` guard used by existing adapters. `engramModel` returns `undefined` for a non-Engram profile instead of casting arbitrary payloads.

- [ ] **Step 4: Implement rank claims and three-valued evaluation**

Parse the sentence only when all fields have the required types and `maxRank` is a positive integer. Evaluation must use a trace whose `turnId` matches and whose `contextPath` begins with the claim context path. Return `indeterminate` for any unknown component; otherwise return:

```ts
const candidate = trace.candidates.find(({ memoryId }) => memoryId === sentence.memoryId);
return candidate !== undefined && candidate.rank <= sentence.maxRank ? "satisfied" : "violated";
```

Construct claims with the snapshot digest in `snapshotDigests`, the snapshot signature, the caller's context or the matching trace context, and an empty provenance list.

- [ ] **Step 5: Run all adapter tests and type checking**

Run: `pnpm --filter @lighthouse/adapter-engram test && pnpm --filter @lighthouse/adapter-engram typecheck`

Expected: export, projection, restriction, obstruction, and satisfaction tests PASS.

- [ ] **Step 6: Commit the conforming adapter**

```bash
git add adapters/engram
git commit -m "feat: add Engram recall trace adapter"
```

---

### Task 3: Pure rank fusion and measurement

**Files:**
- Create: `packages/recall-evaluation/package.json`
- Create: `packages/recall-evaluation/tsconfig.json`
- Create: `packages/recall-evaluation/tsconfig.test.json`
- Create: `packages/recall-evaluation/src/types.ts`
- Create: `packages/recall-evaluation/src/fusion.ts`
- Create: `packages/recall-evaluation/src/metrics.ts`
- Create: `packages/recall-evaluation/src/index.ts`
- Create: `packages/recall-evaluation/test/fusion.test.ts`
- Create: `packages/recall-evaluation/test/metrics.test.ts`

**Interfaces:**
- Consumes: `Snapshot`, `ContextRef`, and `Digest`; `EngramModel` from the adapter.
- Produces: `MemoryRef`, `RecallSource`, `RecallTurnJudgment`, `RankedContribution`, `FusedCandidate`, `RecallMetrics`, `memoryRefKey(ref: MemoryRef): string`, `fuseRankings(inputs: RankedContribution[], k: number): FusedCandidate[]`, and `measureTurn(selected, judgment, authorization): RecallMetrics`.

- [ ] **Step 1: Write failing fusion tests**

Use contributions from local, crew, and intimate publishers. Assert exact weighted RRF values and publisher-qualified identity:

```ts
expect(fuseRankings([
  contribution("urn:local", "same-id", 1, 1),
  contribution("urn:crew", "same-id", 1, 2),
], 2).map(({ ref }) => ref)).toEqual([
  { publisher: "urn:crew", memoryId: "same-id" },
  { publisher: "urn:local", memoryId: "same-id" },
]);
```

Assert that two contributions to the same qualified reference sum, `k` truncates after sorting, lexical canonical-reference order breaks equal scores, and negative, infinite, or NaN weights throw `INVALID_SOURCE_WEIGHT`.

- [ ] **Step 2: Run fusion tests and verify red**

Run: `pnpm --filter @lighthouse/recall-evaluation test -- fusion.test.ts`

Expected: FAIL because evaluation types and fusion functions do not exist.

- [ ] **Step 3: Implement typed weighted reciprocal-rank fusion**

Represent identity as `{ publisher, memoryId }` and use `canonicalize(ref as JsonValue)` as the internal map key and tie-break key. Each contribution carries the source snapshot digest, content digest, rank, and local source weight. Accumulate `weight / (60 + rank)`, preserve all contributions sorted by publisher and rank, then sort candidates by descending score and canonical key.

Validate `k` as a positive integer and weights as finite and non-negative. A zero-weight source is valid but contributes no selected candidate.

- [ ] **Step 4: Write failing exact metric tests**

Use a three-result selection with two relevant references and one forbidden reference. At `k = 3`, assert:

```ts
expect(metrics.rightTurnRecallAtK).toBe(1);
expect(metrics.ndcgAtK).toBeCloseTo((1 + 1 / Math.log2(4)) / (1 + 1 / Math.log2(3)));
expect(metrics.forbiddenExposureAtK).toBe(1);
expect(metrics.unauthorizedSelectionCount).toBe(1);
```

Add cases for zero forbidden exposure, partial relevant recall, and a relevant set of exactly one. Reject a judgment with no relevant references using `EMPTY_RELEVANCE_JUDGMENT`.

- [ ] **Step 5: Implement receiver-owned metrics**

Compute recall as selected relevant count divided by total relevant count. Compute DCG with binary gain `1 / log2(index + 2)` and IDCG using `min(k, relevant.length)` ideal hits. Count forbidden references by canonical key. Count an unauthorized remote selection when its publisher maps to a decision other than `allowed: true`; the receiver publisher is always considered local-authorized.

- [ ] **Step 6: Run package tests and type checking**

Run: `pnpm --filter @lighthouse/recall-evaluation test && pnpm --filter @lighthouse/recall-evaluation typecheck`

Expected: fusion and metric tests PASS with no TypeScript errors.

- [ ] **Step 7: Commit the pure measurement core**

```bash
git add packages/recall-evaluation
git commit -m "feat: measure fused recall rankings"
```

---

### Task 4: Policy-scoped experiment and receipts

**Files:**
- Create: `packages/recall-evaluation/src/receipt.ts`
- Create: `packages/recall-evaluation/src/experiment.ts`
- Modify: `packages/recall-evaluation/src/types.ts`
- Modify: `packages/recall-evaluation/src/index.ts`
- Create: `packages/recall-evaluation/test/experiment.test.ts`

**Interfaces:**
- Consumes: fusion and metrics from Task 3; `evaluateConnectionPolicy`; Engram profile constants and projected models.
- Produces: `RecallExperimentInput`, `RecallExperimentReport`, `RecallModeReport`, `RecallSelectionReceipt`, `sealRecallReceipt(content): RecallSelectionReceipt`, and `runRecallExperiment(input: RecallExperimentInput): RecallExperimentReport`.

- [ ] **Step 1: Write failing policy and mode tests**

Create three in-memory snapshots: local has an irrelevant rank-one candidate, trusted crew has the missing rank-one candidate in `memory/debugging`, and an intimate neighbor has a forbidden rank-one candidate in `memory/relationship` under the same turn ID. Give source weights `1`, `2`, and `3` respectively.

Construct a policy that allows trusted-crew `recall` only for debugging, explicitly denies its `inject_context`, and denies the intimate publisher. Assert:

```ts
expect(mode(report, "local-only").metrics.rightTurnRecallAtK).toBe(0);
expect(mode(report, "policy-scoped").metrics.rightTurnRecallAtK).toBe(1);
expect(mode(report, "policy-scoped").metrics.forbiddenExposureAtK).toBe(0);
expect(mode(report, "policy-scoped").metrics.unauthorizedSelectionCount).toBe(0);
expect(mode(report, "indiscriminate-control").metrics.forbiddenExposureAtK).toBe(1);
expect(mode(report, "indiscriminate-control").metrics.unauthorizedSelectionCount).toBe(1);
```

Also assert that the policy-scoped mode excludes a trace whose context does not exactly match the judged turn context, even if the publisher has another allow rule.

- [ ] **Step 2: Run experiment tests and verify red**

Run: `pnpm --filter @lighthouse/recall-evaluation test -- experiment.test.ts`

Expected: FAIL because receipts and orchestration do not exist.

- [ ] **Step 3: Implement deterministic recall receipts**

The receipt content has literal `kind: "RecallSelectionReceipt"`, `version: "0.1"`, `action: "recall"`, `injected: false`, experiment/mode/turn identifiers, purpose, context, selected refs and content digests, source snapshot digests, weights, policy decisions, and `transformation: "weighted-rrf-v1"`. Seal it with:

```ts
return { ...content, digest: digestJson(content as unknown as JsonValue) };
```

Sort every set-like receipt field before hashing. A repeated call with semantically identical ordered inputs must produce the same digest.

- [ ] **Step 4: Implement admission and the three experiment modes**

For every remote source and turn, build an `AuthorizationRequest` using the fixed profile, domain, action, media type, audience, the turn context ID and purpose, and the experiment timestamp. Evaluate the policy even for the unsafe control so bypasses remain measurable.

Candidate inclusion rules are exact:

```ts
local-only:
  local sources + exact turnId/contextPath traces
policy-scoped:
  local sources + exact turnId/contextPath traces from allowed remotes
indiscriminate-control:
  every source trace with the turnId, ignoring policy and context for this negative control only
```

Fuse, measure, and seal one receipt per turn. Aggregate macro recall and nDCG by arithmetic mean; sum exposure and unauthorized counts. Seal the complete report with `digestJson` over all fields except its digest.

- [ ] **Step 5: Add determinism and non-injection tests**

Run the same experiment twice with source and judgment arrays reversed and assert equal report digests. Assert every receipt contains `action: "recall"`, `injected: false`, no raw `content` or `query` property, and the exact matched rule ID for the trusted source.

- [ ] **Step 6: Run experiment tests and package type checking**

Run: `pnpm --filter @lighthouse/recall-evaluation test && pnpm --filter @lighthouse/recall-evaluation typecheck`

Expected: all fusion, metric, policy, mode, privacy, receipt, and determinism tests PASS.

- [ ] **Step 7: Commit the scoped experiment**

```bash
git add packages/recall-evaluation
git commit -m "feat: add policy-scoped recall experiment"
```

---

### Task 5: Synthetic fixture corpus and executable recall proof

**Files:**
- Create: `fixtures/engram/local.engram.json`
- Create: `fixtures/engram/trusted-crew.engram.json`
- Create: `fixtures/engram/intimate-neighbor.engram.json`
- Create: `fixtures/engram/invalid-dangling.engram.json`
- Create: `packages/recall-evaluation/src/reference.ts`
- Create: `packages/recall-evaluation/src/cli.ts`
- Modify: `packages/recall-evaluation/src/index.ts`
- Create: `packages/recall-evaluation/test/reference.test.ts`
- Modify: `packages/recall-evaluation/package.json`
- Modify: `package.json`

**Interfaces:**
- Consumes: `engramAdapter` and `runRecallExperiment`.
- Produces: `RecallProofCheck`, `RecallProofReport`, `runReferenceRecallProof(fixtureRoot: string): Promise<RecallProofReport>`, CLI command `pnpm recall:proof`, and machine-readable JSON output.

- [ ] **Step 1: Add the fixed opaque fixture corpus**

Use synthetic SHA-256-shaped values only; do not copy live Engram text or IDs. The local fixture has:

- `turn-missing-restart` in `memory/debugging/mcp`, ranking an irrelevant local checklist first;
- `turn-local-bridge` in `memory/debugging/bridge`, ranking a locally relevant bridge-digest memory first.

The trusted fixture has only `turn-missing-restart`, ranking `restart-after-server-change` first in `memory/debugging/mcp`. The intimate fixture reuses `turn-missing-restart` but places `private-relationship-event` first in `memory/relationship`. The malformed fixture names a candidate ID absent from its memory list.

- [ ] **Step 2: Write the failing end-to-end proof test**

Assert a successful report and named checks:

```ts
const report = await runReferenceRecallProof(fixtureRoot);
expect(report.passed).toBe(true);
expect(report.checks.map(({ id }) => id)).toEqual([
  "schema.engram-snapshots",
  "digest.engram-deterministic",
  "restriction.engram-laws",
  "evaluation.rank-claim",
  "policy.recall-allowed",
  "policy.injection-denied",
  "measurement.scoped-improves-recall",
  "measurement.scoped-improves-ndcg",
  "privacy.scoped-no-forbidden-exposure",
  "privacy.scoped-no-unauthorized-selection",
  "negative-control.forbidden-exposure-detected",
  "negative-control.policy-bypass-detected",
  "receipt.no-injection",
  "digest.experiment-deterministic",
]);
```

Assert projecting `invalid-dangling.engram.json` rejects with `DANGLING_CANDIDATE`.

- [ ] **Step 3: Run the reference test and verify red**

Run: `pnpm --filter @lighthouse/recall-evaluation test -- reference.test.ts`

Expected: FAIL because the fixture proof is not implemented.

- [ ] **Step 4: Implement the fixed policy, judgments, and proof gates**

Project fixture copies from separate temporary parents to prove path-independent digests. Create two receiver judgments at `k = 1`: the missing-restart turn marks the trusted memory relevant and intimate memory forbidden; the bridge turn marks the local bridge memory relevant.

Use local source weight `1`, trusted weight `2`, and intimate weight `3`. Construct a sealed local policy with exact allow/deny rules and a validity interval containing the fixed experiment timestamp. Evaluate an independent `inject_context` request with `evaluateConnectionPolicy` and require `EXPLICIT_DENY`.

Build all 14 checks from concrete artifact/report digests. `passed` is true only when every check passes. Run the experiment a second time with reversed inputs for the determinism check.

- [ ] **Step 5: Implement the JSON-only CLI**

`cli.ts` accepts only `proof --fixtures <path>`, emits one canonical JSON line to stdout, emits a stable JSON error to stderr, and exits `0` only for a passing report. Add:

```json
"proof": "tsx src/cli.ts proof --fixtures ../../fixtures/engram"
```

to the package scripts and:

```json
"recall:proof": "pnpm --filter @lighthouse/recall-evaluation proof"
```

to the root scripts.

- [ ] **Step 6: Run proof tests, CLI proof, and malformed negative control**

Run:

```bash
pnpm --filter @lighthouse/recall-evaluation test
pnpm recall:proof
pnpm --filter @lighthouse/adapter-engram test
```

Expected: all tests PASS; the proof exits `0` with 14 passed checks; the adapter test confirms the malformed fixture is rejected.

- [ ] **Step 7: Commit the executable proof**

```bash
git add fixtures/engram packages/recall-evaluation package.json pnpm-lock.yaml
git commit -m "feat: prove scoped Engram recall"
```

---

### Task 6: Normative profile and user-facing documentation

**Files:**
- Create: `spec/engram-recall-v0.1.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: the implemented constants, report fields, proof checks, and observed command output.
- Produces: an implementation-independent contract and reproducible quickstart.

- [ ] **Step 1: Write the normative profile summary**

Specify source minimization, validation invariants, context restriction, three-valued rank satisfaction, receiver-owned judgments, policy request dimensions, rank-fusion equation, receipt fields, metric equations, unsafe-control status, and the distinction between conformance evidence and production efficacy. Use RFC requirement words consistently.

- [ ] **Step 2: Update the README from observed behavior**

Add `pnpm recall:proof` to Quickstart, document the new adapter/evaluation directories, state the exact check count printed by the proof, and show the expected qualitative result:

```text
local-only recall < policy-scoped recall
policy-scoped forbidden exposure = 0
indiscriminate-control forbidden exposure > 0
all recall receipts injected = false
```

Keep the original 15-check proof description unchanged. Link the normative profile and design.

- [ ] **Step 3: Run documentation and full workspace checks**

Run: `pnpm lint && pnpm typecheck && pnpm test`

Expected: documentation formatting, all package types, and every test PASS.

- [ ] **Step 4: Commit the profile documentation**

```bash
git add README.md spec/engram-recall-v0.1.md
git commit -m "docs: specify Engram recall profile"
```

---

### Task 7: Final verification and integration

**Files:**
- Verify only; modify implementation files only in response to a reproduced failure.

**Interfaces:**
- Consumes: all tasks above.
- Produces: verified local `main` with both independent proofs and a clean worktree.

- [ ] **Step 1: Run the complete verification suite from a clean shell**

Run:

```bash
pnpm install --frozen-lockfile
pnpm check
pnpm proof
pnpm recall:proof
git diff --check
```

Expected: install succeeds without lockfile changes; build, lint, typecheck, and tests pass; original proof reports 15 passed checks; recall proof reports 14 passed checks; no whitespace errors.

- [ ] **Step 2: Inspect proof boundaries and repository state**

Run:

```bash
git status --short --branch
git log --oneline --decorate -8
git -C /Users/kairos/Projects/engram status --short --branch
```

Expected: the Lighthouse feature branch is clean; the pre-existing dirty Engram status is byte-for-byte unchanged from the initial inspection; no Hyper repository was touched.

- [ ] **Step 3: Review the implementation against the design**

Confirm each design requirement has direct test or proof evidence: opaque data, deterministic projection, strict references/ranks, restriction laws, three-valued evaluation, deny-by-default remote admission, receiver labels, rank-only fusion, privacy metric negative control, deterministic non-injection receipts, and no live memory access.

- [ ] **Step 4: Integrate with local main and rerun both proofs**

Use the finishing-development-branch workflow. Fast-forward local `main` when possible, then run:

```bash
pnpm proof
pnpm recall:proof
git status --short --branch
```

Expected: both proofs pass on local `main` and the worktree is clean.
