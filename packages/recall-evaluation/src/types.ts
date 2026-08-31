import type { ConnectionPolicy, ContextRef, Digest, Snapshot } from "@lighthouse/protocol";

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

export type RecallExperimentMode = "local-only" | "policy-scoped" | "indiscriminate-control";

export interface RecallSourceDecision {
  publisher: string;
  role: RecallSource["role"];
  allowed: boolean;
  ruleId?: string;
  code?: string;
}

export interface RecallSelectionReceiptContent {
  kind: "RecallSelectionReceipt";
  version: "0.1";
  experimentId: string;
  issuedAt: string;
  mode: RecallExperimentMode;
  turnId: string;
  action: "recall";
  injected: false;
  purpose: string;
  context: ContextRef;
  transformation: "weighted-rrf-v1";
  selected: FusedCandidate[];
  sources: Array<{
    publisher: string;
    snapshotDigest: Digest;
    weight: number;
  }>;
  decisions: RecallSourceDecision[];
}

export interface RecallSelectionReceipt extends RecallSelectionReceiptContent {
  digest: Digest;
}

export interface RecallTurnReport {
  turnId: string;
  selected: FusedCandidate[];
  metrics: RecallMetrics;
  decisions: RecallSourceDecision[];
  receipt: RecallSelectionReceipt;
}

export interface RecallModeReport {
  mode: RecallExperimentMode;
  unsafe: boolean;
  turns: RecallTurnReport[];
  metrics: RecallMetrics;
}

export interface RecallExperimentReportContent {
  kind: "RecallExperimentReport";
  version: "0.1";
  id: string;
  issuedAt: string;
  receiverPublisher: string;
  k: number;
  modes: RecallModeReport[];
}

export interface RecallExperimentReport extends RecallExperimentReportContent {
  digest: Digest;
}

export interface RecallExperimentInput {
  id: string;
  issuedAt: string;
  receiverPublisher: string;
  k: number;
  policy: ConnectionPolicy;
  sources: RecallSource[];
  turns: RecallTurnJudgment[];
}
