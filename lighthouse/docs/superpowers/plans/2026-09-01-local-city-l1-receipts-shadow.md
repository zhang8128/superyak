# Local City L1: Receipts, Export 1.1, Shadow Mode, Labels, Policy Fixtures — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Lighthouse able to validate and evaluate what a live engram receiver emits: a core `RecallReceipt` artifact, a 1.1 export carrying receipts, a preregistered live-shadow evaluation mode, a receiver-owned labels document, and cross-implementation policy fixtures.

**Architecture:** `RecallReceipt` becomes a sixth-plus artifact kind in `packages/protocol` so `sealArtifact`, `parseArtifact`, `lighthouse validate`, and schema generation cover it for free. `packages/recall-evaluation` emits that artifact from the existing experiment (experiment-only fields move to `extensions`), gains a labels parser, a preregistration parser, a seeded bootstrap, and a shadow evaluator that replays receipts against receiver-owned labels. `adapters/engram` accepts `formatVersion: "1.1"` with an optional `receipts` array. A generator script seals policy fixtures and writes the TypeScript evaluator's decisions so engram's Python evaluator can be held to identical outputs.

**Tech Stack:** TypeScript 7 (NodeNext, strict, `exactOptionalPropertyTypes`, `noUncheckedIndexedAccess`), zod 4.4.3, vitest 4.1.10, pnpm 11 workspace, biome 2.5.8, Node 24+, tsx.

**Spec:** `/Users/kairos/Projects/engram/docs/superpowers/specs/2026-09-01-lighthouse-local-city-design.md` (sections 4.6, 4.7, 4.9, 10, 11). Binding names: `/private/tmp/claude-501/-Users-kairos-Projects-engram/d7c226be-bf28-4944-a644-37fc767685b3/scratchpad/local-city-contracts.md` (copy the "Lighthouse (L1 owns)" block into the WP brief if the scratchpad is gone).

## Global Constraints

- Lighthouse `protocolVersion` stays literal `"0.1"`. No change to `packages/protocol/src/json.ts` canonicalization or `digest.ts`.
- Envelope digests use `algorithm: "sha-256"` (protocol convention). Memory content digests and store digests inside payloads use `algorithm: "sha256"` with 64 lowercase hex (engram export convention). Do not unify them.
- `pnpm proof` must still print `"passed":true` with `bridgeDigest` `8f2194e9508bea7887196d8adbf668ddabef24f11c2b93513ab505f3736b4538` and 15 checks. `pnpm recall:proof` must still print `"passed":true` with 14 checks.
- No file under `adapters/hyper`, `adapters/adna`, `bridges/`, `fixtures/hyper`, `fixtures/adna`, `fixtures/bridges` may change.
- Every CLI output is one canonical JSON line. Reports contain counts, metrics, digests, ids, and codes only, never memory content or query text.
- Every new artifact or document schema is `.strict()`. Unknown members are rejected.
- Sorting uses `compareCanonicalJson`, never locale collation.
- Commit after every task with a conventional message. Run `pnpm check` before the final commit of each task.

### Work package brief (paste to the Codex lead)

- **Base ref:** `main` at `0c72ab6` (clean tree, `pnpm check` green).
- **Scope:** Items (a) through (g) of this plan's tasks: RecallReceipt artifact and schema; recall-evaluation emits it with negative controls; engram export 1.1 with receipts; labels document; preregistration and shadow mode with bootstrap; policy conformance fixtures and generator; CLI wiring; spec and README updates.
- **Allowed files:**
  - `packages/protocol/src/schemas.ts`, `packages/protocol/src/index.ts`, `packages/protocol/test/recall-receipt.test.ts` (new), `packages/protocol/test/schema-generation.test.ts`
  - `scripts/generate-schemas.ts`, `schemas/recall-receipt.schema.json` (generated), `scripts/generate-policy-fixtures.ts` (new)
  - `packages/recall-evaluation/src/*.ts`, `packages/recall-evaluation/test/*.ts`, `packages/recall-evaluation/package.json`
  - `adapters/engram/src/export.ts`, `adapters/engram/src/adapter.ts`, `adapters/engram/src/index.ts`, `adapters/engram/test/export.test.ts`, `adapters/engram/test/adapter.test.ts`
  - `packages/calculus/test/policy-fixtures.test.ts` (new)
  - `packages/conformance/src/cli.ts`, `packages/conformance/package.json`, `packages/conformance/test/cli.test.ts`
  - `fixtures/policy-conformance/**` (new), `fixtures/engram/receipts/**` (new)
  - `package.json` (scripts only), `pnpm-lock.yaml` (workspace link only)
  - `spec/engram-recall-v0.1.md`, `spec/lighthouse-v0.1.md`, `spec/vocabulary.md`, `README.md`
- **Forbidden files:** `adapters/hyper/**`, `adapters/adna/**`, `bridges/**`, `fixtures/hyper/**`, `fixtures/adna/**`, `fixtures/bridges/**`, `fixtures/policy/**`, `fixtures/engram/*.engram.json` (the four existing files), `packages/conformance/src/reference.ts`, `packages/conformance/src/report.ts`, `packages/calculus/src/**`, `packages/protocol/src/json.ts`, `packages/protocol/src/digest.ts`, `packages/protocol/src/artifacts.ts`.
- **Acceptance criteria:**
  1. `pnpm check` exits 0.
  2. `pnpm proof | grep -o '"passed":true'` prints `"passed":true`; `pnpm proof | grep -o '"bridgeDigest":"[0-9a-f]*"'` prints the digest above.
  3. `pnpm recall:proof | grep -o '"passed":true'` prints `"passed":true`; `pnpm recall:proof | grep -o '"checks":\[' | wc -l` prints 1 and the checks array has 14 entries.
  4. `pnpm schema:generate && git diff --exit-code schemas/` exits 0 (generated schema committed and current), and `ls schemas/recall-receipt.schema.json` succeeds.
  5. `pnpm lighthouse validate fixtures/engram/receipts/injected-true.json` exits 0 and prints `"kind":"RecallReceipt"`; `pnpm lighthouse validate fixtures/engram/receipts/invalid-injected-mismatch.json` exits 1 with `"code":"SCHEMA_INVALID"`.
  6. `pnpm lighthouse recall shadow --preregistration fixtures/engram/receipts/preregistration.json --export fixtures/engram/receipts/receiver.engram.json --labels fixtures/engram/receipts/receiver.labels.json` exits 0 and prints one line with `"kind":"RecallShadowReport"`; omitting `--preregistration` exits 1 with `"code":"PREREGISTRATION_REQUIRED"`.
  7. `pnpm policy:fixtures && git diff --exit-code fixtures/policy-conformance/` exits 0, and `ls fixtures/policy-conformance/decisions | wc -l` prints 14.
  8. `grep -c '"1.1"' spec/engram-recall-v0.1.md` is at least 1; `grep -c RecallReceipt spec/lighthouse-v0.1.md` is at least 1.
  9. `pnpm lighthouse recall digest --export fixtures/engram/receipts/receiver.engram.json` prints exactly one line, `{"corpusDigest":{"algorithm":"sha-256","value":"…"}}`, whose value equals `corpusDigest.value` in `fixtures/engram/receipts/preregistration.json`.
- **Notes for the lead and the integrator:**
  - The lead accepts a `pnpm-lock.yaml` diff limited to the new workspace dependency `@lighthouse/recall-evaluation` in `packages/conformance`. Any other lockfile change is out of scope.
  - Engram publisher ids use the scheme `urn:engram:<instance>`. The plan's example preregistration document shows `receiverPublisher: "urn:engram:engram"`, and the example receipts and labels use `urn:engram:why` and `urn:engram:blocks`.
  - Turns without a receipt in the export are scored local-only in both modes and reported as `holdout.localOnlyTurns`, so the live run must produce a receipt for every holdout turn or the policy-scoped metric silently equals the local baseline on those turns.
- **Reports to produce:** none beyond the committed fixtures and the passing `pnpm check` output pasted into the final WP report.

---

## File Structure

| File | Responsibility |
|---|---|
| `packages/protocol/src/schemas.ts` | Add `RecallReceipt` kind, payload schema, envelope, union membership, exported types |
| `packages/protocol/src/index.ts` | Export `recallReceiptSchema`, `RecallReceipt` type, `recallReceiptPayloadSchema` |
| `packages/protocol/test/recall-receipt.test.ts` | Seal, parse, verify, invariants, negative controls |
| `scripts/generate-schemas.ts` | Emit `recall-receipt.schema.json` with the injection if/then rule |
| `packages/recall-evaluation/src/receipt.ts` | Build and verify `RecallReceipt` artifacts from experiment data |
| `packages/recall-evaluation/src/types.ts` | Replace `RecallSelectionReceipt*` with protocol `RecallReceipt`; add shadow and labels types |
| `packages/recall-evaluation/src/experiment.ts` | Emit the artifact; map decisions and admissions into payload |
| `packages/recall-evaluation/src/reference.ts` | Read `payload.action` and `payload.injected` in the no-injection check |
| `packages/recall-evaluation/src/labels.ts` | Parse and normalize `*.labels.json` |
| `packages/recall-evaluation/src/preregistration.ts` | Parse a preregistration document |
| `packages/recall-evaluation/src/bootstrap.ts` | Seeded PRNG and percentile bootstrap |
| `packages/recall-evaluation/src/shadow.ts` | Replay receipts against labels; produce `RecallShadowReport` |
| `packages/recall-evaluation/src/cli.ts` | `proof` and `shadow` subcommands |
| `adapters/engram/src/export.ts` | `formatVersion` 1.0 or 1.1; optional `receipts`; validation and sorting |
| `adapters/engram/src/adapter.ts` | Restriction keeps receipts inside the context |
| `scripts/generate-policy-fixtures.ts` | Seal policy sources; write evaluator decisions |
| `fixtures/policy-conformance/{sources,policies,requests,decisions}/` | Shared cross-implementation fixture set |
| `fixtures/engram/receipts/` | Receiver export 1.1, labels, preregistration, receipt validation fixtures |
| `packages/conformance/src/cli.ts` | Route `recall …` to the recall CLI |

---

### Task 1: `RecallReceipt` artifact kind and generated schema

**Files:**
- Modify: `packages/protocol/src/schemas.ts`
- Modify: `packages/protocol/src/index.ts`
- Create: `packages/protocol/test/recall-receipt.test.ts`
- Modify: `scripts/generate-schemas.ts`
- Modify: `packages/protocol/test/schema-generation.test.ts`
- Create (generated): `schemas/recall-receipt.schema.json`

**Interfaces:**
- Produces: `recallReceiptPayloadSchema`, `recallReceiptSchema`, type `RecallReceipt`, kind literal `"RecallReceipt"`, media type `"application/vnd.lighthouse.recall-receipt+json"`. `sealArtifact` and `parseArtifact` accept it unchanged. Payload members: `turnId`, `context`, `purpose`, `audience: "self"`, `action: "recall"`, `injected: boolean`, `transformation: "weighted-rrf-v1"`, `receiverRule: { ruleId: string | null }`, `sources[]`, `selected[]`, `delivered[]`. `policyDecision` and `readDecision` are `{ effect: "allow" | "deny", ruleId: string | null, code: "NO_MATCHING_ALLOW" | "EXPLICIT_DENY" | "OUTSIDE_VALIDITY" | null }` with explicit nulls, never absent members.

- [ ] **Step 1: Write the failing test**

```ts
// packages/protocol/test/recall-receipt.test.ts
import { describe, expect, it } from "vitest";
import {
  parseArtifact,
  type RecallReceipt,
  recallReceiptSchema,
  sealArtifact,
  verifyArtifactDigest,
} from "../src/index.js";

const hex = (c: string) => c.repeat(64);

function unsigned() {
  return {
    kind: "RecallReceipt" as const,
    protocolVersion: "0.1" as const,
    id: "urn:receipt:engram:turn-1",
    issuedAt: "2026-09-01T12:00:00Z",
    issuer: "urn:lighthouse:engram",
    payloadMediaType: "application/vnd.lighthouse.recall-receipt+json",
    payload: {
      turnId: "turn-1",
      context: { id: "memory/technical", path: ["memory", "technical"] },
      purpose: "session-recall",
      audience: "self" as const,
      action: "recall" as const,
      injected: true,
      transformation: "weighted-rrf-v1" as const,
      receiverRule: { ruleId: "allow-why-technical" },
      sources: [
        {
          publisher: "urn:lighthouse:engram",
          role: "local" as const,
          weight: 1,
          storeDigest: { algorithm: "sha256", value: hex("a") },
          policyDecision: { effect: "allow" as const, ruleId: "local:self", code: null },
          traceOutcome: "matched" as const,
        },
        {
          publisher: "urn:lighthouse:why",
          role: "remote" as const,
          weight: 2,
          storeDigest: { algorithm: "sha256", value: hex("b") },
          policyDecision: { effect: "allow" as const, ruleId: "allow-why-technical", code: null },
          traceOutcome: "matched" as const,
        },
      ],
      selected: [
        {
          publisher: "urn:lighthouse:why",
          memoryId: "why-governance-tick",
          contentDigest: { algorithm: "sha256" as const, value: hex("c") },
          score: 2 / 61,
          contributions: [{ publisher: "urn:lighthouse:why", rank: 1 }],
        },
      ],
      delivered: [
        {
          publisher: "urn:lighthouse:why",
          memoryId: "why-governance-tick",
          readDecision: { effect: "allow" as const, ruleId: "allow-why-technical", code: null },
        },
      ],
    },
  };
}

describe("RecallReceipt artifact", () => {
  it("seals, parses through the artifact union, and verifies", () => {
    const receipt: RecallReceipt = sealArtifact(unsigned());
    expect(receipt.digest.algorithm).toBe("sha-256");
    const parsed = parseArtifact(receipt);
    expect(parsed.kind).toBe("RecallReceipt");
    expect(verifyArtifactDigest(parsed)).toEqual({ ok: true });
    expect(recallReceiptSchema.parse(receipt)).toEqual(receipt);
  });

  it("rejects injected:true with nothing delivered", () => {
    const input = unsigned();
    input.payload.delivered = [];
    expect(() => sealArtifact(input)).toThrow(/RECEIPT_INJECTION_MISMATCH/);
  });

  it("rejects injected:false with something delivered", () => {
    const input = unsigned();
    input.payload.injected = false;
    expect(() => sealArtifact(input)).toThrow(/RECEIPT_INJECTION_MISMATCH/);
  });

  it("rejects delivered references that were not selected", () => {
    const input = unsigned();
    input.payload.delivered[0]!.memoryId = "never-selected";
    expect(() => sealArtifact(input)).toThrow(/DELIVERED_NOT_SELECTED/);
  });

  it("rejects delivered references whose read decision is not allow", () => {
    const input = unsigned();
    input.payload.delivered[0]!.readDecision = {
      effect: "deny",
      ruleId: "deny-read",
      code: "EXPLICIT_DENY",
    };
    expect(() => sealArtifact(input)).toThrow(/DELIVERED_WITHOUT_ALLOW/);
  });

  it("rejects unknown members and missing publisher decisions", () => {
    expect(() =>
      sealArtifact({ ...unsigned(), payload: { ...unsigned().payload, query: "leak" } } as never),
    ).toThrow();
    const missing = unsigned();
    // biome-ignore lint/suspicious/noExplicitAny: deliberately malformed input
    delete (missing.payload.sources[1] as any).policyDecision;
    expect(() => sealArtifact(missing)).toThrow();
  });

  it("rejects a memory content digest that is not sha256 hex", () => {
    const input = unsigned();
    input.payload.selected[0]!.contentDigest = { algorithm: "sha256", value: "nothex" };
    expect(() => sealArtifact(input)).toThrow();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter @lighthouse/protocol test -- recall-receipt`
Expected: FAIL. `recallReceiptSchema` and `RecallReceipt` are not exported; `sealArtifact` rejects kind `RecallReceipt`.

- [ ] **Step 3: Add the schema to `packages/protocol/src/schemas.ts`**

Add `"RecallReceipt"` to `artifactKindSchema`:

```ts
export const artifactKindSchema = z.enum([
  "LighthouseDescriptor",
  "Snapshot",
  "Claim",
  "BridgeDescriptor",
  "TranslationWitness",
  "ConnectionPolicy",
  "RecallReceipt",
]);
```

Add, after `connectionPolicyPayloadSchema`:

```ts
export const memoryContentDigestSchema = z
  .object({
    algorithm: z.literal("sha256"),
    value: z.string().regex(/^[0-9a-f]{64}$/),
  })
  .strict();

export const policyDecisionRecordSchema = z
  .object({
    effect: z.enum(["allow", "deny"]),
    ruleId: nonEmptyString.nullable(),
    code: z.enum(["NO_MATCHING_ALLOW", "EXPLICIT_DENY", "OUTSIDE_VALIDITY"]).nullable(),
  })
  .strict();

const receiptSourceSchema = z
  .object({
    publisher: nonEmptyString,
    role: z.enum(["local", "remote"]),
    weight: z.number().finite().nonnegative(),
    storeDigest: memoryContentDigestSchema,
    policyDecision: policyDecisionRecordSchema,
    traceOutcome: z.enum(["matched", "absent", "context-mismatched", "unavailable", "policy-denied"]),
  })
  .strict();

const receiptContributionSchema = z
  .object({ publisher: nonEmptyString, rank: z.number().int().positive() })
  .strict();

const receiptSelectedSchema = z
  .object({
    publisher: nonEmptyString,
    memoryId: nonEmptyString,
    contentDigest: memoryContentDigestSchema,
    score: z.number().finite().nonnegative(),
    contributions: z.array(receiptContributionSchema).min(1),
  })
  .strict();

const receiptDeliveredSchema = z
  .object({
    publisher: nonEmptyString,
    memoryId: nonEmptyString,
    readDecision: policyDecisionRecordSchema,
  })
  .strict();

export const recallReceiptPayloadSchema = z
  .object({
    turnId: nonEmptyString,
    context: contextRefSchema,
    purpose: nonEmptyString,
    audience: z.literal("self"),
    action: z.literal("recall"),
    injected: z.boolean(),
    transformation: z.literal("weighted-rrf-v1"),
    receiverRule: z.object({ ruleId: nonEmptyString.nullable() }).strict(),
    sources: z.array(receiptSourceSchema),
    selected: z.array(receiptSelectedSchema),
    delivered: z.array(receiptDeliveredSchema),
  })
  .strict()
  .superRefine((payload, context) => {
    if (payload.injected !== payload.delivered.length > 0) {
      context.addIssue({
        code: "custom",
        message: "RECEIPT_INJECTION_MISMATCH: injected must equal delivered.length > 0",
        path: ["injected"],
      });
    }
    const selectedKeys = new Set(
      payload.selected.map((item) => `${item.publisher} ${item.memoryId}`),
    );
    payload.delivered.forEach((item, index) => {
      if (!selectedKeys.has(`${item.publisher} ${item.memoryId}`)) {
        context.addIssue({
          code: "custom",
          message: `DELIVERED_NOT_SELECTED: ${item.publisher} ${item.memoryId}`,
          path: ["delivered", index],
        });
      }
      if (item.readDecision.effect !== "allow") {
        context.addIssue({
          code: "custom",
          message: `DELIVERED_WITHOUT_ALLOW: ${item.publisher} ${item.memoryId}`,
          path: ["delivered", index, "readDecision"],
        });
      }
    });
  });
```

Add the envelope and union entries:

```ts
export const recallReceiptSchema = envelopeSchema("RecallReceipt", recallReceiptPayloadSchema);
```

Append `recallReceiptSchema` to the `lighthouseArtifactSchema` discriminated union, and `unsignedEnvelopeSchema("RecallReceipt", recallReceiptPayloadSchema)` to `unsignedArtifactSchema`. Add the type:

```ts
export type RecallReceipt = z.infer<typeof recallReceiptSchema>;
export type RecallReceiptPayload = z.infer<typeof recallReceiptPayloadSchema>;
export type PolicyDecisionRecord = z.infer<typeof policyDecisionRecordSchema>;
```

- [ ] **Step 4: Export from `packages/protocol/src/index.ts`**

Add to the `./schemas.js` export list: `memoryContentDigestSchema`, `type PolicyDecisionRecord`, `policyDecisionRecordSchema`, `type RecallReceipt`, `type RecallReceiptPayload`, `recallReceiptPayloadSchema`, `recallReceiptSchema`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `pnpm --filter @lighthouse/protocol test -- recall-receipt`
Expected: PASS, 7 tests.

- [ ] **Step 6: Extend schema generation and its test**

In `scripts/generate-schemas.ts`, import `recallReceiptSchema`, add `["recall-receipt.schema.json", recallReceiptSchema]` to `schemaEntries`, and add:

```ts
function addReceiptInjectionRules(schema: JsonValue): JsonValue {
  const document = schema as { [key: string]: JsonValue };
  const properties = document.properties as { [key: string]: JsonValue };
  const payload = properties.payload as { [key: string]: JsonValue };
  payload.allOf = [
    {
      if: { properties: { injected: { const: true } }, required: ["injected"] },
      // biome-ignore lint/suspicious/noThenProperty: `then` is a required JSON Schema keyword.
      then: { properties: { delivered: { minItems: 1 } } },
    },
    {
      if: { properties: { injected: { const: false } }, required: ["injected"] },
      // biome-ignore lint/suspicious/noThenProperty: `then` is a required JSON Schema keyword.
      then: { properties: { delivered: { maxItems: 0 } } },
    },
  ];
  return document;
}
```

and in the loop:

```ts
const jsonSchema =
  file === "bridge-descriptor.schema.json"
    ? addBridgeFidelityRules(generated)
    : file === "recall-receipt.schema.json"
      ? addReceiptInjectionRules(generated)
      : generated;
```

In `packages/protocol/test/schema-generation.test.ts`, add `"recall-receipt.schema.json"` to `expectedFiles` (alphabetical position: after `lighthouse-descriptor.schema.json`), and add this test:

```ts
it("preserves the receipt injection invariant for other languages", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "lighthouse-schema-receipt-"));
  await generateSchemas(directory);
  const schema = JSON.parse(
    await readFile(path.join(directory, "recall-receipt.schema.json"), "utf8"),
  );
  const validate = new Ajv2020({ strict: false, validateFormats: false }).compile(schema);
  const base = {
    kind: "RecallReceipt",
    protocolVersion: "0.1",
    id: "urn:receipt:test",
    issuedAt: "2026-09-01T12:00:00Z",
    issuer: "urn:lighthouse:engram",
    payloadMediaType: "application/vnd.lighthouse.recall-receipt+json",
    payload: {
      turnId: "turn-1",
      context: { id: "memory/technical", path: ["memory", "technical"] },
      purpose: "session-recall",
      audience: "self",
      action: "recall",
      injected: true,
      transformation: "weighted-rrf-v1",
      receiverRule: { ruleId: null },
      sources: [],
      selected: [],
      delivered: [],
    },
    digest: { algorithm: "sha-256", value: "0".repeat(64) },
  };
  expect(validate(base)).toBe(false);
  expect(validate({ ...base, payload: { ...base.payload, injected: false } })).toBe(true);
});
```

- [ ] **Step 7: Generate and verify**

Run: `pnpm schema:generate && pnpm --filter @lighthouse/protocol test`
Expected: PASS; `schemas/recall-receipt.schema.json` exists and is canonical JSON with a trailing newline.

- [ ] **Step 8: Commit**

```bash
git add packages/protocol scripts/generate-schemas.ts schemas/recall-receipt.schema.json
git commit -m "feat(protocol): add RecallReceipt artifact kind"
```

---

### Task 2: recall-evaluation emits `RecallReceipt`

**Files:**
- Modify: `packages/recall-evaluation/src/types.ts`
- Modify: `packages/recall-evaluation/src/receipt.ts`
- Modify: `packages/recall-evaluation/src/experiment.ts`
- Modify: `packages/recall-evaluation/src/reference.ts`
- Modify: `packages/recall-evaluation/src/index.ts`
- Modify: `packages/recall-evaluation/test/receipt.test.ts`
- Modify: `packages/recall-evaluation/test/experiment.test.ts` (only if it references `receipt.injected` or `receipt.kind` directly; update the property paths to `receipt.payload.*`)

**Interfaces:**
- Consumes: `recallReceiptSchema`, `RecallReceipt`, `sealArtifact`, `parseArtifact`, `verifyArtifactDigest` from `@lighthouse/protocol`.
- Produces: `buildRecallReceipt(input: RecallReceiptBuildInput): RecallReceipt`, `parseRecallReceipt(input: unknown): RecallReceipt`, `verifyRecallReceiptDigest(input: unknown): RecallReceiptVerification`. `RecallTurnReport.receipt` is now a `RecallReceipt`. Experiment-only fields live at `extensions["lighthouse:experiment"] = { experimentId, mode }`.

- [ ] **Step 1: Rewrite `packages/recall-evaluation/test/receipt.test.ts` to the artifact shape**

```ts
import { describe, expect, it } from "vitest";
import {
  buildRecallReceipt,
  parseRecallReceipt,
  type RecallReceiptBuildInput,
  verifyRecallReceiptDigest,
} from "../src/index.js";

function input(): RecallReceiptBuildInput {
  return {
    id: "urn:receipt:experiment:turn-1",
    issuedAt: "2026-08-30T12:00:00Z",
    issuer: "urn:lighthouse:receiver",
    experimentId: "urn:experiment:receipt",
    mode: "policy-scoped",
    turnId: "turn-1",
    context: { id: "memory/debugging", path: ["memory", "debugging"] },
    purpose: "debugging",
    receiverRuleId: null,
    sources: [],
    selected: [],
    delivered: [],
  };
}

describe("recall receipts as Lighthouse artifacts", () => {
  it("builds a sealed RecallReceipt with experiment data in extensions", () => {
    const receipt = buildRecallReceipt(input());
    expect(receipt.kind).toBe("RecallReceipt");
    expect(receipt.payload.injected).toBe(false);
    expect(receipt.payload.action).toBe("recall");
    expect(receipt.extensions?.["lighthouse:experiment"]).toEqual({
      experimentId: "urn:experiment:receipt",
      mode: "policy-scoped",
    });
    expect(parseRecallReceipt(receipt)).toEqual(receipt);
    expect(verifyRecallReceiptDigest(receipt)).toEqual({ ok: true });
  });

  it("refuses to claim injection when nothing was delivered", () => {
    expect(() => buildRecallReceipt({ ...input(), injected: true })).toThrow(
      /RECEIPT_INJECTION_MISMATCH/,
    );
  });

  it("distinguishes malformed receipts from digest tampering", () => {
    const receipt = buildRecallReceipt(input());
    expect(verifyRecallReceiptDigest({ ...receipt, privateContent: "unexpected" })).toEqual({
      ok: false,
      code: "INVALID_RECEIPT",
    });
    expect(
      verifyRecallReceiptDigest({
        ...receipt,
        payload: { ...receipt.payload, purpose: "tampered" },
      }),
    ).toEqual({ ok: false, code: "DIGEST_MISMATCH" });
  });

  it("rejects artifacts of another kind", () => {
    const receipt = buildRecallReceipt(input());
    expect(verifyRecallReceiptDigest({ ...receipt, kind: "Snapshot" })).toEqual({
      ok: false,
      code: "INVALID_RECEIPT",
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter @lighthouse/recall-evaluation test -- receipt`
Expected: FAIL. `buildRecallReceipt` and `RecallReceiptBuildInput` do not exist.

- [ ] **Step 3: Replace `packages/recall-evaluation/src/receipt.ts`**

```ts
import {
  type ContextRef,
  type Digest,
  type JsonValue,
  type PolicyDecisionRecord,
  parseArtifact,
  type RecallReceipt,
  recallReceiptSchema,
  sealArtifact,
  verifyArtifactDigest,
} from "@lighthouse/protocol";
import type { RecallExperimentMode } from "./types.js";

export interface ReceiptSourceInput {
  publisher: string;
  role: "local" | "remote";
  weight: number;
  storeDigest: { algorithm: "sha256"; value: string };
  policyDecision: PolicyDecisionRecord;
  traceOutcome: "matched" | "absent" | "context-mismatched" | "unavailable" | "policy-denied";
}

export interface ReceiptSelectedInput {
  publisher: string;
  memoryId: string;
  contentDigest: { algorithm: "sha256"; value: string };
  score: number;
  contributions: Array<{ publisher: string; rank: number }>;
}

export interface ReceiptDeliveredInput {
  publisher: string;
  memoryId: string;
  readDecision: PolicyDecisionRecord;
}

export interface RecallReceiptBuildInput {
  id: string;
  issuedAt: string;
  issuer: string;
  experimentId?: string | undefined;
  mode?: RecallExperimentMode | undefined;
  turnId: string;
  context: ContextRef;
  purpose: string;
  injected?: boolean | undefined;
  receiverRuleId: string | null;
  sources: ReceiptSourceInput[];
  selected: ReceiptSelectedInput[];
  delivered: ReceiptDeliveredInput[];
}

export type RecallReceiptVerification =
  | { ok: true }
  | { ok: false; code: "INVALID_RECEIPT" | "DIGEST_MISMATCH" };

export function buildRecallReceipt(input: RecallReceiptBuildInput): RecallReceipt {
  const extensions: { [key: string]: JsonValue } = {};
  if (input.experimentId !== undefined && input.mode !== undefined) {
    extensions["lighthouse:experiment"] = { experimentId: input.experimentId, mode: input.mode };
  }
  return sealArtifact({
    kind: "RecallReceipt",
    protocolVersion: "0.1",
    id: input.id,
    issuedAt: input.issuedAt,
    issuer: input.issuer,
    payloadMediaType: "application/vnd.lighthouse.recall-receipt+json",
    ...(Object.keys(extensions).length === 0 ? {} : { extensions }),
    payload: {
      turnId: input.turnId,
      context: input.context,
      purpose: input.purpose,
      audience: "self",
      action: "recall",
      injected: input.injected ?? input.delivered.length > 0,
      transformation: "weighted-rrf-v1",
      receiverRule: { ruleId: input.receiverRuleId },
      sources: input.sources,
      selected: input.selected,
      delivered: input.delivered,
    },
  });
}

export function parseRecallReceipt(input: unknown): RecallReceipt {
  return recallReceiptSchema.parse(input);
}

export function verifyRecallReceiptDigest(input: unknown): RecallReceiptVerification {
  const parsed = recallReceiptSchema.safeParse(input);
  if (!parsed.success) return { ok: false, code: "INVALID_RECEIPT" };
  const artifact = parseArtifact(parsed.data);
  return verifyArtifactDigest(artifact).ok ? { ok: true } : { ok: false, code: "DIGEST_MISMATCH" };
}

export function receiptDigest(receipt: RecallReceipt): Digest {
  return receipt.digest;
}
```

- [ ] **Step 4: Update `packages/recall-evaluation/src/types.ts`**

Delete `RecallSelectionReceiptContent` and `RecallSelectionReceipt`. Add at the top:

```ts
import type { RecallReceipt } from "@lighthouse/protocol";
```

Change `RecallTurnReport.receipt` to `receipt: RecallReceipt;`.

- [ ] **Step 5: Update `packages/recall-evaluation/src/experiment.ts`**

Replace the import of `sealRecallReceipt` with `buildRecallReceipt` and the `RecallSelectionReceiptContent` type import removed. Replace the `receiptContent` function with:

```ts
function traceOutcomeFor(admission: RecallSourceAdmission): ReceiptSourceInput["traceOutcome"] {
  if (admission.admission === "policy-denied") return "policy-denied";
  if (admission.trace === "matched") return "matched";
  if (admission.trace === "absent") return "absent";
  return "context-mismatched";
}

function policyDecisionFor(decision: RecallSourceDecision): PolicyDecisionRecord {
  if (decision.allowed) return { effect: "allow", ruleId: decision.ruleId, code: null };
  return { effect: "deny", ruleId: decision.ruleId ?? null, code: decision.code };
}

function buildTurnReceipt(
  input: RecallExperimentInput,
  mode: RecallExperimentMode,
  turn: RecallTurnJudgment,
  sources: RecallSource[],
  decisions: RecallSourceDecision[],
  admissions: RecallSourceAdmission[],
  selected: FusedCandidate[],
): RecallReceipt {
  const decisionByPublisher = new Map(decisions.map((d) => [d.publisher, d]));
  const admissionByPublisher = new Map(admissions.map((a) => [a.publisher, a]));
  return buildRecallReceipt({
    id: `${input.id}:${mode}:${turn.turnId}`,
    issuedAt: input.issuedAt,
    issuer: input.receiverPublisher,
    experimentId: input.id,
    mode,
    turnId: turn.turnId,
    context: turn.context,
    purpose: turn.purpose,
    injected: false,
    receiverRuleId: null,
    sources: sources.map((source) => {
      const decision = decisionByPublisher.get(source.snapshot.issuer);
      const admission = admissionByPublisher.get(source.snapshot.issuer);
      if (decision === undefined || admission === undefined) {
        throw new Error(`MISSING_SOURCE_DECISION: ${source.snapshot.issuer}`);
      }
      return {
        publisher: source.snapshot.issuer,
        role: source.role,
        weight: source.weight,
        storeDigest: { algorithm: "sha256", value: source.snapshot.digest.value },
        policyDecision: policyDecisionFor(decision),
        traceOutcome: traceOutcomeFor(admission),
      };
    }),
    selected: selected.map((candidate) => ({
      publisher: candidate.ref.publisher,
      memoryId: candidate.ref.memoryId,
      contentDigest: { algorithm: "sha256", value: candidate.contentDigest.value },
      score: candidate.score,
      contributions: candidate.contributions.map((c) => ({
        publisher: c.ref.publisher,
        rank: c.rank,
      })),
    })),
    delivered: [],
  });
}
```

Add imports: `type PolicyDecisionRecord, type RecallReceipt` from `@lighthouse/protocol`; `buildRecallReceipt, type ReceiptSourceInput` from `./receipt.js`; `type FusedCandidate` from `./types.js`. In `runTurn`, replace `receipt: sealRecallReceipt(receiptContent(...))` with `receipt: buildTurnReceipt(input, mode, turn, sources, decisions, admissions, selected)`.

Note: `source.snapshot.digest.value` is a 64-hex sha-256 of the snapshot; it is carried as the store digest under the `sha256` label because the receipt schema fixes that label for store and content digests. This is the one place the two conventions meet, and the plan chooses the payload convention.

- [ ] **Step 6: Update `packages/recall-evaluation/src/reference.ts`**

In the `receipt.no-injection` check, replace `turn.receipt.action === "recall" && turn.receipt.injected === false` with `turn.receipt.payload.action === "recall" && turn.receipt.payload.injected === false`.

- [ ] **Step 7: Update `packages/recall-evaluation/src/index.ts`**

Replace the receipt export block with:

```ts
export {
  buildRecallReceipt,
  parseRecallReceipt,
  type ReceiptDeliveredInput,
  type ReceiptSelectedInput,
  type ReceiptSourceInput,
  type RecallReceiptBuildInput,
  type RecallReceiptVerification,
  receiptDigest,
  verifyRecallReceiptDigest,
} from "./receipt.js";
```

Remove `RecallSelectionReceipt` and `RecallSelectionReceiptContent` from the type export list.

- [ ] **Step 8: Run the package tests and both proofs**

Run: `pnpm --filter @lighthouse/recall-evaluation test && pnpm recall:proof | grep -o '"passed":[a-z]*' && pnpm proof | grep -o '"passed":[a-z]*'`
Expected: PASS; both print `"passed":true`. If `experiment.test.ts` asserts on `receipt.injected`, change it to `receipt.payload.injected`.

- [ ] **Step 9: Commit**

```bash
git add packages/recall-evaluation
git commit -m "feat(recall): emit RecallReceipt artifacts from the experiment"
```

---

### Task 3: Engram export 1.1 with receipts

**Files:**
- Modify: `adapters/engram/src/export.ts`
- Modify: `adapters/engram/src/adapter.ts`
- Modify: `adapters/engram/src/index.ts`
- Modify: `adapters/engram/test/export.test.ts`
- Modify: `adapters/engram/test/adapter.test.ts`

**Interfaces:**
- Consumes: `recallReceiptSchema`, `parseArtifact`, `verifyArtifactDigest` from `@lighthouse/protocol`.
- Produces: `EngramExport.formatVersion: "1.0" | "1.1"`, `EngramExport.receipts?: RecallReceipt[]` (present only on 1.1; absent members are normalized to `[]` on the model so callers do not branch), diagnostics `RECEIPTS_REQUIRE_1_1`, `RECEIPT_DIGEST_MISMATCH`, `DUPLICATE_RECEIPT`, `CONTEXT_OUTSIDE_ROOT` (reused). `EngramModel.receipts: RecallReceipt[]` always present.

- [ ] **Step 1: Add failing tests to `adapters/engram/test/export.test.ts`**

Add a helper and tests at the end of the file:

```ts
import { sealArtifact } from "@lighthouse/protocol";

function receipt(turnId: string, contextPath: string[]) {
  return sealArtifact({
    kind: "RecallReceipt",
    protocolVersion: "0.1",
    id: `urn:receipt:${turnId}`,
    issuedAt: "2026-09-01T12:00:00Z",
    issuer: "urn:lighthouse:engram",
    payloadMediaType: "application/vnd.lighthouse.recall-receipt+json",
    payload: {
      turnId,
      context: { id: contextPath.join("/"), path: contextPath },
      purpose: "session-recall",
      audience: "self",
      action: "recall",
      injected: false,
      transformation: "weighted-rrf-v1",
      receiverRule: { ruleId: null },
      sources: [],
      selected: [],
      delivered: [],
    },
  });
}

describe("portable Engram export 1.1", () => {
  it("accepts 1.1 with receipts and normalizes receipt order", () => {
    const document = changed((value) => {
      value.formatVersion = "1.1";
      value.receipts = [
        receipt("turn-z", ["memory", "debugging"]),
        receipt("turn-a", ["memory", "debugging"]),
      ];
    });
    const parsed = parseEngramExport(document);
    expect(parsed.receipts.map((r) => r.payload.turnId)).toEqual(["turn-a", "turn-z"]);
  });

  it("normalizes a 1.0 document to an empty receipts list", () => {
    expect(parseEngramExport(validExport()).receipts).toEqual([]);
  });

  it("rejects receipts on a 1.0 document", () => {
    const document = changed((value) => {
      value.receipts = [receipt("turn-1", ["memory"])];
    });
    expect(() => parseEngramExport(document)).toThrow("RECEIPTS_REQUIRE_1_1");
  });

  it("rejects a receipt whose digest does not verify", () => {
    const tampered = receipt("turn-1", ["memory"]);
    tampered.payload.purpose = "tampered";
    const document = changed((value) => {
      value.formatVersion = "1.1";
      value.receipts = [tampered];
    });
    expect(() => parseEngramExport(document)).toThrow("RECEIPT_DIGEST_MISMATCH");
  });

  it("rejects duplicate receipts for one turn and context", () => {
    const document = changed((value) => {
      value.formatVersion = "1.1";
      value.receipts = [receipt("turn-1", ["memory"]), receipt("turn-1", ["memory"])];
    });
    expect(() => parseEngramExport(document)).toThrow("DUPLICATE_RECEIPT");
  });

  it("rejects receipts outside the declared root", () => {
    const document = changed((value) => {
      value.formatVersion = "1.1";
      value.receipts = [receipt("turn-1", ["relationship"])];
    });
    expect(() => parseEngramExport(document)).toThrow("CONTEXT_OUTSIDE_ROOT");
  });
});
```

Update the `TestDocument` interface with `receipts?: unknown[];` so the mutators compile.

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter @lighthouse/adapter-engram test -- export`
Expected: FAIL. `formatVersion: "1.1"` is rejected and `receipts` is an unknown member.

- [ ] **Step 3: Implement in `adapters/engram/src/export.ts`**

Change imports and the document schema:

```ts
import {
  compareCanonicalJson,
  parseArtifact,
  type RecallReceipt,
  recallReceiptSchema,
  verifyArtifactDigest,
} from "@lighthouse/protocol";
```

```ts
const engramExportSchema = z
  .object({
    formatVersion: z.enum(["1.0", "1.1"]),
    instance: nonEmptyString,
    context: z.object({ id: nonEmptyString, path: contextPathSchema }).strict(),
    memories: z.array(memorySchema),
    edges: z.array(edgeSchema),
    recallTraces: z.array(recallTraceSchema),
    receipts: z.array(recallReceiptSchema).optional(),
  })
  .strict();

export type EngramExport = z.infer<typeof engramExportSchema>;
export type EngramModel = Omit<EngramExport, "receipts"> & { receipts: RecallReceipt[] };
```

Add validation:

```ts
function validateReceipts(model: EngramExport): RecallReceipt[] {
  const receipts = model.receipts ?? [];
  if (receipts.length > 0 && model.formatVersion !== "1.1") {
    fail("RECEIPTS_REQUIRE_1_1", model.formatVersion);
  }
  const keys = new Set<string>();
  for (const receipt of receipts) {
    if (!verifyArtifactDigest(parseArtifact(receipt)).ok) {
      fail("RECEIPT_DIGEST_MISMATCH", receipt.id);
    }
    if (!contextStartsWith(model.context.path, receipt.payload.context.path)) {
      fail("CONTEXT_OUTSIDE_ROOT", receipt.id);
    }
    const key = JSON.stringify([receipt.payload.turnId, receipt.payload.context.id]);
    if (keys.has(key)) fail("DUPLICATE_RECEIPT", receipt.payload.turnId);
    keys.add(key);
  }
  return receipts.toSorted((left, right) =>
    compareCanonicalJson(
      [left.payload.turnId, left.payload.context.id],
      [right.payload.turnId, right.payload.context.id],
    ),
  );
}
```

In `parseEngramExport`, after `validateTraces`, compute `const receipts = validateReceipts(parsed);` and return `{ ...parsed, receipts, memories: …, edges: …, recallTraces: … }` (spread `parsed` first so `receipts` overrides the optional member).

- [ ] **Step 4: Restriction keeps receipts inside the context**

In `adapters/engram/src/adapter.ts` `restrictEngramSnapshot`, add to `restrictedModel`:

```ts
receipts: model.receipts.filter((receipt) =>
  contextStartsWith(context.path, receipt.payload.context.path),
),
```

Receipts are sealed and are never rewritten by restriction; a receipt is either inside the restricted context or dropped.

Add to `adapters/engram/test/adapter.test.ts` (using whatever snapshot helper that file already builds; if it projects from `fixtures/engram/local.engram.json`, build a 1.1 document inline with two receipts, one at `["memory","debugging","mcp"]` and one at `["memory","debugging","bridge"]`, write it to a temp dir, project it, restrict to `memory/debugging/mcp`, and assert one receipt survives):

```ts
it("restriction keeps only receipts inside the requested context", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "lighthouse-engram-receipts-"));
  const document = {
    ...JSON.parse(await readFile(path.join(fixtureRoot, "local.engram.json"), "utf8")),
    formatVersion: "1.1",
    receipts: [
      receiptAt(["memory", "debugging", "mcp"]),
      receiptAt(["memory", "debugging", "bridge"]),
    ],
  };
  await writeFile(path.join(directory, "receiver.engram.json"), JSON.stringify(document));
  const snapshot = await engramAdapter.project({
    root: directory,
    id: "urn:snapshot:receipts",
    issuer: "urn:lighthouse:engram",
    issuedAt: "2026-09-01T12:00:00Z",
  });
  const restricted = await engramAdapter.restrictSnapshot(snapshot, {
    id: "memory/debugging/mcp",
    path: ["memory", "debugging", "mcp"],
  });
  if (!restricted.ok) throw new Error(restricted.obstruction.code);
  expect(engramModel(restricted.value)?.receipts).toHaveLength(1);
});
```

with `receiptAt(path: string[])` defined in that test file exactly as `receipt(turnId, contextPath)` in Step 1 but with `turnId` set to `path.join("-")`.

- [ ] **Step 5: Export the type change from `adapters/engram/src/index.ts`**

No new names; confirm `EngramModel` and `EngramExport` are still exported.

- [ ] **Step 6: Run tests and proofs**

Run: `pnpm --filter @lighthouse/adapter-engram test && pnpm --filter @lighthouse/recall-evaluation test && pnpm recall:proof | grep -o '"passed":[a-z]*'`
Expected: PASS; `"passed":true`.

- [ ] **Step 7: Commit**

```bash
git add adapters/engram
git commit -m "feat(engram-adapter): accept export 1.1 with sealed receipts"
```

---

### Task 4: Labels document

**Files:**
- Create: `packages/recall-evaluation/src/labels.ts`
- Create: `packages/recall-evaluation/test/labels.test.ts`
- Modify: `packages/recall-evaluation/src/index.ts`

**Interfaces:**
- Produces: `parseLabelsDocument(input: unknown): LabelsDocument` where `LabelsDocument = { formatVersion: "1.0"; instance: string; turns: RecallTurnJudgment[] }`, turns sorted by `[turnId, context.id]`. Diagnostics: `DUPLICATE_LABEL_TURN`, `EMPTY_RELEVANCE_JUDGMENT`.

- [ ] **Step 1: Write the failing test**

```ts
// packages/recall-evaluation/test/labels.test.ts
import { describe, expect, it } from "vitest";
import { parseLabelsDocument } from "../src/index.js";

function labels() {
  return {
    formatVersion: "1.0",
    instance: "engram-local",
    turns: [
      {
        turnId: "turn-b",
        context: { id: "memory/technical", path: ["memory", "technical"] },
        purpose: "session-recall",
        relevant: [{ publisher: "urn:lighthouse:why", memoryId: "why-1" }],
        forbidden: [],
      },
      {
        turnId: "turn-a",
        context: { id: "memory/technical", path: ["memory", "technical"] },
        purpose: "session-recall",
        relevant: [{ publisher: "urn:lighthouse:engram", memoryId: "local-1" }],
        forbidden: [{ publisher: "urn:lighthouse:blocks", memoryId: "blocks-private" }],
      },
    ],
  };
}

describe("labels document", () => {
  it("parses and sorts turns by turn id then context", () => {
    const parsed = parseLabelsDocument(labels());
    expect(parsed.turns.map((turn) => turn.turnId)).toEqual(["turn-a", "turn-b"]);
  });

  it("rejects duplicate turn keys", () => {
    const document = labels();
    document.turns.push({ ...document.turns[0]! });
    expect(() => parseLabelsDocument(document)).toThrow("DUPLICATE_LABEL_TURN");
  });

  it("rejects a turn with no relevant references", () => {
    const document = labels();
    document.turns[0]!.relevant = [];
    expect(() => parseLabelsDocument(document)).toThrow("EMPTY_RELEVANCE_JUDGMENT");
  });

  it("rejects unknown members and other versions", () => {
    expect(() => parseLabelsDocument({ ...labels(), notes: "leak" })).toThrow();
    expect(() => parseLabelsDocument({ ...labels(), formatVersion: "2.0" })).toThrow();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter @lighthouse/recall-evaluation test -- labels`
Expected: FAIL. `parseLabelsDocument` is not exported.

- [ ] **Step 3: Implement `packages/recall-evaluation/src/labels.ts`**

```ts
import { compareCanonicalJson, contextRefSchema } from "@lighthouse/protocol";
import { z } from "zod";
import type { RecallTurnJudgment } from "./types.js";

const nonEmptyString = z.string().min(1);
const memoryRefSchema = z
  .object({ publisher: nonEmptyString, memoryId: nonEmptyString })
  .strict();

const labelTurnSchema = z
  .object({
    turnId: nonEmptyString,
    context: contextRefSchema,
    purpose: nonEmptyString,
    relevant: z.array(memoryRefSchema),
    forbidden: z.array(memoryRefSchema),
  })
  .strict();

const labelsDocumentSchema = z
  .object({
    formatVersion: z.literal("1.0"),
    instance: nonEmptyString,
    turns: z.array(labelTurnSchema),
  })
  .strict();

export interface LabelsDocument {
  formatVersion: "1.0";
  instance: string;
  turns: RecallTurnJudgment[];
}

export function parseLabelsDocument(input: unknown): LabelsDocument {
  const parsed = labelsDocumentSchema.parse(input);
  const keys = new Set<string>();
  for (const turn of parsed.turns) {
    const key = JSON.stringify([turn.turnId, turn.context.id]);
    if (keys.has(key)) throw new Error(`DUPLICATE_LABEL_TURN: ${turn.turnId}`);
    keys.add(key);
    if (turn.relevant.length === 0) throw new Error(`EMPTY_RELEVANCE_JUDGMENT: ${turn.turnId}`);
  }
  return {
    formatVersion: parsed.formatVersion,
    instance: parsed.instance,
    turns: parsed.turns.toSorted((left, right) =>
      compareCanonicalJson([left.turnId, left.context.id], [right.turnId, right.context.id]),
    ),
  };
}
```

- [ ] **Step 4: Export it**

Add to `packages/recall-evaluation/src/index.ts`: `export { type LabelsDocument, parseLabelsDocument } from "./labels.js";`

- [ ] **Step 5: Run test to verify it passes**

Run: `pnpm --filter @lighthouse/recall-evaluation test -- labels`
Expected: PASS, 4 tests.

- [ ] **Step 6: Commit**

```bash
git add packages/recall-evaluation
git commit -m "feat(recall): add receiver-owned labels document"
```

---

### Task 5: Preregistration, seeded bootstrap, and shadow evaluation

**Files:**
- Create: `packages/recall-evaluation/src/preregistration.ts`
- Create: `packages/recall-evaluation/src/bootstrap.ts`
- Create: `packages/recall-evaluation/src/shadow.ts`
- Create: `packages/recall-evaluation/test/bootstrap.test.ts`
- Create: `packages/recall-evaluation/test/shadow.test.ts`
- Modify: `packages/recall-evaluation/src/types.ts`
- Modify: `packages/recall-evaluation/src/index.ts`
- Modify: `packages/recall-evaluation/package.json` (add `@lighthouse/adapter-engram` is already present; no change unless missing)

**Interfaces:**
- Consumes: `parseEngramExport`, `EngramModel` from `@lighthouse/adapter-engram`; `measureTurn` from `./metrics.js`; `LabelsDocument` from `./labels.js`; `digestJson` from `@lighthouse/protocol`.
- Produces:
  - `parsePreregistration(input: unknown): Preregistration` with `Preregistration = { receiverPublisher: string; corpusDigest: Digest; holdoutTurnIds: string[]; cutoff: number; metrics: ["rightTurnRecall", "nDCG"]; bootstrap: { samples: number; seed: number } }`.
  - `mulberry32(seed: number): () => number`, `bootstrapInterval(values: number[], samples: number, seed: number): { lower: number; upper: number }`.
  - `runShadowEvaluation(input: { exportDocument: unknown; labels: LabelsDocument; preregistration: Preregistration; issuedAt: string }): RecallShadowReport`.
  - `exportCorpusDigest(exportDocument: unknown): Digest`, the `sha-256` protocol digest over the normalized export model. `runShadowEvaluation` compares this against the preregistration, and the `recall digest` CLI subcommand (Task 6) prints it so E3 can write the preregistration without reimplementing the adapter.
  - Diagnostics: `CORPUS_DIGEST_MISMATCH`, `HOLDOUT_TURN_UNLABELED`, `HOLDOUT_TURN_MISSING_TRACE`, `HOLDOUT_TURN_CONTEXT_MISMATCH`, `RECEIPT_SCORE_MISMATCH`, `EMPTY_HOLDOUT`.
  - Report: `{ kind: "RecallShadowReport"; protocolVersion: "0.1"; issuedAt; instance; receiverPublisher; preregistrationDigest: Digest; corpusDigest: Digest; cutoff; holdout: { turns: number; receipts: number; localOnlyTurns: number }; modes: { "local-only": ShadowModeMetrics; "policy-scoped": ShadowModeMetrics }; receiptDigests: string[]; digest: Digest }` where `ShadowModeMetrics = RecallMetrics & { bootstrap: { samples; seed; rightTurnRecallAtK: Interval; ndcgAtK: Interval } }`.

- [ ] **Step 1: Write the failing bootstrap test**

```ts
// packages/recall-evaluation/test/bootstrap.test.ts
import { describe, expect, it } from "vitest";
import { bootstrapInterval, mulberry32 } from "../src/index.js";

describe("seeded bootstrap", () => {
  it("is deterministic for a seed", () => {
    const a = mulberry32(7);
    const b = mulberry32(7);
    expect([a(), a(), a()]).toEqual([b(), b(), b()]);
  });

  it("returns an interval inside the data range and identical across runs", () => {
    const values = [0, 0.5, 1, 1, 0.25];
    const first = bootstrapInterval(values, 200, 42);
    const second = bootstrapInterval(values, 200, 42);
    expect(first).toEqual(second);
    expect(first.lower).toBeGreaterThanOrEqual(0);
    expect(first.upper).toBeLessThanOrEqual(1);
    expect(first.lower).toBeLessThanOrEqual(first.upper);
  });

  it("collapses to the point value for a single observation", () => {
    expect(bootstrapInterval([0.4], 50, 1)).toEqual({ lower: 0.4, upper: 0.4 });
  });
});
```

- [ ] **Step 2: Implement `packages/recall-evaluation/src/bootstrap.ts`**

```ts
export function mulberry32(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export interface Interval {
  lower: number;
  upper: number;
}

function percentile(sorted: number[], fraction: number): number {
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil(fraction * sorted.length) - 1));
  return sorted[index] as number;
}

export function bootstrapInterval(values: number[], samples: number, seed: number): Interval {
  if (values.length === 0) throw new Error("EMPTY_BOOTSTRAP_INPUT");
  if (!Number.isInteger(samples) || samples < 1) throw new Error("INVALID_BOOTSTRAP_SAMPLES");
  const random = mulberry32(seed);
  const means: number[] = [];
  for (let sample = 0; sample < samples; sample += 1) {
    let total = 0;
    for (let index = 0; index < values.length; index += 1) {
      total += values[Math.floor(random() * values.length)] as number;
    }
    means.push(total / values.length);
  }
  means.sort((left, right) => left - right);
  return { lower: percentile(means, 0.025), upper: percentile(means, 0.975) };
}
```

- [ ] **Step 3: Run the bootstrap test**

Run: `pnpm --filter @lighthouse/recall-evaluation test -- bootstrap` (after adding the export in Step 7 below; add it now: `export { bootstrapInterval, type Interval, mulberry32 } from "./bootstrap.js";`)
Expected: PASS, 3 tests.

- [ ] **Step 4: Implement `packages/recall-evaluation/src/preregistration.ts`**

```ts
import { digestSchema } from "@lighthouse/protocol";
import { z } from "zod";

const nonEmptyString = z.string().min(1);

const preregistrationSchema = z
  .object({
    receiverPublisher: nonEmptyString,
    corpusDigest: digestSchema,
    holdoutTurnIds: z.array(nonEmptyString).min(1),
    cutoff: z.number().int().positive(),
    metrics: z.tuple([z.literal("rightTurnRecall"), z.literal("nDCG")]),
    bootstrap: z
      .object({
        samples: z.number().int().positive(),
        seed: z.number().int().nonnegative(),
      })
      .strict(),
  })
  .strict();

export type Preregistration = z.infer<typeof preregistrationSchema>;

export function parsePreregistration(input: unknown): Preregistration {
  const parsed = preregistrationSchema.parse(input);
  const seen = new Set<string>();
  for (const turnId of parsed.holdoutTurnIds) {
    if (seen.has(turnId)) throw new Error(`DUPLICATE_HOLDOUT_TURN: ${turnId}`);
    seen.add(turnId);
  }
  return { ...parsed, holdoutTurnIds: parsed.holdoutTurnIds.toSorted() };
}
```

- [ ] **Step 5: Write the failing shadow test**

```ts
// packages/recall-evaluation/test/shadow.test.ts
import { digestJson, type JsonValue, sealArtifact } from "@lighthouse/protocol";
import { parseEngramExport } from "@lighthouse/adapter-engram";
import { describe, expect, it } from "vitest";
import { parseLabelsDocument, parsePreregistration, runShadowEvaluation } from "../src/index.js";

const hex = (c: string) => c.repeat(64);
const RECEIVER = "urn:lighthouse:engram";
const WHY = "urn:lighthouse:why";
const BLOCKS = "urn:lighthouse:blocks";
const technical = { id: "memory/technical", path: ["memory", "technical"] };

function receiptFor(turnId: string, selected: Array<[string, string, number]>, blocksAllowed: boolean) {
  const weights: Record<string, number> = { [RECEIVER]: 1, [WHY]: 2, [BLOCKS]: 3 };
  return sealArtifact({
    kind: "RecallReceipt",
    protocolVersion: "0.1",
    id: `urn:receipt:${turnId}`,
    issuedAt: "2026-09-01T12:00:00Z",
    issuer: RECEIVER,
    payloadMediaType: "application/vnd.lighthouse.recall-receipt+json",
    payload: {
      turnId,
      context: technical,
      purpose: "session-recall",
      audience: "self",
      action: "recall",
      injected: false,
      transformation: "weighted-rrf-v1",
      receiverRule: { ruleId: "allow-technical" },
      sources: [
        {
          publisher: RECEIVER, role: "local", weight: 1,
          storeDigest: { algorithm: "sha256", value: hex("1") },
          policyDecision: { effect: "allow", ruleId: "local:self", code: null },
          traceOutcome: "matched",
        },
        {
          publisher: WHY, role: "remote", weight: 2,
          storeDigest: { algorithm: "sha256", value: hex("2") },
          policyDecision: { effect: "allow", ruleId: "allow-why", code: null },
          traceOutcome: "matched",
        },
        {
          publisher: BLOCKS, role: "remote", weight: 3,
          storeDigest: { algorithm: "sha256", value: hex("3") },
          policyDecision: blocksAllowed
            ? { effect: "allow", ruleId: "allow-blocks", code: null }
            : { effect: "deny", ruleId: "deny-blocks", code: "EXPLICIT_DENY" },
          traceOutcome: blocksAllowed ? "matched" : "policy-denied",
        },
      ],
      selected: selected.map(([publisher, memoryId, rank]) => ({
        publisher,
        memoryId,
        contentDigest: { algorithm: "sha256", value: hex("a") },
        score: (weights[publisher] as number) / (60 + rank),
        contributions: [{ publisher, rank }],
      })),
      delivered: [],
    },
  });
}

function exportDocument(receipts: unknown[]) {
  return {
    formatVersion: "1.1",
    instance: "engram-local",
    context: { id: "memory", path: ["memory"] },
    memories: [
      { id: "local-1", layer: "episode", contentDigest: { algorithm: "sha256", value: hex("a") }, contextPath: ["memory", "technical"], lane: "work", origin: "lived" },
      { id: "local-2", layer: "episode", contentDigest: { algorithm: "sha256", value: hex("b") }, contextPath: ["memory", "technical"], lane: "work", origin: "lived" },
    ],
    edges: [],
    recallTraces: [
      { turnId: "turn-1", queryDigest: { algorithm: "sha256", value: hex("c") }, contextPath: ["memory", "technical"], candidates: [{ memoryId: "local-2", rank: 1 }, { memoryId: "local-1", rank: 2 }] },
      { turnId: "turn-2", queryDigest: { algorithm: "sha256", value: hex("d") }, contextPath: ["memory", "technical"], candidates: [{ memoryId: "local-1", rank: 1 }] },
    ],
    receipts,
  };
}

function labels() {
  return parseLabelsDocument({
    formatVersion: "1.0",
    instance: "engram-local",
    turns: [
      { turnId: "turn-1", context: technical, purpose: "session-recall", relevant: [{ publisher: WHY, memoryId: "why-missing-piece" }], forbidden: [{ publisher: BLOCKS, memoryId: "blocks-private" }] },
      { turnId: "turn-2", context: technical, purpose: "session-recall", relevant: [{ publisher: RECEIVER, memoryId: "local-1" }], forbidden: [] },
    ],
  });
}

function preregistrationFor(document: unknown, overrides: Record<string, unknown> = {}) {
  const corpusDigest = digestJson(parseEngramExport(document) as unknown as JsonValue);
  return parsePreregistration({
    receiverPublisher: RECEIVER,
    corpusDigest,
    holdoutTurnIds: ["turn-1", "turn-2"],
    cutoff: 5,
    metrics: ["rightTurnRecall", "nDCG"],
    bootstrap: { samples: 100, seed: 3 },
    ...overrides,
  });
}

describe("shadow evaluation", () => {
  it("replays receipts against receiver labels and reports both modes", () => {
    const document = exportDocument([
      receiptFor("turn-1", [[WHY, "why-missing-piece", 1], [RECEIVER, "local-2", 1]], false),
    ]);
    const report = runShadowEvaluation({
      exportDocument: document,
      labels: labels(),
      preregistration: preregistrationFor(document),
      issuedAt: "2026-09-01T13:00:00Z",
    });
    expect(report.kind).toBe("RecallShadowReport");
    expect(report.holdout).toEqual({ turns: 2, receipts: 1, localOnlyTurns: 1 });
    expect(report.modes["local-only"].rightTurnRecallAtK).toBe(0.5);
    expect(report.modes["policy-scoped"].rightTurnRecallAtK).toBe(1);
    expect(report.modes["policy-scoped"].forbiddenExposureAtK).toBe(0);
    expect(report.modes["policy-scoped"].unauthorizedSelectionCount).toBe(0);
    expect(report.modes["policy-scoped"].bootstrap.rightTurnRecallAtK.upper).toBeLessThanOrEqual(1);
  });

  it("counts a forbidden and unauthorized selection when a denied publisher was selected", () => {
    const document = exportDocument([
      receiptFor("turn-1", [[BLOCKS, "blocks-private", 1]], false),
    ]);
    const report = runShadowEvaluation({
      exportDocument: document,
      labels: labels(),
      preregistration: preregistrationFor(document),
      issuedAt: "2026-09-01T13:00:00Z",
    });
    expect(report.modes["policy-scoped"].forbiddenExposureAtK).toBe(1);
    expect(report.modes["policy-scoped"].unauthorizedSelectionCount).toBe(1);
  });

  it("is deterministic and never carries content or query members", () => {
    const document = exportDocument([receiptFor("turn-1", [[WHY, "why-missing-piece", 1]], false)]);
    const run = () =>
      runShadowEvaluation({
        exportDocument: document,
        labels: labels(),
        preregistration: preregistrationFor(document),
        issuedAt: "2026-09-01T13:00:00Z",
      });
    expect(run().digest).toEqual(run().digest);
    const keys = new Set<string>();
    const walk = (value: unknown) => {
      if (Array.isArray(value)) for (const item of value) walk(item);
      else if (value && typeof value === "object")
        for (const [key, item] of Object.entries(value)) {
          keys.add(key);
          walk(item);
        }
    };
    walk(run());
    expect(keys.has("content")).toBe(false);
    expect(keys.has("query")).toBe(false);
  });

  it("refuses a corpus that does not match the preregistration", () => {
    const document = exportDocument([]);
    const preregistration = preregistrationFor(document, {
      corpusDigest: { algorithm: "sha-256", value: hex("f") },
    });
    expect(() =>
      runShadowEvaluation({ exportDocument: document, labels: labels(), preregistration, issuedAt: "2026-09-01T13:00:00Z" }),
    ).toThrow("CORPUS_DIGEST_MISMATCH");
  });

  it("refuses holdout turns without labels or local traces", () => {
    const document = exportDocument([]);
    expect(() =>
      runShadowEvaluation({
        exportDocument: document,
        labels: labels(),
        preregistration: preregistrationFor(document, { holdoutTurnIds: ["turn-1", "turn-9"] }),
        issuedAt: "2026-09-01T13:00:00Z",
      }),
    ).toThrow("HOLDOUT_TURN_UNLABELED");
    const unlabeledTrace = parseLabelsDocument({
      ...labels(),
      turns: [...labels().turns, { turnId: "turn-9", context: technical, purpose: "session-recall", relevant: [{ publisher: RECEIVER, memoryId: "local-1" }], forbidden: [] }],
    });
    expect(() =>
      runShadowEvaluation({
        exportDocument: document,
        labels: unlabeledTrace,
        preregistration: preregistrationFor(document, { holdoutTurnIds: ["turn-9"] }),
        issuedAt: "2026-09-01T13:00:00Z",
      }),
    ).toThrow("HOLDOUT_TURN_MISSING_TRACE");
  });

  it("refuses a receipt whose scores disagree with its contributions", () => {
    const receipt = receiptFor("turn-1", [[WHY, "why-missing-piece", 1]], false);
    const forged = sealArtifact({
      ...(({ digest: _d, ...rest }) => rest)(receipt),
      payload: {
        ...receipt.payload,
        selected: [{ ...receipt.payload.selected[0]!, score: 0.9 }],
      },
    });
    const document = exportDocument([forged]);
    expect(() =>
      runShadowEvaluation({ exportDocument: document, labels: labels(), preregistration: preregistrationFor(document), issuedAt: "2026-09-01T13:00:00Z" }),
    ).toThrow("RECEIPT_SCORE_MISMATCH");
  });
});
```

- [ ] **Step 6: Run the shadow test to verify it fails**

Run: `pnpm --filter @lighthouse/recall-evaluation test -- shadow`
Expected: FAIL. `runShadowEvaluation` and `parsePreregistration` are not exported.

- [ ] **Step 7: Implement `packages/recall-evaluation/src/shadow.ts`**

```ts
import { type EngramModel, parseEngramExport } from "@lighthouse/adapter-engram";
import {
  compareCanonicalJson,
  type Digest,
  digestJson,
  type JsonValue,
  type RecallReceipt,
} from "@lighthouse/protocol";
import { bootstrapInterval, type Interval } from "./bootstrap.js";
import type { LabelsDocument } from "./labels.js";
import { measureTurn } from "./metrics.js";
import type { Preregistration } from "./preregistration.js";
import type { FusedCandidate, RecallMetrics, RecallTurnJudgment } from "./types.js";

export interface ShadowModeMetrics extends RecallMetrics {
  bootstrap: { samples: number; seed: number; rightTurnRecallAtK: Interval; ndcgAtK: Interval };
}

export interface RecallShadowReportContent {
  kind: "RecallShadowReport";
  protocolVersion: "0.1";
  issuedAt: string;
  instance: string;
  receiverPublisher: string;
  preregistrationDigest: Digest;
  corpusDigest: Digest;
  cutoff: number;
  holdout: { turns: number; receipts: number; localOnlyTurns: number };
  modes: { "local-only": ShadowModeMetrics; "policy-scoped": ShadowModeMetrics };
  receiptDigests: string[];
}

export interface RecallShadowReport extends RecallShadowReportContent {
  digest: Digest;
}

export interface ShadowEvaluationInput {
  exportDocument: unknown;
  labels: LabelsDocument;
  preregistration: Preregistration;
  issuedAt: string;
}

function samePath(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((segment, index) => right[index] === segment);
}

function localCandidates(
  model: EngramModel,
  turn: RecallTurnJudgment,
  receiverPublisher: string,
): FusedCandidate[] {
  const traces = model.recallTraces.filter((trace) => trace.turnId === turn.turnId);
  if (traces.length === 0) throw new Error(`HOLDOUT_TURN_MISSING_TRACE: ${turn.turnId}`);
  const trace = traces.find((candidate) => samePath(candidate.contextPath, turn.context.path));
  if (trace === undefined) throw new Error(`HOLDOUT_TURN_CONTEXT_MISMATCH: ${turn.turnId}`);
  const memories = new Map(model.memories.map((memory) => [memory.id, memory]));
  return trace.candidates.map((candidate) => {
    const memory = memories.get(candidate.memoryId);
    if (memory === undefined) throw new Error(`DANGLING_CANDIDATE: ${candidate.memoryId}`);
    return {
      ref: { publisher: receiverPublisher, memoryId: candidate.memoryId },
      contentDigest: { algorithm: "sha256", value: memory.contentDigest.value },
      score: 1 / (60 + candidate.rank),
      contributions: [],
    };
  });
}

function verifyReceiptScores(receipt: RecallReceipt): void {
  const weights = new Map(receipt.payload.sources.map((source) => [source.publisher, source.weight]));
  for (const item of receipt.payload.selected) {
    let expected = 0;
    for (const contribution of item.contributions) {
      const weight = weights.get(contribution.publisher);
      if (weight === undefined) throw new Error(`RECEIPT_SCORE_MISMATCH: ${item.memoryId}`);
      expected += weight / (60 + contribution.rank);
    }
    if (Math.abs(expected - item.score) > 1e-9) {
      throw new Error(`RECEIPT_SCORE_MISMATCH: ${item.memoryId}`);
    }
  }
}

function scopedCandidates(receipt: RecallReceipt): FusedCandidate[] {
  verifyReceiptScores(receipt);
  return receipt.payload.selected.map((item) => ({
    ref: { publisher: item.publisher, memoryId: item.memoryId },
    contentDigest: { algorithm: "sha256", value: item.contentDigest.value },
    score: item.score,
    contributions: [],
  }));
}

function authorized(receipt: RecallReceipt | undefined): Record<string, boolean> {
  if (receipt === undefined) return {};
  return Object.fromEntries(
    receipt.payload.sources.map((source) => [
      source.publisher,
      source.policyDecision.effect === "allow",
    ]),
  );
}

function aggregate(perTurn: RecallMetrics[], samples: number, seed: number): ShadowModeMetrics {
  const count = perTurn.length;
  const recalls = perTurn.map((metrics) => metrics.rightTurnRecallAtK);
  const ndcgs = perTurn.map((metrics) => metrics.ndcgAtK);
  return {
    rightTurnRecallAtK: recalls.reduce((total, value) => total + value, 0) / count,
    ndcgAtK: ndcgs.reduce((total, value) => total + value, 0) / count,
    forbiddenExposureAtK: perTurn.reduce((total, m) => total + m.forbiddenExposureAtK, 0),
    unauthorizedSelectionCount: perTurn.reduce(
      (total, m) => total + m.unauthorizedSelectionCount,
      0,
    ),
    bootstrap: {
      samples,
      seed,
      rightTurnRecallAtK: bootstrapInterval(recalls, samples, seed),
      ndcgAtK: bootstrapInterval(ndcgs, samples, seed + 1),
    },
  };
}

export function exportCorpusDigest(exportDocument: unknown): Digest {
  return digestJson(parseEngramExport(exportDocument) as unknown as JsonValue);
}

export function runShadowEvaluation(input: ShadowEvaluationInput): RecallShadowReport {
  const model = parseEngramExport(input.exportDocument);
  const corpusDigest = digestJson(model as unknown as JsonValue);
  const { preregistration } = input;
  if (
    corpusDigest.algorithm !== preregistration.corpusDigest.algorithm ||
    corpusDigest.value !== preregistration.corpusDigest.value
  ) {
    throw new Error("CORPUS_DIGEST_MISMATCH");
  }
  if (preregistration.holdoutTurnIds.length === 0) throw new Error("EMPTY_HOLDOUT");
  const labelsByTurn = new Map(input.labels.turns.map((turn) => [turn.turnId, turn]));
  const receiptsByTurn = new Map(
    model.receipts.map((receipt) => [receipt.payload.turnId, receipt]),
  );
  const localOnly: RecallMetrics[] = [];
  const scoped: RecallMetrics[] = [];
  const usedReceipts: RecallReceipt[] = [];
  let localOnlyTurns = 0;
  for (const turnId of preregistration.holdoutTurnIds) {
    const turn = labelsByTurn.get(turnId);
    if (turn === undefined) throw new Error(`HOLDOUT_TURN_UNLABELED: ${turnId}`);
    const local = localCandidates(model, turn, preregistration.receiverPublisher);
    const receipt = receiptsByTurn.get(turnId);
    const options = {
      k: preregistration.cutoff,
      receiverPublisher: preregistration.receiverPublisher,
      authorizedPublishers: authorized(receipt),
    };
    localOnly.push(measureTurn(local, turn, { ...options, authorizedPublishers: {} }));
    if (receipt === undefined) {
      localOnlyTurns += 1;
      scoped.push(measureTurn(local, turn, { ...options, authorizedPublishers: {} }));
      continue;
    }
    usedReceipts.push(receipt);
    scoped.push(measureTurn(scopedCandidates(receipt), turn, options));
  }
  const { samples, seed } = preregistration.bootstrap;
  const content: RecallShadowReportContent = {
    kind: "RecallShadowReport",
    protocolVersion: "0.1",
    issuedAt: input.issuedAt,
    instance: model.instance,
    receiverPublisher: preregistration.receiverPublisher,
    preregistrationDigest: digestJson(preregistration as unknown as JsonValue),
    corpusDigest,
    cutoff: preregistration.cutoff,
    holdout: {
      turns: preregistration.holdoutTurnIds.length,
      receipts: usedReceipts.length,
      localOnlyTurns,
    },
    modes: {
      "local-only": aggregate(localOnly, samples, seed),
      "policy-scoped": aggregate(scoped, samples, seed),
    },
    receiptDigests: usedReceipts
      .map((receipt) => receipt.digest.value)
      .toSorted((left, right) => compareCanonicalJson(left, right)),
  };
  return { ...content, digest: digestJson(content as unknown as JsonValue) };
}
```

- [ ] **Step 8: Export from `packages/recall-evaluation/src/index.ts`**

```ts
export { type Preregistration, parsePreregistration } from "./preregistration.js";
export {
  exportCorpusDigest,
  type RecallShadowReport,
  type RecallShadowReportContent,
  runShadowEvaluation,
  type ShadowEvaluationInput,
  type ShadowModeMetrics,
} from "./shadow.js";
```

- [ ] **Step 9: Run the tests**

Run: `pnpm --filter @lighthouse/recall-evaluation test`
Expected: PASS, including 6 shadow tests. If the typecheck complains that `metrics: ["rightTurnRecall", "nDCG"]` in the test is `string[]`, add `as const` to that tuple in the test helper.

- [ ] **Step 10: Commit**

```bash
git add packages/recall-evaluation
git commit -m "feat(recall): add preregistered shadow evaluation with seeded bootstrap"
```

---

### Task 6: CLI wiring: `recall shadow`

**Files:**
- Modify: `packages/recall-evaluation/src/cli.ts`
- Modify: `packages/recall-evaluation/test/cli.test.ts`
- Modify: `packages/conformance/src/cli.ts`
- Modify: `packages/conformance/package.json`
- Modify: `packages/conformance/test/cli.test.ts`
- Create: `fixtures/engram/receipts/receiver.engram.json`, `fixtures/engram/receipts/receiver.labels.json`, `fixtures/engram/receipts/preregistration.json`, `fixtures/engram/receipts/injected-true.json`, `fixtures/engram/receipts/invalid-injected-mismatch.json`

**Interfaces:**
- Produces: `pnpm lighthouse recall shadow --preregistration <file> --export <file> --labels <file>`; `pnpm lighthouse recall digest --export <file>`; `pnpm lighthouse validate <receipt.json>`. `shadow`: exit 0 with one `RecallShadowReport` line; exit 1 with `{"ok":false,"code":"PREREGISTRATION_REQUIRED",...}` when the flag is missing; exit 1 with `"code":"SHADOW_FAILED"` and the thrown diagnostic in `message` for any evaluator error. `digest`: exit 0 with exactly one line of canonical JSON `{"corpusDigest":{"algorithm":"sha-256","value":"…"}}` and nothing else on stdout; exit 1 with `"code":"DIGEST_FAILED"` when the export does not parse.

- [ ] **Step 1: Update `packages/recall-evaluation/test/cli.test.ts`**

Change the usage expectation to `"Usage: recall-proof proof --fixtures <path> | recall-proof shadow --preregistration <file> --export <file> --labels <file> | recall-proof digest --export <file>"`, add `import { readFile } from "node:fs/promises";` and `import { exportCorpusDigest, parseLabelsDocument, parsePreregistration, runShadowEvaluation } from "../src/index.js";` at the top, and add:

```ts
const receiptsRoot = path.resolve(import.meta.dirname, "../../../fixtures/engram/receipts");

it("runs a preregistered shadow evaluation", async () => {
  const stdout: string[] = [];
  const stderr: string[] = [];
  const exitCode = await runRecallCli(
    [
      "shadow",
      "--preregistration", path.join(receiptsRoot, "preregistration.json"),
      "--export", path.join(receiptsRoot, "receiver.engram.json"),
      "--labels", path.join(receiptsRoot, "receiver.labels.json"),
    ],
    { stdout: (v) => stdout.push(v), stderr: (v) => stderr.push(v) },
  );
  expect(exitCode).toBe(0);
  expect(stderr).toEqual([]);
  const report = JSON.parse(stdout.join(""));
  expect(report.kind).toBe("RecallShadowReport");
  expect(report.holdout.turns).toBe(2);
});

it("refuses to run shadow without a preregistration", async () => {
  const stderr: string[] = [];
  const exitCode = await runRecallCli(
    ["shadow", "--export", path.join(receiptsRoot, "receiver.engram.json"), "--labels", path.join(receiptsRoot, "receiver.labels.json")],
    { stdout: () => undefined, stderr: (v) => stderr.push(v) },
  );
  expect(exitCode).toBe(1);
  expect(JSON.parse(stderr.join("")).code).toBe("PREREGISTRATION_REQUIRED");
});

it("prints the corpus digest the shadow evaluation compares against", async () => {
  const exportFile = path.join(receiptsRoot, "receiver.engram.json");
  const stdout: string[] = [];
  const stderr: string[] = [];
  const exitCode = await runRecallCli(["digest", "--export", exportFile], {
    stdout: (v) => stdout.push(v),
    stderr: (v) => stderr.push(v),
  });
  expect(exitCode).toBe(0);
  expect(stderr).toEqual([]);
  expect(stdout).toHaveLength(1);
  const printed = JSON.parse(stdout[0] as string);
  expect(Object.keys(printed)).toEqual(["corpusDigest"]);

  const exportDocument = JSON.parse(await readFile(exportFile, "utf8"));
  const report = runShadowEvaluation({
    exportDocument,
    labels: parseLabelsDocument(
      JSON.parse(await readFile(path.join(receiptsRoot, "receiver.labels.json"), "utf8")),
    ),
    preregistration: parsePreregistration(
      JSON.parse(await readFile(path.join(receiptsRoot, "preregistration.json"), "utf8")),
    ),
    issuedAt: "2026-09-01T13:00:00Z",
  });
  expect(printed.corpusDigest).toEqual(report.corpusDigest);
  expect(printed.corpusDigest).toEqual(exportCorpusDigest(exportDocument));
});
```

- [ ] **Step 2: Create the fixtures**

Generate them with a one-off script run from the repo root (do not commit the script), so the digests are real:

```bash
pnpm exec tsx -e '
import { writeFile, mkdir } from "node:fs/promises";
import { digestJson, sealArtifact, canonicalize } from "./packages/protocol/src/index.ts";
import { parseEngramExport } from "./adapters/engram/src/index.ts";
const hex = (c) => c.repeat(64);
const R = "urn:engram:engram", W = "urn:engram:why", B = "urn:engram:blocks";
const technical = { id: "memory/technical", path: ["memory", "technical"] };
const src = (p, role, w, d, allow) => ({ publisher: p, role, weight: w, storeDigest: { algorithm: "sha256", value: hex(d) },
  policyDecision: allow ? { effect: "allow", ruleId: p === R ? "local:self" : "allow-" + p.split(":").pop(), code: null } : { effect: "deny", ruleId: "deny-" + p.split(":").pop(), code: "EXPLICIT_DENY" },
  traceOutcome: allow ? "matched" : "policy-denied" });
const base = (turnId, selected, delivered) => sealArtifact({ kind: "RecallReceipt", protocolVersion: "0.1", id: "urn:receipt:" + turnId, issuedAt: "2026-09-01T12:00:00Z", issuer: R,
  payloadMediaType: "application/vnd.lighthouse.recall-receipt+json",
  payload: { turnId, context: technical, purpose: "session-recall", audience: "self", action: "recall", injected: delivered.length > 0, transformation: "weighted-rrf-v1",
    receiverRule: { ruleId: "allow-technical" }, sources: [src(R, "local", 1, "1", true), src(W, "remote", 2, "2", true), src(B, "remote", 3, "3", false)], selected, delivered } });
const sel = (p, id, rank, w) => ({ publisher: p, memoryId: id, contentDigest: { algorithm: "sha256", value: hex("a") }, score: w / (60 + rank), contributions: [{ publisher: p, rank }] });
const r1 = base("turn-1", [sel(W, "why-missing-piece", 1, 2), sel(R, "local-2", 1, 1)], []);
const injected = base("turn-3", [sel(W, "why-missing-piece", 1, 2)], [{ publisher: W, memoryId: "why-missing-piece", readDecision: { effect: "allow", ruleId: "allow-why", code: null } }]);
const mismatch = { ...injected, payload: { ...injected.payload, delivered: [] } };
const doc = { formatVersion: "1.1", instance: "engram-local", context: { id: "memory", path: ["memory"] },
  memories: [ { id: "local-1", layer: "episode", contentDigest: { algorithm: "sha256", value: hex("a") }, contextPath: ["memory","technical"], lane: "work", origin: "lived" },
              { id: "local-2", layer: "episode", contentDigest: { algorithm: "sha256", value: hex("b") }, contextPath: ["memory","technical"], lane: "work", origin: "lived" } ],
  edges: [],
  recallTraces: [ { turnId: "turn-1", queryDigest: { algorithm: "sha256", value: hex("c") }, contextPath: ["memory","technical"], candidates: [{ memoryId: "local-2", rank: 1 }, { memoryId: "local-1", rank: 2 }] },
                  { turnId: "turn-2", queryDigest: { algorithm: "sha256", value: hex("d") }, contextPath: ["memory","technical"], candidates: [{ memoryId: "local-1", rank: 1 }] } ],
  receipts: [r1] };
const labels = { formatVersion: "1.0", instance: "engram-local", turns: [
  { turnId: "turn-1", context: technical, purpose: "session-recall", relevant: [{ publisher: W, memoryId: "why-missing-piece" }], forbidden: [{ publisher: B, memoryId: "blocks-private" }] },
  { turnId: "turn-2", context: technical, purpose: "session-recall", relevant: [{ publisher: R, memoryId: "local-1" }], forbidden: [] } ] };
const pre = { receiverPublisher: R, corpusDigest: digestJson(parseEngramExport(doc)), holdoutTurnIds: ["turn-1", "turn-2"], cutoff: 5, metrics: ["rightTurnRecall", "nDCG"], bootstrap: { samples: 1000, seed: 20260901 } };
await mkdir("fixtures/engram/receipts", { recursive: true });
const w = (f, v) => writeFile("fixtures/engram/receipts/" + f, canonicalize(v) + "\n");
await w("receiver.engram.json", doc); await w("receiver.labels.json", labels); await w("preregistration.json", pre);
await w("injected-true.json", injected); await w("invalid-injected-mismatch.json", mismatch);
'
```

Note: `invalid-injected-mismatch.json` keeps the original digest, so it fails schema validation on the injection invariant before digest verification; that is the intended negative control.

- [ ] **Step 3: Implement the `shadow` subcommand in `packages/recall-evaluation/src/cli.ts`**

```ts
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { canonicalize, type JsonValue } from "@lighthouse/protocol";
import { parseLabelsDocument } from "./labels.js";
import { parsePreregistration } from "./preregistration.js";
import { runReferenceRecallProof } from "./reference.js";
import { exportCorpusDigest, runShadowEvaluation } from "./shadow.js";

export interface RecallCliIo {
  stdout(value: string): void;
  stderr(value: string): void;
}

const USAGE =
  "Usage: recall-proof proof --fixtures <path> | recall-proof shadow --preregistration <file> --export <file> --labels <file> | recall-proof digest --export <file>";

function emit(target: RecallCliIo["stdout"], value: JsonValue): void {
  target(`${canonicalize(value)}\n`);
}

function usage(io: RecallCliIo): number {
  emit(io.stderr, { ok: false, code: "USAGE", message: USAGE });
  return 1;
}

function flag(args: string[], name: string): string | undefined {
  const index = args.indexOf(name);
  return index === -1 ? undefined : args[index + 1];
}

async function readJson(file: string): Promise<unknown> {
  return JSON.parse(await readFile(file, "utf8"));
}

async function runProof(args: string[], io: RecallCliIo): Promise<number> {
  const fixtures = flag(args, "--fixtures");
  if (args.length !== 2 || fixtures === undefined) return usage(io);
  try {
    const report = await runReferenceRecallProof(fixtures);
    emit(io.stdout, report as unknown as JsonValue);
    return report.passed ? 0 : 1;
  } catch (error) {
    emit(io.stderr, {
      ok: false,
      code: "RECALL_PROOF_FAILED",
      message: error instanceof Error ? error.message : String(error),
    });
    return 1;
  }
}

async function runShadow(args: string[], io: RecallCliIo): Promise<number> {
  const preregistrationFile = flag(args, "--preregistration");
  const exportFile = flag(args, "--export");
  const labelsFile = flag(args, "--labels");
  if (preregistrationFile === undefined) {
    emit(io.stderr, {
      ok: false,
      code: "PREREGISTRATION_REQUIRED",
      message: "shadow refuses to run without --preregistration <file>",
    });
    return 1;
  }
  if (exportFile === undefined || labelsFile === undefined) return usage(io);
  try {
    const report = runShadowEvaluation({
      exportDocument: await readJson(exportFile),
      labels: parseLabelsDocument(await readJson(labelsFile)),
      preregistration: parsePreregistration(await readJson(preregistrationFile)),
      issuedAt: new Date().toISOString(),
    });
    emit(io.stdout, report as unknown as JsonValue);
    return 0;
  } catch (error) {
    emit(io.stderr, {
      ok: false,
      code: "SHADOW_FAILED",
      message: error instanceof Error ? error.message : String(error),
    });
    return 1;
  }
}

async function runDigest(args: string[], io: RecallCliIo): Promise<number> {
  const exportFile = flag(args, "--export");
  if (args.length !== 2 || exportFile === undefined) return usage(io);
  try {
    const corpusDigest = exportCorpusDigest(await readJson(exportFile));
    emit(io.stdout, { corpusDigest: { algorithm: corpusDigest.algorithm, value: corpusDigest.value } });
    return 0;
  } catch (error) {
    emit(io.stderr, {
      ok: false,
      code: "DIGEST_FAILED",
      message: error instanceof Error ? error.message : String(error),
    });
    return 1;
  }
}

export async function runRecallCli(args: string[], io: RecallCliIo): Promise<number> {
  const [command, ...rest] = args;
  if (command === "proof") return runProof(rest, io);
  if (command === "shadow") return runShadow(rest, io);
  if (command === "digest") return runDigest(rest, io);
  return usage(io);
}

const entrypoint = process.argv[1];
if (entrypoint !== undefined && import.meta.url === pathToFileURL(entrypoint).href) {
  process.exitCode = await runRecallCli(process.argv.slice(2), {
    stdout: (value) => process.stdout.write(value),
    stderr: (value) => process.stderr.write(value),
  });
}
```

`issuedAt` is the only non-deterministic member of the report and it is excluded from nothing; two runs differ only in `issuedAt` and therefore in `digest`. The shadow test in Task 5 pins determinism by passing a fixed `issuedAt`.

- [ ] **Step 4: Route from the conformance CLI**

In `packages/conformance/package.json` add `"@lighthouse/recall-evaluation": "workspace:*"` to `dependencies`, then run `pnpm install --frozen-lockfile=false` once so the lockfile links the workspace package (commit the lockfile change).

In `packages/conformance/src/cli.ts` add `import { runRecallCli } from "@lighthouse/recall-evaluation";` and in `runCli`:

```ts
if (command === "recall") {
  return runRecallCli(rest, { stdout: io.stdout, stderr: io.stderr });
}
```

and change the usage message to `"Expected validate, prove, authorize, or recall"`.

In `packages/conformance/test/cli.test.ts` add:

```ts
it("routes recall subcommands and validates a RecallReceipt", async () => {
  const receiptsRoot = path.resolve(import.meta.dirname, "../../../fixtures/engram/receipts");
  const out: string[] = [];
  const err: string[] = [];
  const io = { stdout: (t: string) => out.push(t), stderr: (t: string) => err.push(t) };
  expect(await runCli(["validate", path.join(receiptsRoot, "injected-true.json")], io)).toBe(0);
  expect(JSON.parse(out[0] as string).kind).toBe("RecallReceipt");
  expect(
    await runCli(["validate", path.join(receiptsRoot, "invalid-injected-mismatch.json")], io),
  ).toBe(1);
  expect(JSON.parse(err[0] as string).code).toBe("SCHEMA_INVALID");
  expect(await runCli(["recall", "shadow"], io)).toBe(1);
  expect(JSON.parse(err[1] as string).code).toBe("PREREGISTRATION_REQUIRED");
});
```

If that test file lacks a `path` import, add `import path from "node:path";`. If its existing usage test asserts the old message string, update it to the new one.

- [ ] **Step 5: Run everything**

Run: `pnpm check && pnpm proof | grep -o '"passed":[a-z]*' && pnpm recall:proof | grep -o '"passed":[a-z]*' && pnpm lighthouse recall shadow --preregistration fixtures/engram/receipts/preregistration.json --export fixtures/engram/receipts/receiver.engram.json --labels fixtures/engram/receipts/receiver.labels.json | grep -o '"kind":"RecallShadowReport"' && pnpm --silent lighthouse recall digest --export fixtures/engram/receipts/receiver.engram.json && grep -o '"corpusDigest":{[^}]*}' fixtures/engram/receipts/preregistration.json`
Expected: `pnpm check` exits 0; two `"passed":true`; `"kind":"RecallShadowReport"`; then two lines whose `corpusDigest` values are identical (the `digest` subcommand's line and the preregistration's member).

- [ ] **Step 6: Commit**

```bash
git add packages/recall-evaluation packages/conformance fixtures/engram/receipts pnpm-lock.yaml
git commit -m "feat(cli): add recall shadow subcommand and receipt fixtures"
```

---

### Task 7: Policy conformance fixtures and generator

**Files:**
- Create: `scripts/generate-policy-fixtures.ts`
- Create: `fixtures/policy-conformance/sources/local-city.policy.json`
- Create: `fixtures/policy-conformance/requests/*.json` (14 files, listed below)
- Create (generated): `fixtures/policy-conformance/policies/local-city.json`, `fixtures/policy-conformance/decisions/*.json`
- Create: `packages/calculus/test/policy-fixtures.test.ts`
- Modify: `packages/conformance/test/cli.test.ts` (authorize parity test, Step 5b)
- Modify: `package.json` (add script `"policy:fixtures": "tsx scripts/generate-policy-fixtures.ts"`)

**Interfaces:**
- Produces: `generatePolicyFixtures(root: string): Promise<void>` exported from the script, reading `sources/` and `requests/`, writing `policies/` (sealed) and `decisions/`. Request file shape: `{ "policy": "local-city", "request": AuthorizationRequest }`. Decision file shape: `{ "policy": "local-city", "request": "<request file stem>", "decision": AuthorizationDecision }`, canonical JSON, trailing newline. Engram vendors `policies/`, `requests/`, `decisions/` verbatim.
- **Decision shape guarantee:** each decision file's `decision` member is byte-for-byte the object `pnpm lighthouse authorize <policy> <request>` prints for that policy and bare request: `{"allowed":true,"ruleId":"…"}` or `{"allowed":false,"code":"…"}` or `{"allowed":false,"code":"…","ruleId":"…"}`. Both paths call `evaluateConnectionPolicy` and serialize with `canonicalize`, and canonical JSON of a nested member equals canonical JSON of that member alone, so the bytes match. Step 5b pins this with a test so engram's Python evaluator can compare its `to_lighthouse()` output against `decision` directly. If `authorize` ever prints a different shape, the generator must write exactly what `authorize` prints; the test is the tripwire.

- [ ] **Step 1: Write the policy source**

`fixtures/policy-conformance/sources/local-city.policy.json` (unsigned; the generator seals it). Every rule uses `profiles: ["urn:lighthouse:profile:engram-recall-trace"]`, `domains: ["memory.recall"]`, `claimMediaTypes: ["application/vnd.engram.recall-rank-claim+json"]`, `purposes: ["session-recall"]`, `audiences: ["self"]`, `validFrom: "2026-09-01T00:00:00Z"`, `validUntil: "2026-10-01T00:00:00Z"`, `requiredEvidence: []`, `requiredAttestations: []`, and the members below:

| id | effect | publishers | actions | contexts |
|---|---|---|---|---|
| `allow-why-technical` | allow | `urn:lighthouse:why` | `recall`, `read`, `inject_context` | `memory/technical` |
| `allow-blocks-recall` | allow | `urn:lighthouse:blocks` | `recall` | `memory/technical` |
| `deny-blocks-inject` | deny | `urn:lighthouse:blocks` | `inject_context` | `memory/technical` |
| `deny-gil-memory-prefix` | deny | `urn:lighthouse:gil` | `recall` | `memory/*` |
| `allow-gil-technical-exact` | allow | `urn:lighthouse:gil` | `recall` | `memory/technical` |
| `allow-agi-technical` | allow | `urn:lighthouse:agi` | `recall` | `memory/technical` |
| `deny-agi-technical` | deny | `urn:lighthouse:agi` | `recall` | `memory/technical` |

Envelope members: `kind: "ConnectionPolicy"`, `protocolVersion: "0.1"`, `id: "urn:policy:local-city"`, `issuedAt: "2026-09-01T00:00:00Z"`, `issuer: "urn:lighthouse:engram"`, `payloadMediaType: "application/vnd.lighthouse.connection-policy+json"`, `payload: { rules: [...] }`. No `digest` member in the source.

- [ ] **Step 2: Write the fourteen requests**

Each file in `fixtures/policy-conformance/requests/` is `{ "policy": "local-city", "request": { … } }` with the request defaulting to `profile: "urn:lighthouse:profile:engram-recall-trace"`, `domain: "memory.recall"`, `context: "memory/technical"`, `claimMediaType: "application/vnd.engram.recall-rank-claim+json"`, `purpose: "session-recall"`, `audience: "self"`, `at: "2026-09-15T00:00:00Z"`, `evidence: []`, `attestations: []`, varying only these members:

| file | publisher | action | other | expected decision |
|---|---|---|---|---|
| `no-matching-allow.json` | `urn:lighthouse:claw` | recall | | `{allowed:false, code:"NO_MATCHING_ALLOW"}` |
| `explicit-deny.json` | `urn:lighthouse:blocks` | inject_context | | `{allowed:false, code:"EXPLICIT_DENY", ruleId:"deny-blocks-inject"}` |
| `deny-wins-specificity-tie.json` | `urn:lighthouse:agi` | recall | | `{allowed:false, code:"EXPLICIT_DENY", ruleId:"deny-agi-technical"}` |
| `exact-beats-prefix.json` | `urn:lighthouse:gil` | recall | | `{allowed:true, ruleId:"allow-gil-technical-exact"}` |
| `prefix-deny-applies.json` | `urn:lighthouse:gil` | recall | `context: "memory/personal"` | `{allowed:false, code:"EXPLICIT_DENY", ruleId:"deny-gil-memory-prefix"}` |
| `outside-validity.json` | `urn:lighthouse:why` | recall | `at: "2026-12-01T00:00:00Z"` | `{allowed:false, code:"OUTSIDE_VALIDITY"}` |
| `non-transitive-claw.json` | `urn:lighthouse:claw` | read | | `{allowed:false, code:"NO_MATCHING_ALLOW"}` |
| `action-recall.json` | `urn:lighthouse:blocks` | recall | | `{allowed:true, ruleId:"allow-blocks-recall"}` |
| `action-read.json` | `urn:lighthouse:blocks` | read | | `{allowed:false, code:"NO_MATCHING_ALLOW"}` |
| `action-suggest.json` | `urn:lighthouse:blocks` | suggest | | `{allowed:false, code:"NO_MATCHING_ALLOW"}` |
| `action-inject-context.json` | `urn:lighthouse:blocks` | inject_context | | `{allowed:false, code:"EXPLICIT_DENY", ruleId:"deny-blocks-inject"}` |
| `action-derive.json` | `urn:lighthouse:blocks` | derive | | `{allowed:false, code:"NO_MATCHING_ALLOW"}` |
| `action-retain.json` | `urn:lighthouse:blocks` | retain | | `{allowed:false, code:"NO_MATCHING_ALLOW"}` |
| `action-reshare.json` | `urn:lighthouse:blocks` | reshare | | `{allowed:false, code:"NO_MATCHING_ALLOW"}` |

The `non-transitive-claw` case encodes the rule that `why` trusting `claw` grants `claw` nothing in engram's policy: engram's policy simply never names `claw`.

- [ ] **Step 3: Write the failing test**

```ts
// packages/calculus/test/policy-fixtures.test.ts
import { cp, mkdtemp, readdir, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { generatePolicyFixtures } from "../../../scripts/generate-policy-fixtures.js";

const root = path.resolve(import.meta.dirname, "../../../fixtures/policy-conformance");

async function readDecision(directory: string, name: string) {
  return JSON.parse(await readFile(path.join(directory, "decisions", `${name}.json`), "utf8"));
}

describe("policy conformance fixtures", () => {
  it("regenerates byte-identically from sources and requests", async () => {
    const scratch = await mkdtemp(path.join(os.tmpdir(), "lighthouse-policy-fixtures-"));
    await cp(path.join(root, "sources"), path.join(scratch, "sources"), { recursive: true });
    await cp(path.join(root, "requests"), path.join(scratch, "requests"), { recursive: true });
    await generatePolicyFixtures(scratch);
    for (const directory of ["policies", "decisions"]) {
      const files = (await readdir(path.join(root, directory))).sort();
      expect((await readdir(path.join(scratch, directory))).sort()).toEqual(files);
      for (const file of files) {
        expect(await readFile(path.join(scratch, directory, file), "utf8")).toBe(
          await readFile(path.join(root, directory, file), "utf8"),
        );
      }
    }
  });

  it("covers the required decision cases", async () => {
    expect((await readDecision(root, "no-matching-allow")).decision).toEqual({
      allowed: false,
      code: "NO_MATCHING_ALLOW",
    });
    expect((await readDecision(root, "explicit-deny")).decision).toEqual({
      allowed: false,
      code: "EXPLICIT_DENY",
      ruleId: "deny-blocks-inject",
    });
    expect((await readDecision(root, "deny-wins-specificity-tie")).decision).toEqual({
      allowed: false,
      code: "EXPLICIT_DENY",
      ruleId: "deny-agi-technical",
    });
    expect((await readDecision(root, "exact-beats-prefix")).decision).toEqual({
      allowed: true,
      ruleId: "allow-gil-technical-exact",
    });
    expect((await readDecision(root, "outside-validity")).decision).toEqual({
      allowed: false,
      code: "OUTSIDE_VALIDITY",
    });
    expect((await readDecision(root, "non-transitive-claw")).decision).toEqual({
      allowed: false,
      code: "NO_MATCHING_ALLOW",
    });
    expect((await readDecision(root, "action-recall")).decision.allowed).toBe(true);
    for (const action of ["read", "suggest", "derive", "retain", "reshare"]) {
      expect((await readDecision(root, `action-${action}`)).decision).toEqual({
        allowed: false,
        code: "NO_MATCHING_ALLOW",
      });
    }
    expect((await readDecision(root, "action-inject-context")).decision.code).toBe("EXPLICIT_DENY");
    expect((await readdir(path.join(root, "decisions"))).length).toBe(14);
  });
});
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pnpm --filter @lighthouse/calculus test -- policy-fixtures`
Expected: FAIL. The script does not exist.

- [ ] **Step 5: Implement `scripts/generate-policy-fixtures.ts`**

```ts
import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import {
  type AuthorizationRequest,
  evaluateConnectionPolicy,
} from "../packages/calculus/src/index.js";
import { canonicalize, type JsonValue } from "../packages/protocol/src/json.js";
import { parseArtifact, sealArtifact } from "../packages/protocol/src/artifacts.js";
import type { ConnectionPolicy } from "../packages/protocol/src/schemas.js";

async function readJson(file: string): Promise<unknown> {
  return JSON.parse(await readFile(file, "utf8"));
}

async function writeCanonical(file: string, value: JsonValue): Promise<void> {
  await mkdir(path.dirname(file), { recursive: true });
  await writeFile(file, `${canonicalize(value)}\n`);
}

export async function generatePolicyFixtures(root: string): Promise<void> {
  const policies = new Map<string, ConnectionPolicy>();
  const sourceDirectory = path.join(root, "sources");
  for (const file of (await readdir(sourceDirectory)).filter((f) => f.endsWith(".policy.json")).sort()) {
    const name = file.slice(0, -".policy.json".length);
    const sealed = parseArtifact(sealArtifact((await readJson(path.join(sourceDirectory, file))) as never));
    if (sealed.kind !== "ConnectionPolicy") throw new Error(`NOT_A_POLICY: ${file}`);
    policies.set(name, sealed);
    await writeCanonical(path.join(root, "policies", `${name}.json`), sealed as unknown as JsonValue);
  }
  const requestDirectory = path.join(root, "requests");
  for (const file of (await readdir(requestDirectory)).filter((f) => f.endsWith(".json")).sort()) {
    const name = file.slice(0, -".json".length);
    const document = (await readJson(path.join(requestDirectory, file))) as {
      policy: string;
      request: AuthorizationRequest;
    };
    const policy = policies.get(document.policy);
    if (policy === undefined) throw new Error(`UNKNOWN_POLICY: ${document.policy}`);
    const decision = evaluateConnectionPolicy(policy, document.request);
    await writeCanonical(path.join(root, "decisions", `${name}.json`), {
      policy: document.policy,
      request: name,
      decision: decision as unknown as JsonValue,
    });
  }
}

const entrypoint = process.argv[1];
if (entrypoint !== undefined && import.meta.url === pathToFileURL(entrypoint).href) {
  await generatePolicyFixtures(path.resolve("fixtures/policy-conformance"));
}
```

Add to root `package.json` scripts: `"policy:fixtures": "tsx scripts/generate-policy-fixtures.ts"`.

- [ ] **Step 5b: Pin authorize parity in `packages/conformance/test/cli.test.ts`**

Add these imports if the file lacks them: `import { mkdtemp, readdir, readFile, writeFile } from "node:fs/promises";`, `import os from "node:os";`, `import path from "node:path";`, `import { canonicalize } from "@lighthouse/protocol";`. Then add:

```ts
it("writes decision fixtures byte-identical to what authorize prints", async () => {
  const root = path.resolve(import.meta.dirname, "../../../fixtures/policy-conformance");
  const policyFile = path.join(root, "policies", "local-city.json");
  const scratch = await mkdtemp(path.join(os.tmpdir(), "lighthouse-authorize-parity-"));
  const requests = (await readdir(path.join(root, "requests"))).sort();
  expect(requests).toHaveLength(14);
  for (const file of requests) {
    const document = JSON.parse(await readFile(path.join(root, "requests", file), "utf8"));
    const requestFile = path.join(scratch, file);
    await writeFile(requestFile, JSON.stringify(document.request));
    const out: string[] = [];
    await runCli(["authorize", policyFile, requestFile], {
      stdout: (t) => out.push(t),
      stderr: () => undefined,
    });
    const { decision } = JSON.parse(await readFile(path.join(root, "decisions", file), "utf8"));
    expect(out.join("")).toBe(`${canonicalize(decision)}\n`);
  }
});
```

`authorize` exits 1 for a deny; the test reads stdout only, so the exit code is irrelevant here.

- [ ] **Step 6: Generate, then run the test**

Run: `pnpm policy:fixtures && pnpm --filter @lighthouse/calculus test -- policy-fixtures && pnpm --filter @lighthouse/conformance test`
Expected: `fixtures/policy-conformance/policies/local-city.json` and 14 decision files written; PASS. If any expected decision differs, the request file is wrong, not the evaluator: fix the request and regenerate. `packages/calculus/src/**` is forbidden.

- [ ] **Step 7: Commit**

```bash
git add scripts/generate-policy-fixtures.ts fixtures/policy-conformance packages/calculus/test/policy-fixtures.test.ts packages/conformance/test/cli.test.ts package.json
git commit -m "feat(policy): add cross-implementation conformance fixtures"
```

---

### Task 8: Spec, vocabulary, and README updates

**Files:**
- Modify: `spec/engram-recall-v0.1.md`
- Modify: `spec/lighthouse-v0.1.md`
- Modify: `spec/vocabulary.md`
- Modify: `README.md`

- [ ] **Step 1: `spec/engram-recall-v0.1.md`**

Replace the paragraph beginning "An adapter consumes one JSON source document with literal `formatVersion: "1.0"`" with:

```markdown
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
```

Replace the "Recall selection receipts" section with:

```markdown
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
```

- [ ] **Step 2: `spec/lighthouse-v0.1.md`**

In "Artifact envelope", after the sentence "A Lighthouse artifact MUST conform to one schema in `schemas/`", add: "The 0.1 artifact kinds are `LighthouseDescriptor`, `Snapshot`, `Claim`, `BridgeDescriptor`, `TranslationWitness`, `ConnectionPolicy`, and `RecallReceipt`." In "Local connection policy", replace "Future Engram adapters that inject active context MUST emit a local receipt…" with "An Engram receiver that delivers neighbor content into a recall response MUST emit a `RecallReceipt` whose `injected` member is true and whose `delivered` list names the material; the receipt identifies the source lighthouse, matched policy, declared purpose, selected material, and transformation." Add a final paragraph to "Conformance": "Policy evaluation is shared across implementations through `fixtures/policy-conformance/`; an implementation conforms only if it reproduces every committed decision byte for byte."

- [ ] **Step 3: `spec/vocabulary.md`**

Add a row to Terms: `| Recall receipt | Content-addressed record of one policy-scoped recall: sources, decisions, selection, delivery, and whether active context was injected. |`. Add rows to Stable diagnostic codes: `RECEIPT_INJECTION_MISMATCH`, `DELIVERED_NOT_SELECTED`, `DELIVERED_WITHOUT_ALLOW`, `RECEIPTS_REQUIRE_1_1`, `RECEIPT_DIGEST_MISMATCH`, `DUPLICATE_RECEIPT`, `DUPLICATE_LABEL_TURN`, `EMPTY_RELEVANCE_JUDGMENT`, `PREREGISTRATION_REQUIRED`, `CORPUS_DIGEST_MISMATCH`, `HOLDOUT_TURN_UNLABELED`, `HOLDOUT_TURN_MISSING_TRACE`, `HOLDOUT_TURN_CONTEXT_MISMATCH`, `RECEIPT_SCORE_MISMATCH`, each with the one-line meaning used in Step 1.

- [ ] **Step 4: `README.md`**

Under Quickstart, after `pnpm recall:proof`, add `pnpm policy:fixtures` with the note "regenerates the shared policy decision fixtures; `git diff --exit-code fixtures/policy-conformance` must be clean." Under CLI add:

```markdown
Replay a receiver's 1.1 export against its own labels under a preregistration:

```bash
pnpm lighthouse recall shadow \
  --preregistration fixtures/engram/receipts/preregistration.json \
  --export fixtures/engram/receipts/receiver.engram.json \
  --labels fixtures/engram/receipts/receiver.labels.json
```
```

Under Repository add `fixtures/policy-conformance/  Shared policy decisions for other implementations` and `schemas/recall-receipt.schema.json` is covered by the existing `schemas/` line. Under Boundaries, replace "Every selection receipt says `"injected":false`." with "The reference proof's receipts say `"injected":false`; a live receiver's receipts say `true` only when their `delivered` list is non-empty, and the schema enforces the equivalence."

- [ ] **Step 5: Final check and commit**

Run: `pnpm check && pnpm proof | grep -o '"passed":[a-z]*' && pnpm recall:proof | grep -o '"passed":[a-z]*' && git status --short`
Expected: exit 0, two `"passed":true`, clean tree after the commit below.

```bash
git add spec README.md
git commit -m "docs: specify RecallReceipt, export 1.1, labels, and shadow evaluation"
```

---

## Self-Review

**Spec coverage.** 4.6 receipt fields → Task 1 payload. 4.7 receipt artifact → Task 1; negative controls → Tasks 1 and 2; live-shadow mode with preregistration and bootstrap → Task 5; labeling-queue format → Task 4; policy validation and shared decision fixtures → Task 7; export 1.1 → Task 3; CLI → Task 6; docs → Task 8. Section 11 cross-implementation conformance → Task 7 produces the fixture set engram vendors. Nothing in 4.7 is uncovered.

**Placeholder scan.** No TBD, no "similar to Task N"; every code step carries its code. The one-off fixture generator in Task 6 Step 2 is deliberately not committed and is fully specified inline.

**Type consistency.** `PolicyDecisionRecord` (Task 1) is the type used by `ReceiptSourceInput.policyDecision` and `ReceiptDeliveredInput.readDecision` (Task 2) and by `authorized()` (Task 5). `RecallTurnJudgment` (existing) is the element type of `LabelsDocument.turns` (Task 4) and the input to `measureTurn` (Task 5). `Preregistration.metrics` is a fixed tuple; the test fixtures use `as const` where inference needs it. `EngramModel.receipts` is always an array (Task 3), so `shadow.ts` never branches on its presence. `runRecallCli` keeps its name and signature; only its usage string and subcommand set change (Task 6).
