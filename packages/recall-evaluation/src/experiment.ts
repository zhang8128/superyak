import {
  ENGRAM_PROFILE,
  ENGRAM_RECALL_RANK_CLAIM_MEDIA_TYPE,
  engramModel,
} from "@lighthouse/adapter-engram";
import { evaluateConnectionPolicy } from "@lighthouse/calculus";
import { compareCanonicalJson, digestJson, type JsonValue } from "@lighthouse/protocol";
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
  RecallSourceAdmission,
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
        compareCanonicalJson(left.snapshot.issuer, right.snapshot.issuer) ||
        compareCanonicalJson(left.snapshot.digest.value, right.snapshot.digest.value),
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
  if (decision.allowed) {
    return {
      publisher: source.snapshot.issuer,
      role: "remote",
      allowed: true,
      ruleId: decision.ruleId,
    };
  }
  return {
    publisher: source.snapshot.issuer,
    role: "remote",
    allowed: false,
    code: decision.code,
    ...(decision.ruleId === undefined ? {} : { ruleId: decision.ruleId }),
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

interface SourceTraceResult {
  trace: RecallSourceAdmission["trace"];
  contributions: RankedContribution[];
}

function traceResultFor(
  mode: RecallExperimentMode,
  source: RecallSource,
  turn: RecallTurnJudgment,
): SourceTraceResult {
  const model = engramModel(source.snapshot);
  if (model === undefined) return { trace: "absent", contributions: [] };
  const memories = new Map(model.memories.map((memory) => [memory.id, memory]));
  const turnTraces = model.recallTraces.filter((trace) => trace.turnId === turn.turnId);
  if (turnTraces.length === 0) return { trace: "absent", contributions: [] };
  const matchingTraces =
    mode === "indiscriminate-control"
      ? turnTraces
      : turnTraces.filter((trace) => samePath(trace.contextPath, turn.context.path));
  if (matchingTraces.length === 0) {
    return { trace: "context-mismatch", contributions: [] };
  }
  const contributions = matchingTraces.flatMap((trace) =>
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
  return { trace: "matched", contributions };
}

function sourceAdmission(
  mode: RecallExperimentMode,
  source: RecallSource,
  decision: RecallSourceDecision,
  traceResult: SourceTraceResult,
): RecallSourceAdmission {
  let admission: RecallSourceAdmission["admission"];
  if (!includeSource(mode, source, decision)) {
    admission =
      mode === "policy-scoped" && source.role === "remote" && !decision.allowed
        ? "policy-denied"
        : "mode-excluded";
  } else if (source.weight === 0) {
    admission = "zero-weight";
  } else if (traceResult.trace !== "matched") {
    admission = "trace-unavailable";
  } else {
    admission = "admitted";
  }
  return {
    publisher: source.snapshot.issuer,
    trace: traceResult.trace,
    admission,
    candidateCount: traceResult.contributions.length,
  };
}

function sortedDecisions(decisions: RecallSourceDecision[]): RecallSourceDecision[] {
  return decisions.toSorted((left, right) => compareCanonicalJson(left.publisher, right.publisher));
}

function sortedAdmissions(admissions: RecallSourceAdmission[]): RecallSourceAdmission[] {
  return admissions.toSorted((left, right) =>
    compareCanonicalJson(left.publisher, right.publisher),
  );
}

function receiptContent(
  input: RecallExperimentInput,
  mode: RecallExperimentMode,
  turn: RecallTurnJudgment,
  sources: RecallSource[],
  decisions: RecallSourceDecision[],
  admissions: RecallSourceAdmission[],
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
    admissions: sortedAdmissions(admissions),
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
  const sourceResults = sources.map((source) => {
    const decision = byPublisher.get(source.snapshot.issuer);
    if (decision === undefined)
      throw new Error(`MISSING_SOURCE_DECISION: ${source.snapshot.issuer}`);
    const traceResult = traceResultFor(mode, source, turn);
    const admission = sourceAdmission(mode, source, decision, traceResult);
    return { admission, contributions: traceResult.contributions };
  });
  const admissions = sortedAdmissions(sourceResults.map(({ admission }) => admission));
  const contributions = sourceResults.flatMap(({ admission, contributions }) =>
    admission.admission === "admitted" ? contributions : [],
  );
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
    admissions,
    receipt: sealRecallReceipt(
      receiptContent(input, mode, turn, sources, decisions, admissions, selected),
    ),
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
  const turnKeys = new Set<string>();
  for (const turn of input.turns) {
    const key = JSON.stringify([turn.turnId, turn.context.id]);
    if (turnKeys.has(key)) throw new Error(`DUPLICATE_EXPERIMENT_TURN: ${turn.turnId}`);
    turnKeys.add(key);
  }
  const turns = input.turns.toSorted((left, right) =>
    compareCanonicalJson([left.turnId, left.context.id], [right.turnId, right.context.id]),
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
