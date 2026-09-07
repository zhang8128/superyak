import { describe, expect, it } from "vitest";
import { parseLabelsDocument } from "../src/index.js";

function labels() {
  return {
    formatVersion: "1.0",
    instance: "engram-local",
    turns: [
      {
        turnId: "turn-b",
        context: { id: "memory/technical", path: ["memory", "technical"] },
        purpose: "session-recall",
        relevant: [{ publisher: "urn:lighthouse:why", memoryId: "why-1" }],
        forbidden: [],
      },
      {
        turnId: "turn-a",
        context: { id: "memory/technical", path: ["memory", "technical"] },
        purpose: "session-recall",
        relevant: [{ publisher: "urn:lighthouse:engram", memoryId: "local-1" }],
        forbidden: [{ publisher: "urn:lighthouse:blocks", memoryId: "blocks-private" }],
      },
    ],
  };
}

describe("labels document", () => {
  it("parses and sorts turns by turn id then context", () => {
    const parsed = parseLabelsDocument(labels());
    expect(parsed.turns.map((turn) => turn.turnId)).toEqual(["turn-a", "turn-b"]);
  });

  it("rejects duplicate turn keys", () => {
    const document = labels();
    const duplicate = document.turns[0];
    if (duplicate === undefined) throw new Error("test fixture must include a turn");
    document.turns.push({ ...duplicate });
    expect(() => parseLabelsDocument(document)).toThrow("DUPLICATE_LABEL_TURN");
  });

  it("rejects a turn with no relevant references", () => {
    const document = labels();
    const turn = document.turns[0];
    if (turn === undefined) throw new Error("test fixture must include a turn");
    turn.relevant = [];
    expect(() => parseLabelsDocument(document)).toThrow("EMPTY_RELEVANCE_JUDGMENT");
  });

  it("rejects unknown members and other versions", () => {
    expect(() => parseLabelsDocument({ ...labels(), notes: "leak" })).toThrow();
    expect(() => parseLabelsDocument({ ...labels(), formatVersion: "2.0" })).toThrow();
  });
});
