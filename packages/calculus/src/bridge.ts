import {
  type BridgeDescriptor,
  type Claim,
  type Fidelity,
  type ProfileRef,
  type Snapshot,
  sealArtifact,
  type TranslationWitness,
} from "@lighthouse/protocol";
import type { InstitutionAdapter, OperationResult } from "./adapter.js";

export interface RuntimeBridge {
  readonly descriptor: BridgeDescriptor;
  readonly lineage: readonly BridgeDescriptor[];
  translateClaim(claim: Claim): Promise<OperationResult<Claim>>;
}

export interface BridgeEnvelopeMetadata {
  id: string;
  issuer: string;
  issuedAt: string;
}

export interface TranslationResult {
  translatedClaim?: Claim;
  witness: TranslationWitness;
}

function sameProfile(left: ProfileRef, right: ProfileRef): boolean {
  return left.id === right.id && left.version === right.version;
}

export function identityBridge(
  profile: ProfileRef,
  claimMediaTypes: string[],
  metadata: BridgeEnvelopeMetadata,
): RuntimeBridge {
  const descriptor = sealArtifact({
    kind: "BridgeDescriptor",
    protocolVersion: "0.1",
    ...metadata,
    payloadMediaType: "application/vnd.lighthouse.bridge+json",
    payload: {
      source: profile,
      target: profile,
      domain: { contexts: ["*"], claimMediaTypes },
      fidelity: "exact",
      implementation: "urn:lighthouse:implementation:identity",
      dependencies: [],
    },
  });
  return {
    descriptor,
    lineage: [],
    async translateClaim(claim) {
      if (
        !sameProfile(claim.payload.profile, profile) ||
        !claimMediaTypes.includes(claim.payload.sentenceMediaType)
      ) {
        return {
          ok: false,
          obstruction: {
            code: "BRIDGE_CLAIM_UNMAPPED",
            message: "The claim is outside the identity bridge domain",
            paths: ["payload.profile", "payload.sentenceMediaType"],
          },
        };
      }
      return { ok: true, value: claim };
    },
  };
}

function composedFidelity(first: Fidelity, second: Fidelity): Fidelity {
  if (first === "approximate" || second === "approximate") return "approximate";
  if (first === "partial" || second === "partial") return "partial";
  return "exact";
}

export function composeBridges(
  first: RuntimeBridge,
  second: RuntimeBridge,
  metadata: BridgeEnvelopeMetadata,
): RuntimeBridge {
  if (!sameProfile(first.descriptor.payload.target, second.descriptor.payload.source)) {
    throw new Error("Bridge profile mismatch: first target must equal second source");
  }
  const fidelity = composedFidelity(
    first.descriptor.payload.fidelity,
    second.descriptor.payload.fidelity,
  );
  if (fidelity === "approximate") {
    throw new Error("Approximate bridge composition requires an explicit metric contract");
  }
  const descriptor = sealArtifact({
    kind: "BridgeDescriptor",
    protocolVersion: "0.1",
    ...metadata,
    payloadMediaType: "application/vnd.lighthouse.bridge+json",
    payload: {
      source: first.descriptor.payload.source,
      target: second.descriptor.payload.target,
      domain: {
        contexts: first.descriptor.payload.domain.contexts,
        claimMediaTypes: first.descriptor.payload.domain.claimMediaTypes,
      },
      fidelity,
      implementation: "urn:lighthouse:implementation:composition",
      dependencies: [first.descriptor.digest, second.descriptor.digest],
    },
  });
  return {
    descriptor,
    lineage: [...first.lineage, ...second.lineage],
    async translateClaim(claim) {
      const intermediate = await first.translateClaim(claim);
      if (!intermediate.ok) return intermediate;
      return second.translateClaim(intermediate.value);
    },
  };
}

function witnessMetadata(bridge: RuntimeBridge, sourceClaim: Claim) {
  return {
    id: `urn:lighthouse:witness:${sourceClaim.digest.value}:${bridge.descriptor.digest.value}`,
    issuer: bridge.descriptor.issuer,
    issuedAt: sourceClaim.issuedAt,
  };
}

export async function translateWithWitness(
  bridge: RuntimeBridge,
  sourceClaim: Claim,
  sourceAdapter: InstitutionAdapter,
  sourceSnapshot: Snapshot,
  targetAdapter: InstitutionAdapter,
  targetSnapshot: Snapshot,
): Promise<TranslationResult> {
  const sourceEvaluation = await sourceAdapter.evaluate(sourceSnapshot, sourceClaim);
  const translated = await bridge.translateClaim(sourceClaim);
  const lineage = bridge.lineage.map((descriptor) => descriptor.digest);

  if (!translated.ok) {
    return {
      witness: sealArtifact({
        kind: "TranslationWitness",
        protocolVersion: "0.1",
        ...witnessMetadata(bridge, sourceClaim),
        payloadMediaType: "application/vnd.lighthouse.translation-witness+json",
        payload: {
          sourceClaimDigest: sourceClaim.digest,
          sourceSnapshotDigests: [sourceSnapshot.digest],
          bridgeDigest: bridge.descriptor.digest,
          bridgeLineage: lineage,
          outcome: "unmapped",
          mappedPaths: [],
          unmappedPaths: translated.obstruction.paths,
          sourceEvaluation,
          evidenceDigests: [sourceSnapshot.digest],
          diagnostics: [translated.obstruction],
        },
      }),
    };
  }

  const targetEvaluation = await targetAdapter.evaluate(targetSnapshot, translated.value);
  const approximate = bridge.descriptor.payload.fidelity === "approximate";
  const preserved =
    !approximate && sourceEvaluation !== "indeterminate" && sourceEvaluation === targetEvaluation;
  const outcome = approximate ? "approximate" : preserved ? "preserved" : "invalid";
  const diagnostics =
    preserved || approximate
      ? []
      : [
          {
            code: "SATISFACTION_NOT_PRESERVED",
            message: `Source evaluated ${sourceEvaluation}; target evaluated ${targetEvaluation}`,
            paths: ["payload.sentence"],
          },
        ];
  const approximation = bridge.descriptor.payload.approximation;

  return {
    translatedClaim: translated.value,
    witness: sealArtifact({
      kind: "TranslationWitness",
      protocolVersion: "0.1",
      ...witnessMetadata(bridge, sourceClaim),
      payloadMediaType: "application/vnd.lighthouse.translation-witness+json",
      payload: {
        sourceClaimDigest: sourceClaim.digest,
        targetClaimDigest: translated.value.digest,
        sourceSnapshotDigests: [sourceSnapshot.digest],
        targetSnapshotDigests: [targetSnapshot.digest],
        bridgeDigest: bridge.descriptor.digest,
        bridgeLineage: lineage,
        outcome,
        mappedPaths: ["payload.signature", "payload.context", "payload.sentence"],
        unmappedPaths: [],
        sourceEvaluation,
        targetEvaluation,
        evidenceDigests: [sourceSnapshot.digest, targetSnapshot.digest],
        ...(approximation === undefined ? {} : { approximation }),
        diagnostics,
      },
    }),
  };
}
