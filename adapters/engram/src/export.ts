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
    formatVersion: z.literal("1.0"),
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
  })
  .strict();

export type EngramMemory = z.infer<typeof memorySchema>;
export type EngramEdge = z.infer<typeof edgeSchema>;
export type EngramRecallTrace = z.infer<typeof recallTraceSchema>;
export type EngramExport = z.infer<typeof engramExportSchema>;
export type EngramModel = EngramExport;

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
    for (const candidate of trace.candidates) {
      if (!memoryIds.has(candidate.memoryId)) {
        fail("DANGLING_CANDIDATE", `${trace.turnId}:${candidate.memoryId}`);
      }
      if (ranks.has(candidate.rank)) {
        fail("DUPLICATE_CANDIDATE_RANK", `${trace.turnId}:${candidate.rank}`);
      }
      ranks.add(candidate.rank);
    }
    const orderedRanks = [...ranks].sort((left, right) => left - right);
    if (orderedRanks.some((rank, index) => rank !== index + 1)) {
      fail("NON_CONTIGUOUS_RANKS", trace.turnId);
    }
  }
}

export function parseEngramExport(input: unknown): EngramModel {
  const parsed = engramExportSchema.parse(input);
  const memoryIds = validateMemories(parsed);
  validateEdges(parsed, memoryIds);
  validateTraces(parsed, memoryIds);

  return {
    ...parsed,
    memories: parsed.memories.toSorted((left, right) => left.id.localeCompare(right.id)),
    edges: parsed.edges.toSorted((left, right) =>
      `${left.source}\u0000${left.target}\u0000${left.type}`.localeCompare(
        `${right.source}\u0000${right.target}\u0000${right.type}`,
      ),
    ),
    recallTraces: parsed.recallTraces
      .map((trace) => ({
        ...trace,
        candidates: trace.candidates.toSorted((left, right) => left.rank - right.rank),
      }))
      .toSorted((left, right) =>
        `${left.turnId}\u0000${left.contextPath.join("/")}`.localeCompare(
          `${right.turnId}\u0000${right.contextPath.join("/")}`,
        ),
      ),
  };
}
