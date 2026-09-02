import { cp, mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {
  createEngramRankClaim,
  ENGRAM_PROFILE,
  ENGRAM_RECALL_RANK_CLAIM_MEDIA_TYPE,
  engramAdapter,
} from "@lighthouse/adapter-engram";
import {
  checkRestrictionComposition,
  checkRestrictionIdentity,
  evaluateConnectionPolicy,
} from "@lighthouse/calculus";
import {
  type ConnectionPolicy,
  digestJson,
  type JsonValue,
  type ProfileRef,
  parseArtifact,
  type Snapshot,
  sealArtifact,
  verifyArtifactDigest,
} from "@lighthouse/protocol";
import { runRecallExperiment } from "./experiment.js";
import type { RecallExperimentInput, RecallExperimentReport, RecallModeReport } from "./types.js";

const issuedAt = "2026-08-30T12:00:00Z";

export interface RecallProofDiagnostic {
  code: string;
  message: string;
}

export interface RecallProofCheck {
  id: string;
  status: "passed" | "failed";
  evidenceDigests: string[];
  diagnostics: RecallProofDiagnostic[];
}

export interface RecallProofReportContent {
  kind: "RecallProofReport";
  protocolVersion: "0.1";
  profile: ProfileRef;
  passed: boolean;
  checks: RecallProofCheck[];
  experiment: RecallExperimentReport;
}

export interface RecallProofReport extends RecallProofReportContent {
  digest: ReturnType<typeof digestJson>;
}

function check(
  id: string,
  passed: boolean,
  evidenceDigests: string[],
  code: string,
  message: string,
): RecallProofCheck {
  return {
    id,
    status: passed ? "passed" : "failed",
    evidenceDigests: [...evidenceDigests].sort(),
    diagnostics: passed ? [] : [{ code, message }],
  };
}

async function projectFixture(file: string, id: string, issuer: string): Promise<Snapshot> {
  return engramAdapter.project({ root: file, id, issuer, issuedAt });
}

async function copiedProjection(
  source: string,
  id: string,
  issuer: string,
): Promise<[Snapshot, Snapshot]> {
  const first = await mkdtemp(path.join(os.tmpdir(), "lighthouse-engram-first-"));
  const second = await mkdtemp(path.join(os.tmpdir(), "lighthouse-engram-second-"));
  const filename = path.basename(source);
  await Promise.all([
    cp(source, path.join(first, filename)),
    cp(source, path.join(second, filename)),
  ]);
  return Promise.all([projectFixture(first, id, issuer), projectFixture(second, id, issuer)]);
}

function recallPolicy(): ConnectionPolicy {
  const selectorDefaults = {
    profiles: [ENGRAM_PROFILE.id],
    domains: ["memory.recall"],
    contexts: ["memory/debugging/*"],
    claimMediaTypes: [ENGRAM_RECALL_RANK_CLAIM_MEDIA_TYPE],
    purposes: ["debugging"],
    audiences: ["self"],
    validFrom: "2026-08-30T00:00:00Z",
    validUntil: "2027-08-30T00:00:00Z",
    requiredEvidence: [],
    requiredAttestations: [],
  };
  return sealArtifact({
    kind: "ConnectionPolicy",
    protocolVersion: "0.1",
    id: "urn:policy:engram-reference",
    issuedAt,
    issuer: "urn:lighthouse:receiver",
    payloadMediaType: "application/vnd.lighthouse.connection-policy+json",
    payload: {
      rules: [
        {
          id: "allow-crew-debug-recall",
          effect: "allow",
          publishers: ["urn:lighthouse:trusted-crew"],
          actions: ["recall"],
          ...selectorDefaults,
        },
        {
          id: "deny-crew-context-injection",
          effect: "deny",
          publishers: ["urn:lighthouse:trusted-crew"],
          actions: ["inject_context"],
          ...selectorDefaults,
        },
        {
          id: "deny-intimate-neighbor-recall",
          effect: "deny",
          publishers: ["urn:lighthouse:intimate-neighbor"],
          actions: ["recall"],
          ...selectorDefaults,
        },
      ],
    },
  });
}

function policyRequest(action: "recall" | "inject_context") {
  return {
    publisher: "urn:lighthouse:trusted-crew",
    profile: ENGRAM_PROFILE.id,
    domain: "memory.recall",
    action,
    context: "memory/debugging/mcp",
    claimMediaType: ENGRAM_RECALL_RANK_CLAIM_MEDIA_TYPE,
    purpose: "debugging",
    audience: "self",
    at: issuedAt,
    evidence: [],
    attestations: [],
  };
}

function experimentInput(
  policy: ConnectionPolicy,
  local: Snapshot,
  crew: Snapshot,
  intimate: Snapshot,
): RecallExperimentInput {
  return {
    id: "urn:experiment:engram-reference",
    issuedAt,
    receiverPublisher: local.issuer,
    k: 1,
    policy,
    sources: [
      { snapshot: local, role: "local", weight: 1 },
      { snapshot: crew, role: "remote", weight: 2 },
      { snapshot: intimate, role: "remote", weight: 3 },
    ],
    turns: [
      {
        turnId: "turn-missing-restart",
        context: { id: "memory/debugging/mcp", path: ["memory", "debugging", "mcp"] },
        purpose: "debugging",
        relevant: [
          {
            publisher: crew.issuer,
            memoryId: "restart-after-server-change",
          },
        ],
        forbidden: [
          {
            publisher: intimate.issuer,
            memoryId: "private-relationship-event",
          },
        ],
      },
      {
        turnId: "turn-local-bridge",
        context: { id: "memory/debugging/bridge", path: ["memory", "debugging", "bridge"] },
        purpose: "debugging",
        relevant: [{ publisher: local.issuer, memoryId: "local-bridge-digest" }],
        forbidden: [],
      },
    ],
  };
}

function mode(report: RecallExperimentReport, id: RecallModeReport["mode"]): RecallModeReport {
  const found = report.modes.find((candidate) => candidate.mode === id);
  if (found === undefined) throw new Error(`REFERENCE_MODE_MISSING: ${id}`);
  return found;
}

export async function runReferenceRecallProof(fixtureRoot: string): Promise<RecallProofReport> {
  const localFile = path.join(fixtureRoot, "local.engram.json");
  const [local, localCopy] = await copiedProjection(
    localFile,
    "urn:snapshot:engram-local",
    "urn:lighthouse:receiver",
  );
  const crew = await projectFixture(
    path.join(fixtureRoot, "trusted-crew.engram.json"),
    "urn:snapshot:engram-trusted-crew",
    "urn:lighthouse:trusted-crew",
  );
  const intimate = await projectFixture(
    path.join(fixtureRoot, "intimate-neighbor.engram.json"),
    "urn:snapshot:engram-intimate-neighbor",
    "urn:lighthouse:intimate-neighbor",
  );
  const policy = recallPolicy();
  const rankClaim = createEngramRankClaim(crew, {
    turnId: "turn-missing-restart",
    memoryId: "restart-after-server-change",
    maxRank: 1,
  });
  const artifacts = [local, crew, intimate, policy, rankClaim];
  const schemaValid = artifacts.every((artifact) => {
    const parsed = parseArtifact(artifact);
    return verifyArtifactDigest(parsed).ok;
  });
  const identityLaw = await checkRestrictionIdentity(engramAdapter, local);
  const compositionLaw = await checkRestrictionComposition(
    engramAdapter,
    local,
    { id: "memory/debugging", path: ["memory", "debugging"] },
    { id: "memory/debugging/mcp", path: ["memory", "debugging", "mcp"] },
  );
  const rankEvaluation = await engramAdapter.evaluate(crew, rankClaim);
  const recallDecision = evaluateConnectionPolicy(policy, policyRequest("recall"));
  const injectionDecision = evaluateConnectionPolicy(policy, policyRequest("inject_context"));
  const input = experimentInput(policy, local, crew, intimate);
  const experiment = runRecallExperiment(input);
  const reversedExperiment = runRecallExperiment({
    ...input,
    sources: input.sources.toReversed(),
    turns: input.turns.toReversed(),
  });
  const localOnly = mode(experiment, "local-only");
  const scoped = mode(experiment, "policy-scoped");
  const unsafe = mode(experiment, "indiscriminate-control");
  const artifactDigests = artifacts.map((artifact) => artifact.digest.value);
  const receiptDigests = experiment.modes.flatMap((candidate) =>
    candidate.turns.map((turn) => turn.receipt.digest.value),
  );

  const checks: RecallProofCheck[] = [
    check(
      "schema.engram-snapshots",
      schemaValid,
      artifactDigests,
      "SCHEMA_OR_DIGEST_INVALID",
      "One or more projected artifacts failed schema or digest validation",
    ),
    check(
      "digest.engram-deterministic",
      local.digest.value === localCopy.digest.value,
      [local.digest.value, localCopy.digest.value],
      "SNAPSHOT_NOT_DETERMINISTIC",
      "Copied Engram exports produced different snapshot digests",
    ),
    check(
      "restriction.engram-laws",
      identityLaw.passed && compositionLaw.passed,
      [local.digest.value],
      "RESTRICTION_LAW_FAILED",
      "Engram restriction identity or composition failed",
    ),
    check(
      "evaluation.rank-claim",
      rankEvaluation === "satisfied",
      [crew.digest.value, rankClaim.digest.value],
      "RANK_CLAIM_NOT_SATISFIED",
      "The trusted trace did not satisfy its recorded rank claim",
    ),
    check(
      "policy.recall-allowed",
      recallDecision.allowed && recallDecision.ruleId === "allow-crew-debug-recall",
      [policy.digest.value],
      "RECALL_NOT_ALLOWED",
      "The trusted crew recall request was not allowed",
    ),
    check(
      "policy.injection-denied",
      !injectionDecision.allowed &&
        injectionDecision.code === "EXPLICIT_DENY" &&
        injectionDecision.ruleId === "deny-crew-context-injection",
      [policy.digest.value],
      "INJECTION_NOT_DENIED",
      "Recall permission became context injection permission",
    ),
    check(
      "measurement.scoped-improves-recall",
      scoped.metrics.rightTurnRecallAtK > localOnly.metrics.rightTurnRecallAtK,
      [experiment.digest.value],
      "RECALL_DID_NOT_IMPROVE",
      "Policy-scoped neighbors did not improve right-turn recall",
    ),
    check(
      "measurement.scoped-improves-ndcg",
      scoped.metrics.ndcgAtK > localOnly.metrics.ndcgAtK,
      [experiment.digest.value],
      "NDCG_DID_NOT_IMPROVE",
      "Policy-scoped neighbors did not improve nDCG",
    ),
    check(
      "privacy.scoped-no-forbidden-exposure",
      scoped.metrics.forbiddenExposureAtK === 0,
      [experiment.digest.value],
      "FORBIDDEN_MEMORY_EXPOSED",
      "Policy-scoped recall exposed a receiver-forbidden memory",
    ),
    check(
      "privacy.scoped-no-unauthorized-selection",
      scoped.metrics.unauthorizedSelectionCount === 0,
      [experiment.digest.value],
      "UNAUTHORIZED_MEMORY_SELECTED",
      "Policy-scoped recall selected an unauthorized memory",
    ),
    check(
      "negative-control.forbidden-exposure-detected",
      unsafe.metrics.forbiddenExposureAtK > 0,
      [experiment.digest.value],
      "LEAKAGE_INSTRUMENT_INSENSITIVE",
      "The unsafe control did not trigger forbidden exposure",
    ),
    check(
      "negative-control.policy-bypass-detected",
      unsafe.metrics.unauthorizedSelectionCount > 0,
      [experiment.digest.value],
      "POLICY_BYPASS_NOT_DETECTED",
      "The unsafe control did not record unauthorized selection",
    ),
    check(
      "receipt.no-injection",
      experiment.modes.every((candidate) =>
        candidate.turns.every(
          (turn) =>
            turn.receipt.payload.action === "recall" && turn.receipt.payload.injected === false,
        ),
      ),
      receiptDigests,
      "RECEIPT_CLAIMS_INJECTION",
      "A recall receipt claimed active context injection",
    ),
    check(
      "digest.experiment-deterministic",
      experiment.digest.value === reversedExperiment.digest.value,
      [experiment.digest.value, reversedExperiment.digest.value],
      "EXPERIMENT_NOT_DETERMINISTIC",
      "Input ordering changed the experiment digest",
    ),
  ];
  const content: RecallProofReportContent = {
    kind: "RecallProofReport",
    protocolVersion: "0.1",
    profile: ENGRAM_PROFILE,
    passed: checks.every((candidate) => candidate.status === "passed"),
    checks,
    experiment,
  };
  return { ...content, digest: digestJson(content as unknown as JsonValue) };
}
