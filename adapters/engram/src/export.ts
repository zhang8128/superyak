import {
  compareCanonicalJson,
  parseArtifact,
  type RecallReceipt,
  recallReceiptSchema,
  verifyArtifactDigest,
} from "@lighthouse/protocol";
import { z } from "zod";

const nonEmptyString = z.string().min(1);
const contextPathSchema = z.array(nonEmptyString).min(1);
const sha256DigestSchema = z
  .object({
    algorithm: z.literal("sha256"),
    value: z.string().regex(/^[0-9a-f]{64}$/),
  })
  .strict();

const memorySchema = z
  .object({
    id: nonEmptyString,
    layer: z.enum(["episode", "semantic", "instinct", "skill", "other"]),
    contentDigest: sha256DigestSchema,
    contextPath: contextPathSchema,
    lane: nonEmptyString,
    origin: z.enum(["lived", "organic", "external", "direct", "unknown"]),
  })
  .strict();

const edgeSchema = z
  .object({
    source: nonEmptyString,
    target: nonEmptyString,
    type: nonEmptyString,
    weight: z.number().finite().min(0).max(1),
    directed: z.boolean(),
  })
  .strict();

const recallTraceSchema = z
  .object({
    turnId: nonEmptyString,
    queryDigest: sha256DigestSchema,
    contextPath: contextPathSchema,
    candidates: z.array(
      z
        .object({
          memoryId: nonEmptyString,
          rank: z.number().int().positive(),
        })
        .strict(),
    ),
  })
  .strict();

const engramExportSchema = z
  .object({
    formatVersion: z.enum(["1.0", "1.1"]),
    instance: nonEmptyString,
    context: z
      .object({
        id: nonEmptyString,
        path: contextPathSchema,
      })
      .strict(),
    memories: z.array(memorySchema),
    edges: z.array(edgeSchema),
    recallTraces: z.array(recallTraceSchema),
    receipts: z.array(recallReceiptSchema).optional(),
  })
  .strict();

export type EngramMemory = z.infer<typeof memorySchema>;
export type EngramEdge = z.infer<typeof edgeSchema>;
export type EngramRecallTrace = z.infer<typeof recallTraceSchema>;
export type EngramExport = z.infer<typeof engramExportSchema>;
export type EngramModel = Omit<EngramExport, "receipts"> & { receipts: RecallReceipt[] };

export function contextStartsWith(parent: string[], child: string[]): boolean {
  return parent.every((segment, index) => child[index] === segment);
}

function fail(code: string, detail: string): never {
  throw new Error(`${code}: ${detail}`);
}

function validateMemories(model: EngramExport): Set<string> {
  const memoryIds = new Set<string>();
  for (const memory of model.memories) {
    if (memoryIds.has(memory.id)) fail("DUPLICATE_MEMORY_ID", memory.id);
    memoryIds.add(memory.id);
    if (!contextStartsWith(model.context.path, memory.contextPath)) {
      fail("CONTEXT_OUTSIDE_ROOT", memory.id);
    }
  }
  return memoryIds;
}

function validateEdges(model: EngramExport, memoryIds: Set<string>): void {
  for (const edge of model.edges) {
    if (!memoryIds.has(edge.source) || !memoryIds.has(edge.target)) {
      fail("DANGLING_EDGE", `${edge.source}->${edge.target}`);
    }
  }
}

function validateTraces(model: EngramExport, memoryIds: Set<string>): void {
  const traceKeys = new Set<string>();
  for (const trace of model.recallTraces) {
    if (!contextStartsWith(model.context.path, trace.contextPath)) {
      fail("CONTEXT_OUTSIDE_ROOT", trace.turnId);
    }
    const traceKey = JSON.stringify([trace.turnId, trace.contextPath]);
    if (traceKeys.has(traceKey)) fail("DUPLICATE_RECALL_TRACE", trace.turnId);
    traceKeys.add(traceKey);

    const ranks = new Set<number>();
    const candidateMemoryIds = new Set<string>();
    for (const candidate of trace.candidates) {
      if (!memoryIds.has(candidate.memoryId)) {
        fail("DANGLING_CANDIDATE", `${trace.turnId}:${candidate.memoryId}`);
      }
      if (ranks.has(candidate.rank)) {
        fail("DUPLICATE_CANDIDATE_RANK", `${trace.turnId}:${candidate.rank}`);
      }
      if (candidateMemoryIds.has(candidate.memoryId)) {
        fail("DUPLICATE_CANDIDATE_MEMORY", `${trace.turnId}:${candidate.memoryId}`);
      }
      ranks.add(candidate.rank);
      candidateMemoryIds.add(candidate.memoryId);
    }
    const orderedRanks = [...ranks].sort((left, right) => left - right);
    if (orderedRanks.some((rank, index) => rank !== index + 1)) {
      fail("NON_CONTIGUOUS_RANKS", trace.turnId);
    }
  }
}

function validateReceipts(model: EngramExport): RecallReceipt[] {
  const receipts = model.receipts ?? [];
  if (model.receipts !== undefined && model.formatVersion !== "1.1") {
    fail("RECEIPTS_REQUIRE_1_1", model.formatVersion);
  }
  const keys = new Set<string>();
  for (const receipt of receipts) {
    if (!verifyArtifactDigest(parseArtifact(receipt)).ok) {
      fail("RECEIPT_DIGEST_MISMATCH", receipt.id);
    }
    if (!contextStartsWith(model.context.path, receipt.payload.context.path)) {
      fail("CONTEXT_OUTSIDE_ROOT", receipt.id);
    }
    const key = JSON.stringify([receipt.payload.turnId, receipt.payload.context.id]);
    if (keys.has(key)) fail("DUPLICATE_RECEIPT", receipt.payload.turnId);
    keys.add(key);
  }
  return receipts.toSorted((left, right) =>
    compareCanonicalJson(
      [left.payload.turnId, left.payload.context.id],
      [right.payload.turnId, right.payload.context.id],
    ),
  );
}

export function parseEngramExport(input: unknown): EngramModel {
  const parsed = engramExportSchema.parse(input);
  const memoryIds = validateMemories(parsed);
  validateEdges(parsed, memoryIds);
  validateTraces(parsed, memoryIds);
  const receipts = validateReceipts(parsed);

  const model: EngramModel = {
    ...parsed,
    receipts,
    memories: parsed.memories.toSorted((left, right) => compareCanonicalJson(left.id, right.id)),
    edges: parsed.edges.toSorted((left, right) => compareCanonicalJson(left, right)),
    recallTraces: parsed.recallTraces
      .map((trace) => ({
        ...trace,
        candidates: trace.candidates.toSorted((left, right) => left.rank - right.rank),
      }))
      .toSorted((left, right) =>
        compareCanonicalJson([left.turnId, left.contextPath], [right.turnId, right.contextPath]),
      ),
  };
  if (model.formatVersion === "1.0") {
    Object.defineProperty(model, "receipts", {
      value: receipts,
      enumerable: false,
      configurable: true,
      writable: true,
    });
  }
  return model;
}
