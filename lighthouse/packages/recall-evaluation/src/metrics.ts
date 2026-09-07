import { memoryRefKey } from "./fusion.js";
import type {
  FusedCandidate,
  MeasurementOptions,
  RecallMetrics,
  RecallTurnJudgment,
} from "./types.js";

function discountedGain(relevantAtRank: boolean, zeroBasedRank: number): number {
  return relevantAtRank ? 1 / Math.log2(zeroBasedRank + 2) : 0;
}

export function measureTurn(
  selected: FusedCandidate[],
  judgment: RecallTurnJudgment,
  options: MeasurementOptions,
): RecallMetrics {
  if (!Number.isInteger(options.k) || options.k < 1) {
    throw new Error(`INVALID_RESULT_LIMIT: ${String(options.k)}`);
  }
  const relevant = new Set(judgment.relevant.map(memoryRefKey));
  if (relevant.size === 0) throw new Error(`EMPTY_RELEVANCE_JUDGMENT: ${judgment.turnId}`);
  const forbidden = new Set(judgment.forbidden.map(memoryRefKey));
  const topK = selected.slice(0, options.k);
  const selectedRelevant = topK.filter((candidate) =>
    relevant.has(memoryRefKey(candidate.ref)),
  ).length;
  const dcg = topK.reduce(
    (total, candidate, index) =>
      total + discountedGain(relevant.has(memoryRefKey(candidate.ref)), index),
    0,
  );
  const idealHits = Math.min(options.k, relevant.size);
  let idcg = 0;
  for (let index = 0; index < idealHits; index += 1) idcg += discountedGain(true, index);

  return {
    rightTurnRecallAtK: selectedRelevant / relevant.size,
    ndcgAtK: idcg === 0 ? 0 : dcg / idcg,
    forbiddenExposureAtK: topK.filter((candidate) => forbidden.has(memoryRefKey(candidate.ref)))
      .length,
    unauthorizedSelectionCount: topK.filter(
      (candidate) =>
        candidate.ref.publisher !== options.receiverPublisher &&
        options.authorizedPublishers[candidate.ref.publisher] !== true,
    ).length,
  };
}
