import { cp, mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { checkRestrictionComposition, checkRestrictionIdentity } from "@lighthouse/calculus";
import { type Claim, sealArtifact } from "@lighthouse/protocol";
import { describe, expect, it } from "vitest";
import {
  createEngramRankClaim,
  ENGRAM_RECALL_RANK_CLAIM_MEDIA_TYPE,
  engramAdapter,
  engramModel,
} from "../src/index.js";

const metadata = {
  id: "urn:snapshot:engram-test",
  issuer: "urn:lighthouse:test-memory",
  issuedAt: "2026-08-30T12:00:00Z",
};

function sourceDocument(): Record<string, unknown> {
  return {
    formatVersion: "1.0",
    instance: "test-memory",
    context: { id: "memory", path: ["memory"] },
    memories: [
      {
        id: "memory-a",
        layer: "episode",
        contentDigest: { algorithm: "sha256", value: "a".repeat(64) },
        contextPath: ["memory", "debugging"],
        lane: "technical",
        origin: "lived",
      },
      {
        id: "memory-b",
        layer: "semantic",
        contentDigest: { algorithm: "sha256", value: "b".repeat(64) },
        contextPath: ["memory", "debugging", "mcp"],
        lane: "technical",
        origin: "organic",
      },
    ],
    edges: [
      {
        source: "memory-a",
        target: "memory-b",
        type: "provenance",
        weight: 0.8,
        directed: true,
      },
    ],
    recallTraces: [
      {
        turnId: "turn-1",
        queryDigest: { algorithm: "sha256", value: "c".repeat(64) },
        contextPath: ["memory", "debugging", "mcp"],
        candidates: [
          { memoryId: "memory-b", rank: 1 },
          { memoryId: "memory-a", rank: 2 },
        ],
      },
    ],
  };
}

function receiptAt(contextPath: string[]) {
  const turnId = contextPath.join("-");
  return sealArtifact({
    kind: "RecallReceipt",
    protocolVersion: "0.1",
    id: `urn:receipt:${turnId}`,
    issuedAt: "2026-09-01T12:00:00Z",
    issuer: "urn:lighthouse:engram",
    payloadMediaType: "application/vnd.lighthouse.recall-receipt+json",
    payload: {
      turnId,
      context: { id: contextPath.join("/"), path: contextPath },
      purpose: "session-recall",
      audience: "self",
      action: "recall",
      injected: false,
      transformation: "weighted-rrf-v1",
      receiverRule: { ruleId: null },
      sources: [],
      selected: [],
      delivered: [],
    },
  });
}

async function sourceDirectory(prefix: string): Promise<string> {
  const root = await mkdtemp(path.join(os.tmpdir(), prefix));
  await writeFile(path.join(root, "sample.engram.json"), JSON.stringify(sourceDocument()));
  return root;
}

function withClaimPayload(claim: Claim, payload: Partial<Claim["payload"]>): Claim {
  const { digest: _digest, attestations: _attestations, ...common } = claim;
  return sealArtifact({ ...common, payload: { ...claim.payload, ...payload } });
}

describe("Engram trace adapter", () => {
  it("projects the same sealed snapshot from different checkout paths", async () => {
    const source = await sourceDirectory("lighthouse-engram-source-");
    const first = await mkdtemp(path.join(os.tmpdir(), "lighthouse-engram-first-"));
    const second = await mkdtemp(path.join(os.tmpdir(), "lighthouse-engram-second-"));
    await cp(source, first, { recursive: true });
    await cp(source, second, { recursive: true });

    const firstSnapshot = await engramAdapter.project({ root: first, ...metadata });
    const secondSnapshot = await engramAdapter.project({ root: second, ...metadata });

    expect(secondSnapshot.payload.model).toEqual(firstSnapshot.payload.model);
    expect(secondSnapshot.digest).toEqual(firstSnapshot.digest);
  });

  it("rejects a directory with an ambiguous export", async () => {
    const root = await sourceDirectory("lighthouse-engram-ambiguous-");
    await writeFile(path.join(root, "second.engram.json"), JSON.stringify(sourceDocument()));

    await expect(engramAdapter.project({ root, ...metadata })).rejects.toThrow(
      "AMBIGUOUS_ENGRAM_EXPORT",
    );
  });

  it("obeys restriction identity and composition", async () => {
    const snapshot = await engramAdapter.project({
      root: await sourceDirectory("lighthouse-engram-laws-"),
      ...metadata,
    });

    expect(await checkRestrictionIdentity(engramAdapter, snapshot)).toEqual({ passed: true });
    expect(
      await checkRestrictionComposition(
        engramAdapter,
        snapshot,
        { id: "memory/debugging", path: ["memory", "debugging"] },
        { id: "memory/debugging/mcp", path: ["memory", "debugging", "mcp"] },
      ),
    ).toEqual({ passed: true });
  });

  it("restriction keeps only receipts inside the requested context", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "lighthouse-engram-receipts-"));
    const document = {
      ...sourceDocument(),
      formatVersion: "1.1",
      receipts: [
        receiptAt(["memory", "debugging", "mcp"]),
        receiptAt(["memory", "debugging", "bridge"]),
      ],
    };
    await writeFile(path.join(root, "receiver.engram.json"), JSON.stringify(document));
    const snapshot = await engramAdapter.project({ root, ...metadata });
    const restricted = await engramAdapter.restrictSnapshot(snapshot, {
      id: "memory/debugging/mcp",
      path: ["memory", "debugging", "mcp"],
    });
    if (!restricted.ok) throw new Error(restricted.obstruction.code);
    expect(engramModel(restricted.value)?.receipts).toHaveLength(1);
  });

  it("returns an honest obstruction outside the snapshot domain", async () => {
    const snapshot = await engramAdapter.project({
      root: await sourceDirectory("lighthouse-engram-obstruction-"),
      ...metadata,
    });

    expect(
      await engramAdapter.restrictSnapshot(snapshot, { id: "workflow", path: ["workflow"] }),
    ).toEqual({
      ok: false,
      obstruction: {
        code: "CONTEXT_OUTSIDE_DOMAIN",
        message: "workflow is not within memory",
        paths: ["workflow"],
      },
    });
  });

  it("satisfies only rank claims at or below the recorded bound", async () => {
    const snapshot = await engramAdapter.project({
      root: await sourceDirectory("lighthouse-engram-evaluation-"),
      ...metadata,
    });

    expect(
      await engramAdapter.evaluate(
        snapshot,
        createEngramRankClaim(snapshot, { turnId: "turn-1", memoryId: "memory-b", maxRank: 1 }),
      ),
    ).toBe("satisfied");
    expect(
      await engramAdapter.evaluate(
        snapshot,
        createEngramRankClaim(snapshot, { turnId: "turn-1", memoryId: "memory-a", maxRank: 1 }),
      ),
    ).toBe("violated");
  });

  it("stays indeterminate for claims outside its language or evidence", async () => {
    const snapshot = await engramAdapter.project({
      root: await sourceDirectory("lighthouse-engram-indeterminate-"),
      ...metadata,
    });
    const known = createEngramRankClaim(snapshot, {
      turnId: "turn-1",
      memoryId: "memory-b",
      maxRank: 1,
    });
    const unknownMediaType = withClaimPayload(known, {
      sentenceMediaType: "application/vnd.example.unknown+json",
    });
    const outsideTraceContext = withClaimPayload(known, {
      context: { id: "memory/relationship", path: ["memory", "relationship"] },
    });

    expect(known.payload.sentenceMediaType).toBe(ENGRAM_RECALL_RANK_CLAIM_MEDIA_TYPE);
    expect(await engramAdapter.evaluate(snapshot, unknownMediaType)).toBe("indeterminate");
    expect(
      await engramAdapter.evaluate(
        snapshot,
        createEngramRankClaim(snapshot, {
          turnId: "missing-turn",
          memoryId: "memory-b",
          maxRank: 1,
        }),
      ),
    ).toBe("indeterminate");
    expect(
      await engramAdapter.evaluate(
        snapshot,
        createEngramRankClaim(snapshot, {
          turnId: "turn-1",
          memoryId: "missing-memory",
          maxRank: 1,
        }),
      ),
    ).toBe("indeterminate");
    expect(await engramAdapter.evaluate(snapshot, outsideTraceContext)).toBe("indeterminate");
  });
});
