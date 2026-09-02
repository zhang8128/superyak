import { type EngramModel, parseEngramExport } from "@lighthouse/adapter-engram";
import {
  compareCanonicalJson,
  type Digest,
  digestJson,
  type JsonValue,
  type RecallReceipt,
} from "@lighthouse/protocol";
import { bootstrapInterval, type Interval } from "./bootstrap.js";
import type { LabelsDocument } from "./labels.js";
import { measureTurn } from "./metrics.js";
import type { Preregistration } from "./preregistration.js";
import type { FusedCandidate, RecallMetrics, RecallTurnJudgment } from "./types.js";

export interface ShadowModeMetrics extends RecallMetrics {
  bootstrap: {
    samples: number;
    seed: number;
    rightTurnRecallAtK: Interval;
    ndcgAtK: Interval;
  };
}

export interface RecallShadowReportContent {
  kind: "RecallShadowReport";
  protocolVersion: "0.1";
  issuedAt: string;
  instance: string;
  receiverPublisher: string;
  preregistrationDigest: Digest;
  corpusDigest: Digest;
  cutoff: number;
  holdout: { turns: number; receipts: number; localOnlyTurns: number };
  modes: { "local-only": ShadowModeMetrics; "policy-scoped": ShadowModeMetrics };
  receiptDigests: string[];
}

export interface RecallShadowReport extends RecallShadowReportContent {
  digest: Digest;
}

export interface ShadowEvaluationInput {
  exportDocument: unknown;
  labels: LabelsDocument;
  preregistration: Preregistration;
  issuedAt: string;
}

function samePath(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((segment, index) => right[index] === segment);
}

function localCandidates(
  model: EngramModel,
  turn: RecallTurnJudgment,
  receiverPublisher: string,
): FusedCandidate[] {
  const traces = model.recallTraces.filter((trace) => trace.turnId === turn.turnId);
  if (traces.length === 0) throw new Error(`HOLDOUT_TURN_MISSING_TRACE: ${turn.turnId}`);
  const trace = traces.find((candidate) => samePath(candidate.contextPath, turn.context.path));
  if (trace === undefined) throw new Error(`HOLDOUT_TURN_CONTEXT_MISMATCH: ${turn.turnId}`);
  const memories = new Map(model.memories.map((memory) => [memory.id, memory]));
  return trace.candidates.map((candidate) => {
    const memory = memories.get(candidate.memoryId);
    if (memory === undefined) throw new Error(`DANGLING_CANDIDATE: ${candidate.memoryId}`);
    return {
      ref: { publisher: receiverPublisher, memoryId: candidate.memoryId },
      contentDigest: { algorithm: "sha256", value: memory.contentDigest.value },
      score: 1 / (60 + candidate.rank),
      contributions: [],
    };
  });
}

function verifyReceiptScores(receipt: RecallReceipt): void {
  const weights = new Map(
    receipt.payload.sources.map((source) => [source.publisher, source.weight]),
  );
  for (const item of receipt.payload.selected) {
    let expected = 0;
    for (const contribution of item.contributions) {
      const weight = weights.get(contribution.publisher);
      if (weight === undefined) throw new Error(`RECEIPT_SCORE_MISMATCH: ${item.memoryId}`);
      expected += weight / (60 + contribution.rank);
    }
    if (Math.abs(expected - item.score) > 1e-9) {
      throw new Error(`RECEIPT_SCORE_MISMATCH: ${item.memoryId}`);
    }
  }
}

function scopedCandidates(receipt: RecallReceipt): FusedCandidate[] {
  verifyReceiptScores(receipt);
  return receipt.payload.selected.map((item) => ({
    ref: { publisher: item.publisher, memoryId: item.memoryId },
    contentDigest: { algorithm: "sha256", value: item.contentDigest.value },
    score: item.score,
    contributions: [],
  }));
}

function authorized(receipt: RecallReceipt | undefined): Record<string, boolean> {
  if (receipt === undefined) return {};
  return Object.fromEntries(
    receipt.payload.sources.map((source) => [
      source.publisher,
      source.policyDecision.effect === "allow",
    ]),
  );
}

function aggregate(perTurn: RecallMetrics[], samples: number, seed: number): ShadowModeMetrics {
  const count = perTurn.length;
  const recalls = perTurn.map((metrics) => metrics.rightTurnRecallAtK);
  const ndcgs = perTurn.map((metrics) => metrics.ndcgAtK);
  return {
    rightTurnRecallAtK: recalls.reduce((total, value) => total + value, 0) / count,
    ndcgAtK: ndcgs.reduce((total, value) => total + value, 0) / count,
    forbiddenExposureAtK: perTurn.reduce(
      (total, metrics) => total + metrics.forbiddenExposureAtK,
      0,
    ),
    unauthorizedSelectionCount: perTurn.reduce(
      (total, metrics) => total + metrics.unauthorizedSelectionCount,
      0,
    ),
    bootstrap: {
      samples,
      seed,
      rightTurnRecallAtK: bootstrapInterval(recalls, samples, seed),
      ndcgAtK: bootstrapInterval(ndcgs, samples, seed + 1),
    },
  };
}

export function exportCorpusDigest(exportDocument: unknown): Digest {
  return digestJson(parseEngramExport(exportDocument) as unknown as JsonValue);
}

export function runShadowEvaluation(input: ShadowEvaluationInput): RecallShadowReport {
  const model = parseEngramExport(input.exportDocument);
  const corpusDigest = digestJson(model as unknown as JsonValue);
  const { preregistration } = input;
  if (
    corpusDigest.algorithm !== preregistration.corpusDigest.algorithm ||
    corpusDigest.value !== preregistration.corpusDigest.value
  ) {
    throw new Error("CORPUS_DIGEST_MISMATCH");
  }
  if (preregistration.holdoutTurnIds.length === 0) throw new Error("EMPTY_HOLDOUT");
  const labelsByTurn = new Map(input.labels.turns.map((turn) => [turn.turnId, turn]));
  const receiptsByTurn = new Map<string, RecallReceipt[]>();
  for (const receipt of model.receipts) {
    const receipts = receiptsByTurn.get(receipt.payload.turnId) ?? [];
    receipts.push(receipt);
    receiptsByTurn.set(receipt.payload.turnId, receipts);
  }
  const localOnly: RecallMetrics[] = [];
  const scoped: RecallMetrics[] = [];
  const usedReceipts: RecallReceipt[] = [];
  let localOnlyTurns = 0;
  for (const turnId of preregistration.holdoutTurnIds) {
    const turn = labelsByTurn.get(turnId);
    if (turn === undefined) throw new Error(`HOLDOUT_TURN_UNLABELED: ${turnId}`);
    const local = localCandidates(model, turn, preregistration.receiverPublisher);
    const turnReceipts = receiptsByTurn.get(turnId) ?? [];
    const receipt = turnReceipts.find(
      (candidate) =>
        candidate.payload.context.id === turn.context.id &&
        samePath(candidate.payload.context.path, turn.context.path),
    );
    if (receipt === undefined && turnReceipts.length > 0) {
      throw new Error(`HOLDOUT_TURN_CONTEXT_MISMATCH: ${turnId}`);
    }
    const options = {
      k: preregistration.cutoff,
      receiverPublisher: preregistration.receiverPublisher,
      authorizedPublishers: authorized(receipt),
    };
    localOnly.push(measureTurn(local, turn, { ...options, authorizedPublishers: {} }));
    if (receipt === undefined) {
      localOnlyTurns += 1;
      scoped.push(measureTurn(local, turn, { ...options, authorizedPublishers: {} }));
      continue;
    }
    usedReceipts.push(receipt);
    scoped.push(measureTurn(scopedCandidates(receipt), turn, options));
  }
  const { samples, seed } = preregistration.bootstrap;
  const content: RecallShadowReportContent = {
    kind: "RecallShadowReport",
    protocolVersion: "0.1",
    issuedAt: input.issuedAt,
    instance: model.instance,
    receiverPublisher: preregistration.receiverPublisher,
    preregistrationDigest: digestJson(preregistration as unknown as JsonValue),
    corpusDigest,
    cutoff: preregistration.cutoff,
    holdout: {
      turns: preregistration.holdoutTurnIds.length,
      receipts: usedReceipts.length,
      localOnlyTurns,
    },
    modes: {
      "local-only": aggregate(localOnly, samples, seed),
      "policy-scoped": aggregate(scoped, samples, seed),
    },
    receiptDigests: usedReceipts
      .map((receipt) => receipt.digest.value)
      .toSorted(compareCanonicalJson),
  };
  return { ...content, digest: digestJson(content as unknown as JsonValue) };
}
