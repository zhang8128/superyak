import {
  sealArtifact,
  type Claim,
  type ContextRef,
  type Snapshot,
} from "@lighthouse/protocol";
import { describe, expect, it } from "vitest";
import {
  checkRestrictionComposition,
  checkRestrictionIdentity,
  isSubcontext,
  type InstitutionAdapter,
  type OperationResult,
} from "../src/index.js";

const contexts = {
  workflow: { id: "workflow", path: ["workflow"] },
  orders: { id: "workflow/orders", path: ["workflow", "orders"] },
  contracts: {
    id: "workflow/orders/contracts",
    path: ["workflow", "orders", "contracts"],
  },
} satisfies Record<string, ContextRef>;

const snapshot = sealArtifact({
  kind: "Snapshot",
  protocolVersion: "0.1",
  id: "urn:snapshot:restriction-fixture",
  issuedAt: "2026-08-30T12:00:00Z",
  issuer: "urn:lighthouse:test",
  payloadMediaType: "application/vnd.lighthouse.snapshot+json",
  payload: {
    profile: { id: "urn:profile:restriction-fixture", version: "1.0.0" },
    signature: { id: "urn:signature:restriction-fixture", version: "1.0.0" },
    context: contexts.workflow,
    model: {
      records: [
        { id: "orders", contextPath: ["workflow", "orders"] },
        { id: "contracts", contextPath: ["workflow", "orders", "contracts"] },
        { id: "unrelated", contextPath: ["workflow", "unrelated"] },
      ],
    },
    lineage: [],
  },
});

function restrictSnapshot(
  current: Snapshot,
  context: ContextRef,
): OperationResult<Snapshot> {
  if (!isSubcontext(current.payload.context, context)) {
    return {
      ok: false,
      obstruction: {
        code: "CONTEXT_OUTSIDE_DOMAIN",
        message: `${context.id} is not within ${current.payload.context.id}`,
        paths: [context.id],
      },
    };
  }
  const model = current.payload.model as {
    records: Array<{ id: string; contextPath: string[] }>;
  };
  const { digest: _digest, ...unsigned } = current;
  return {
    ok: true,
    value: sealArtifact({
      ...unsigned,
      payload: {
        ...current.payload,
        context,
        model: {
          records: model.records.filter((record) =>
            context.path.every((segment, index) => record.contextPath[index] === segment),
          ),
        },
      },
    }),
  };
}

const adapter: InstitutionAdapter = {
  profile: { id: "urn:profile:restriction-fixture", version: "1.0.0" },
  async project() {
    return snapshot;
  },
  async restrictSnapshot(current, context) {
    return restrictSnapshot(current, context);
  },
  async restrictClaim(_claim: Claim, context: ContextRef) {
    return {
      ok: false,
      obstruction: {
        code: "CLAIM_RESTRICTION_UNSUPPORTED",
        message: "The fixture has no claims",
        paths: [context.id],
      },
    };
  },
  async evaluate() {
    return "indeterminate";
  },
};

describe("restriction laws", () => {
  it("preserves the semantic model under identity restriction", async () => {
    expect(await checkRestrictionIdentity(adapter, snapshot)).toEqual({ passed: true });
  });

  it("makes two-step restriction agree with direct restriction", async () => {
    expect(
      await checkRestrictionComposition(adapter, snapshot, contexts.orders, contexts.contracts),
    ).toEqual({ passed: true });
  });

  it("returns an obstruction outside the declared context", () => {
    expect(restrictSnapshot(snapshot, { id: "finance", path: ["finance"] })).toEqual({
      ok: false,
      obstruction: {
        code: "CONTEXT_OUTSIDE_DOMAIN",
        message: "finance is not within workflow",
        paths: ["finance"],
      },
    });
  });
});
