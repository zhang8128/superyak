import { cp, mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { checkRestrictionComposition, checkRestrictionIdentity } from "@lighthouse/calculus";
import { describe, expect, it } from "vitest";
import { createHyperDependencyClaim, createHyperLeaseClaim, hyperAdapter } from "../src/index.js";

const fixtureRoot = path.resolve(import.meta.dirname, "../../../fixtures/hyper/orders");
const metadata = {
  id: "urn:snapshot:hyper-orders",
  issuer: "urn:lighthouse:hyper-local",
  issuedAt: "2026-08-30T12:00:00Z",
};

async function copyFixture(prefix: string): Promise<string> {
  const root = await mkdtemp(path.join(os.tmpdir(), prefix));
  await cp(fixtureRoot, root, { recursive: true });
  return root;
}

describe("Hyper adapter", () => {
  it("projects identical snapshots from different checkout paths", async () => {
    const firstRoot = await copyFixture("lighthouse-hyper-first-");
    const secondRoot = await copyFixture("lighthouse-hyper-second-");

    const first = await hyperAdapter.project({ root: firstRoot, ...metadata });
    const second = await hyperAdapter.project({ root: secondRoot, ...metadata });

    expect(second.digest).toEqual(first.digest);
    expect(second.payload.model).toEqual(first.payload.model);
  });

  it("satisfies the shared dependency claim locally", async () => {
    const snapshot = await hyperAdapter.project({ root: fixtureRoot, ...metadata });

    expect(await hyperAdapter.evaluate(snapshot, createHyperDependencyClaim(snapshot))).toBe(
      "satisfied",
    );
  });

  it("returns indeterminate for a lease claim outside this profile fragment", async () => {
    const snapshot = await hyperAdapter.project({ root: fixtureRoot, ...metadata });

    expect(await hyperAdapter.evaluate(snapshot, createHyperLeaseClaim(snapshot))).toBe(
      "indeterminate",
    );
  });

  it("obeys identity and composition for declared contexts", async () => {
    const snapshot = await hyperAdapter.project({ root: fixtureRoot, ...metadata });

    expect(await checkRestrictionIdentity(hyperAdapter, snapshot)).toEqual({ passed: true });
    expect(
      await checkRestrictionComposition(
        hyperAdapter,
        snapshot,
        { id: "workflow/orders", path: ["workflow", "orders"] },
        {
          id: "workflow/orders/contracts",
          path: ["workflow", "orders", "contracts"],
        },
      ),
    ).toEqual({ passed: true });
  });
});
