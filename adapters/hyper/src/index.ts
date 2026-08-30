import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import {
  isSubcontext,
  type InstitutionAdapter,
  type OperationResult,
  type ProjectionRequest,
} from "@lighthouse/calculus";
import {
  sealArtifact,
  type Claim,
  type ContextRef,
  type Evaluation,
  type JsonValue,
  type ProfileRef,
  type Snapshot,
} from "@lighthouse/protocol";

export const HYPER_PROFILE = {
  id: "urn:lighthouse:profile:hyper-modules",
  version: "1.0.0",
} satisfies ProfileRef;

export const HYPER_DEPENDENCY_MEDIA_TYPE = "application/vnd.hyper.dependency-claim+json";
export const HYPER_LEASE_MEDIA_TYPE = "application/vnd.hyper.lease-claim+json";

interface HyperBrickResource {
  id: string;
  kind: "brick";
  version: string;
  contextPath: string[];
}

interface HyperEventSchemaResource {
  id: string;
  kind: "event-schema";
  topic: string;
  mediaType: string;
  contextPath: string[];
}

export type HyperResource = HyperBrickResource | HyperEventSchemaResource;

export interface HyperEdge {
  from: string;
  to: string;
  kind: "PUBLISHES" | "SUBSCRIBES";
  topic: string;
  contextPath: string[];
}

export interface HyperModel {
  resources: HyperResource[];
  edges: HyperEdge[];
}

interface EventDeclaration {
  schema: string;
}

interface BrickDescriptor {
  id: string;
  version: string;
  events: {
    publishes: Record<string, EventDeclaration>;
    subscribes: Record<string, EventDeclaration>;
  };
}

async function filesBelow(root: string): Promise<string[]> {
  const entries = await readdir(root, { withFileTypes: true });
  const files: string[] = [];
  for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
    const absolute = path.join(root, entry.name);
    if (entry.isDirectory()) files.push(...(await filesBelow(absolute)));
    else if (entry.isFile()) files.push(absolute);
  }
  return files;
}

async function readJson(file: string): Promise<unknown> {
  return JSON.parse(await readFile(file, "utf8"));
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function parseEventSchema(value: unknown, file: string): { topic: string; mediaType: string } {
  const record = asRecord(value);
  if (typeof record?.$id !== "string" || typeof record.mediaType !== "string") {
    throw new Error(`Invalid Hyper event schema ${file}`);
  }
  return { topic: record.$id, mediaType: record.mediaType };
}

function parseBrick(value: unknown, file: string): BrickDescriptor {
  const record = asRecord(value);
  const events = asRecord(record?.events);
  const publishes = asRecord(events?.publishes);
  const subscribes = asRecord(events?.subscribes);
  if (
    typeof record?.id !== "string" ||
    typeof record.version !== "string" ||
    publishes === undefined ||
    subscribes === undefined
  ) {
    throw new Error(`Invalid Hyper brick descriptor ${file}`);
  }
  return {
    id: record.id,
    version: record.version,
    events: {
      publishes: publishes as Record<string, EventDeclaration>,
      subscribes: subscribes as Record<string, EventDeclaration>,
    },
  };
}

function sortModel(model: HyperModel): HyperModel {
  return {
    resources: model.resources.sort((left, right) => left.id.localeCompare(right.id)),
    edges: model.edges.sort((left, right) =>
      `${left.kind}:${left.from}:${left.to}:${left.topic}`.localeCompare(
        `${right.kind}:${right.from}:${right.to}:${right.topic}`,
      ),
    ),
  };
}

async function projectHyper(request: ProjectionRequest): Promise<Snapshot> {
  const allFiles = await filesBelow(request.root);
  const resources: HyperResource[] = [];
  const edges: HyperEdge[] = [];
  const schemas = new Map<string, HyperEventSchemaResource>();

  for (const file of allFiles.filter((candidate) => candidate.endsWith(".schema.json"))) {
    const schema = parseEventSchema(await readJson(file), path.relative(request.root, file));
    const namespace = schema.topic.split(".")[0] ?? "shared";
    const resource: HyperEventSchemaResource = {
      id: `event-schema:${schema.topic}`,
      kind: "event-schema",
      topic: schema.topic,
      mediaType: schema.mediaType,
      contextPath: ["workflow", namespace, "contracts"],
    };
    schemas.set(schema.topic, resource);
    resources.push(resource);
  }

  for (const file of allFiles.filter((candidate) => candidate.endsWith("/brick.json"))) {
    const brick = parseBrick(await readJson(file), path.relative(request.root, file));
    const namespace = brick.id.split(":")[0] ?? "shared";
    resources.push({
      id: brick.id,
      kind: "brick",
      version: brick.version,
      contextPath: ["workflow", namespace],
    });
    for (const topic of Object.keys(brick.events.publishes).sort()) {
      if (!schemas.has(topic)) throw new Error(`Brick ${brick.id} publishes missing schema ${topic}`);
      edges.push({
        from: brick.id,
        to: `event-schema:${topic}`,
        kind: "PUBLISHES",
        topic,
        contextPath: ["workflow", namespace],
      });
    }
    for (const topic of Object.keys(brick.events.subscribes).sort()) {
      if (!schemas.has(topic)) throw new Error(`Brick ${brick.id} subscribes to missing schema ${topic}`);
      edges.push({
        from: brick.id,
        to: `event-schema:${topic}`,
        kind: "SUBSCRIBES",
        topic,
        contextPath: ["workflow", namespace],
      });
    }
  }

  const model = sortModel({ resources, edges });
  return sealArtifact({
    kind: "Snapshot",
    protocolVersion: "0.1",
    id: request.id,
    issuedAt: request.issuedAt,
    issuer: request.issuer,
    payloadMediaType: "application/vnd.lighthouse.snapshot+json",
    payload: {
      profile: HYPER_PROFILE,
      signature: { id: "urn:lighthouse:signature:hyper-modules", version: "1.0.0" },
      context: { id: "workflow", path: ["workflow"] },
      model: model as unknown as JsonValue,
      lineage: [],
    },
  });
}

function hyperModel(snapshot: Snapshot): HyperModel {
  return snapshot.payload.model as unknown as HyperModel;
}

function contextContains(context: ContextRef, pathSegments: string[]): boolean {
  return context.path.every((segment, index) => pathSegments[index] === segment);
}

function restrictHyperSnapshot(
  snapshot: Snapshot,
  context: ContextRef,
): OperationResult<Snapshot> {
  if (!isSubcontext(snapshot.payload.context, context)) {
    return {
      ok: false,
      obstruction: {
        code: "CONTEXT_OUTSIDE_DOMAIN",
        message: `${context.id} is not within ${snapshot.payload.context.id}`,
        paths: [context.id],
      },
    };
  }
  const model = hyperModel(snapshot);
  const restricted = sortModel({
    resources: model.resources.filter((resource) => contextContains(context, resource.contextPath)),
    edges: model.edges.filter((edge) => contextContains(context, edge.contextPath)),
  });
  const { digest: _digest, attestations: _attestations, ...common } = snapshot;
  return {
    ok: true,
    value: sealArtifact({
      ...common,
      payload: {
        ...snapshot.payload,
        context,
        model: restricted as unknown as JsonValue,
      },
    }),
  };
}

function restrictHyperClaim(claim: Claim, context: ContextRef): OperationResult<Claim> {
  if (!isSubcontext(claim.payload.context, context)) {
    return {
      ok: false,
      obstruction: {
        code: "CONTEXT_OUTSIDE_DOMAIN",
        message: `${context.id} is not within ${claim.payload.context.id}`,
        paths: [context.id],
      },
    };
  }
  const { digest: _digest, attestations: _attestations, ...common } = claim;
  return {
    ok: true,
    value: sealArtifact({
      ...common,
      payload: { ...claim.payload, context },
    }),
  };
}

function evaluateHyper(snapshot: Snapshot, claim: Claim): Evaluation {
  if (
    snapshot.payload.profile.id !== HYPER_PROFILE.id ||
    claim.payload.profile.id !== HYPER_PROFILE.id ||
    claim.payload.sentenceMediaType !== HYPER_DEPENDENCY_MEDIA_TYPE
  ) {
    return "indeterminate";
  }
  const sentence = asRecord(claim.payload.sentence);
  if (
    typeof sentence?.producerId !== "string" ||
    typeof sentence.consumerId !== "string" ||
    typeof sentence.topic !== "string" ||
    typeof sentence.valueType !== "string"
  ) {
    return "indeterminate";
  }
  const model = hyperModel(snapshot);
  const target = `event-schema:${sentence.topic}`;
  const eventSchema = model.resources.find(
    (resource): resource is HyperEventSchemaResource =>
      resource.kind === "event-schema" && resource.id === target,
  );
  const publishes = model.edges.some(
    (edge) =>
      edge.kind === "PUBLISHES" && edge.from === sentence.producerId && edge.to === target,
  );
  const subscribes = model.edges.some(
    (edge) =>
      edge.kind === "SUBSCRIBES" && edge.from === sentence.consumerId && edge.to === target,
  );
  return publishes && subscribes && eventSchema?.mediaType === sentence.valueType
    ? "satisfied"
    : "violated";
}

export const hyperAdapter: InstitutionAdapter = {
  profile: HYPER_PROFILE,
  project: projectHyper,
  async restrictSnapshot(snapshot, context) {
    return restrictHyperSnapshot(snapshot, context);
  },
  async restrictClaim(claim, context) {
    return restrictHyperClaim(claim, context);
  },
  async evaluate(snapshot, claim) {
    return evaluateHyper(snapshot, claim);
  },
};

export function createHyperDependencyClaim(snapshot: Snapshot): Claim {
  return sealArtifact({
    kind: "Claim",
    protocolVersion: "0.1",
    id: "urn:claim:hyper-orders-dependency",
    issuedAt: snapshot.issuedAt,
    issuer: snapshot.issuer,
    payloadMediaType: "application/vnd.lighthouse.claim+json",
    payload: {
      profile: HYPER_PROFILE,
      signature: snapshot.payload.signature,
      context: { id: "workflow/orders", path: ["workflow", "orders"] },
      sentenceMediaType: HYPER_DEPENDENCY_MEDIA_TYPE,
      sentence: {
        producerId: "orders:producer",
        consumerId: "orders:consumer",
        topic: "orders.created.v1",
        valueType: "application/vnd.example.order+json",
      },
      snapshotDigests: [snapshot.digest],
      provenance: [],
    },
  });
}

export function createHyperLeaseClaim(snapshot: Snapshot): Claim {
  return sealArtifact({
    kind: "Claim",
    protocolVersion: "0.1",
    id: "urn:claim:hyper-orders-lease",
    issuedAt: snapshot.issuedAt,
    issuer: snapshot.issuer,
    payloadMediaType: "application/vnd.lighthouse.claim+json",
    payload: {
      profile: HYPER_PROFILE,
      signature: snapshot.payload.signature,
      context: { id: "workflow/orders", path: ["workflow", "orders"] },
      sentenceMediaType: HYPER_LEASE_MEDIA_TYPE,
      sentence: { resourceId: "orders:producer", holder: "urn:agent:worker-1", fencingToken: 7 },
      snapshotDigests: [snapshot.digest],
      provenance: [],
    },
  });
}
