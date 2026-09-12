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
  type ProfileRef,
  type Snapshot,
  sealArtifact,
} from "@lighthouse/protocol";
import { parse as parseYaml } from "yaml";

export const ADNA_PROFILE = {
  id: "urn:lighthouse:profile:adna-lattice",
  version: "1.0.0",
} satisfies ProfileRef;

export const ADNA_PORT_CLAIM_MEDIA_TYPE = "application/vnd.adna.port-compatibility-claim+json";

export interface AdnaNode {
  id: string;
  ref?: string;
  inputs: Record<string, string>;
  outputs: Record<string, string>;
  contextPath: string[];
}

export interface AdnaEdge {
  from: string;
  to: string;
  port?: string;
  dataMapping: Record<string, string>;
  contextPath: string[];
}

export interface AdnaModel {
  nodes: AdnaNode[];
  edges: AdnaEdge[];
}

export interface AdnaPortClaimInput {
  outputNodeId: string;
  outputPort: string;
  inputNodeId: string;
  inputPort: string;
  valueType: string;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function stringRecord(value: unknown, label: string): Record<string, string> {
  const record = value === undefined ? {} : asRecord(value);
  if (record === undefined) throw new Error(`${label} must be an object`);
  const result: Record<string, string> = {};
  for (const key of Object.keys(record).sort()) {
    const item = record[key];
    if (typeof item !== "string") throw new Error(`${label}.${key} must be a string`);
    result[key] = item;
  }
  return result;
}

async function latticeFile(root: string): Promise<string> {
  if ((await stat(root)).isFile()) return root;
  const candidates = (await readdir(root))
    .filter((file) => file.endsWith(".lattice.yaml") || file.endsWith(".lattice.yml"))
    .sort();
  const selected = candidates[0];
  if (selected === undefined) throw new Error(`No aDNA lattice YAML found in ${root}`);
  if (candidates.length !== 1)
    throw new Error("Multiple aDNA lattices found; select an explicit file");
  return path.join(root, selected);
}

function parseLattice(value: unknown): { name: string; model: AdnaModel } {
  const document = asRecord(value);
  const lattice = document && "lattice" in document ? asRecord(document.lattice) : document;
  if (document && "lattice" in document && ("nodes" in document || "name" in document)) {
    throw new Error("Ambiguous aDNA lattice envelope");
  }
  if (
    typeof lattice?.name !== "string" ||
    !Array.isArray(lattice.nodes) ||
    !Array.isArray(lattice.edges)
  ) {
    throw new Error("Invalid aDNA lattice: name, nodes, and edges are required");
  }
  const contextPath = ["workflow", lattice.name];
  const nodes: AdnaNode[] = [];
  const ids = new Set<string>();
  for (const item of lattice.nodes) {
    const node = asRecord(item);
    const config = node?.config === undefined ? {} : asRecord(node.config);
    if (config === undefined) throw new Error("Invalid aDNA node config");
    if (typeof node?.id !== "string" || !node.id || ids.has(node.id))
      throw new Error("Invalid or duplicate aDNA node id");
    ids.add(node.id);
    if (node.id === "lattice_interface") continue;
    if (node.ref !== undefined && (typeof node.ref !== "string" || !node.ref))
      throw new Error("Invalid aDNA node reference");
    nodes.push({
      id: node.id,
      ...(typeof node.ref === "string" ? { ref: node.ref } : {}),
      inputs: stringRecord(config.inputs, `${node.id}.inputs`),
      outputs: stringRecord(config.outputs, `${node.id}.outputs`),
      contextPath,
    });
  }
  const edges: AdnaEdge[] = lattice.edges.map((item) => {
    const edge = asRecord(item);
    if (typeof edge?.from !== "string" || typeof edge.to !== "string") {
      throw new Error("Invalid aDNA edge endpoints");
    }
    if (!nodes.some((n) => n.id === edge.from) || !nodes.some((n) => n.id === edge.to)) {
      throw new Error("aDNA edge has a missing executable endpoint");
    }
    if (edge.port !== undefined && typeof edge.port !== "string")
      throw new Error("Invalid aDNA edge port");
    return {
      from: edge.from,
      to: edge.to,
      ...(typeof edge.port === "string" ? { port: edge.port } : {}),
      dataMapping: stringRecord(edge.data_mapping, `${edge.from}->${edge.to}.data_mapping`),
      contextPath,
    };
  });
  return {
    name: lattice.name,
    model: {
      nodes: nodes.sort((left, right) => left.id.localeCompare(right.id)),
      edges: edges.sort((left, right) =>
        `${left.from}:${left.to}`.localeCompare(`${right.from}:${right.to}`),
      ),
    },
  };
}

async function projectAdna(request: ProjectionRequest): Promise<Snapshot> {
  const file = await latticeFile(request.root);
  const lattice = parseLattice(parseYaml(await readFile(file, "utf8")));
  return sealArtifact({
    kind: "Snapshot",
    protocolVersion: "0.1",
    id: request.id,
    issuedAt: request.issuedAt,
    issuer: request.issuer,
    payloadMediaType: "application/vnd.lighthouse.snapshot+json",
    payload: {
      profile: ADNA_PROFILE,
      signature: { id: "urn:lighthouse:signature:adna-lattice", version: "1.0.0" },
      context: { id: "workflow", path: ["workflow"] },
      model: lattice.model as unknown as JsonValue,
      lineage: [],
    },
  });
}

function adnaModel(snapshot: Snapshot): AdnaModel {
  return snapshot.payload.model as unknown as AdnaModel;
}

function contextContains(context: ContextRef, candidate: string[]): boolean {
  return context.path.every((segment, index) => candidate[index] === segment);
}

function restrictAdnaSnapshot(snapshot: Snapshot, context: ContextRef): OperationResult<Snapshot> {
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
  const model = adnaModel(snapshot);
  const restricted: AdnaModel = {
    nodes: model.nodes.filter((node) => contextContains(context, node.contextPath)),
    edges: model.edges.filter((edge) => contextContains(context, edge.contextPath)),
  };
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

function restrictAdnaClaim(claim: Claim, context: ContextRef): OperationResult<Claim> {
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
    value: sealArtifact({ ...common, payload: { ...claim.payload, context } }),
  };
}

function portSentence(value: JsonValue): AdnaPortClaimInput | undefined {
  const record = asRecord(value);
  if (
    typeof record?.outputNodeId !== "string" ||
    typeof record.outputPort !== "string" ||
    typeof record.inputNodeId !== "string" ||
    typeof record.inputPort !== "string" ||
    typeof record.valueType !== "string"
  ) {
    return undefined;
  }
  return record as unknown as AdnaPortClaimInput;
}

function evaluateAdna(snapshot: Snapshot, claim: Claim): Evaluation {
  if (
    snapshot.payload.profile.id !== ADNA_PROFILE.id ||
    claim.payload.profile.id !== ADNA_PROFILE.id ||
    claim.payload.sentenceMediaType !== ADNA_PORT_CLAIM_MEDIA_TYPE
  ) {
    return "indeterminate";
  }
  const sentence = portSentence(claim.payload.sentence);
  if (sentence === undefined) return "indeterminate";
  const model = adnaModel(snapshot);
  const outputNode = model.nodes.find((node) => node.id === sentence.outputNodeId);
  const inputNode = model.nodes.find((node) => node.id === sentence.inputNodeId);
  const connected = model.edges.some(
    (edge) =>
      edge.from === sentence.outputNodeId &&
      edge.to === sentence.inputNodeId &&
      edge.dataMapping[sentence.outputPort] === sentence.inputPort,
  );
  if (
    connected &&
    outputNode?.outputs[sentence.outputPort] === sentence.valueType &&
    inputNode?.inputs[sentence.inputPort] === sentence.valueType
  ) {
    return "satisfied";
  }
  const edgeExists = model.edges.some(
    (edge) => edge.from === sentence.outputNodeId && edge.to === sentence.inputNodeId,
  );
  if (
    edgeExists &&
    outputNode &&
    inputNode &&
    (outputNode.outputs[sentence.outputPort] === undefined ||
      inputNode.inputs[sentence.inputPort] === undefined ||
      model.edges.some(
        (edge) =>
          edge.from === sentence.outputNodeId &&
          edge.to === sentence.inputNodeId &&
          Object.keys(edge.dataMapping).length === 0,
      ))
  ) {
    return "indeterminate";
  }
  return "violated";
}

export const adnaAdapter: InstitutionAdapter = {
  profile: ADNA_PROFILE,
  project: projectAdna,
  async restrictSnapshot(snapshot, context) {
    return restrictAdnaSnapshot(snapshot, context);
  },
  async restrictClaim(claim, context) {
    return restrictAdnaClaim(claim, context);
  },
  async evaluate(snapshot, claim) {
    return evaluateAdna(snapshot, claim);
  },
};

const defaultPortClaim: AdnaPortClaimInput = {
  outputNodeId: "publish_order",
  outputPort: "order_created",
  inputNodeId: "consume_order",
  inputPort: "order_created",
  valueType: "application/vnd.example.order+json",
};

export function createAdnaPortClaim(
  snapshot: Snapshot,
  input: AdnaPortClaimInput = defaultPortClaim,
): Claim {
  const contextPath =
    adnaModel(snapshot).nodes.find((node) => node.id === input.outputNodeId)?.contextPath ??
    snapshot.payload.context.path;
  return sealArtifact({
    kind: "Claim",
    protocolVersion: "0.1",
    id: "urn:claim:adna-orders-port-compatibility",
    issuedAt: snapshot.issuedAt,
    issuer: snapshot.issuer,
    payloadMediaType: "application/vnd.lighthouse.claim+json",
    payload: {
      profile: ADNA_PROFILE,
      signature: snapshot.payload.signature,
      context: { id: contextPath.join("/"), path: contextPath },
      sentenceMediaType: ADNA_PORT_CLAIM_MEDIA_TYPE,
      sentence: input as unknown as JsonValue,
      snapshotDigests: [snapshot.digest],
      provenance: [],
    },
  });
}
