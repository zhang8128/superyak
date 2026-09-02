import { describe, expect, it } from "vitest";
import { bootstrapInterval, mulberry32 } from "../src/index.js";

describe("seeded bootstrap", () => {
  it("is deterministic for a seed", () => {
    const a = mulberry32(7);
    const b = mulberry32(7);
    expect([a(), a(), a()]).toEqual([b(), b(), b()]);
  });

  it("returns an interval inside the data range and identical across runs", () => {
    const values = [0, 0.5, 1, 1, 0.25];
    const first = bootstrapInterval(values, 200, 42);
    const second = bootstrapInterval(values, 200, 42);
    expect(first).toEqual(second);
    expect(first.lower).toBeGreaterThanOrEqual(0);
    expect(first.upper).toBeLessThanOrEqual(1);
    expect(first.lower).toBeLessThanOrEqual(first.upper);
  });

  it("collapses to the point value for a single observation", () => {
    expect(bootstrapInterval([0.4], 50, 1)).toEqual({ lower: 0.4, upper: 0.4 });
  });
});
