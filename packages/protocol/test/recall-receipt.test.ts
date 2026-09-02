import { describe, expect, it } from "vitest";
import {
  parseArtifact,
  type RecallReceipt,
  recallReceiptSchema,
  sealArtifact,
  type UnsignedLighthouseArtifact,
  verifyArtifactDigest,
} from "../src/index.js";

const hex = (c: string) => c.repeat(64);
type UnsignedRecallReceipt = Extract<UnsignedLighthouseArtifact, { kind: "RecallReceipt" }>;

function unsigned(): UnsignedRecallReceipt {
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
          policyDecision: {
            effect: "allow" as const,
            ruleId: "allow-why-technical",
            code: null,
          },
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
          readDecision: {
            effect: "allow" as const,
            ruleId: "allow-why-technical",
            code: null,
          },
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
    const delivered = input.payload.delivered[0];
    if (delivered === undefined) throw new Error("test fixture must include a delivered reference");
    delivered.memoryId = "never-selected";
    expect(() => sealArtifact(input)).toThrow(/DELIVERED_NOT_SELECTED/);
  });

  it("rejects delivered references whose tuple only matches through a delimiter collision", () => {
    const input = unsigned();
    const selected = input.payload.selected[0];
    const delivered = input.payload.delivered[0];
    if (selected === undefined || delivered === undefined) {
      throw new Error("test fixture must include selected and delivered references");
    }
    selected.publisher = "a";
    selected.memoryId = "b c";
    delivered.publisher = "a b";
    delivered.memoryId = "c";
    expect(() => sealArtifact(input)).toThrow(/DELIVERED_NOT_SELECTED/);
  });

  it("rejects delivered references whose read decision is not allow", () => {
    const input = unsigned();
    const delivered = input.payload.delivered[0];
    if (delivered === undefined) throw new Error("test fixture must include a delivered reference");
    delivered.readDecision = {
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
    const selected = input.payload.selected[0];
    if (selected === undefined) throw new Error("test fixture must include a selected reference");
    selected.contentDigest = { algorithm: "sha256", value: "nothex" };
    expect(() => sealArtifact(input)).toThrow();
  });
});
