import { parseEngramExport } from "@lighthouse/adapter-engram";
import { digestJson, type JsonValue, sealArtifact } from "@lighthouse/protocol";
import { describe, expect, it } from "vitest";
import { parseLabelsDocument, parsePreregistration, runShadowEvaluation } from "../src/index.js";

const hex = (character: string) => character.repeat(64);
const RECEIVER = "urn:lighthouse:engram";
const WHY = "urn:lighthouse:why";
const BLOCKS = "urn:lighthouse:blocks";
const technical = { id: "memory/technical", path: ["memory", "technical"] };

function receiptFor(
  turnId: string,
  selected: Array<[string, string, number]>,
  blocksAllowed: boolean,
) {
  const weights: Record<string, number> = { [RECEIVER]: 1, [WHY]: 2, [BLOCKS]: 3 };
  return sealArtifact({
    kind: "RecallReceipt",
    protocolVersion: "0.1",
    id: `urn:receipt:${turnId}`,
    issuedAt: "2026-09-01T12:00:00Z",
    issuer: RECEIVER,
    payloadMediaType: "application/vnd.lighthouse.recall-receipt+json",
    payload: {
      turnId,
      context: technical,
      purpose: "session-recall",
      audience: "self",
      action: "recall",
      injected: false,
      transformation: "weighted-rrf-v1",
      receiverRule: { ruleId: "allow-technical" },
      sources: [
        {
          publisher: RECEIVER,
          role: "local",
          weight: 1,
          storeDigest: { algorithm: "sha256", value: hex("1") },
          policyDecision: { effect: "allow", ruleId: "local:self", code: null },
          traceOutcome: "matched",
        },
        {
          publisher: WHY,
          role: "remote",
          weight: 2,
          storeDigest: { algorithm: "sha256", value: hex("2") },
          policyDecision: { effect: "allow", ruleId: "allow-why", code: null },
          traceOutcome: "matched",
        },
        {
          publisher: BLOCKS,
          role: "remote",
          weight: 3,
          storeDigest: { algorithm: "sha256", value: hex("3") },
          policyDecision: blocksAllowed
            ? { effect: "allow", ruleId: "allow-blocks", code: null }
            : { effect: "deny", ruleId: "deny-blocks", code: "EXPLICIT_DENY" },
          traceOutcome: blocksAllowed ? "matched" : "policy-denied",
        },
      ],
      selected: selected.map(([publisher, memoryId, rank]) => ({
        publisher,
        memoryId,
        contentDigest: { algorithm: "sha256", value: hex("a") },
        score: (weights[publisher] as number) / (60 + rank),
        contributions: [{ publisher, rank }],
      })),
      delivered: [],
    },
  });
}

function exportDocument(receipts: unknown[]) {
  return {
    formatVersion: "1.1",
    instance: "engram-local",
    context: { id: "memory", path: ["memory"] },
    memories: [
      {
        id: "local-1",
        layer: "episode",
        contentDigest: { algorithm: "sha256", value: hex("a") },
        contextPath: ["memory", "technical"],
        lane: "work",
        origin: "lived",
      },
      {
        id: "local-2",
        layer: "episode",
        contentDigest: { algorithm: "sha256", value: hex("b") },
        contextPath: ["memory", "technical"],
        lane: "work",
        origin: "lived",
      },
    ],
    edges: [],
    recallTraces: [
      {
        turnId: "turn-1",
        queryDigest: { algorithm: "sha256", value: hex("c") },
        contextPath: ["memory", "technical"],
        candidates: [
          { memoryId: "local-2", rank: 1 },
          { memoryId: "local-1", rank: 2 },
        ],
      },
      {
        turnId: "turn-2",
        queryDigest: { algorithm: "sha256", value: hex("d") },
        contextPath: ["memory", "technical"],
        candidates: [{ memoryId: "local-1", rank: 1 }],
      },
    ],
    receipts,
  };
}

function labels() {
  return parseLabelsDocument({
    formatVersion: "1.0",
    instance: "engram-local",
    turns: [
      {
        turnId: "turn-1",
        context: technical,
        purpose: "session-recall",
        relevant: [{ publisher: WHY, memoryId: "why-missing-piece" }],
        forbidden: [{ publisher: BLOCKS, memoryId: "blocks-private" }],
      },
      {
        turnId: "turn-2",
        context: technical,
        purpose: "session-recall",
        relevant: [{ publisher: RECEIVER, memoryId: "local-1" }],
        forbidden: [],
      },
    ],
  });
}

function preregistrationFor(document: unknown, overrides: Record<string, unknown> = {}) {
  const corpusDigest = digestJson(parseEngramExport(document) as unknown as JsonValue);
  return parsePreregistration({
    receiverPublisher: RECEIVER,
    corpusDigest,
    holdoutTurnIds: ["turn-1", "turn-2"],
    cutoff: 5,
    metrics: ["rightTurnRecall", "nDCG"],
    bootstrap: { samples: 100, seed: 3 },
    ...overrides,
  });
}

describe("shadow evaluation", () => {
  it("replays receipts against receiver labels and reports both modes", () => {
    const document = exportDocument([
      receiptFor(
        "turn-1",
        [
          [WHY, "why-missing-piece", 1],
          [RECEIVER, "local-2", 1],
        ],
        false,
      ),
    ]);
    const report = runShadowEvaluation({
      exportDocument: document,
      labels: labels(),
      preregistration: preregistrationFor(document),
      issuedAt: "2026-09-01T13:00:00Z",
    });
    expect(report.kind).toBe("RecallShadowReport");
    expect(report.holdout).toEqual({ turns: 2, receipts: 1, localOnlyTurns: 1 });
    expect(report.modes["local-only"].rightTurnRecallAtK).toBe(0.5);
    expect(report.modes["policy-scoped"].rightTurnRecallAtK).toBe(1);
    expect(report.modes["policy-scoped"].forbiddenExposureAtK).toBe(0);
    expect(report.modes["policy-scoped"].unauthorizedSelectionCount).toBe(0);
    expect(report.modes["policy-scoped"].bootstrap.rightTurnRecallAtK.upper).toBeLessThanOrEqual(1);
  });

  it("counts a forbidden and unauthorized selection when a denied publisher was selected", () => {
    const document = exportDocument([receiptFor("turn-1", [[BLOCKS, "blocks-private", 1]], false)]);
    const report = runShadowEvaluation({
      exportDocument: document,
      labels: labels(),
      preregistration: preregistrationFor(document),
      issuedAt: "2026-09-01T13:00:00Z",
    });
    expect(report.modes["policy-scoped"].forbiddenExposureAtK).toBe(1);
    expect(report.modes["policy-scoped"].unauthorizedSelectionCount).toBe(1);
  });

  it("is deterministic and never carries content or query members", () => {
    const document = exportDocument([receiptFor("turn-1", [[WHY, "why-missing-piece", 1]], false)]);
    const run = () =>
      runShadowEvaluation({
        exportDocument: document,
        labels: labels(),
        preregistration: preregistrationFor(document),
        issuedAt: "2026-09-01T13:00:00Z",
      });
    expect(run().digest).toEqual(run().digest);
    const keys = new Set<string>();
    const walk = (value: unknown) => {
      if (Array.isArray(value)) for (const item of value) walk(item);
      else if (value && typeof value === "object") {
        for (const [key, item] of Object.entries(value)) {
          keys.add(key);
          walk(item);
        }
      }
    };
    walk(run());
    expect(keys.has("content")).toBe(false);
    expect(keys.has("query")).toBe(false);
  });

  it("refuses a corpus that does not match the preregistration", () => {
    const document = exportDocument([]);
    const preregistration = preregistrationFor(document, {
      corpusDigest: { algorithm: "sha-256", value: hex("f") },
    });
    expect(() =>
      runShadowEvaluation({
        exportDocument: document,
        labels: labels(),
        preregistration,
        issuedAt: "2026-09-01T13:00:00Z",
      }),
    ).toThrow("CORPUS_DIGEST_MISMATCH");
  });

  it("requires the protocol sha-256 convention for the corpus digest", () => {
    const document = exportDocument([]);
    expect(() =>
      preregistrationFor(document, {
        corpusDigest: { algorithm: "sha256", value: hex("f") },
      }),
    ).toThrow();
  });

  it("refuses holdout turns without labels or local traces", () => {
    const document = exportDocument([]);
    expect(() =>
      runShadowEvaluation({
        exportDocument: document,
        labels: labels(),
        preregistration: preregistrationFor(document, {
          holdoutTurnIds: ["turn-1", "turn-9"],
        }),
        issuedAt: "2026-09-01T13:00:00Z",
      }),
    ).toThrow("HOLDOUT_TURN_UNLABELED");
    const unlabeledTrace = parseLabelsDocument({
      ...labels(),
      turns: [
        ...labels().turns,
        {
          turnId: "turn-9",
          context: technical,
          purpose: "session-recall",
          relevant: [{ publisher: RECEIVER, memoryId: "local-1" }],
          forbidden: [],
        },
      ],
    });
    expect(() =>
      runShadowEvaluation({
        exportDocument: document,
        labels: unlabeledTrace,
        preregistration: preregistrationFor(document, { holdoutTurnIds: ["turn-9"] }),
        issuedAt: "2026-09-01T13:00:00Z",
      }),
    ).toThrow("HOLDOUT_TURN_MISSING_TRACE");
  });

  it("refuses a receipt whose scores disagree with its contributions", () => {
    const receipt = receiptFor("turn-1", [[WHY, "why-missing-piece", 1]], false);
    const selected = receipt.payload.selected[0];
    if (selected === undefined) throw new Error("test receipt must contain a selected item");
    const forged = sealArtifact({
      ...(({ digest: _digest, ...rest }) => rest)(receipt),
      payload: {
        ...receipt.payload,
        selected: [{ ...selected, score: 0.9 }],
      },
    });
    const document = exportDocument([forged]);
    expect(() =>
      runShadowEvaluation({
        exportDocument: document,
        labels: labels(),
        preregistration: preregistrationFor(document),
        issuedAt: "2026-09-01T13:00:00Z",
      }),
    ).toThrow("RECEIPT_SCORE_MISMATCH");
  });

  it("refuses selected provenance relabeled from a different publisher", () => {
    const receipt = receiptFor("turn-1", [[WHY, "why-missing-piece", 1]], false);
    const selected = receipt.payload.selected[0];
    if (selected === undefined) throw new Error("test receipt must contain a selected item");
    const relabeled = sealArtifact({
      ...(({ digest: _digest, ...rest }) => rest)(receipt),
      payload: {
        ...receipt.payload,
        selected: [
          {
            ...selected,
            score: 3 / 61,
            contributions: [{ publisher: BLOCKS, rank: 1 }],
          },
        ],
      },
    });
    const document = exportDocument([relabeled]);
    expect(() =>
      runShadowEvaluation({
        exportDocument: document,
        labels: labels(),
        preregistration: preregistrationFor(document),
        issuedAt: "2026-09-01T13:00:00Z",
      }),
    ).toThrow("RECEIPT_SCORE_MISMATCH");
  });

  it("refuses duplicate publisher-qualified selected references", () => {
    const receipt = receiptFor("turn-1", [[WHY, "why-missing-piece", 1]], false);
    const selected = receipt.payload.selected[0];
    if (selected === undefined) throw new Error("test receipt must contain a selected item");
    const duplicated = sealArtifact({
      ...(({ digest: _digest, ...rest }) => rest)(receipt),
      payload: {
        ...receipt.payload,
        selected: [selected, { ...selected }],
      },
    });
    const document = exportDocument([duplicated]);
    expect(() =>
      runShadowEvaluation({
        exportDocument: document,
        labels: labels(),
        preregistration: preregistrationFor(document),
        issuedAt: "2026-09-01T13:00:00Z",
      }),
    ).toThrow("RECEIPT_SCORE_MISMATCH");
  });

  it("refuses a receipt outside the labeled holdout context", () => {
    const receipt = receiptFor("turn-1", [[WHY, "why-missing-piece", 1]], false);
    const mismatched = sealArtifact({
      ...(({ digest: _digest, ...rest }) => rest)(receipt),
      payload: {
        ...receipt.payload,
        context: { id: "memory/personal", path: ["memory", "personal"] },
      },
    });
    const document = exportDocument([mismatched]);
    expect(() =>
      runShadowEvaluation({
        exportDocument: document,
        labels: labels(),
        preregistration: preregistrationFor(document),
        issuedAt: "2026-09-01T13:00:00Z",
      }),
    ).toThrow("HOLDOUT_TURN_CONTEXT_MISMATCH");
  });
});
