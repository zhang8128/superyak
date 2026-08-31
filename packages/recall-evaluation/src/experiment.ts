import {
  ENGRAM_PROFILE,
  ENGRAM_RECALL_RANK_CLAIM_MEDIA_TYPE,
  engramModel,
} from "@lighthouse/adapter-engram";
import { evaluateConnectionPolicy } from "@lighthouse/calculus";
import { digestJson, type JsonValue } from "@lighthouse/protocol";
import { fuseRankings } from "./fusion.js";
import { measureTurn } from "./metrics.js";
import { sealRecallReceipt } from "./receipt.js";
import type {
  RankedContribution,
  RecallExperimentInput,
  RecallExperimentMode,
  RecallExperimentReport,
  RecallExperimentReportContent,
  RecallMetrics,
  RecallModeReport,
  RecallSelectionReceiptContent,
  RecallSource,
  RecallSourceDecision,
  RecallTurnJudgment,
  RecallTurnReport,
} from "./types.js";

const modes: RecallExperimentMode[] = ["local-only", "policy-scoped", "indiscriminate-control"];

function samePath(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((segment, index) => right[index] === segment);
}

function validateAndSortSources(input: RecallExperimentInput): RecallSource[] {
  const publishers = new Set<string>();
  return input.sources
    .map((source) => {
      if (!Number.isFinite(source.weight) || source.weight < 0) {
        throw new Error(`INVALID_SOURCE_WEIGHT: ${String(source.weight)}`);
      }
      if (source.role === "local" && source.snapshot.issuer !== input.receiverPublisher) {
        throw new Error(`LOCAL_PUBLISHER_MISMATCH: ${source.snapshot.issuer}`);
      }
      if (publishers.has(source.snapshot.issuer)) {
        throw new Error(`DUPLICATE_SOURCE_PUBLISHER: ${source.snapshot.issuer}`);
      }
      publishers.add(source.snapshot.issuer);
      if (engramModel(source.snapshot) === undefined) {
        throw new Error(`INVALID_ENGRAM_SNAPSHOT: ${source.snapshot.id}`);
      }
      return source;
    })
    .sort(
      (left, right) =>
        left.snapshot.issuer.localeCompare(right.snapshot.issuer) ||
        left.snapshot.digest.value.localeCompare(right.snapshot.digest.value),
    );
}

function decisionFor(
  input: RecallExperimentInput,
  source: RecallSource,
  turn: RecallTurnJudgment,
): RecallSourceDecision {
  if (source.role === "local") {
    return {
      publisher: source.snapshot.issuer,
      role: source.role,
      allowed: true,
      ruleId: "local:self",
    };
  }
  const decision = evaluateConnectionPolicy(input.policy, {
    publisher: source.snapshot.issuer,
    profile: ENGRAM_PROFILE.id,
    domain: "memory.recall",
    action: "recall",
    context: turn.context.id,
    claimMediaType: ENGRAM_RECALL_RANK_CLAIM_MEDIA_TYPE,
    purpose: turn.purpose,
    audience: "self",
    at: input.issuedAt,
    evidence: [],
    attestations: [],
  });
  return {
    publisher: source.snapshot.issuer,
    role: source.role,
    allowed: decision.allowed,
    ...(decision.allowed ? { ruleId: decision.ruleId } : { code: decision.code }),
    ...(!decision.allowed && decision.ruleId !== undefined ? { ruleId: decision.ruleId } : {}),
  };
}

function includeSource(
  mode: RecallExperimentMode,
  source: RecallSource,
  decision: RecallSourceDecision,
): boolean {
  if (mode === "indiscriminate-control") return true;
  if (source.role === "local") return true;
  return mode === "policy-scoped" && decision.allowed;
}

function contributionsFor(
  mode: RecallExperimentMode,
  source: RecallSource,
  turn: RecallTurnJudgment,
): RankedContribution[] {
  const model = engramModel(source.snapshot);
  if (model === undefined) return [];
  const memories = new Map(model.memories.map((memory) => [memory.id, memory]));
  return model.recallTraces
    .filter(
      (trace) =>
        trace.turnId === turn.turnId &&
        (mode === "indiscriminate-control" || samePath(trace.contextPath, turn.context.path)),
    )
    .flatMap((trace) =>
      trace.candidates.flatMap((candidate) => {
        const memory = memories.get(candidate.memoryId);
        if (memory === undefined) return [];
        return [
          {
            ref: { publisher: source.snapshot.issuer, memoryId: memory.id },
            contentDigest: memory.contentDigest,
            sourceSnapshotDigest: source.snapshot.digest,
            rank: candidate.rank,
            sourceWeight: source.weight,
          },
        ];
      }),
    );
}

function sortedDecisions(decisions: RecallSourceDecision[]): RecallSourceDecision[] {
  return decisions.toSorted((left, right) => left.publisher.localeCompare(right.publisher));
}

function receiptContent(
  input: RecallExperimentInput,
  mode: RecallExperimentMode,
  turn: RecallTurnJudgment,
  sources: RecallSource[],
  decisions: RecallSourceDecision[],
  selected: ReturnType<typeof fuseRankings>,
): RecallSelectionReceiptContent {
  return {
    kind: "RecallSelectionReceipt",
    version: "0.1",
    experimentId: input.id,
    issuedAt: input.issuedAt,
    mode,
    turnId: turn.turnId,
    action: "recall",
    injected: false,
    purpose: turn.purpose,
    context: turn.context,
    transformation: "weighted-rrf-v1",
    selected,
    sources: sources.map((source) => ({
      publisher: source.snapshot.issuer,
      snapshotDigest: source.snapshot.digest,
      weight: source.weight,
    })),
    decisions: sortedDecisions(decisions),
  };
}

function runTurn(
  input: RecallExperimentInput,
  mode: RecallExperimentMode,
  sources: RecallSource[],
  turn: RecallTurnJudgment,
): RecallTurnReport {
  const decisions = sortedDecisions(sources.map((source) => decisionFor(input, source, turn)));
  const byPublisher = new Map(decisions.map((decision) => [decision.publisher, decision]));
  const contributions = sources.flatMap((source) => {
    const decision = byPublisher.get(source.snapshot.issuer);
    return decision !== undefined && includeSource(mode, source, decision)
      ? contributionsFor(mode, source, turn)
      : [];
  });
  const selected = fuseRankings(contributions, input.k);
  const authorizedPublishers = Object.fromEntries(
    decisions.map((decision) => [decision.publisher, decision.allowed]),
  );
  const metrics = measureTurn(selected, turn, {
    k: input.k,
    receiverPublisher: input.receiverPublisher,
    authorizedPublishers,
  });
  return {
    turnId: turn.turnId,
    selected,
    metrics,
    decisions,
    receipt: sealRecallReceipt(receiptContent(input, mode, turn, sources, decisions, selected)),
  };
}

function aggregateMetrics(turns: RecallTurnReport[]): RecallMetrics {
  const count = turns.length;
  return {
    rightTurnRecallAtK:
      turns.reduce((total, turn) => total + turn.metrics.rightTurnRecallAtK, 0) / count,
    ndcgAtK: turns.reduce((total, turn) => total + turn.metrics.ndcgAtK, 0) / count,
    forbiddenExposureAtK: turns.reduce(
      (total, turn) => total + turn.metrics.forbiddenExposureAtK,
      0,
    ),
    unauthorizedSelectionCount: turns.reduce(
      (total, turn) => total + turn.metrics.unauthorizedSelectionCount,
      0,
    ),
  };
}

function modeReport(
  input: RecallExperimentInput,
  mode: RecallExperimentMode,
  sources: RecallSource[],
  turns: RecallTurnJudgment[],
): RecallModeReport {
  const turnReports = turns.map((turn) => runTurn(input, mode, sources, turn));
  return {
    mode,
    unsafe: mode === "indiscriminate-control",
    turns: turnReports,
    metrics: aggregateMetrics(turnReports),
  };
}

export function runRecallExperiment(input: RecallExperimentInput): RecallExperimentReport {
  if (input.turns.length === 0) throw new Error("EMPTY_EXPERIMENT_TURNS");
  const sources = validateAndSortSources(input);
  const turns = input.turns.toSorted((left, right) =>
    `${left.turnId}\u0000${left.context.id}`.localeCompare(
      `${right.turnId}\u0000${right.context.id}`,
    ),
  );
  const content: RecallExperimentReportContent = {
    kind: "RecallExperimentReport",
    version: "0.1",
    id: input.id,
    issuedAt: input.issuedAt,
    receiverPublisher: input.receiverPublisher,
    k: input.k,
    modes: modes.map((mode) => modeReport(input, mode, sources, turns)),
  };
  return { ...content, digest: digestJson(content as unknown as JsonValue) };
}
