import {
  type ContextRef,
  type Digest,
  type JsonValue,
  type PolicyDecisionRecord,
  parseArtifact,
  type RecallReceipt,
  recallReceiptSchema,
  sealArtifact,
  verifyArtifactDigest,
} from "@lighthouse/protocol";
import type { RecallExperimentMode } from "./types.js";

export interface ReceiptSourceInput {
  publisher: string;
  role: "local" | "remote";
  weight: number;
  storeDigest: { algorithm: "sha256"; value: string };
  policyDecision: PolicyDecisionRecord;
  traceOutcome: "matched" | "absent" | "context-mismatched" | "unavailable" | "policy-denied";
}

export interface ReceiptSelectedInput {
  publisher: string;
  memoryId: string;
  contentDigest: { algorithm: "sha256"; value: string };
  score: number;
  contributions: Array<{ publisher: string; rank: number }>;
}

export interface ReceiptDeliveredInput {
  publisher: string;
  memoryId: string;
  readDecision: PolicyDecisionRecord;
}

export interface RecallReceiptBuildInput {
  id: string;
  issuedAt: string;
  issuer: string;
  experimentId?: string | undefined;
  mode?: RecallExperimentMode | undefined;
  turnId: string;
  context: ContextRef;
  purpose: string;
  injected?: boolean | undefined;
  receiverRuleId: string | null;
  sources: ReceiptSourceInput[];
  selected: ReceiptSelectedInput[];
  delivered: ReceiptDeliveredInput[];
}

export type RecallReceiptVerification =
  | { ok: true }
  | { ok: false; code: "INVALID_RECEIPT" | "DIGEST_MISMATCH" };

export function buildRecallReceipt(input: RecallReceiptBuildInput): RecallReceipt {
  const extensions: { [key: string]: JsonValue } = {};
  if (input.experimentId !== undefined && input.mode !== undefined) {
    extensions["lighthouse:experiment"] = { experimentId: input.experimentId, mode: input.mode };
  }
  return sealArtifact({
    kind: "RecallReceipt",
    protocolVersion: "0.1",
    id: input.id,
    issuedAt: input.issuedAt,
    issuer: input.issuer,
    payloadMediaType: "application/vnd.lighthouse.recall-receipt+json",
    ...(Object.keys(extensions).length === 0 ? {} : { extensions }),
    payload: {
      turnId: input.turnId,
      context: input.context,
      purpose: input.purpose,
      audience: "self",
      action: "recall",
      injected: input.injected ?? input.delivered.length > 0,
      transformation: "weighted-rrf-v1",
      receiverRule: { ruleId: input.receiverRuleId },
      sources: input.sources,
      selected: input.selected,
      delivered: input.delivered,
    },
  });
}

export function parseRecallReceipt(input: unknown): RecallReceipt {
  return recallReceiptSchema.parse(input);
}

export function verifyRecallReceiptDigest(input: unknown): RecallReceiptVerification {
  const parsed = recallReceiptSchema.safeParse(input);
  if (!parsed.success) return { ok: false, code: "INVALID_RECEIPT" };
  const artifact = parseArtifact(parsed.data);
  return verifyArtifactDigest(artifact).ok ? { ok: true } : { ok: false, code: "DIGEST_MISMATCH" };
}

export function receiptDigest(receipt: RecallReceipt): Digest {
  return receipt.digest;
}
