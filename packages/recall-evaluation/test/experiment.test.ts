import {
  ENGRAM_PROFILE,
  ENGRAM_RECALL_RANK_CLAIM_MEDIA_TYPE,
  ENGRAM_SIGNATURE,
  parseEngramExport,
} from "@lighthouse/adapter-engram";
import { type ConnectionPolicy, type JsonValue, sealArtifact } from "@lighthouse/protocol";
import { describe, expect, it } from "vitest";
import {
  type RecallExperimentReport,
  type RecallModeReport,
  runRecallExperiment,
} from "../src/index.js";

const issuedAt = "2026-08-30T12:00:00Z";

function snapshot(
  issuer: string,
  memoryId: string,
  memoryContext: string[],
  weightCharacter: string,
) {
  const model = parseEngramExport({
    formatVersion: "1.0",
    instance: issuer,
    context: { id: "memory", path: ["memory"] },
    memories: [
      {
        id: memoryId,
        layer: "semantic",
        contentDigest: { algorithm: "sha256", value: weightCharacter.repeat(64) },
        contextPath: memoryContext,
        lane: "test",
        origin: "organic",
      },
    ],
    edges: [],
    recallTraces: [
      {
        turnId: "turn-missing-restart",
        queryDigest: { algorithm: "sha256", value: "f".repeat(64) },
        contextPath: memoryContext,
        candidates: [{ memoryId, rank: 1 }],
      },
    ],
  });
  return sealArtifact({
    kind: "Snapshot",
    protocolVersion: "0.1",
    id: `urn:snapshot:${memoryId}`,
    issuedAt,
    issuer,
    payloadMediaType: "application/vnd.lighthouse.snapshot+json",
    payload: {
      profile: ENGRAM_PROFILE,
      signature: ENGRAM_SIGNATURE,
      context: model.context,
      model: model as unknown as JsonValue,
      lineage: [],
    },
  });
}

function policy(): ConnectionPolicy {
  const selectorDefaults = {
    profiles: [ENGRAM_PROFILE.id],
    domains: ["memory.recall"],
    contexts: ["memory/debugging/mcp"],
    claimMediaTypes: [ENGRAM_RECALL_RANK_CLAIM_MEDIA_TYPE],
    purposes: ["debugging"],
    audiences: ["self"],
    validFrom: "2026-08-30T00:00:00Z",
    validUntil: "2027-08-30T00:00:00Z",
    requiredEvidence: [],
    requiredAttestations: [],
  };
  return sealArtifact({
    kind: "ConnectionPolicy",
    protocolVersion: "0.1",
    id: "urn:policy:recall-experiment",
    issuedAt,
    issuer: "urn:receiver",
    payloadMediaType: "application/vnd.lighthouse.connection-policy+json",
    payload: {
      rules: [
        {
          id: "allow-crew-debug-recall",
          effect: "allow",
          publishers: ["urn:crew"],
          actions: ["recall"],
          ...selectorDefaults,
        },
        {
          id: "deny-crew-context-injection",
          effect: "deny",
          publishers: ["urn:crew"],
          actions: ["inject_context"],
          ...selectorDefaults,
        },
        {
          id: "deny-intimate-neighbor-recall",
          effect: "deny",
          publishers: ["urn:intimate-neighbor"],
          actions: ["recall"],
          ...selectorDefaults,
        },
      ],
    },
  });
}

function policyAllowingIntimatePublisher(): ConnectionPolicy {
  const original = policy();
  const { digest: _digest, attestations: _attestations, ...common } = original;
  return sealArtifact({
    ...common,
    payload: {
      rules: original.payload.rules.map((rule) =>
        rule.id === "deny-intimate-neighbor-recall"
          ? { ...rule, id: "allow-intimate-neighbor-recall", effect: "allow" as const }
          : rule,
      ),
    },
  });
}

function input() {
  const local = snapshot(
    "urn:receiver",
    "local-debug-checklist",
    ["memory", "debugging", "mcp"],
    "a",
  );
  const crew = snapshot(
    "urn:crew",
    "restart-after-server-change",
    ["memory", "debugging", "mcp"],
    "b",
  );
  const intimate = snapshot(
    "urn:intimate-neighbor",
    "private-relationship-event",
    ["memory", "relationship"],
    "c",
  );
  return {
    id: "urn:experiment:right-turn",
    issuedAt,
    receiverPublisher: "urn:receiver",
    k: 1,
    policy: policy(),
    sources: [
      { snapshot: local, role: "local" as const, weight: 1 },
      { snapshot: crew, role: "remote" as const, weight: 2 },
      { snapshot: intimate, role: "remote" as const, weight: 3 },
    ],
    turns: [
      {
        turnId: "turn-missing-restart",
        context: { id: "memory/debugging/mcp", path: ["memory", "debugging", "mcp"] },
        purpose: "debugging",
        relevant: [{ publisher: "urn:crew", memoryId: "restart-after-server-change" }],
        forbidden: [{ publisher: "urn:intimate-neighbor", memoryId: "private-relationship-event" }],
      },
    ],
  };
}

function mode(report: RecallExperimentReport, id: RecallModeReport["mode"]): RecallModeReport {
  const found = report.modes.find((candidate) => candidate.mode === id);
  if (found === undefined) throw new Error(`missing mode ${id}`);
  return found;
}

describe("policy-scoped recall experiment", () => {
  it("improves right-turn recall without admitting forbidden relational material", () => {
    const report = runRecallExperiment(input());

    expect(mode(report, "local-only").metrics.rightTurnRecallAtK).toBe(0);
    expect(mode(report, "policy-scoped").metrics.rightTurnRecallAtK).toBe(1);
    expect(mode(report, "policy-scoped").metrics.forbiddenExposureAtK).toBe(0);
    expect(mode(report, "policy-scoped").metrics.unauthorizedSelectionCount).toBe(0);
    expect(mode(report, "indiscriminate-control").metrics.forbiddenExposureAtK).toBe(1);
    expect(mode(report, "indiscriminate-control").metrics.unauthorizedSelectionCount).toBe(1);
    expect(mode(report, "local-only").turns[0]?.admissions).toContainEqual({
      publisher: "urn:crew",
      trace: "matched",
      admission: "mode-excluded",
      candidateCount: 1,
    });
  });

  it("records deterministic recall-only receipts with the matched local rule", () => {
    const first = runRecallExperiment(input());
    const reversed = input();
    reversed.sources.reverse();
    reversed.turns.reverse();
    const second = runRecallExperiment(reversed);
    const scopedTurn = mode(first, "policy-scoped").turns[0];

    expect(second.digest).toEqual(first.digest);
    expect(scopedTurn?.receipt.payload.action).toBe("recall");
    expect(scopedTurn?.receipt.payload.injected).toBe(false);
    expect(scopedTurn?.receipt.payload.sources).toContainEqual({
      publisher: "urn:crew",
      role: "remote",
      weight: 2,
      storeDigest: expect.objectContaining({ algorithm: "sha256" }),
      policyDecision: {
        effect: "allow",
        ruleId: "allow-crew-debug-recall",
        code: null,
      },
      traceOutcome: "matched",
    });
    expect(JSON.stringify(scopedTurn?.receipt)).not.toMatch(/"content"|"query"/);
  });

  it("keeps an allowed publisher's trace outside the requested memory context excluded", () => {
    const experiment = input();
    experiment.policy = policyAllowingIntimatePublisher();

    const scoped = mode(runRecallExperiment(experiment), "policy-scoped");

    expect(scoped.metrics.rightTurnRecallAtK).toBe(1);
    expect(scoped.metrics.forbiddenExposureAtK).toBe(0);
    expect(scoped.turns[0]?.decisions).toContainEqual({
      publisher: "urn:intimate-neighbor",
      role: "remote",
      allowed: true,
      ruleId: "allow-intimate-neighbor-recall",
    });
    expect(scoped.turns[0]?.admissions).toContainEqual({
      publisher: "urn:intimate-neighbor",
      trace: "context-mismatch",
      admission: "trace-unavailable",
      candidateCount: 0,
    });
  });

  it("records an unknown turn as absent separately from authorization", () => {
    const experiment = input();
    const turn = experiment.turns[0];
    if (turn === undefined) throw new Error("missing experiment turn");
    turn.turnId = "turn-unknown";

    const scopedTurn = mode(runRecallExperiment(experiment), "policy-scoped").turns[0];

    expect(scopedTurn?.decisions).toContainEqual({
      publisher: "urn:crew",
      role: "remote",
      allowed: true,
      ruleId: "allow-crew-debug-recall",
    });
    expect(scopedTurn?.admissions).toContainEqual({
      publisher: "urn:crew",
      trace: "absent",
      admission: "trace-unavailable",
      candidateCount: 0,
    });
    expect(scopedTurn?.receipt.payload.sources).toContainEqual({
      publisher: "urn:crew",
      role: "remote",
      weight: 2,
      storeDigest: expect.objectContaining({ algorithm: "sha256" }),
      policyDecision: {
        effect: "allow",
        ruleId: "allow-crew-debug-recall",
        code: null,
      },
      traceOutcome: "absent",
    });
  });

  it("records a zero-weight matching source without selecting it", () => {
    const experiment = input();
    const crew = experiment.sources.find(({ snapshot }) => snapshot.issuer === "urn:crew");
    if (crew === undefined) throw new Error("missing crew source");
    crew.weight = 0;

    const scopedTurn = mode(runRecallExperiment(experiment), "policy-scoped").turns[0];

    expect(scopedTurn?.admissions).toContainEqual({
      publisher: "urn:crew",
      trace: "matched",
      admission: "zero-weight",
      candidateCount: 1,
    });
    expect(scopedTurn?.selected).not.toContainEqual(
      expect.objectContaining({
        ref: { publisher: "urn:crew", memoryId: "restart-after-server-change" },
      }),
    );
  });

  it("denies an unmatched remote source by default and records the exclusion", () => {
    const experiment = input();
    experiment.sources.push({
      snapshot: snapshot(
        "urn:unmatched",
        "unmatched-debug-memory",
        ["memory", "debugging", "mcp"],
        "d",
      ),
      role: "remote",
      weight: 4,
    });

    const scopedTurn = mode(runRecallExperiment(experiment), "policy-scoped").turns[0];

    expect(scopedTurn?.decisions).toContainEqual({
      publisher: "urn:unmatched",
      role: "remote",
      allowed: false,
      code: "NO_MATCHING_ALLOW",
    });
    expect(scopedTurn?.admissions).toContainEqual({
      publisher: "urn:unmatched",
      trace: "matched",
      admission: "policy-denied",
      candidateCount: 1,
    });
    expect(scopedTurn?.selected).not.toContainEqual(
      expect.objectContaining({ ref: { publisher: "urn:unmatched" } }),
    );
  });

  it("rejects duplicate logical turn keys instead of preserving caller order", () => {
    const experiment = input();
    const turn = experiment.turns[0];
    if (turn === undefined) throw new Error("missing experiment turn");
    experiment.turns.push({
      ...structuredClone(turn),
      purpose: "different-judgment",
    });

    expect(() => runRecallExperiment(experiment)).toThrow("DUPLICATE_EXPERIMENT_TURN");
  });
});
