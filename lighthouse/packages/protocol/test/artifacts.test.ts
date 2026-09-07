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
    sentence: {
      producerId: "orders:producer",
      consumerId: "orders:consumer",
      topic: "orders.created.v1",
    },
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
    const signed = {
      ...claim,
      attestations: [{ algorithm: "ml-dsa-65", keyId: "urn:key:1", signature: "abc" }],
    };

    expect(parseArtifact(signed).digest).toEqual(claim.digest);
    expect(verifyArtifactDigest(signed)).toEqual({ ok: true });
  });

  it("detects payload tampering", () => {
    const claim = sealArtifact(unsignedClaim);
    const tampered = {
      ...claim,
      payload: {
        ...claim.payload,
        sentence: { ...claim.payload.sentence, topic: "orders.deleted.v1" },
      },
    };

    expect(verifyArtifactDigest(tampered)).toEqual({ ok: false, code: "DIGEST_MISMATCH" });
  });

  it("rejects unknown core members", () => {
    expect(() => parseArtifact({ ...sealArtifact(unsignedClaim), surprise: true })).toThrow();
  });

  it("requires an evidence contract for approximate bridges", () => {
    expect(() =>
      sealArtifact({
        kind: "BridgeDescriptor",
        protocolVersion: "0.1",
        id: "urn:bridge:approximate-without-evidence",
        issuedAt: "2026-08-30T12:00:00Z",
        issuer: "urn:lighthouse:bridge-author",
        payloadMediaType: "application/vnd.lighthouse.bridge+json",
        payload: {
          source: { id: "urn:profile:source", version: "1.0.0" },
          target: { id: "urn:profile:target", version: "1.0.0" },
          domain: { contexts: ["workflow"], claimMediaTypes: ["application/example"] },
          fidelity: "approximate",
          implementation: "urn:implementation:local-only",
          dependencies: [],
        },
      }),
    ).toThrow("approximation");
  });
});
