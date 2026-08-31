import type { ContextRef, Digest, Snapshot } from "@lighthouse/protocol";

export interface MemoryRef {
  publisher: string;
  memoryId: string;
}

export interface RecallSource {
  snapshot: Snapshot;
  role: "local" | "remote";
  weight: number;
}

export interface RecallTurnJudgment {
  turnId: string;
  context: ContextRef;
  purpose: string;
  relevant: MemoryRef[];
  forbidden: MemoryRef[];
}

export interface RankedContribution {
  ref: MemoryRef;
  contentDigest: Digest;
  sourceSnapshotDigest: Digest;
  rank: number;
  sourceWeight: number;
}

export interface FusedCandidate {
  ref: MemoryRef;
  contentDigest: Digest;
  score: number;
  contributions: RankedContribution[];
}

export interface RecallMetrics {
  rightTurnRecallAtK: number;
  ndcgAtK: number;
  forbiddenExposureAtK: number;
  unauthorizedSelectionCount: number;
}

export interface MeasurementOptions {
  k: number;
  receiverPublisher: string;
  authorizedPublishers: Record<string, boolean>;
}
