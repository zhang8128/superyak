import { describe, expect, it } from "vitest";
import {
  parseRecallReceipt,
  type RecallSelectionReceiptContent,
  sealRecallReceipt,
  verifyRecallReceiptDigest,
} from "../src/index.js";

function content(): RecallSelectionReceiptContent {
  return {
    kind: "RecallSelectionReceipt",
    version: "0.1",
    experimentId: "urn:experiment:receipt",
    issuedAt: "2026-08-30T12:00:00Z",
    mode: "policy-scoped",
    turnId: "turn-1",
    action: "recall",
    injected: false,
    purpose: "debugging",
    context: { id: "memory/debugging", path: ["memory", "debugging"] },
    transformation: "weighted-rrf-v1",
    selected: [],
    sources: [],
    decisions: [],
    admissions: [],
  };
}

describe("recall selection receipts", () => {
  it("strictly seals, parses, clones, and verifies receipt content", () => {
    const input = content();
    const receipt = sealRecallReceipt(input);
    input.context.path.push("mutated-after-sealing");

    expect(parseRecallReceipt(receipt)).toEqual(receipt);
    expect(receipt.context.path).toEqual(["memory", "debugging"]);
    expect(verifyRecallReceiptDigest(receipt)).toEqual({ ok: true });
  });

  it("rejects unknown fields and claims of active injection", () => {
    expect(() =>
      sealRecallReceipt({ ...content(), privateContent: "do not seal" } as never),
    ).toThrow();
    expect(() => sealRecallReceipt({ ...content(), injected: true } as never)).toThrow();
  });

  it("distinguishes malformed receipts from digest tampering", () => {
    const receipt = sealRecallReceipt(content());

    expect(verifyRecallReceiptDigest({ ...receipt, privateContent: "unexpected" })).toEqual({
      ok: false,
      code: "INVALID_RECEIPT",
    });
    expect(verifyRecallReceiptDigest({ ...receipt, purpose: "tampered" })).toEqual({
      ok: false,
      code: "DIGEST_MISMATCH",
    });
  });
});
