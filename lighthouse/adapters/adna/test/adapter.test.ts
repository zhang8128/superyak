import { cp, mkdtemp, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { type AdnaPortClaimInput, adnaAdapter, createAdnaPortClaim } from "../src/index.js";

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
  it("projects the pinned upstream example and scopes claims to its actual workflow", async () => {
    const snapshot = await adnaAdapter.project({
      root: path.join(fixtureRoot, "../adna-upstream/hello_world.lattice.yaml"),
      ...metadata,
    });
    const claim = createAdnaPortClaim(snapshot, {
      outputNodeId: "input_data",
      outputPort: "data",
      inputNodeId: "transform",
      inputPort: "data",
      valueType: "text/plain",
    });
    expect(claim.payload.context.path).toEqual(["workflow", "hello_world"]);
    expect(await adnaAdapter.evaluate(snapshot, claim)).toBe("indeterminate");
  });

  it("accepts the current lattice envelope without changing typed-port meaning", async () => {
    const root = await copyFixture("lighthouse-adna-envelope-");
    const file = path.join(root, "orders.lattice.yaml");
    const original = await adnaAdapter.project({ root, ...metadata });
    const body = await readFile(file, "utf8");
    await writeFile(
      file,
      `lattice:\n${body
        .split("\n")
        .map((line) => `  ${line}`)
        .join("\n")}`,
    );
    const wrapped = await adnaAdapter.project({ root, ...metadata });
    expect(wrapped.payload.model).toEqual(original.payload.model);
    expect(await adnaAdapter.evaluate(wrapped, createAdnaPortClaim(wrapped))).toBe("satisfied");
  });

  it("requires an explicit file when a directory contains several lattices", async () => {
    const root = await copyFixture("lighthouse-adna-multiple-");
    await cp(path.join(root, "orders.lattice.yaml"), path.join(root, "other.lattice.yaml"));
    await expect(adnaAdapter.project({ root, ...metadata })).rejects.toThrow(/multiple|explicit/i);
  });

  it("keeps named edge ports and distinguishes absent mapping from incompatibility", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lighthouse-adna-untyped-"));
    await writeFile(
      path.join(root, "untyped.lattice.yaml"),
      `lattice:
  name: untyped
  nodes:
    - id: publish_order
    - id: consume_order
  edges:
    - from: publish_order
      to: consume_order
      port: result
`,
    );
    const snapshot = await adnaAdapter.project({ root, ...metadata });
    expect(JSON.stringify(snapshot.payload.model)).toContain('"port":"result"');
    expect(await adnaAdapter.evaluate(snapshot, createAdnaPortClaim(snapshot))).toBe(
      "indeterminate",
    );
  });

  it("retains unresolved external references and does not invent their port types", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lighthouse-adna-external-"));
    await writeFile(
      path.join(root, "external.lattice.yaml"),
      `lattice:
  name: external
  nodes:
    - id: publish_order
      type: module
      ref: lattice://stanley/observations
    - id: consume_order
      type: process
  edges:
    - from: publish_order
      to: consume_order
      data_mapping:
        order_created: order_created
`,
    );
    const snapshot = await adnaAdapter.project({ root, ...metadata });
    expect(JSON.stringify(snapshot.payload.model)).toContain("lattice://stanley/observations");
    expect(await adnaAdapter.evaluate(snapshot, createAdnaPortClaim(snapshot))).toBe(
      "indeterminate",
    );
  });

  it.each([
    ["duplicate node", "nodes:\n  - id: a\n  - id: a\nedges: []"],
    ["missing endpoint", "nodes:\n  - id: a\nedges:\n  - from: a\n    to: missing"],
    ["invalid ports", "nodes:\n  - id: a\n    config:\n      inputs: [bad]\nedges: []"],
  ])("rejects %s rather than publishing a misleading projection", async (_label, body) => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lighthouse-adna-invalid-"));
    await writeFile(path.join(root, "bad.lattice.yaml"), `name: bad\n${body}\n`);
    await expect(adnaAdapter.project({ root, ...metadata })).rejects.toThrow();
  });

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

  it("keeps a proven connection satisfied when an incomplete parallel edge is added", async () => {
    const root = await copyFixture("lighthouse-adna-parallel-");
    const file = path.join(root, "orders.lattice.yaml");
    await writeFile(
      file,
      `${await readFile(file, "utf8")}  - from: publish_order\n    to: consume_order\n    port: another_output\n`,
    );
    const snapshot = await adnaAdapter.project({ root, ...metadata });
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
