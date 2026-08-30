import { readFile } from "node:fs/promises";
import path from "node:path";
import {
  ADNA_PORT_CLAIM_MEDIA_TYPE,
  ADNA_PROFILE,
  adnaAdapter,
} from "@lighthouse/adapter-adna";
import {
  HYPER_DEPENDENCY_MEDIA_TYPE,
  HYPER_PROFILE,
  createHyperDependencyClaim,
  createHyperLeaseClaim,
  hyperAdapter,
} from "@lighthouse/adapter-hyper";
import {
  composeBridges,
  identityBridge,
  translateWithWitness,
} from "@lighthouse/calculus";
import { describe, expect, it } from "vitest";
import {
  createHyperAdnaBridge,
  type HyperAdnaMapping,
} from "../src/index.js";

const root = path.resolve(import.meta.dirname, "../../..");
const issuedAt = "2026-08-30T12:00:00Z";
const metadata = {
  id: "urn:bridge:hyper-adna-orders",
  issuer: "urn:lighthouse:bridge-author",
  issuedAt,
};

async function readMapping(name: string): Promise<HyperAdnaMapping> {
  return JSON.parse(await readFile(path.join(root, "fixtures/bridges", name), "utf8"));
}

async function referenceState() {
  const hyperSnapshot = await hyperAdapter.project({
    root: path.join(root, "fixtures/hyper/orders"),
    id: "urn:snapshot:hyper-orders",
    issuer: "urn:lighthouse:hyper-local",
    issuedAt,
  });
  const adnaSnapshot = await adnaAdapter.project({
    root: path.join(root, "fixtures/adna"),
    id: "urn:snapshot:adna-orders",
    issuer: "urn:lighthouse:adna-local",
    issuedAt,
  });
  return { hyperSnapshot, adnaSnapshot };
}

describe("Hyper to aDNA bridge", () => {
  it("translates the shared dependency claim", async () => {
    const { hyperSnapshot } = await referenceState();
    const bridge = createHyperAdnaBridge(await readMapping("hyper-adna.json"), metadata);

    const translated = await bridge.translateClaim(createHyperDependencyClaim(hyperSnapshot));

    expect(translated.ok).toBe(true);
    if (translated.ok) {
      expect(translated.value.payload.sentenceMediaType).toBe(ADNA_PORT_CLAIM_MEDIA_TYPE);
      expect(translated.value.payload.sentence).toEqual({
        outputNodeId: "publish_order",
        outputPort: "order_created",
        inputNodeId: "consume_order",
        inputPort: "order_created",
        valueType: "application/vnd.example.order+json",
      });
    }
  });

  it("leaves Hyper lease semantics explicitly unmapped", async () => {
    const { hyperSnapshot } = await referenceState();
    const bridge = createHyperAdnaBridge(await readMapping("hyper-adna.json"), metadata);

    expect(await bridge.translateClaim(createHyperLeaseClaim(hyperSnapshot))).toEqual({
      ok: false,
      obstruction: {
        code: "BRIDGE_CLAIM_UNMAPPED",
        message: "Hyper lease claims are outside the v0.1 bridge domain",
        paths: ["payload.sentence"],
      },
    });
  });

  it("preserves independent local satisfaction", async () => {
    const { hyperSnapshot, adnaSnapshot } = await referenceState();
    const bridge = createHyperAdnaBridge(await readMapping("hyper-adna.json"), metadata);

    const result = await translateWithWitness(
      bridge,
      createHyperDependencyClaim(hyperSnapshot),
      hyperAdapter,
      hyperSnapshot,
      adnaAdapter,
      adnaSnapshot,
    );

    expect(result.witness.payload.sourceEvaluation).toBe("satisfied");
    expect(result.witness.payload.targetEvaluation).toBe("satisfied");
    expect(result.witness.payload.outcome).toBe("preserved");
  });

  it("rejects a mapping that changes the value type", async () => {
    const { hyperSnapshot, adnaSnapshot } = await referenceState();
    const bridge = createHyperAdnaBridge(await readMapping("hyper-adna-invalid.json"), {
      ...metadata,
      id: "urn:bridge:hyper-adna-orders-invalid",
    });

    const result = await translateWithWitness(
      bridge,
      createHyperDependencyClaim(hyperSnapshot),
      hyperAdapter,
      hyperSnapshot,
      adnaAdapter,
      adnaSnapshot,
    );

    expect(result.witness.payload.targetEvaluation).toBe("violated");
    expect(result.witness.payload.outcome).toBe("invalid");
    expect(result.witness.payload.diagnostics[0]?.code).toBe(
      "SATISFACTION_NOT_PRESERVED",
    );
  });

  it("composes associatively with source and target identities", async () => {
    const { hyperSnapshot } = await referenceState();
    const bridge = createHyperAdnaBridge(await readMapping("hyper-adna.json"), metadata);
    const sourceIdentity = identityBridge(HYPER_PROFILE, [HYPER_DEPENDENCY_MEDIA_TYPE], {
      ...metadata,
      id: "urn:bridge:hyper-identity",
    });
    const targetIdentity = identityBridge(ADNA_PROFILE, [ADNA_PORT_CLAIM_MEDIA_TYPE], {
      ...metadata,
      id: "urn:bridge:adna-identity",
    });
    const left = composeBridges(
      composeBridges(sourceIdentity, bridge, { ...metadata, id: "urn:bridge:left-a" }),
      targetIdentity,
      { ...metadata, id: "urn:bridge:left-b" },
    );
    const right = composeBridges(
      sourceIdentity,
      composeBridges(bridge, targetIdentity, { ...metadata, id: "urn:bridge:right-a" }),
      { ...metadata, id: "urn:bridge:right-b" },
    );
    const claim = createHyperDependencyClaim(hyperSnapshot);
    const leftResult = await left.translateClaim(claim);
    const rightResult = await right.translateClaim(claim);

    expect(left.lineage.map((item) => item.digest)).toEqual(
      right.lineage.map((item) => item.digest),
    );
    expect(leftResult.ok).toBe(true);
    expect(rightResult.ok).toBe(true);
    if (leftResult.ok && rightResult.ok) {
      expect(leftResult.value.digest).toEqual(rightResult.value.digest);
    }
  });
});
