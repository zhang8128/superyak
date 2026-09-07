# Lighthouse Interchange Protocol v0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline, falsifiable reference kit that translates one scoped workflow-dependency claim between Hyper and aDNA while preserving local evaluation, surfacing obstructions, and enforcing local consent policy.

**Architecture:** A pnpm TypeScript workspace separates language-neutral artifacts (`protocol`), executable mathematical laws (`calculus`), two local-system adapters, one cross-profile bridge, and the conformance harness/CLI. JSON Schema and canonical JSON are the wire surface; adapters retain authority over local models and evaluation. The first proof uses only local fixtures and makes invalid mappings, unsupported claims, and denied memory actions observable.

**Tech Stack:** Node.js >=24, pnpm 11.20.0, TypeScript 7.0.2, Zod 4.4.3, YAML 2.8.1, Vitest 4.1.10, tsx 4.23.12, Biome 2.5.8, Node `crypto` SHA-256.

**Spec:** `docs/superpowers/specs/2026-08-30-lighthouse-interchange-protocol-design.md`

## Global Constraints

- The reference proof is offline: no networking, registry, replication, blockchain, or consensus code.
- The protocol transports data and implementation identifiers, never executable adapter or bridge code.
- Canonical artifact identity excludes only `digest` and `attestations`; filesystem paths and object member order cannot affect digests.
- Evaluation has exactly `satisfied`, `violated`, and `indeterminate`; missing evidence is never converted to `violated`.
- Bridge outcomes distinguish `preserved`, `partial`, `approximate`, `unmapped`, `conflict`, and `invalid`.
- Exact and partial bridges satisfy the preservation law on their declared domains; approximate bridges require metric, tolerance, and evidence.
- Trust is local, directional, deny-by-default, non-transitive, time-bounded, and scoped by publisher, profile, domain, action, context, purpose, and audience.
- `read`, `recall`, `suggest`, `inject_context`, `derive`, `retain`, and `reshare` are independent actions.
- Core schemas are strict; extension data appears only under namespaced `extensions`.
- Each task follows red-green-refactor, runs its focused tests, runs the affected package typecheck, and ends in one reviewable commit.

## File Map

```text
package.json                         Workspace commands and pinned tool versions
pnpm-workspace.yaml                 Package discovery
pnpm-lock.yaml                      Reproducible dependency graph
tsconfig.base.json                  Strict NodeNext TypeScript settings
biome.json                          Formatting and lint rules
.gitignore                          Generated build and coverage exclusions
packages/protocol/src/json.ts       JSON value model and canonical serialization
packages/protocol/src/digest.ts     SHA-256 creation and verification
packages/protocol/src/schemas.ts    Strict Zod schemas for all wire artifacts
packages/protocol/src/artifacts.ts  Seal, parse, and verify artifact envelopes
packages/protocol/src/index.ts      Public protocol surface
packages/protocol/test/*.test.ts    Canonicalization, digest, and schema vectors
schemas/*.schema.json               Generated language-neutral schemas
scripts/generate-schemas.ts         Deterministic schema generation
packages/calculus/src/adapter.ts    Institution adapter and obstruction contracts
packages/calculus/src/restriction.ts Context/restriction operations and laws
packages/calculus/src/bridge.ts     Runtime bridges, identity, composition, witnesses
packages/calculus/src/policy.ts     Local connection-policy evaluation
packages/calculus/src/index.ts      Public calculus surface
packages/calculus/test/*.test.ts    Restriction, bridge, and consent-policy laws
adapters/hyper/src/index.ts         Hyper projection, claims, restriction, evaluation
adapters/hyper/test/*.test.ts       Hyper determinism and local truth tests
adapters/adna/src/index.ts          aDNA projection, claims, restriction, evaluation
adapters/adna/test/*.test.ts        aDNA determinism and local truth tests
bridges/hyper-adna/src/index.ts     Scoped Hyper-to-aDNA claim translation
bridges/hyper-adna/test/*.test.ts   Valid, invalid, unmapped, identity, composition tests
packages/conformance/src/report.ts  Machine-readable conformance report types
packages/conformance/src/reference.ts Reference proof orchestration
packages/conformance/src/cli.ts     validate, prove, and authorize commands
packages/conformance/src/index.ts   Public conformance surface
packages/conformance/test/*.test.ts End-to-end law and CLI exit-code tests
fixtures/hyper/orders/**            Minimal Hyper bricks and event schema
fixtures/adna/orders.lattice.yaml   Equivalent aDNA typed-port workflow
fixtures/bridges/*.json             Valid and deliberately invalid mappings
fixtures/policy/*.json              Consent-aware local policy/request examples
spec/lighthouse-v0.1.md             Normative artifact and conformance summary
spec/vocabulary.md                  Stable terms and diagnostic codes
README.md                           Quickstart, proof output, and limits
```

---

### Task 1: Workspace, canonical JSON, and content digests

**Files:**
- Create: `package.json`
- Create: `pnpm-workspace.yaml`
- Create: `tsconfig.base.json`
- Create: `biome.json`
- Create: `.gitignore`
- Create: `packages/protocol/package.json`
- Create: `packages/protocol/tsconfig.json`
- Create: `packages/protocol/tsconfig.test.json`
- Create: `packages/protocol/src/json.ts`
- Create: `packages/protocol/src/digest.ts`
- Create: `packages/protocol/src/index.ts`
- Create: `packages/protocol/test/canonical.test.ts`

**Interfaces:**
- Consumes: Node `crypto`, JSON-compatible values.
- Produces: `JsonValue`, `canonicalize(value): string`, `Digest`, `digestJson(value): Digest`, `verifyJsonDigest(value, digest): boolean`.

- [ ] **Step 1: Add workspace manifests and the failing canonicalization test**

```ts
import { describe, expect, it } from "vitest";
import { canonicalize, digestJson } from "../src/index.js";

describe("canonical JSON", () => {
  it("ignores object insertion order but preserves array order", () => {
    const left = { z: [3, 2, 1], a: { y: true, x: null } };
    const right = { a: { x: null, y: true }, z: [3, 2, 1] };
    expect(canonicalize(left)).toBe('{"a":{"x":null,"y":true},"z":[3,2,1]}');
    expect(digestJson(left)).toEqual(digestJson(right));
    expect(digestJson({ z: [1, 2, 3], a: { x: null, y: true } })).not.toEqual(
      digestJson(left),
    );
  });

  it("rejects non-finite numbers and undefined", () => {
    expect(() => canonicalize(Number.NaN)).toThrow("finite JSON number");
    expect(() => canonicalize({ hidden: undefined } as never)).toThrow("JSON value");
  });
});
```

Use `packageManager: "pnpm@11.20.0"`, `engines.node: ">=24"`, workspace globs `packages/*`, `adapters/*`, and `bridges/*`, and root scripts `build`, `lint`, `typecheck`, `test`, `check`, `schema:generate`, and `proof`.

- [ ] **Step 2: Install and run the focused test to verify the red state**

Run: `pnpm install && pnpm --filter @lighthouse/protocol test -- canonical.test.ts`

Expected: FAIL because `../src/index.js` does not exist.

- [ ] **Step 3: Implement canonicalization and SHA-256 digesting**

```ts
export type JsonPrimitive = boolean | null | number | string;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };

export function canonicalize(value: JsonValue): string {
  if (value === null || typeof value === "boolean" || typeof value === "string") {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new TypeError("Expected a finite JSON number");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonicalize).join(",")}]`;
  if (typeof value !== "object") throw new TypeError("Expected a JSON value");
  return `{${Object.keys(value)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${canonicalize(value[key] as JsonValue)}`)
    .join(",")}}`;
}
```

```ts
import { createHash, timingSafeEqual } from "node:crypto";
import { canonicalize, type JsonValue } from "./json.js";

export interface Digest { algorithm: string; value: string }

export function digestJson(value: JsonValue): Digest {
  return { algorithm: "sha-256", value: createHash("sha256").update(canonicalize(value)).digest("hex") };
}

export function verifyJsonDigest(value: JsonValue, expected: Digest): boolean {
  if (expected.algorithm !== "sha-256" || !/^[0-9a-f]{64}$/.test(expected.value)) return false;
  const actual = digestJson(value);
  return timingSafeEqual(Buffer.from(actual.value, "hex"), Buffer.from(expected.value, "hex"));
}
```

- [ ] **Step 4: Run protocol tests and typecheck**

Run: `pnpm --filter @lighthouse/protocol test && pnpm --filter @lighthouse/protocol typecheck`

Expected: PASS with two tests and no TypeScript errors.

- [ ] **Step 5: Commit the canonical core**

```bash
git add package.json pnpm-workspace.yaml pnpm-lock.yaml tsconfig.base.json biome.json .gitignore packages/protocol
git commit -m "feat(protocol): add canonical JSON artifact digests"
```

---

### Task 2: Strict artifact envelopes and generated JSON Schemas

**Files:**
- Create: `packages/protocol/src/schemas.ts`
- Create: `packages/protocol/src/artifacts.ts`
- Modify: `packages/protocol/src/index.ts`
- Modify: `packages/protocol/package.json`
- Create: `packages/protocol/test/artifacts.test.ts`
- Create: `scripts/generate-schemas.ts`
- Create: `schemas/lighthouse-descriptor.schema.json`
- Create: `schemas/snapshot.schema.json`
- Create: `schemas/claim.schema.json`
- Create: `schemas/bridge-descriptor.schema.json`
- Create: `schemas/translation-witness.schema.json`
- Create: `schemas/connection-policy.schema.json`

**Interfaces:**
- Consumes: `JsonValue`, `Digest`, `digestJson`, `verifyJsonDigest` from Task 1.
- Produces: strict artifact schemas/types, `sealArtifact(input)`, `parseArtifact(input)`, `verifyArtifactDigest(artifact)`, and deterministic JSON Schema files.

- [ ] **Step 1: Write failing artifact tests**

```ts
import { describe, expect, it } from "vitest";
import { parseArtifact, sealArtifact, verifyArtifactDigest } from "../src/index.js";

const unsignedClaim = {
  kind: "Claim" as const,
  protocolVersion: "0.1" as const,
  id: "urn:claim:orders-dependency",
  issuedAt: "2026-08-30T12:00:00Z",
  issuer: "urn:lighthouse:hyper-local",
  payloadMediaType: "application/vnd.lighthouse.claim+json",
  payload: {
    profile: { id: "urn:lighthouse:profile:hyper-modules", version: "1.0.0" },
    signature: { id: "urn:signature:hyper-orders", version: "1.0.0" },
    context: { id: "workflow/orders", path: ["workflow", "orders"] },
    sentenceMediaType: "application/vnd.hyper.dependency-claim+json",
    sentence: { producerId: "orders:producer", consumerId: "orders:consumer", topic: "orders.created.v1" },
    snapshotDigests: [],
    provenance: [],
  },
};

describe("artifact envelopes", () => {
  it("seals and verifies a strict claim", () => {
    const claim = sealArtifact(unsignedClaim);
    expect(parseArtifact(claim)).toEqual(claim);
    expect(verifyArtifactDigest(claim)).toEqual({ ok: true });
  });

  it("keeps identity stable when attestations are added", () => {
    const claim = sealArtifact(unsignedClaim);
    const signed = { ...claim, attestations: [{ algorithm: "ml-dsa-65", keyId: "urn:key:1", signature: "abc" }] };
    expect(verifyArtifactDigest(signed)).toEqual({ ok: true });
  });

  it("rejects unknown core members", () => {
    expect(() => parseArtifact({ ...sealArtifact(unsignedClaim), surprise: true })).toThrow();
  });
});
```

- [ ] **Step 2: Run the focused test to verify the red state**

Run: `pnpm --filter @lighthouse/protocol test -- artifacts.test.ts`

Expected: FAIL because the artifact functions are not exported.

- [ ] **Step 3: Define strict common and payload schemas**

Implement strict Zod schemas for these exact kinds and payloads:

```ts
export const artifactKindSchema = z.enum([
  "LighthouseDescriptor", "Snapshot", "Claim", "BridgeDescriptor", "TranslationWitness", "ConnectionPolicy",
]);
export const evaluationSchema = z.enum(["satisfied", "violated", "indeterminate"]);
export const witnessOutcomeSchema = z.enum(["preserved", "partial", "approximate", "unmapped", "conflict", "invalid"]);
export const fidelitySchema = z.enum(["exact", "partial", "approximate"]);
export const profileRefSchema = z.object({ id: z.string().min(1), version: z.string().min(1), digest: digestSchema.optional() }).strict();
export const contextRefSchema = z.object({ id: z.string().min(1), path: z.array(z.string().min(1)) }).strict();
```

Define these payloads without open core fields:

- `LighthouseDescriptor`: `name`, `protocolVersions`, `profiles`, `actions`, and inert `artifactEndpoints` strings.
- `Snapshot`: `profile`, `signature`, `context`, opaque JSON `model`, and `lineage` digest references.
- `Claim`: `profile`, `signature`, `context`, `sentenceMediaType`, opaque JSON `sentence`, `snapshotDigests`, `provenance`, `validFrom`, and `validUntil`.
- `BridgeDescriptor`: `source`, `target`, domain `contexts`/`claimMediaTypes`, `fidelity`, `implementation`, `dependencies`, and an optional approximation object containing `metric`, finite non-negative `tolerance`, and `evidenceProcedure`. Require that object exactly when fidelity is `approximate`.
- `TranslationWitness`: source/optional target claim digests, source/optional target snapshot digests, bridge digest and lineage, outcome, mapped/unmapped paths, source/optional target evaluation, evidence digests, optional approximation details, and diagnostics `{ code, message, paths }`.
- `ConnectionPolicy`: rules containing `id`, `effect`, non-empty arrays for `publishers`, `profiles`, `domains`, `actions`, `contexts`, `claimMediaTypes`, `purposes`, and `audiences`, plus `validFrom`, `validUntil`, `requiredEvidence`, and `requiredAttestations`.

All envelope schemas require `kind`, literal protocol version `0.1`, `id`, offset-aware `issuedAt`, `issuer`, `payloadMediaType`, `payload`, algorithm-agile `digest`, optional `attestations`, and optional namespaced `extensions`. The six discriminated schemas use `.strict()` at every core object boundary.

- [ ] **Step 4: Implement sealing, parsing, and digest verification**

```ts
export function artifactDigestContent(artifact: LighthouseArtifact): JsonValue {
  const { attestations: _attestations, digest: _digest, ...content } = artifact;
  return content as JsonValue;
}

export function sealArtifact<T extends UnsignedLighthouseArtifact>(input: T): T & { digest: Digest } {
  const parsed = unsignedArtifactSchema.parse(input) as T;
  const { attestations: _attestations, ...content } = parsed;
  return { ...parsed, digest: digestJson(content as JsonValue) };
}

export function verifyArtifactDigest(artifact: LighthouseArtifact): { ok: true } | { ok: false; code: "DIGEST_MISMATCH" } {
  return verifyJsonDigest(artifactDigestContent(artifact), artifact.digest)
    ? { ok: true }
    : { ok: false, code: "DIGEST_MISMATCH" };
}
```

- [ ] **Step 5: Generate and test stable JSON Schemas**

`scripts/generate-schemas.ts` calls `z.toJSONSchema` for each artifact schema, recursively sorts schema object keys with `canonicalize`, appends one newline, and writes the six named files. Add a test that runs generation into a temporary directory twice and asserts byte equality, then parses every generated schema as JSON.

Run: `pnpm schema:generate && pnpm --filter @lighthouse/protocol test && pnpm --filter @lighthouse/protocol typecheck`

Expected: PASS; a second `pnpm schema:generate` leaves `git diff -- schemas` empty.

- [ ] **Step 6: Commit artifact contracts and schemas**

```bash
git add packages/protocol scripts/generate-schemas.ts schemas package.json pnpm-lock.yaml
git commit -m "feat(protocol): define strict Lighthouse artifacts"
```

---

### Task 3: Institution adapters, contexts, and restriction laws

**Files:**
- Create: `packages/calculus/package.json`
- Create: `packages/calculus/tsconfig.json`
- Create: `packages/calculus/tsconfig.test.json`
- Create: `packages/calculus/src/adapter.ts`
- Create: `packages/calculus/src/restriction.ts`
- Create: `packages/calculus/src/index.ts`
- Create: `packages/calculus/test/restriction.test.ts`

**Interfaces:**
- Consumes: `ProfileRef`, `ContextRef`, `Snapshot`, `Claim`, and `JsonValue` from `@lighthouse/protocol`.
- Produces: `InstitutionAdapter`, `ProjectionRequest`, `Evaluation`, `OperationResult<T>`, `Obstruction`, `isSubcontext`, `checkRestrictionIdentity`, and `checkRestrictionComposition`.

- [ ] **Step 1: Write failing restriction-law tests with a minimal fixture adapter**

```ts
it("obeys identity and composition on declared subcontexts", async () => {
  expect(await checkRestrictionIdentity(adapter, snapshot)).toMatchObject({ passed: true });
  expect(await checkRestrictionComposition(adapter, snapshot, contexts.orders, contexts.contracts)).toMatchObject({ passed: true });
});

it("returns an obstruction outside the declared context", async () => {
  expect(await adapter.restrictSnapshot(snapshot, { id: "finance", path: ["finance"] })).toEqual({
    ok: false,
    obstruction: { code: "CONTEXT_OUTSIDE_DOMAIN", message: "finance is not within workflow", paths: ["finance"] },
  });
});
```

The fixture adapter restricts a JSON model whose records each carry a `contextPath`; direct and composed restrictions produce byte-identical sealed snapshots.

- [ ] **Step 2: Run the focused test to verify the red state**

Run: `pnpm --filter @lighthouse/calculus test -- restriction.test.ts`

Expected: FAIL because the calculus package is absent.

- [ ] **Step 3: Implement the adapter and obstruction contracts**

```ts
export type Evaluation = "satisfied" | "violated" | "indeterminate";
export interface Obstruction { code: string; message: string; paths: string[] }
export type OperationResult<T> = { ok: true; value: T } | { ok: false; obstruction: Obstruction };
export interface ProjectionRequest { root: string; id: string; issuer: string; issuedAt: string }
export interface InstitutionAdapter {
  readonly profile: ProfileRef;
  project(request: ProjectionRequest): Promise<Snapshot>;
  restrictSnapshot(snapshot: Snapshot, context: ContextRef): Promise<OperationResult<Snapshot>>;
  restrictClaim(claim: Claim, context: ContextRef): Promise<OperationResult<Claim>>;
  evaluate(snapshot: Snapshot, claim: Claim): Promise<Evaluation>;
}
```

`isSubcontext(parent, child)` compares path prefixes. Law checks compare the semantic projection `{ profile, signature, context, model }`; transport metadata and a second sealing pass cannot make two unequal models look equal or two equal restrictions look different.

- [ ] **Step 4: Run calculus tests and typecheck**

Run: `pnpm --filter @lighthouse/calculus test && pnpm --filter @lighthouse/calculus typecheck`

Expected: PASS for identity, composition, and explicit obstruction.

- [ ] **Step 5: Commit adapter calculus**

```bash
git add packages/calculus pnpm-lock.yaml
git commit -m "feat(calculus): add institution adapters and restriction laws"
```

---

### Task 4: Partial bridges, composition, and preservation witnesses

**Files:**
- Create: `packages/calculus/src/bridge.ts`
- Modify: `packages/calculus/src/index.ts`
- Create: `packages/calculus/test/bridge.test.ts`

**Interfaces:**
- Consumes: protocol artifacts and `InstitutionAdapter`, `OperationResult<T>` from Tasks 2-3.
- Produces: `RuntimeBridge`, `identityBridge`, `composeBridges`, `translateWithWitness`, and `TranslationResult`.

- [ ] **Step 1: Write failing identity, composition, and preservation tests**

```ts
it("identity preserves a supported claim", async () => {
  const result = await translateWithWitness(identity, claim, adapter, snapshot, adapter, snapshot);
  expect(result.witness.payload.outcome).toBe("preserved");
  expect(result.translatedClaim?.payload.sentence).toEqual(claim.payload.sentence);
});

it("flattens bridge lineage so composition is associative", () => {
  const left = composeBridges(composeBridges(identitySource, bridge, meta), identityTarget, meta);
  const right = composeBridges(identitySource, composeBridges(bridge, identityTarget, meta), meta);
  expect(left.lineage.map((item) => item.digest)).toEqual(right.lineage.map((item) => item.digest));
});

it("marks disagreement as invalid rather than preserved", async () => {
  const result = await translateWithWitness(invalidBridge, claim, sourceAdapter, sourceSnapshot, targetAdapter, targetSnapshot);
  expect(result.witness.payload.outcome).toBe("invalid");
  expect(result.witness.payload.diagnostics[0]?.code).toBe("SATISFACTION_NOT_PRESERVED");
});
```

- [ ] **Step 2: Run the focused test to verify the red state**

Run: `pnpm --filter @lighthouse/calculus test -- bridge.test.ts`

Expected: FAIL because `RuntimeBridge` and bridge functions do not exist.

- [ ] **Step 3: Implement runtime bridge contracts and honest obstruction**

```ts
export interface RuntimeBridge {
  readonly descriptor: BridgeDescriptor;
  readonly lineage: readonly BridgeDescriptor[];
  translateClaim(claim: Claim): Promise<OperationResult<Claim>>;
}

export interface TranslationResult {
  translatedClaim?: Claim;
  witness: TranslationWitness;
}
```

`identityBridge` accepts only claims for its exact profile/version. `composeBridges` requires the first target to equal the second source, applies translations in sequence, and flattens non-identity lineage. A failed first or second translation propagates one `unmapped` witness with the originating obstruction code and path.

- [ ] **Step 4: Implement witness-producing satisfaction comparison**

```ts
const sourceEvaluation = await sourceAdapter.evaluate(sourceSnapshot, sourceClaim);
const translated = await bridge.translateClaim(sourceClaim);
if (!translated.ok) return witnessForObstruction(sourceClaim, bridge, translated.obstruction, meta);
const targetEvaluation = await targetAdapter.evaluate(targetSnapshot, translated.value);
const exact = bridge.descriptor.payload.fidelity !== "approximate";
const outcome = exact && sourceEvaluation !== "indeterminate" && sourceEvaluation === targetEvaluation
  ? "preserved"
  : exact
    ? "invalid"
    : "approximate";
```

Witness payloads bind source/target claim digests, snapshot digests, bridge digest/lineage, both evaluations, mapped/unmapped paths, evidence digests, and stable diagnostics.

- [ ] **Step 5: Run calculus tests and typecheck**

Run: `pnpm --filter @lighthouse/calculus test && pnpm --filter @lighthouse/calculus typecheck`

Expected: PASS for identity, associative lineage, preservation, invalid mapping, and obstruction cases.

- [ ] **Step 6: Commit bridge calculus**

```bash
git add packages/calculus
git commit -m "feat(calculus): add partial bridges and preservation witnesses"
```

---

### Task 5: Directional, purpose-bound connection policy

**Files:**
- Create: `packages/calculus/src/policy.ts`
- Modify: `packages/calculus/src/index.ts`
- Create: `packages/calculus/test/policy.test.ts`
- Create: `fixtures/policy/workflow-policy.json`
- Create: `fixtures/policy/recall-request.json`
- Create: `fixtures/policy/inject-request.json`

**Interfaces:**
- Consumes: `ConnectionPolicy` from Task 2.
- Produces: `AuthorizationRequest`, `AuthorizationDecision`, `evaluateConnectionPolicy(policy, request)`.

- [ ] **Step 1: Write failing tests for scope, intimacy actions, expiry, and non-transitivity**

```ts
it("allows workflow structure without granting unrelated actions", () => {
  expect(evaluateConnectionPolicy(policy, workflowRead)).toMatchObject({ allowed: true, ruleId: "allow-french-lab-workflow-read" });
  expect(evaluateConnectionPolicy(policy, { ...workflowRead, domain: "personal.memory" })).toMatchObject({ allowed: false, code: "NO_MATCHING_ALLOW" });
});

it("does not turn read or recall into context injection", () => {
  expect(evaluateConnectionPolicy(policy, recallRequest)).toMatchObject({ allowed: true });
  expect(evaluateConnectionPolicy(policy, { ...recallRequest, action: "inject_context" })).toMatchObject({ allowed: false });
  expect(evaluateConnectionPolicy(policy, { ...recallRequest, action: "reshare" })).toMatchObject({ allowed: false });
});

it("requires the declared purpose and direct publisher", () => {
  expect(evaluateConnectionPolicy(policy, { ...recallRequest, purpose: "debugging" }).allowed).toBe(true);
  expect(evaluateConnectionPolicy(policy, { ...recallRequest, purpose: "profiling" }).allowed).toBe(false);
  expect(evaluateConnectionPolicy(policy, { ...recallRequest, publisher: "urn:lighthouse:friend-of-friend" }).allowed).toBe(false);
});

it("denies expired grants and lets an equally specific deny win", () => {
  expect(evaluateConnectionPolicy(policy, { ...recallRequest, at: "2028-01-01T00:00:00Z" })).toMatchObject({ allowed: false });
});
```

- [ ] **Step 2: Run the focused test to verify the red state**

Run: `pnpm --filter @lighthouse/calculus test -- policy.test.ts`

Expected: FAIL because policy evaluation does not exist.

- [ ] **Step 3: Implement exact request matching and specificity**

```ts
export interface AuthorizationRequest {
  publisher: string;
  profile: string;
  domain: string;
  action: string;
  context: string;
  claimMediaType: string;
  purpose: string;
  audience: string;
  at: string;
}

export type AuthorizationDecision =
  | { allowed: true; ruleId: string }
  | { allowed: false; code: "EXPLICIT_DENY" | "NO_MATCHING_ALLOW" | "OUTSIDE_VALIDITY"; ruleId?: string };
```

Selectors support exact strings and suffix `*` prefixes such as `urn:lighthouse:university:*`. Empty selector arrays match nothing. Keep only currently valid matching rules, sort by specificity (exact matches count 2, prefix matches count 1), choose the highest score, and let `deny` win a tie. Do not inspect another publisher's policy or follow relationship links.

- [ ] **Step 4: Add sealed policy and request fixtures**

The workflow rule allows only `read` for domain `workflow.structure`. The memory rule allows only `recall` for publisher `urn:lighthouse:trusted-crew`, purpose `debugging`, audience `self`, and the interval `2026-08-30T00:00:00Z` through `2027-08-30T00:00:00Z`. Separate deny rules reject `inject_context` and `reshare`.

- [ ] **Step 5: Run policy tests and typecheck**

Run: `pnpm --filter @lighthouse/calculus test && pnpm --filter @lighthouse/calculus typecheck`

Expected: PASS; no request gains permission through a neighboring action or publisher.

- [ ] **Step 6: Commit local policy enforcement**

```bash
git add packages/calculus fixtures/policy
git commit -m "feat(calculus): enforce scoped relational consent"
```

---

### Task 6: Deterministic Hyper adapter

**Files:**
- Create: `adapters/hyper/package.json`
- Create: `adapters/hyper/tsconfig.json`
- Create: `adapters/hyper/tsconfig.test.json`
- Create: `adapters/hyper/src/index.ts`
- Create: `adapters/hyper/test/adapter.test.ts`
- Create: `fixtures/hyper/orders/schemas/events/orders-created.schema.json`
- Create: `fixtures/hyper/orders/bricks/orders/producer/brick.json`
- Create: `fixtures/hyper/orders/bricks/orders/consumer/brick.json`

**Interfaces:**
- Consumes: protocol artifacts and `InstitutionAdapter`.
- Produces: `hyperAdapter`, `createHyperDependencyClaim`, `createHyperLeaseClaim`, `HYPER_PROFILE`, and Hyper model types.

- [ ] **Step 1: Write failing deterministic projection and evaluation tests**

```ts
it("projects identical snapshots from different checkout paths", async () => {
  const firstRoot = await copyFixtureToTemporaryDirectory("hyper-first-");
  const secondRoot = await copyFixtureToTemporaryDirectory("hyper-second-");
  const metadata = { id: "urn:snapshot:hyper-orders", issuer: "urn:lighthouse:hyper-local", issuedAt: "2026-08-30T12:00:00Z" };
  const first = await hyperAdapter.project({ root: firstRoot, ...metadata });
  const second = await hyperAdapter.project({ root: secondRoot, ...metadata });
  expect(second.digest).toEqual(first.digest);
  expect(second.payload.model).toEqual(first.payload.model);
});

it("satisfies the shared dependency claim locally", async () => {
  expect(await hyperAdapter.evaluate(snapshot, createHyperDependencyClaim(snapshot))).toBe("satisfied");
});

it("returns indeterminate for an unsupported sentence kind", async () => {
  expect(await hyperAdapter.evaluate(snapshot, createHyperLeaseClaim(snapshot))).toBe("indeterminate");
});
```

- [ ] **Step 2: Run the focused test to verify the red state**

Run: `pnpm --filter @lighthouse/adapter-hyper test`

Expected: FAIL because the adapter package is absent.

- [ ] **Step 3: Implement path-independent Hyper projection**

Read `brick.json` files in lexicographically sorted relative-path order. Emit resources keyed only by descriptor IDs and event topics. Emit sorted `PUBLISHES` and `SUBSCRIBES` edges to `event-schema:<topic>`. Do not include the projection root or absolute filenames in the model.

```ts
export interface HyperModel {
  resources: Array<{ id: string; kind: "brick" | "event-schema"; contextPath: string[] }>;
  edges: Array<{ from: string; to: string; kind: "PUBLISHES" | "SUBSCRIBES"; topic: string; contextPath: string[] }>;
}
```

Use media types `application/vnd.hyper.dependency-claim+json` and `application/vnd.hyper.lease-claim+json`. The dependency evaluator requires both producer `PUBLISHES` and consumer `SUBSCRIBES` edges for the exact topic.

- [ ] **Step 4: Implement context restriction**

Restrict Hyper resources/edges by `contextPath` prefix, retain the requested context in the new snapshot/claim, reseal it with stable metadata, and return `CONTEXT_OUTSIDE_DOMAIN` when the requested path is not beneath the current context.

- [ ] **Step 5: Run Hyper tests and typecheck**

Run: `pnpm --filter @lighthouse/adapter-hyper test && pnpm --filter @lighthouse/adapter-hyper typecheck`

Expected: PASS for clone-path determinism, local satisfaction, indeterminate unsupported claims, identity restriction, and composed restriction.

- [ ] **Step 6: Commit the Hyper adapter**

```bash
git add adapters/hyper fixtures/hyper pnpm-lock.yaml
git commit -m "feat(adapters): project Hyper workflow claims"
```

---

### Task 7: Deterministic aDNA adapter and scoped Hyper bridge

**Files:**
- Create: `adapters/adna/package.json`
- Create: `adapters/adna/tsconfig.json`
- Create: `adapters/adna/tsconfig.test.json`
- Create: `adapters/adna/src/index.ts`
- Create: `adapters/adna/test/adapter.test.ts`
- Create: `bridges/hyper-adna/package.json`
- Create: `bridges/hyper-adna/tsconfig.json`
- Create: `bridges/hyper-adna/tsconfig.test.json`
- Create: `bridges/hyper-adna/src/index.ts`
- Create: `bridges/hyper-adna/test/bridge.test.ts`
- Create: `fixtures/adna/orders.lattice.yaml`
- Create: `fixtures/bridges/hyper-adna.json`
- Create: `fixtures/bridges/hyper-adna-invalid.json`

**Interfaces:**
- Consumes: protocol/calculus APIs and Hyper claim media types.
- Produces: `adnaAdapter`, `createAdnaPortClaim`, `ADNA_PROFILE`, and `createHyperAdnaBridge(mapping, metadata)`.

- [ ] **Step 1: Write failing aDNA projection/evaluation tests**

```ts
it("projects typed ports deterministically", async () => {
  const first = await adnaAdapter.project({ root: firstFixtureRoot, ...metadata });
  const second = await adnaAdapter.project({ root: secondFixtureRoot, ...metadata });
  expect(second.digest).toEqual(first.digest);
});

it("satisfies a connected compatible-port claim", async () => {
  expect(await adnaAdapter.evaluate(snapshot, createAdnaPortClaim(snapshot))).toBe("satisfied");
});

it("violates a claim whose port types differ", async () => {
  expect(await adnaAdapter.evaluate(snapshot, claimWithInvoiceType)).toBe("violated");
});
```

- [ ] **Step 2: Run the aDNA test to verify the red state**

Run: `pnpm --filter @lighthouse/adapter-adna test`

Expected: FAIL because the aDNA adapter does not exist.

- [ ] **Step 3: Implement YAML projection and local evaluation**

Parse one lattice YAML file with sorted `nodes`, `entry_nodes`, `exit_nodes`, ports, and edges. Normalize into:

```ts
export interface AdnaModel {
  nodes: Array<{ id: string; inputs: Record<string, string>; outputs: Record<string, string>; contextPath: string[] }>;
  edges: Array<{ from: string; to: string; dataMapping: Record<string, string>; contextPath: string[] }>;
}
```

Use `application/vnd.adna.port-compatibility-claim+json`. Evaluation requires the named output, named input, equal declared type, and a connecting edge whose `data_mapping` binds those ports.

- [ ] **Step 4: Write failing valid, unmapped, and invalid bridge tests**

```ts
it("translates the shared dependency claim", async () => {
  const translated = await bridge.translateClaim(hyperDependencyClaim);
  expect(translated).toMatchObject({ ok: true, value: { payload: { sentenceMediaType: "application/vnd.adna.port-compatibility-claim+json" } } });
});

it("leaves Hyper lease semantics explicitly unmapped", async () => {
  expect(await bridge.translateClaim(hyperLeaseClaim)).toEqual({
    ok: false,
    obstruction: { code: "BRIDGE_CLAIM_UNMAPPED", message: "Hyper lease claims are outside the v0.1 bridge domain", paths: ["payload.sentence"] },
  });
});

it("makes the deliberately wrong type mapping violate target truth", async () => {
  const result = await translateWithWitness(invalidBridge, hyperDependencyClaim, hyperAdapter, hyperSnapshot, adnaAdapter, adnaSnapshot);
  expect(result.witness.payload.outcome).toBe("invalid");
});
```

- [ ] **Step 5: Run the bridge test to verify the red state**

Run: `pnpm --filter @lighthouse/bridge-hyper-adna test`

Expected: FAIL because the bridge package does not exist.

- [ ] **Step 6: Implement the mapping-driven partial bridge**

The valid mapping binds `orders:producer` to `publish_order`, `orders:consumer` to `consume_order`, topic `orders.created.v1` to ports `order_created`, and type `application/vnd.example.order+json`. The invalid fixture substitutes `application/vnd.example.invoice+json`. The bridge declares `partial` fidelity because lease, fencing, and channel cursor semantics remain outside its domain.

- [ ] **Step 7: Run adapter and bridge verification**

Run: `pnpm --filter @lighthouse/adapter-adna test && pnpm --filter @lighthouse/adapter-adna typecheck && pnpm --filter @lighthouse/bridge-hyper-adna test && pnpm --filter @lighthouse/bridge-hyper-adna typecheck`

Expected: PASS for deterministic aDNA snapshots, local truth, valid preservation, invalid mapping, unmapped lease, identity, and associative composition with identities.

- [ ] **Step 8: Commit the aDNA adapter and reference bridge**

```bash
git add adapters/adna bridges/hyper-adna fixtures/adna fixtures/bridges pnpm-lock.yaml
git commit -m "feat(adapters): bridge Hyper claims into aDNA"
```

---

### Task 8: Machine-readable conformance proof

**Files:**
- Create: `packages/conformance/package.json`
- Create: `packages/conformance/tsconfig.json`
- Create: `packages/conformance/tsconfig.test.json`
- Create: `packages/conformance/src/report.ts`
- Create: `packages/conformance/src/reference.ts`
- Create: `packages/conformance/src/index.ts`
- Create: `packages/conformance/test/reference.test.ts`

**Interfaces:**
- Consumes: both adapters, the reference bridge, restriction/bridge laws, and policy evaluation.
- Produces: `ConformanceCheck`, `ConformanceReport`, `runReferenceConformance(options)`.

- [ ] **Step 1: Write one failing end-to-end acceptance test**

```ts
it("passes the complete valid reference proof", async () => {
  const report = await runReferenceConformance({ fixtureRoot, invalidBridge: false });
  expect(report.passed).toBe(true);
  expect(Object.fromEntries(report.checks.map((check) => [check.id, check.status]))).toEqual({
    "schema.artifacts": "passed",
    "digest.hyper-deterministic": "passed",
    "digest.adna-deterministic": "passed",
    "restriction.identity": "passed",
    "restriction.composition": "passed",
    "bridge.shared-claim": "passed",
    "bridge.source-satisfied": "passed",
    "bridge.target-satisfied": "passed",
    "bridge.identity": "passed",
    "bridge.associative": "passed",
    "bridge.lease-unmapped": "passed",
    "bridge.invalid-rejected": "passed",
    "policy.workflow-scoped": "passed",
    "policy.inject-denied": "passed",
    "policy.reshare-denied": "passed",
  });
});
```

- [ ] **Step 2: Run the focused test to verify the red state**

Run: `pnpm --filter @lighthouse/conformance test -- reference.test.ts`

Expected: FAIL because the conformance package is absent.

- [ ] **Step 3: Implement report types and reference orchestration**

```ts
export interface ConformanceCheck {
  id: string;
  status: "passed" | "failed";
  artifactDigests: string[];
  diagnostics: Array<{ code: string; message: string }>;
}
export interface ConformanceReport {
  protocolVersion: "0.1";
  profileIds: string[];
  bridgeDigest: string;
  passed: boolean;
  checks: ConformanceCheck[];
}
```

The runner creates both snapshots twice from distinct temporary checkout roots; seals source/target claims; runs schema/digest, restriction, identity/composition, valid/invalid satisfaction, obstruction, and policy checks; and sets `passed` only when every required check passed. Approximate checks are absent from exact conformance and cannot improve `passed`.

- [ ] **Step 4: Add the failing-candidate report test**

```ts
it("fails a candidate bridge that breaks satisfaction", async () => {
  const report = await runReferenceConformance({ fixtureRoot, invalidBridge: true });
  expect(report.passed).toBe(false);
  expect(report.checks.find((check) => check.id === "bridge.shared-claim")).toMatchObject({
    status: "failed",
    diagnostics: [{ code: "SATISFACTION_NOT_PRESERVED" }],
  });
});
```

- [ ] **Step 5: Run conformance tests and typecheck**

Run: `pnpm --filter @lighthouse/conformance test && pnpm --filter @lighthouse/conformance typecheck`

Expected: PASS for both valid and deliberately invalid reports.

- [ ] **Step 6: Commit conformance orchestration**

```bash
git add packages/conformance pnpm-lock.yaml
git commit -m "feat(conformance): prove scoped semantic preservation"
```

---

### Task 9: CLI, normative docs, and clean-checkout proof

**Files:**
- Create: `packages/conformance/src/cli.ts`
- Modify: `packages/conformance/src/index.ts`
- Modify: `packages/conformance/package.json`
- Create: `packages/conformance/test/cli.test.ts`
- Create: `spec/lighthouse-v0.1.md`
- Create: `spec/vocabulary.md`
- Create: `README.md`

**Interfaces:**
- Consumes: `parseArtifact`, `verifyArtifactDigest`, `runReferenceConformance`, and `evaluateConnectionPolicy`.
- Produces: `runCli(args, io): Promise<number>` plus the `lighthouse` executable with `validate`, `prove`, and `authorize` commands.

- [ ] **Step 1: Write failing CLI exit-code and JSON-output tests**

```ts
it("returns zero and JSON for the valid proof", async () => {
  const io = memoryIo();
  expect(await runCli(["prove", "--fixtures", fixtureRoot], io)).toBe(0);
  expect(JSON.parse(io.stdout).passed).toBe(true);
});

it("returns non-zero for schema, digest, bridge, and policy failures", async () => {
  expect(await runCli(["validate", invalidSchemaPath], memoryIo())).toBe(1);
  expect(await runCli(["validate", invalidDigestPath], memoryIo())).toBe(1);
  expect(await runCli(["prove", "--fixtures", fixtureRoot, "--invalid-bridge"], memoryIo())).toBe(1);
  expect(await runCli(["authorize", policyPath, injectRequestPath], memoryIo())).toBe(1);
});
```

- [ ] **Step 2: Run the CLI test to verify the red state**

Run: `pnpm --filter @lighthouse/conformance test -- cli.test.ts`

Expected: FAIL because `runCli` does not exist.

- [ ] **Step 3: Implement data-only commands and stable errors**

```ts
export interface CliIo { stdout(text: string): void; stderr(text: string): void }

export async function runCli(args: string[], io: CliIo): Promise<number> {
  const [command] = args;
  if (command === "validate") return runValidate(args.slice(1), io);
  if (command === "prove") return runProof(args.slice(1), io);
  if (command === "authorize") return runAuthorize(args.slice(1), io);
  io.stderr(JSON.stringify({ ok: false, code: "USAGE", message: "Expected validate, prove, or authorize" }));
  return 2;
}
```

All commands print one canonical JSON object and a newline. `validate` parses strict schema and verifies the digest. `prove` emits the conformance report. `authorize` parses a sealed policy plus a plain authorization request and emits the local decision. Input is parsed as data; the CLI never imports modules named by a descriptor.

- [ ] **Step 4: Write normative and operator documentation**

`spec/lighthouse-v0.1.md` states artifact digest coverage, evaluation values, bridge laws, conformance scope, and exact/partial/approximate rules. `spec/vocabulary.md` lists the domain terms plus diagnostic codes `DIGEST_MISMATCH`, `SCHEMA_INVALID`, `CONTEXT_OUTSIDE_DOMAIN`, `BRIDGE_DOMAIN_MISMATCH`, `BRIDGE_CLAIM_UNMAPPED`, `SATISFACTION_NOT_PRESERVED`, `NO_MATCHING_ALLOW`, `EXPLICIT_DENY`, and `OUTSIDE_VALIDITY`.

`README.md` documents:

```bash
corepack enable
pnpm install --frozen-lockfile
pnpm check
pnpm build
pnpm proof
```

It also states that v0.1 is offline, that its successful report applies only to the declared Hyper/aDNA profiles and fixture domain, that bridges are locally installed, that consent does not become transitive, and that revocation cannot force recipients to forget disclosed plaintext.

- [ ] **Step 5: Run focused and repository-wide verification**

Run: `pnpm schema:generate && git diff --exit-code -- schemas && pnpm check && pnpm build && pnpm proof`

Expected: all commands exit 0; proof JSON contains `"passed":true` and all 15 required check IDs.

- [ ] **Step 6: Commit the executable v0.1 kit**

```bash
git add packages/conformance spec README.md package.json pnpm-lock.yaml
git commit -m "feat: ship Lighthouse v0.1 reference proof"
```

- [ ] **Step 7: Verify a clean checkout using the committed lockfile**

Run:

```bash
verification_root="$(mktemp -d)"
git archive HEAD | tar -x -C "$verification_root"
pnpm --dir "$verification_root" install --offline --frozen-lockfile
pnpm --dir "$verification_root" check
pnpm --dir "$verification_root" build
pnpm --dir "$verification_root" proof
```

Expected: install, check, build, and proof all exit 0 outside the working tree.

- [ ] **Step 8: Record final evidence**

Run: `git status --short --branch && git log --oneline --decorate -12 && pnpm proof`

Expected: clean `main`, an ordered commit history for Tasks 1-9, and a final machine-readable passing report. Do not create a remote, publish packages, or add network integration in v0.1.
