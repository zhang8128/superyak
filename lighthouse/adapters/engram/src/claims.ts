import {
  type Claim,
  type ContextRef,
  type JsonValue,
  type ProfileRef,
  type SignatureRef,
  type Snapshot,
  sealArtifact,
} from "@lighthouse/protocol";
import { parseEngramExport } from "./export.js";

export const ENGRAM_PROFILE = {
  id: "urn:lighthouse:profile:engram-recall-trace",
  version: "1.0.0",
} satisfies ProfileRef;

export const ENGRAM_SIGNATURE = {
  id: "urn:lighthouse:signature:engram-recall-trace",
  version: "1.0.0",
} satisfies SignatureRef;

export const ENGRAM_RECALL_RANK_CLAIM_MEDIA_TYPE = "application/vnd.engram.recall-rank-claim+json";

export interface EngramRankClaimInput {
  turnId: string;
  memoryId: string;
  maxRank: number;
}

function asRecord(value: JsonValue): Record<string, JsonValue> | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, JsonValue>)
    : undefined;
}

export function parseEngramRankSentence(value: JsonValue): EngramRankClaimInput | undefined {
  const record = asRecord(value);
  if (
    typeof record?.turnId !== "string" ||
    record.turnId.length === 0 ||
    typeof record.memoryId !== "string" ||
    record.memoryId.length === 0 ||
    typeof record.maxRank !== "number" ||
    !Number.isInteger(record.maxRank) ||
    record.maxRank < 1
  ) {
    return undefined;
  }
  return {
    turnId: record.turnId,
    memoryId: record.memoryId,
    maxRank: record.maxRank,
  };
}

function claimContext(snapshot: Snapshot, turnId: string): ContextRef {
  const model = parseEngramExport(snapshot.payload.model);
  const trace = model.recallTraces.find((candidate) => candidate.turnId === turnId);
  return trace === undefined
    ? snapshot.payload.context
    : { id: trace.contextPath.join("/"), path: trace.contextPath };
}

export function createEngramRankClaim(snapshot: Snapshot, input: EngramRankClaimInput): Claim {
  if (
    snapshot.payload.profile.id !== ENGRAM_PROFILE.id ||
    snapshot.payload.profile.version !== ENGRAM_PROFILE.version
  ) {
    throw new Error("PROFILE_MISMATCH: expected an Engram recall trace snapshot");
  }
  return sealArtifact({
    kind: "Claim",
    protocolVersion: "0.1",
    id: "urn:claim:engram-recall-rank",
    issuedAt: snapshot.issuedAt,
    issuer: snapshot.issuer,
    payloadMediaType: "application/vnd.lighthouse.claim+json",
    payload: {
      profile: ENGRAM_PROFILE,
      signature: snapshot.payload.signature,
      context: claimContext(snapshot, input.turnId),
      sentenceMediaType: ENGRAM_RECALL_RANK_CLAIM_MEDIA_TYPE,
      sentence: input as unknown as JsonValue,
      snapshotDigests: [snapshot.digest],
      provenance: [],
    },
  });
}
