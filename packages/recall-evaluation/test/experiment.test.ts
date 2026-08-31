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
  });

  it("records deterministic recall-only receipts with the matched local rule", () => {
    const first = runRecallExperiment(input());
    const reversed = input();
    reversed.sources.reverse();
    reversed.turns.reverse();
    const second = runRecallExperiment(reversed);
    const scopedTurn = mode(first, "policy-scoped").turns[0];

    expect(second.digest).toEqual(first.digest);
    expect(scopedTurn?.receipt.action).toBe("recall");
    expect(scopedTurn?.receipt.injected).toBe(false);
    expect(scopedTurn?.receipt.decisions).toContainEqual({
      publisher: "urn:crew",
      role: "remote",
      allowed: true,
      ruleId: "allow-crew-debug-recall",
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
  });
});
