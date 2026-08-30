import { describe, expect, it } from "vitest";
import { canonicalize, digestJson } from "../src/index.js";

describe("canonical JSON", () => {
  it("ignores object insertion order while preserving array order", () => {
    const left = { z: [3, 2, 1], a: { y: true, x: null } };
    const right = { a: { x: null, y: true }, z: [3, 2, 1] };

    expect(canonicalize(left)).toBe('{"a":{"x":null,"y":true},"z":[3,2,1]}');
    expect(digestJson(left)).toEqual(digestJson(right));
    expect(digestJson({ z: [1, 2, 3], a: { x: null, y: true } })).not.toEqual(digestJson(left));
  });

  it("rejects non-finite numbers", () => {
    expect(() => canonicalize(Number.NaN)).toThrow("finite JSON number");
  });

  it("rejects values outside the JSON data model", () => {
    expect(() => canonicalize({ hidden: undefined } as never)).toThrow("JSON value");
  });
});
