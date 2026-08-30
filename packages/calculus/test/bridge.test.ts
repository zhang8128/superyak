import {
  sealArtifact,
  type BridgeDescriptor,
  type Claim,
  type ProfileRef,
  type Snapshot,
} from "@lighthouse/protocol";
import { describe, expect, it } from "vitest";
import {
  composeBridges,
  identityBridge,
  translateWithWitness,
  type InstitutionAdapter,
  type RuntimeBridge,
} from "../src/index.js";

const sourceProfile = { id: "urn:profile:source", version: "1.0.0" };
const targetProfile = { id: "urn:profile:target", version: "1.0.0" };
const issuedAt = "2026-08-30T12:00:00Z";

function makeSnapshot(profile: ProfileRef, id: string): Snapshot {
  return sealArtifact({
    kind: "Snapshot",
    protocolVersion: "0.1",
    id,
    issuedAt,
    issuer: "urn:lighthouse:test",
    payloadMediaType: "application/vnd.lighthouse.snapshot+json",
    payload: {
      profile,
      signature: { id: `${profile.id}:signature`, version: "1.0.0" },
      context: { id: "workflow", path: ["workflow"] },
      model: { available: true },
      lineage: [],
    },
  });
}

const sourceSnapshot = makeSnapshot(sourceProfile, "urn:snapshot:source");
const targetSnapshot = makeSnapshot(targetProfile, "urn:snapshot:target");

const sourceClaim = sealArtifact({
  kind: "Claim",
  protocolVersion: "0.1",
  id: "urn:claim:source-truth",
  issuedAt,
  issuer: "urn:lighthouse:test",
  payloadMediaType: "application/vnd.lighthouse.claim+json",
  payload: {
    profile: sourceProfile,
    signature: { id: "urn:profile:source:signature", version: "1.0.0" },
    context: { id: "workflow", path: ["workflow"] },
    sentenceMediaType: "application/vnd.example.source-truth+json",
    sentence: { truth: true },
    snapshotDigests: [sourceSnapshot.digest],
    provenance: [],
  },
});

function makeAdapter(profile: ProfileRef): InstitutionAdapter {
  return {
    profile,
    async project() {
      return profile.id === sourceProfile.id ? sourceSnapshot : targetSnapshot;
    },
    async restrictSnapshot(snapshot) {
      return { ok: true, value: snapshot };
    },
    async restrictClaim(claim) {
      return { ok: true, value: claim };
    },
    async evaluate(_snapshot, claim) {
      if (claim.payload.profile.id !== profile.id) return "indeterminate";
      const sentence = claim.payload.sentence as { truth?: boolean };
      return sentence.truth === true ? "satisfied" : "violated";
    },
  };
}

const sourceAdapter = makeAdapter(sourceProfile);
const targetAdapter = makeAdapter(targetProfile);

function makeDescriptor(id: string): BridgeDescriptor {
  return sealArtifact({
    kind: "BridgeDescriptor",
    protocolVersion: "0.1",
    id,
    issuedAt,
    issuer: "urn:lighthouse:test",
    payloadMediaType: "application/vnd.lighthouse.bridge+json",
    payload: {
      source: sourceProfile,
      target: targetProfile,
      domain: {
        contexts: ["workflow"],
        claimMediaTypes: ["application/vnd.example.source-truth+json"],
      },
      fidelity: "partial",
      implementation: "urn:implementation:test-bridge",
      dependencies: [],
    },
  });
}

function truthBridge(id: string, flipTruth: boolean): RuntimeBridge {
  const descriptor = makeDescriptor(id);
  return {
    descriptor,
    lineage: [descriptor],
    async translateClaim(claim: Claim) {
      if (claim.payload.sentenceMediaType !== "application/vnd.example.source-truth+json") {
        return {
          ok: false as const,
          obstruction: {
            code: "BRIDGE_CLAIM_UNMAPPED",
            message: "The claim media type is outside the bridge domain",
            paths: ["payload.sentenceMediaType"],
          },
        };
      }
      const sourceSentence = claim.payload.sentence as { truth: boolean };
      const { digest: _digest, attestations: _attestations, ...common } = claim;
      return {
        ok: true as const,
        value: sealArtifact({
          ...common,
          id: `${claim.id}:translated`,
          issuer: descriptor.issuer,
          payload: {
            ...claim.payload,
            profile: targetProfile,
            signature: { id: "urn:profile:target:signature", version: "1.0.0" },
            sentenceMediaType: "application/vnd.example.target-truth+json",
            sentence: { truth: flipTruth ? !sourceSentence.truth : sourceSentence.truth },
            provenance: [claim.digest],
          },
        }),
      };
    },
  };
}

const bridge = truthBridge("urn:bridge:truth", false);
const invalidBridge = truthBridge("urn:bridge:falsehood", true);
const compositionMetadata = {
  id: "urn:bridge:composition",
  issuer: "urn:lighthouse:test",
  issuedAt,
};

describe("bridge laws", () => {
  it("preserves a supported claim through identity", async () => {
    const identity = identityBridge(
      sourceProfile,
      ["application/vnd.example.source-truth+json"],
      { id: "urn:bridge:source-identity", issuer: "urn:lighthouse:test", issuedAt },
    );

    const result = await translateWithWitness(
      identity,
      sourceClaim,
      sourceAdapter,
      sourceSnapshot,
      sourceAdapter,
      sourceSnapshot,
    );

    expect(result.witness.payload.outcome).toBe("preserved");
    expect(result.translatedClaim?.payload.sentence).toEqual({ truth: true });
  });

  it("flattens lineage so identity-wrapped composition is associative", async () => {
    const sourceIdentity = identityBridge(
      sourceProfile,
      ["application/vnd.example.source-truth+json"],
      { id: "urn:bridge:source-identity", issuer: "urn:lighthouse:test", issuedAt },
    );
    const targetIdentity = identityBridge(
      targetProfile,
      ["application/vnd.example.target-truth+json"],
      { id: "urn:bridge:target-identity", issuer: "urn:lighthouse:test", issuedAt },
    );
    const left = composeBridges(
      composeBridges(sourceIdentity, bridge, { ...compositionMetadata, id: "urn:bridge:left-a" }),
      targetIdentity,
      { ...compositionMetadata, id: "urn:bridge:left-b" },
    );
    const right = composeBridges(
      sourceIdentity,
      composeBridges(bridge, targetIdentity, {
        ...compositionMetadata,
        id: "urn:bridge:right-a",
      }),
      { ...compositionMetadata, id: "urn:bridge:right-b" },
    );

    expect(left.lineage.map((item) => item.digest)).toEqual(
      right.lineage.map((item) => item.digest),
    );
    const leftResult = await left.translateClaim(sourceClaim);
    const rightResult = await right.translateClaim(sourceClaim);
    expect(leftResult.ok).toBe(true);
    expect(rightResult.ok).toBe(true);
    if (leftResult.ok && rightResult.ok) {
      expect(leftResult.value.digest).toEqual(rightResult.value.digest);
    }
  });

  it("marks evaluator disagreement as invalid", async () => {
    const result = await translateWithWitness(
      invalidBridge,
      sourceClaim,
      sourceAdapter,
      sourceSnapshot,
      targetAdapter,
      targetSnapshot,
    );

    expect(result.witness.payload.outcome).toBe("invalid");
    expect(result.witness.payload.diagnostics[0]?.code).toBe(
      "SATISFACTION_NOT_PRESERVED",
    );
  });

  it("rejects composition across mismatched profiles", () => {
    const targetIdentity = identityBridge(
      targetProfile,
      ["application/vnd.example.target-truth+json"],
      { id: "urn:bridge:target-identity", issuer: "urn:lighthouse:test", issuedAt },
    );

    expect(() => composeBridges(targetIdentity, bridge, compositionMetadata)).toThrow(
      "Bridge profile mismatch",
    );
  });
});
