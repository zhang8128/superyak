import type { Digest } from "@lighthouse/protocol";
import { describe, expect, it } from "vitest";
import {
  type FusedCandidate,
  type MemoryRef,
  measureTurn,
  type RecallTurnJudgment,
} from "../src/index.js";

const digest: Digest = { algorithm: "sha256", value: "d".repeat(64) };

function ref(publisher: string, memoryId: string): MemoryRef {
  return { publisher, memoryId };
}

function candidate(memoryRef: MemoryRef, score: number): FusedCandidate {
  return {
    ref: memoryRef,
    contentDigest: digest,
    score,
    contributions: [
      {
        ref: memoryRef,
        contentDigest: digest,
        sourceSnapshotDigest: digest,
        rank: 1,
        sourceWeight: 1,
      },
    ],
  };
}

function judgment(relevant: MemoryRef[], forbidden: MemoryRef[] = []): RecallTurnJudgment {
  return {
    turnId: "turn-1",
    context: { id: "memory/debugging", path: ["memory", "debugging"] },
    purpose: "debugging",
    relevant,
    forbidden,
  };
}

describe("receiver-owned recall metrics", () => {
  it("measures relevance position, forbidden exposure, and unauthorized selection", () => {
    const relevantA = ref("urn:local", "relevant-a");
    const forbidden = ref("urn:stranger", "forbidden");
    const relevantB = ref("urn:crew", "relevant-b");
    const metrics = measureTurn(
      [candidate(relevantA, 3), candidate(forbidden, 2), candidate(relevantB, 1)],
      judgment([relevantA, relevantB], [forbidden]),
      {
        k: 3,
        receiverPublisher: "urn:local",
        authorizedPublishers: { "urn:crew": true, "urn:stranger": false },
      },
    );

    expect(metrics.rightTurnRecallAtK).toBe(1);
    expect(metrics.ndcgAtK).toBeCloseTo((1 + 1 / Math.log2(4)) / (1 + 1 / Math.log2(3)));
    expect(metrics.forbiddenExposureAtK).toBe(1);
    expect(metrics.unauthorizedSelectionCount).toBe(1);
  });

  it("measures partial recall without inventing privacy failures", () => {
    const relevantA = ref("urn:local", "relevant-a");
    const relevantB = ref("urn:crew", "relevant-b");
    const metrics = measureTurn([candidate(relevantA, 1)], judgment([relevantA, relevantB]), {
      k: 3,
      receiverPublisher: "urn:local",
      authorizedPublishers: { "urn:crew": true },
    });

    expect(metrics.rightTurnRecallAtK).toBe(0.5);
    expect(metrics.ndcgAtK).toBeCloseTo(1 / (1 + 1 / Math.log2(3)));
    expect(metrics.forbiddenExposureAtK).toBe(0);
    expect(metrics.unauthorizedSelectionCount).toBe(0);
  });

  it("scores a single relevant result as perfect", () => {
    const relevant = ref("urn:crew", "relevant");
    const metrics = measureTurn([candidate(relevant, 1)], judgment([relevant]), {
      k: 1,
      receiverPublisher: "urn:local",
      authorizedPublishers: { "urn:crew": true },
    });

    expect(metrics.rightTurnRecallAtK).toBe(1);
    expect(metrics.ndcgAtK).toBe(1);
  });

  it("rejects an empty relevance judgment", () => {
    expect(() =>
      measureTurn([], judgment([]), {
        k: 1,
        receiverPublisher: "urn:local",
        authorizedPublishers: {},
      }),
    ).toThrow("EMPTY_RELEVANCE_JUDGMENT");
  });
});
