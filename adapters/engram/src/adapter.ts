import { readdir, readFile, stat } from "node:fs/promises";
import path from "node:path";
import {
  type InstitutionAdapter,
  isSubcontext,
  type OperationResult,
  type ProjectionRequest,
} from "@lighthouse/calculus";
import {
  type Claim,
  type ContextRef,
  type Evaluation,
  type JsonValue,
  type Snapshot,
  sealArtifact,
} from "@lighthouse/protocol";
import {
  ENGRAM_PROFILE,
  ENGRAM_RECALL_RANK_CLAIM_MEDIA_TYPE,
  ENGRAM_SIGNATURE,
  parseEngramRankSentence,
} from "./claims.js";
import { contextStartsWith, type EngramModel, parseEngramExport } from "./export.js";

async function exportFile(root: string): Promise<string> {
  if ((await stat(root)).isFile()) return root;
  const candidates = (await readdir(root)).filter((file) => file.endsWith(".engram.json")).sort();
  if (candidates.length === 0) {
    throw new Error(`NO_ENGRAM_EXPORT: ${root}`);
  }
  if (candidates.length !== 1) {
    throw new Error(`AMBIGUOUS_ENGRAM_EXPORT: ${candidates.join(",")}`);
  }
  return path.join(root, candidates[0] as string);
}

function portableModel(model: EngramModel): JsonValue {
  if (model.formatVersion === "1.1") return model as unknown as JsonValue;
  const { receipts: _receipts, ...withoutReceipts } = model;
  return withoutReceipts as unknown as JsonValue;
}

async function projectEngram(request: ProjectionRequest): Promise<Snapshot> {
  const source = await exportFile(request.root);
  const model = parseEngramExport(JSON.parse(await readFile(source, "utf8")));
  return sealArtifact({
    kind: "Snapshot",
    protocolVersion: "0.1",
    id: request.id,
    issuedAt: request.issuedAt,
    issuer: request.issuer,
    payloadMediaType: "application/vnd.lighthouse.snapshot+json",
    payload: {
      profile: ENGRAM_PROFILE,
      signature: ENGRAM_SIGNATURE,
      context: model.context,
      model: portableModel(model),
      lineage: [],
    },
  });
}

export function engramModel(snapshot: Snapshot): EngramModel | undefined {
  if (
    snapshot.payload.profile.id !== ENGRAM_PROFILE.id ||
    snapshot.payload.profile.version !== ENGRAM_PROFILE.version
  ) {
    return undefined;
  }
  try {
    return parseEngramExport(snapshot.payload.model);
  } catch {
    return undefined;
  }
}

function outsideDomain(current: ContextRef, requested: ContextRef): OperationResult<never> {
  return {
    ok: false,
    obstruction: {
      code: "CONTEXT_OUTSIDE_DOMAIN",
      message: `${requested.id} is not within ${current.id}`,
      paths: [requested.id],
    },
  };
}

function restrictEngramSnapshot(
  snapshot: Snapshot,
  context: ContextRef,
): OperationResult<Snapshot> {
  if (!isSubcontext(snapshot.payload.context, context)) {
    return outsideDomain(snapshot.payload.context, context);
  }
  const model = engramModel(snapshot);
  if (model === undefined) {
    return {
      ok: false,
      obstruction: {
        code: "PROFILE_MISMATCH",
        message: `${snapshot.id} is not an Engram recall trace snapshot`,
        paths: [snapshot.id],
      },
    };
  }
  const memories = model.memories.filter((memory) =>
    contextStartsWith(context.path, memory.contextPath),
  );
  const surviving = new Set(memories.map(({ id }) => id));
  const restrictedModel: EngramModel = {
    ...model,
    context,
    memories,
    edges: model.edges.filter((edge) => surviving.has(edge.source) && surviving.has(edge.target)),
    recallTraces: model.recallTraces
      .filter((trace) => contextStartsWith(context.path, trace.contextPath))
      .map((trace) => ({
        ...trace,
        candidates: trace.candidates
          .filter((candidate) => surviving.has(candidate.memoryId))
          .map((candidate, index) => ({ ...candidate, rank: index + 1 })),
      })),
    receipts: model.receipts.filter((receipt) =>
      contextStartsWith(context.path, receipt.payload.context.path),
    ),
  };
  const { digest: _digest, attestations: _attestations, ...common } = snapshot;
  return {
    ok: true,
    value: sealArtifact({
      ...common,
      payload: {
        ...snapshot.payload,
        context,
        model: portableModel(restrictedModel),
      },
    }),
  };
}

function restrictEngramClaim(claim: Claim, context: ContextRef): OperationResult<Claim> {
  if (!isSubcontext(claim.payload.context, context)) {
    return outsideDomain(claim.payload.context, context);
  }
  const { digest: _digest, attestations: _attestations, ...common } = claim;
  return {
    ok: true,
    value: sealArtifact({ ...common, payload: { ...claim.payload, context } }),
  };
}

function evaluateEngram(snapshot: Snapshot, claim: Claim): Evaluation {
  if (
    claim.payload.profile.id !== ENGRAM_PROFILE.id ||
    claim.payload.profile.version !== ENGRAM_PROFILE.version ||
    claim.payload.sentenceMediaType !== ENGRAM_RECALL_RANK_CLAIM_MEDIA_TYPE
  ) {
    return "indeterminate";
  }
  const model = engramModel(snapshot);
  const sentence = parseEngramRankSentence(claim.payload.sentence);
  if (
    model === undefined ||
    sentence === undefined ||
    !model.memories.some((memory) => memory.id === sentence.memoryId)
  ) {
    return "indeterminate";
  }
  const traces = model.recallTraces.filter(
    (trace) =>
      trace.turnId === sentence.turnId &&
      contextStartsWith(claim.payload.context.path, trace.contextPath),
  );
  if (traces.length !== 1) return "indeterminate";
  const candidate = traces[0]?.candidates.find(({ memoryId }) => memoryId === sentence.memoryId);
  return candidate !== undefined && candidate.rank <= sentence.maxRank ? "satisfied" : "violated";
}

export const engramAdapter: InstitutionAdapter = {
  profile: ENGRAM_PROFILE,
  project: projectEngram,
  async restrictSnapshot(snapshot, context) {
    return restrictEngramSnapshot(snapshot, context);
  },
  async restrictClaim(claim, context) {
    return restrictEngramClaim(claim, context);
  },
  async evaluate(snapshot, claim) {
    return evaluateEngram(snapshot, claim);
  },
};
