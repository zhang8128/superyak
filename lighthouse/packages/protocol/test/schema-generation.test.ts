import { mkdtemp, readdir, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { Ajv2020 } from "ajv/dist/2020.js";
import { describe, expect, it } from "vitest";
import { generateSchemas } from "../../../scripts/generate-schemas.js";

describe("JSON Schema generation", () => {
  it("writes the complete schema set deterministically", async () => {
    const firstDirectory = await mkdtemp(path.join(os.tmpdir(), "lighthouse-schema-first-"));
    const secondDirectory = await mkdtemp(path.join(os.tmpdir(), "lighthouse-schema-second-"));

    await generateSchemas(firstDirectory);
    await generateSchemas(secondDirectory);

    const expectedFiles = [
      "bridge-descriptor.schema.json",
      "claim.schema.json",
      "connection-policy.schema.json",
      "lighthouse-descriptor.schema.json",
      "recall-receipt.schema.json",
      "snapshot.schema.json",
      "translation-witness.schema.json",
    ];
    expect(await readdir(firstDirectory)).toEqual(expectedFiles);

    for (const file of expectedFiles) {
      const first = await readFile(path.join(firstDirectory, file), "utf8");
      const second = await readFile(path.join(secondDirectory, file), "utf8");
      expect(second).toBe(first);
      expect(() => JSON.parse(first)).not.toThrow();
    }
  });

  it("preserves approximate-bridge evidence requirements for other languages", async () => {
    const directory = await mkdtemp(path.join(os.tmpdir(), "lighthouse-schema-bridge-"));
    await generateSchemas(directory);
    const schema = JSON.parse(
      await readFile(path.join(directory, "bridge-descriptor.schema.json"), "utf8"),
    );
    const validate = new Ajv2020({ strict: false, validateFormats: false }).compile(schema);

    const accepted = validate({
      kind: "BridgeDescriptor",
      protocolVersion: "0.1",
      id: "urn:bridge:approximate-without-evidence",
      issuedAt: "2026-08-30T12:00:00Z",
      issuer: "urn:lighthouse:bridge-author",
      payloadMediaType: "application/vnd.lighthouse.bridge+json",
      payload: {
        source: { id: "urn:profile:source", version: "1.0.0" },
        target: { id: "urn:profile:target", version: "1.0.0" },
        domain: { contexts: ["workflow"], claimMediaTypes: ["application/example"] },
        fidelity: "approximate",
        implementation: "urn:implementation:local-only",
        dependencies: [],
      },
      digest: { algorithm: "sha-256", value: "0".repeat(64) },
    });

    expect(accepted).toBe(false);
    expect(validate.errors?.some((error) => error.keyword === "required")).toBe(true);
  });

  it("rejects approximation contracts on exact bridges in other languages", async () => {
    const directory = await mkdtemp(path.join(os.tmpdir(), "lighthouse-schema-exact-"));
    await generateSchemas(directory);
    const schema = JSON.parse(
      await readFile(path.join(directory, "bridge-descriptor.schema.json"), "utf8"),
    );
    const validate = new Ajv2020({ strict: false, validateFormats: false }).compile(schema);

    const accepted = validate({
      kind: "BridgeDescriptor",
      protocolVersion: "0.1",
      id: "urn:bridge:exact-with-approximation",
      issuedAt: "2026-08-30T12:00:00Z",
      issuer: "urn:lighthouse:bridge-author",
      payloadMediaType: "application/vnd.lighthouse.bridge+json",
      payload: {
        source: { id: "urn:profile:source", version: "1.0.0" },
        target: { id: "urn:profile:target", version: "1.0.0" },
        domain: { contexts: ["workflow"], claimMediaTypes: ["application/example"] },
        fidelity: "exact",
        implementation: "urn:implementation:local-only",
        dependencies: [],
        approximation: {
          metric: "cosine-distance",
          tolerance: 0.01,
          evidenceProcedure: "urn:procedure:cosine-v1",
        },
      },
      digest: { algorithm: "sha-256", value: "0".repeat(64) },
    });

    expect(accepted).toBe(false);
    expect(validate.errors?.some((error) => error.keyword === "not")).toBe(true);
  });

  it("preserves the receipt injection invariant for other languages", async () => {
    const directory = await mkdtemp(path.join(os.tmpdir(), "lighthouse-schema-receipt-"));
    await generateSchemas(directory);
    const schema = JSON.parse(
      await readFile(path.join(directory, "recall-receipt.schema.json"), "utf8"),
    );
    const validate = new Ajv2020({ strict: false, validateFormats: false }).compile(schema);
    const base = {
      kind: "RecallReceipt",
      protocolVersion: "0.1",
      id: "urn:receipt:test",
      issuedAt: "2026-09-01T12:00:00Z",
      issuer: "urn:lighthouse:engram",
      payloadMediaType: "application/vnd.lighthouse.recall-receipt+json",
      payload: {
        turnId: "turn-1",
        context: { id: "memory/technical", path: ["memory", "technical"] },
        purpose: "session-recall",
        audience: "self",
        action: "recall",
        injected: true,
        transformation: "weighted-rrf-v1",
        receiverRule: { ruleId: null },
        sources: [],
        selected: [],
        delivered: [],
      },
      digest: { algorithm: "sha-256", value: "0".repeat(64) },
    };
    expect(validate(base)).toBe(false);
    expect(validate({ ...base, payload: { ...base.payload, injected: false } })).toBe(true);
  });
});
