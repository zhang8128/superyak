import path from "node:path";
import { describe, expect, it } from "vitest";
import { runReferenceConformance } from "../src/index.js";

const fixtureRoot = path.resolve(import.meta.dirname, "../../../fixtures");

describe("reference conformance", () => {
  it("passes the complete valid reference proof", async () => {
    const report = await runReferenceConformance({ fixtureRoot, invalidBridge: false });

    expect(report.passed).toBe(true);
    expect(Object.fromEntries(report.checks.map((check) => [check.id, check.status]))).toEqual({
      "schema.artifacts": "passed",
      "digest.hyper-deterministic": "passed",
      "digest.adna-deterministic": "passed",
      "restriction.identity": "passed",
      "restriction.composition": "passed",
      "bridge.shared-claim": "passed",
      "bridge.source-satisfied": "passed",
      "bridge.target-satisfied": "passed",
      "bridge.identity": "passed",
      "bridge.associative": "passed",
      "bridge.lease-unmapped": "passed",
      "bridge.invalid-rejected": "passed",
      "policy.workflow-scoped": "passed",
      "policy.inject-denied": "passed",
      "policy.reshare-denied": "passed",
    });
  });

  it("fails a candidate bridge that breaks satisfaction", async () => {
    const report = await runReferenceConformance({ fixtureRoot, invalidBridge: true });

    expect(report.passed).toBe(false);
    expect(report.checks.find((check) => check.id === "bridge.shared-claim")).toMatchObject({
      status: "failed",
      diagnostics: [{ code: "SATISFACTION_NOT_PRESERVED" }],
    });
  });
});
