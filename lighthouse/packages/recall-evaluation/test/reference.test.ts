import path from "node:path";
import { engramAdapter } from "@lighthouse/adapter-engram";
import { describe, expect, it } from "vitest";
import { runReferenceRecallProof } from "../src/index.js";

const fixtureRoot = path.resolve(import.meta.dirname, "../../../fixtures/engram");

describe("reference Engram recall proof", () => {
  it("passes every recall, policy, privacy, receipt, and determinism check", async () => {
    const report = await runReferenceRecallProof(fixtureRoot);

    expect(report.passed).toBe(true);
    expect(report.checks.map(({ id }) => id)).toEqual([
      "schema.engram-snapshots",
      "digest.engram-deterministic",
      "restriction.engram-laws",
      "evaluation.rank-claim",
      "policy.recall-allowed",
      "policy.injection-denied",
      "measurement.scoped-improves-recall",
      "measurement.scoped-improves-ndcg",
      "privacy.scoped-no-forbidden-exposure",
      "privacy.scoped-no-unauthorized-selection",
      "negative-control.forbidden-exposure-detected",
      "negative-control.policy-bypass-detected",
      "receipt.no-injection",
      "digest.experiment-deterministic",
    ]);
    expect(report.checks.every(({ status }) => status === "passed")).toBe(true);
  });

  it("rejects the malformed dangling-candidate fixture", async () => {
    await expect(
      engramAdapter.project({
        root: path.join(fixtureRoot, "invalid-dangling.engram.json"),
        id: "urn:snapshot:invalid",
        issuer: "urn:lighthouse:invalid",
        issuedAt: "2026-08-30T12:00:00Z",
      }),
    ).rejects.toThrow("DANGLING_CANDIDATE");
  });
});
