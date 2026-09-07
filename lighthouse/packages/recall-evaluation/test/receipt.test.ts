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
