import { sealArtifact } from "@lighthouse/protocol";
import { describe, expect, it } from "vitest";
import {
  evaluateConnectionPolicy,
  type AuthorizationRequest,
} from "../src/index.js";

const selectorDefaults = {
  profiles: ["urn:lighthouse:profile:hyper-modules"],
  contexts: ["workflow/orders"],
  claimMediaTypes: ["application/vnd.hyper.dependency-claim+json"],
  requiredEvidence: [],
  requiredAttestations: [],
};

const policy = sealArtifact({
  kind: "ConnectionPolicy",
  protocolVersion: "0.1",
  id: "urn:policy:local-connections",
  issuedAt: "2026-08-30T12:00:00Z",
  issuer: "urn:lighthouse:local",
  payloadMediaType: "application/vnd.lighthouse.connection-policy+json",
  payload: {
    rules: [
      {
        id: "allow-french-lab-workflow-read",
        effect: "allow",
        publishers: ["urn:lighthouse:french-cheese-institute"],
        domains: ["workflow.structure"],
        actions: ["read"],
        purposes: ["coordination"],
        audiences: ["self"],
        validFrom: "2026-08-30T00:00:00Z",
        validUntil: "2027-08-30T00:00:00Z",
        ...selectorDefaults,
      },
      {
        id: "allow-crew-debug-recall",
        effect: "allow",
        publishers: ["urn:lighthouse:trusted-crew"],
        domains: ["personal.memory"],
        actions: ["recall"],
        purposes: ["debugging"],
        audiences: ["self"],
        validFrom: "2026-08-30T00:00:00Z",
        validUntil: "2027-08-30T00:00:00Z",
        ...selectorDefaults,
      },
      {
        id: "deny-crew-context-injection",
        effect: "deny",
        publishers: ["urn:lighthouse:trusted-crew"],
        domains: ["personal.memory"],
        actions: ["inject_context"],
        purposes: ["debugging"],
        audiences: ["self"],
        validFrom: "2026-08-30T00:00:00Z",
        validUntil: "2027-08-30T00:00:00Z",
        ...selectorDefaults,
      },
      {
        id: "deny-crew-reshare",
        effect: "deny",
        publishers: ["urn:lighthouse:trusted-crew"],
        domains: ["personal.memory"],
        actions: ["reshare"],
        purposes: ["debugging"],
        audiences: ["self"],
        validFrom: "2026-08-30T00:00:00Z",
        validUntil: "2027-08-30T00:00:00Z",
        ...selectorDefaults,
      },
    ],
  },
});

const workflowRead: AuthorizationRequest = {
  publisher: "urn:lighthouse:french-cheese-institute",
  profile: "urn:lighthouse:profile:hyper-modules",
  domain: "workflow.structure",
  action: "read",
  context: "workflow/orders",
  claimMediaType: "application/vnd.hyper.dependency-claim+json",
  purpose: "coordination",
  audience: "self",
  at: "2026-09-01T00:00:00Z",
  evidence: [],
  attestations: [],
};

const recallRequest: AuthorizationRequest = {
  ...workflowRead,
  publisher: "urn:lighthouse:trusted-crew",
  domain: "personal.memory",
  action: "recall",
  purpose: "debugging",
};

describe("connection policy", () => {
  it("allows workflow structure without granting unrelated domains", () => {
    expect(evaluateConnectionPolicy(policy, workflowRead)).toEqual({
      allowed: true,
      ruleId: "allow-french-lab-workflow-read",
    });
    expect(
      evaluateConnectionPolicy(policy, { ...workflowRead, domain: "personal.memory" }),
    ).toEqual({ allowed: false, code: "NO_MATCHING_ALLOW" });
  });

  it("does not turn read or recall into context injection or resharing", () => {
    expect(evaluateConnectionPolicy(policy, recallRequest)).toEqual({
      allowed: true,
      ruleId: "allow-crew-debug-recall",
    });
    expect(
      evaluateConnectionPolicy(policy, { ...recallRequest, action: "inject_context" }),
    ).toEqual({
      allowed: false,
      code: "EXPLICIT_DENY",
      ruleId: "deny-crew-context-injection",
    });
    expect(evaluateConnectionPolicy(policy, { ...recallRequest, action: "reshare" })).toEqual({
      allowed: false,
      code: "EXPLICIT_DENY",
      ruleId: "deny-crew-reshare",
    });
  });

  it("requires the declared purpose and direct publisher", () => {
    expect(evaluateConnectionPolicy(policy, { ...recallRequest, purpose: "profiling" })).toEqual({
      allowed: false,
      code: "NO_MATCHING_ALLOW",
    });
    expect(
      evaluateConnectionPolicy(policy, {
        ...recallRequest,
        publisher: "urn:lighthouse:friend-of-friend",
      }),
    ).toEqual({ allowed: false, code: "NO_MATCHING_ALLOW" });
  });

  it("denies a grant outside its validity interval", () => {
    expect(
      evaluateConnectionPolicy(policy, { ...recallRequest, at: "2028-01-01T00:00:00Z" }),
    ).toEqual({ allowed: false, code: "OUTSIDE_VALIDITY" });
  });
});
