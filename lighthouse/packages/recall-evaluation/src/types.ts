import type {
  ConnectionPolicy,
  ContextRef,
  Digest,
  RecallReceipt,
  Snapshot,
} from "@lighthouse/protocol";

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

export type RecallDenialCode = "EXPLICIT_DENY" | "NO_MATCHING_ALLOW" | "OUTSIDE_VALIDITY";

export type RecallSourceDecision =
  | {
      publisher: string;
      role: "local";
      allowed: true;
      ruleId: "local:self";
    }
  | {
      publisher: string;
      role: "remote";
      allowed: true;
      ruleId: string;
    }
  | {
      publisher: string;
      role: "remote";
      allowed: false;
      code: RecallDenialCode;
      ruleId?: string | undefined;
    };

export interface RecallSourceAdmission {
  publisher: string;
  trace: "matched" | "absent" | "context-mismatch";
  admission: "admitted" | "mode-excluded" | "policy-denied" | "zero-weight" | "trace-unavailable";
  candidateCount: number;
}

export interface RecallTurnReport {
  turnId: string;
  selected: FusedCandidate[];
  metrics: RecallMetrics;
  decisions: RecallSourceDecision[];
  admissions: RecallSourceAdmission[];
  receipt: RecallReceipt;
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
