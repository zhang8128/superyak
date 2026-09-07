import { cp, mkdtemp, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { ADNA_PORT_CLAIM_MEDIA_TYPE, ADNA_PROFILE, adnaAdapter } from "@lighthouse/adapter-adna";
import {
  createHyperDependencyClaim,
  createHyperLeaseClaim,
  HYPER_DEPENDENCY_MEDIA_TYPE,
  HYPER_PROFILE,
  hyperAdapter,
} from "@lighthouse/adapter-hyper";
import { createHyperAdnaBridge, type HyperAdnaMapping } from "@lighthouse/bridge-hyper-adna";
import {
  type AuthorizationRequest,
  checkRestrictionComposition,
  checkRestrictionIdentity,
  composeBridges,
  evaluateConnectionPolicy,
  type InstitutionAdapter,
  identityBridge,
  translateWithWitness,
} from "@lighthouse/calculus";
import {
  type ConnectionPolicy,
  type LighthouseArtifact,
  parseArtifact,
  type Snapshot,
  sealArtifact,
  verifyArtifactDigest,
} from "@lighthouse/protocol";
import type { ConformanceCheck, ConformanceDiagnostic, ConformanceReport } from "./report.js";

export interface ReferenceConformanceOptions {
  fixtureRoot: string;
  invalidBridge: boolean;
}

const issuedAt = "2026-08-30T12:00:00Z";

function check(
  id: string,
  passed: boolean,
  artifacts: LighthouseArtifact[],
  diagnostics: ConformanceDiagnostic[] = [],
): ConformanceCheck {
  return {
    id,
    status: passed ? "passed" : "failed",
    artifactDigests: artifacts.map((artifact) => artifact.digest.value),
    diagnostics: passed ? [] : diagnostics,
  };
}

async function copiedProjection(
  adapter: InstitutionAdapter,
  source: string,
  id: string,
  issuer: string,
  prefix: string,
): Promise<[Snapshot, Snapshot]> {
  const firstParent = await mkdtemp(path.join(os.tmpdir(), `${prefix}-first-`));
  const secondParent = await mkdtemp(path.join(os.tmpdir(), `${prefix}-second-`));
  const firstRoot = path.join(firstParent, "checkout");
  const secondRoot = path.join(secondParent, "checkout");
  await cp(source, firstRoot, { recursive: true });
  await cp(source, secondRoot, { recursive: true });
  return Promise.all([
    adapter.project({ root: firstRoot, id, issuer, issuedAt }),
    adapter.project({ root: secondRoot, id, issuer, issuedAt }),
  ]);
}

async function readMapping(file: string): Promise<HyperAdnaMapping> {
  return JSON.parse(await readFile(file, "utf8"));
}

function policyRequest(overrides: Partial<AuthorizationRequest> = {}): AuthorizationRequest {
  return {
    publisher: "urn:lighthouse:french-cheese-institute",
    profile: HYPER_PROFILE.id,
    domain: "workflow.structure",
    action: "read",
    context: "workflow/orders",
    claimMediaType: HYPER_DEPENDENCY_MEDIA_TYPE,
    purpose: "coordination",
    audience: "self",
    at: "2026-09-01T00:00:00Z",
    evidence: [],
    attestations: [],
    ...overrides,
  };
}

function diagnosticFromUnknown(error: unknown): ConformanceDiagnostic {
  return {
    code: "SCHEMA_INVALID",
    message: error instanceof Error ? error.message : String(error),
  };
}

export async function runReferenceConformance(
  options: ReferenceConformanceOptions,
): Promise<ConformanceReport> {
  const [hyperFirst, hyperSecond] = await copiedProjection(
    hyperAdapter,
    path.join(options.fixtureRoot, "hyper/orders"),
    "urn:snapshot:hyper-orders",
    "urn:lighthouse:hyper-local",
    "lighthouse-hyper",
  );
  const [adnaFirst, adnaSecond] = await copiedProjection(
    adnaAdapter,
    path.join(options.fixtureRoot, "adna"),
    "urn:snapshot:adna-orders",
    "urn:lighthouse:adna-local",
    "lighthouse-adna",
  );
  const validMapping = await readMapping(path.join(options.fixtureRoot, "bridges/hyper-adna.json"));
  const invalidMapping = await readMapping(
    path.join(options.fixtureRoot, "bridges/hyper-adna-invalid.json"),
  );
  const candidate = createHyperAdnaBridge(options.invalidBridge ? invalidMapping : validMapping, {
    id: options.invalidBridge
      ? "urn:bridge:hyper-adna-orders-invalid"
      : "urn:bridge:hyper-adna-orders",
    issuer: "urn:lighthouse:bridge-author",
    issuedAt,
  });
  const invalidBridge = createHyperAdnaBridge(invalidMapping, {
    id: "urn:bridge:hyper-adna-orders-negative-control",
    issuer: "urn:lighthouse:bridge-author",
    issuedAt,
  });
  const sourceClaim = createHyperDependencyClaim(hyperFirst);
  const translated = await translateWithWitness(
    candidate,
    sourceClaim,
    hyperAdapter,
    hyperFirst,
    adnaAdapter,
    adnaFirst,
  );
  const negativeControl = await translateWithWitness(
    invalidBridge,
    sourceClaim,
    hyperAdapter,
    hyperFirst,
    adnaAdapter,
    adnaFirst,
  );

  const parsedPolicy = parseArtifact(
    JSON.parse(
      await readFile(path.join(options.fixtureRoot, "policy/workflow-policy.json"), "utf8"),
    ),
  );
  if (parsedPolicy.kind !== "ConnectionPolicy") {
    throw new Error("Reference policy fixture is not a ConnectionPolicy");
  }
  const policy: ConnectionPolicy = parsedPolicy;
  const descriptor = sealArtifact({
    kind: "LighthouseDescriptor",
    protocolVersion: "0.1",
    id: "urn:lighthouse:reference",
    issuedAt,
    issuer: "urn:lighthouse:reference",
    payloadMediaType: "application/vnd.lighthouse.descriptor+json",
    payload: {
      name: "Lighthouse reference proof",
      protocolVersions: ["0.1"],
      profiles: [HYPER_PROFILE, ADNA_PROFILE],
      actions: ["read", "recall", "inject_context", "reshare"],
      artifactEndpoints: [],
    },
  });

  const checks: ConformanceCheck[] = [];
  const schemaArtifacts: LighthouseArtifact[] = [
    descriptor,
    hyperFirst,
    adnaFirst,
    sourceClaim,
    candidate.descriptor,
    translated.witness,
    policy,
  ];
  try {
    for (const artifact of schemaArtifacts) {
      const parsed = parseArtifact(artifact);
      if (!verifyArtifactDigest(parsed).ok) throw new Error(`Digest mismatch for ${artifact.id}`);
    }
    checks.push(check("schema.artifacts", true, schemaArtifacts));
  } catch (error) {
    checks.push(check("schema.artifacts", false, schemaArtifacts, [diagnosticFromUnknown(error)]));
  }

  checks.push(
    check(
      "digest.hyper-deterministic",
      hyperFirst.digest.value === hyperSecond.digest.value,
      [hyperFirst, hyperSecond],
      [{ code: "SNAPSHOT_NOT_DETERMINISTIC", message: "Hyper snapshot digests differ" }],
    ),
  );
  checks.push(
    check(
      "digest.adna-deterministic",
      adnaFirst.digest.value === adnaSecond.digest.value,
      [adnaFirst, adnaSecond],
      [{ code: "SNAPSHOT_NOT_DETERMINISTIC", message: "aDNA snapshot digests differ" }],
    ),
  );

  const restrictionIdentity = await checkRestrictionIdentity(hyperAdapter, hyperFirst);
  checks.push(
    check(
      "restriction.identity",
      restrictionIdentity.passed,
      [hyperFirst],
      restrictionIdentity.passed ? [] : restrictionIdentity.diagnostics,
    ),
  );
  const restrictionComposition = await checkRestrictionComposition(
    hyperAdapter,
    hyperFirst,
    { id: "workflow/orders", path: ["workflow", "orders"] },
    { id: "workflow/orders/contracts", path: ["workflow", "orders", "contracts"] },
  );
  checks.push(
    check(
      "restriction.composition",
      restrictionComposition.passed,
      [hyperFirst],
      restrictionComposition.passed ? [] : restrictionComposition.diagnostics,
    ),
  );

  checks.push(
    check(
      "bridge.shared-claim",
      translated.witness.payload.outcome === "preserved",
      [candidate.descriptor, sourceClaim, translated.witness],
      translated.witness.payload.diagnostics,
    ),
  );
  checks.push(
    check(
      "bridge.source-satisfied",
      translated.witness.payload.sourceEvaluation === "satisfied",
      [hyperFirst, sourceClaim, translated.witness],
      [{ code: "SOURCE_NOT_SATISFIED", message: "Hyper did not satisfy the source claim" }],
    ),
  );
  checks.push(
    check(
      "bridge.target-satisfied",
      translated.witness.payload.targetEvaluation === "satisfied",
      [adnaFirst, translated.witness],
      [{ code: "TARGET_NOT_SATISFIED", message: "aDNA did not satisfy the translated claim" }],
    ),
  );

  const sourceIdentity = identityBridge(HYPER_PROFILE, [HYPER_DEPENDENCY_MEDIA_TYPE], {
    id: "urn:bridge:hyper-identity",
    issuer: "urn:lighthouse:reference",
    issuedAt,
  });
  const targetIdentity = identityBridge(ADNA_PROFILE, [ADNA_PORT_CLAIM_MEDIA_TYPE], {
    id: "urn:bridge:adna-identity",
    issuer: "urn:lighthouse:reference",
    issuedAt,
  });
  const identityResult = await translateWithWitness(
    sourceIdentity,
    sourceClaim,
    hyperAdapter,
    hyperFirst,
    hyperAdapter,
    hyperFirst,
  );
  checks.push(
    check(
      "bridge.identity",
      identityResult.witness.payload.outcome === "preserved" &&
        identityResult.translatedClaim?.digest.value === sourceClaim.digest.value,
      [sourceIdentity.descriptor, sourceClaim, identityResult.witness],
      [{ code: "BRIDGE_IDENTITY_FAILED", message: "Identity changed the source claim" }],
    ),
  );

  const composedLeft = composeBridges(
    composeBridges(sourceIdentity, candidate, {
      id: "urn:bridge:composition-left-a",
      issuer: "urn:lighthouse:reference",
      issuedAt,
    }),
    targetIdentity,
    { id: "urn:bridge:composition-left-b", issuer: "urn:lighthouse:reference", issuedAt },
  );
  const composedRight = composeBridges(
    sourceIdentity,
    composeBridges(candidate, targetIdentity, {
      id: "urn:bridge:composition-right-a",
      issuer: "urn:lighthouse:reference",
      issuedAt,
    }),
    { id: "urn:bridge:composition-right-b", issuer: "urn:lighthouse:reference", issuedAt },
  );
  const leftResult = await composedLeft.translateClaim(sourceClaim);
  const rightResult = await composedRight.translateClaim(sourceClaim);
  const associative =
    leftResult.ok &&
    rightResult.ok &&
    leftResult.value.digest.value === rightResult.value.digest.value &&
    JSON.stringify(composedLeft.lineage.map((item) => item.digest)) ===
      JSON.stringify(composedRight.lineage.map((item) => item.digest));
  checks.push(
    check(
      "bridge.associative",
      associative,
      [composedLeft.descriptor, composedRight.descriptor],
      [{ code: "BRIDGE_COMPOSITION_FAILED", message: "Supported composition is not associative" }],
    ),
  );

  const leaseResult = await candidate.translateClaim(createHyperLeaseClaim(hyperFirst));
  checks.push(
    check(
      "bridge.lease-unmapped",
      !leaseResult.ok && leaseResult.obstruction.code === "BRIDGE_CLAIM_UNMAPPED",
      [candidate.descriptor],
      [{ code: "OBSTRUCTION_MISSING", message: "Hyper lease claim was not explicitly unmapped" }],
    ),
  );
  checks.push(
    check(
      "bridge.invalid-rejected",
      negativeControl.witness.payload.outcome === "invalid",
      [invalidBridge.descriptor, negativeControl.witness],
      [{ code: "INVALID_BRIDGE_ACCEPTED", message: "The negative control was not rejected" }],
    ),
  );

  const workflowAllowed = evaluateConnectionPolicy(policy, policyRequest()).allowed;
  const unrelatedAllowed = evaluateConnectionPolicy(
    policy,
    policyRequest({ domain: "personal.memory" }),
  ).allowed;
  checks.push(
    check(
      "policy.workflow-scoped",
      workflowAllowed && !unrelatedAllowed,
      [policy],
      [{ code: "POLICY_SCOPE_FAILED", message: "Workflow trust escaped its domain" }],
    ),
  );
  const memoryBase = {
    publisher: "urn:lighthouse:trusted-crew",
    domain: "personal.memory",
    purpose: "debugging",
  };
  const injectDecision = evaluateConnectionPolicy(
    policy,
    policyRequest({ ...memoryBase, action: "inject_context" }),
  );
  checks.push(
    check(
      "policy.inject-denied",
      !injectDecision.allowed && injectDecision.code === "EXPLICIT_DENY",
      [policy],
      [{ code: "CONTEXT_INJECTION_ALLOWED", message: "Recall consent leaked into injection" }],
    ),
  );
  const reshareDecision = evaluateConnectionPolicy(
    policy,
    policyRequest({ ...memoryBase, action: "reshare" }),
  );
  checks.push(
    check(
      "policy.reshare-denied",
      !reshareDecision.allowed && reshareDecision.code === "EXPLICIT_DENY",
      [policy],
      [{ code: "RESHARE_ALLOWED", message: "Recall consent leaked into resharing" }],
    ),
  );

  return {
    protocolVersion: "0.1",
    profileIds: [HYPER_PROFILE.id, ADNA_PROFILE.id].sort(),
    bridgeDigest: candidate.descriptor.digest.value,
    passed: checks.every((item) => item.status === "passed"),
    checks,
  };
}
