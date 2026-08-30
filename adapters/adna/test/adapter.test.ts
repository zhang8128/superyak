import { cp, mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  adnaAdapter,
  createAdnaPortClaim,
  type AdnaPortClaimInput,
} from "../src/index.js";

const fixtureRoot = path.resolve(import.meta.dirname, "../../../fixtures/adna");
const metadata = {
  id: "urn:snapshot:adna-orders",
  issuer: "urn:lighthouse:adna-local",
  issuedAt: "2026-08-30T12:00:00Z",
};

async function copyFixture(prefix: string): Promise<string> {
  const root = await mkdtemp(path.join(os.tmpdir(), prefix));
  await cp(fixtureRoot, root, { recursive: true });
  return root;
}

describe("aDNA adapter", () => {
  it("projects identical typed-port snapshots from different paths", async () => {
    const firstRoot = await copyFixture("lighthouse-adna-first-");
    const secondRoot = await copyFixture("lighthouse-adna-second-");

    const first = await adnaAdapter.project({ root: firstRoot, ...metadata });
    const second = await adnaAdapter.project({ root: secondRoot, ...metadata });

    expect(second.digest).toEqual(first.digest);
    expect(second.payload.model).toEqual(first.payload.model);
  });

  it("satisfies a connected compatible-port claim", async () => {
    const snapshot = await adnaAdapter.project({ root: fixtureRoot, ...metadata });

    expect(await adnaAdapter.evaluate(snapshot, createAdnaPortClaim(snapshot))).toBe("satisfied");
  });

  it("violates a claim whose declared value type differs", async () => {
    const snapshot = await adnaAdapter.project({ root: fixtureRoot, ...metadata });
    const wrongType: AdnaPortClaimInput = {
      outputNodeId: "publish_order",
      outputPort: "order_created",
      inputNodeId: "consume_order",
      inputPort: "order_created",
      valueType: "application/vnd.example.invoice+json",
    };

    expect(await adnaAdapter.evaluate(snapshot, createAdnaPortClaim(snapshot, wrongType))).toBe(
      "violated",
    );
  });
});
