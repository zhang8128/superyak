import { describe, expect, it } from "vitest";
import { parseEngramExport } from "../src/export.js";

const digestA = "a".repeat(64);
const digestB = "b".repeat(64);
const queryDigest = "c".repeat(64);

interface TestMemory {
  id: string;
  layer: string;
  contentDigest: { algorithm: string; value: string };
  contextPath: string[];
  lane: string;
  origin: string;
}

interface TestEdge {
  source: string;
  target: string;
  type: string;
  weight: number;
  directed: boolean;
}

interface TestTrace {
  turnId: string;
  queryDigest: { algorithm: string; value: string };
  contextPath: string[];
  candidates: [{ memoryId: string; rank: number }, { memoryId: string; rank: number }];
}

interface TestDocument {
  [key: string]: unknown;
  formatVersion: string;
  instance: string;
  context: { id: string; path: string[] };
  memories: [TestMemory, TestMemory];
  edges: [TestEdge];
  recallTraces: [TestTrace];
}

function validExport(): TestDocument {
  return {
    formatVersion: "1.0",
    instance: "test-memory",
    context: { id: "memory", path: ["memory"] },
    memories: [
      {
        id: "memory-b",
        layer: "semantic",
        contentDigest: { algorithm: "sha256", value: digestB },
        contextPath: ["memory", "debugging", "mcp"],
        lane: "technical",
        origin: "organic",
      },
      {
        id: "memory-a",
        layer: "episode",
        contentDigest: { algorithm: "sha256", value: digestA },
        contextPath: ["memory", "debugging"],
        lane: "technical",
        origin: "lived",
      },
    ],
    edges: [
      {
        source: "memory-a",
        target: "memory-b",
        type: "provenance",
        weight: 0.8,
        directed: true,
      },
    ],
    recallTraces: [
      {
        turnId: "turn-1",
        queryDigest: { algorithm: "sha256", value: queryDigest },
        contextPath: ["memory", "debugging", "mcp"],
        candidates: [
          { memoryId: "memory-a", rank: 2 },
          { memoryId: "memory-b", rank: 1 },
        ],
      },
    ],
  };
}

function changed(mutator: (document: TestDocument) => void): TestDocument {
  const document = structuredClone(validExport());
  mutator(document);
  return document;
}

describe("portable Engram export", () => {
  it("normalizes set-like memories and ranked candidates", () => {
    const parsed = parseEngramExport(validExport());

    expect(parsed.memories.map(({ id }) => id)).toEqual(["memory-a", "memory-b"]);
    expect(parsed.recallTraces[0]?.candidates).toEqual([
      { memoryId: "memory-b", rank: 1 },
      { memoryId: "memory-a", rank: 2 },
    ]);
  });

  it("rejects duplicate memory identities", () => {
    const document = changed((value) => value.memories.push(value.memories[0]));
    expect(() => parseEngramExport(document)).toThrow("DUPLICATE_MEMORY_ID");
  });

  it("rejects edges with missing endpoints", () => {
    const document = changed((value) => {
      value.edges[0].target = "missing";
    });
    expect(() => parseEngramExport(document)).toThrow("DANGLING_EDGE");
  });

  it("rejects recall candidates absent from the memory set", () => {
    const document = changed((value) => {
      value.recallTraces[0].candidates[0].memoryId = "missing";
    });
    expect(() => parseEngramExport(document)).toThrow("DANGLING_CANDIDATE");
  });

  it("rejects two candidates at the same rank", () => {
    const document = changed((value) => {
      value.recallTraces[0].candidates[0].rank = 1;
    });
    expect(() => parseEngramExport(document)).toThrow("DUPLICATE_CANDIDATE_RANK");
  });

  it("rejects one memory occupying multiple candidate ranks", () => {
    const document = changed((value) => {
      value.recallTraces[0].candidates[0].memoryId = value.recallTraces[0].candidates[1].memoryId;
    });
    expect(() => parseEngramExport(document)).toThrow("DUPLICATE_CANDIDATE_MEMORY");
  });

  it("rejects gaps in candidate ranks", () => {
    const document = changed((value) => {
      value.recallTraces[0].candidates[0].rank = 3;
    });
    expect(() => parseEngramExport(document)).toThrow("NON_CONTIGUOUS_RANKS");
  });

  it("rejects memory and trace contexts outside the declared root", () => {
    const memoryOutside = changed((value) => {
      value.memories[0].contextPath = ["relationship"];
    });
    const traceOutside = changed((value) => {
      value.recallTraces[0].contextPath = ["relationship"];
    });

    expect(() => parseEngramExport(memoryOutside)).toThrow("CONTEXT_OUTSIDE_ROOT");
    expect(() => parseEngramExport(traceOutside)).toThrow("CONTEXT_OUTSIDE_ROOT");
  });

  it("rejects duplicate traces for one turn and context", () => {
    const document = changed((value) => value.recallTraces.push(value.recallTraces[0]));
    expect(() => parseEngramExport(document)).toThrow("DUPLICATE_RECALL_TRACE");
  });

  it("rejects unknown source members", () => {
    const document = changed((value) => {
      value.unexpected = true;
    });
    expect(() => parseEngramExport(document)).toThrow();
  });

  it("normalizes Unicode identities and parallel edges independently of input order", () => {
    const first = changed((value) => {
      value.memories[0].id = "memory-ä";
      value.memories[1].id = "memory-z";
      value.edges[0].source = "memory-z";
      value.edges[0].target = "memory-ä";
      value.edges.push({ ...value.edges[0], weight: 0.2, directed: false });
      value.recallTraces[0].candidates[0].memoryId = "memory-z";
      value.recallTraces[0].candidates[1].memoryId = "memory-ä";
    });
    const reversed = structuredClone(first);
    reversed.memories.reverse();
    reversed.edges.reverse();

    const normalized = parseEngramExport(first);
    expect(parseEngramExport(reversed)).toEqual(normalized);
    expect(normalized.memories.map(({ id }) => id)).toEqual(["memory-z", "memory-ä"]);
    expect(normalized.edges.map(({ weight }) => weight)).toEqual([0.2, 0.8]);
  });
});
