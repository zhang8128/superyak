import { canonicalize, type JsonValue } from "@lighthouse/protocol";
import type { FusedCandidate, MemoryRef, RankedContribution } from "./types.js";

export function memoryRefKey(ref: MemoryRef): string {
  return canonicalize(ref as unknown as JsonValue);
}

function validateContribution(contribution: RankedContribution): void {
  if (!Number.isFinite(contribution.sourceWeight) || contribution.sourceWeight < 0) {
    throw new Error(`INVALID_SOURCE_WEIGHT: ${String(contribution.sourceWeight)}`);
  }
  if (!Number.isInteger(contribution.rank) || contribution.rank < 1) {
    throw new Error(`INVALID_SOURCE_RANK: ${String(contribution.rank)}`);
  }
}

function contributionKey(contribution: RankedContribution): string {
  return canonicalize({
    ref: contribution.ref,
    rank: contribution.rank,
    sourceSnapshotDigest: contribution.sourceSnapshotDigest,
    sourceWeight: contribution.sourceWeight,
  } as unknown as JsonValue);
}

export function fuseRankings(inputs: RankedContribution[], k: number): FusedCandidate[] {
  if (!Number.isInteger(k) || k < 1) throw new Error(`INVALID_RESULT_LIMIT: ${String(k)}`);

  const candidates = new Map<string, FusedCandidate>();
  for (const contribution of inputs) {
    validateContribution(contribution);
    if (contribution.sourceWeight === 0) continue;
    const key = memoryRefKey(contribution.ref);
    const current = candidates.get(key);
    if (current === undefined) {
      candidates.set(key, {
        ref: contribution.ref,
        contentDigest: contribution.contentDigest,
        score: contribution.sourceWeight / (60 + contribution.rank),
        contributions: [contribution],
      });
      continue;
    }
    if (
      current.contentDigest.algorithm !== contribution.contentDigest.algorithm ||
      current.contentDigest.value !== contribution.contentDigest.value
    ) {
      throw new Error(`MEMORY_DIGEST_CONFLICT: ${key}`);
    }
    current.score += contribution.sourceWeight / (60 + contribution.rank);
    current.contributions.push(contribution);
  }

  return [...candidates.values()]
    .map((candidate) => ({
      ...candidate,
      contributions: candidate.contributions.toSorted((left, right) =>
        contributionKey(left).localeCompare(contributionKey(right)),
      ),
    }))
    .sort(
      (left, right) =>
        right.score - left.score || memoryRefKey(left.ref).localeCompare(memoryRefKey(right.ref)),
    )
    .slice(0, k);
}
