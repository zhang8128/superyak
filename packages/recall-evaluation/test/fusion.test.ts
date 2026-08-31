import type { Digest } from "@lighthouse/protocol";
import { describe, expect, it } from "vitest";
import { fuseRankings, type MemoryRef, type RankedContribution } from "../src/index.js";

const snapshotDigest: Digest = { algorithm: "sha256", value: "1".repeat(64) };

function contribution(
  publisher: string,
  memoryId: string,
  rank: number,
  sourceWeight: number,
): RankedContribution {
  return {
    ref: { publisher, memoryId },
    contentDigest: { algorithm: "sha256", value: memoryId.padEnd(64, "0").slice(0, 64) },
    sourceSnapshotDigest: snapshotDigest,
    rank,
    sourceWeight,
  };
}

describe("weighted reciprocal-rank fusion", () => {
  it("keeps equal local IDs distinct by publisher and applies local source weights", () => {
    const selected = fuseRankings(
      [contribution("urn:local", "same-id", 1, 1), contribution("urn:crew", "same-id", 1, 2)],
      2,
    );

    expect(selected.map(({ ref }) => ref)).toEqual([
      { publisher: "urn:crew", memoryId: "same-id" },
      { publisher: "urn:local", memoryId: "same-id" },
    ]);
    expect(selected.map(({ score }) => score)).toEqual([2 / 61, 1 / 61]);
  });

  it("sums independent contributions to the same qualified memory", () => {
    const ref: MemoryRef = { publisher: "urn:crew", memoryId: "shared" };
    const selected = fuseRankings(
      [
        contribution(ref.publisher, ref.memoryId, 1, 1),
        contribution(ref.publisher, ref.memoryId, 2, 2),
      ],
      1,
    );

    expect(selected).toHaveLength(1);
    expect(selected[0]?.score).toBe(1 / 61 + 2 / 62);
    expect(selected[0]?.contributions).toHaveLength(2);
  });

  it("uses canonical qualified identity to break equal-score ties", () => {
    const selected = fuseRankings(
      [contribution("urn:local", "memory-b", 1, 1), contribution("urn:local", "memory-a", 1, 1)],
      2,
    );

    expect(selected.map(({ ref }) => ref.memoryId)).toEqual(["memory-a", "memory-b"]);
  });

  it("truncates only after all candidates are fused", () => {
    const selected = fuseRankings(
      [
        contribution("urn:local", "memory-a", 2, 1),
        contribution("urn:local", "memory-b", 1, 1),
        contribution("urn:local", "memory-a", 1, 1),
      ],
      1,
    );

    expect(selected.map(({ ref }) => ref.memoryId)).toEqual(["memory-a"]);
  });

  it.each([-1, Number.POSITIVE_INFINITY, Number.NaN])(
    "rejects an invalid source weight %s",
    (sourceWeight) => {
      expect(() =>
        fuseRankings([contribution("urn:local", "memory-a", 1, sourceWeight)], 1),
      ).toThrow("INVALID_SOURCE_WEIGHT");
    },
  );

  it("does not select candidates from a zero-weight source", () => {
    expect(fuseRankings([contribution("urn:local", "memory-a", 1, 0)], 1)).toEqual([]);
  });
});
