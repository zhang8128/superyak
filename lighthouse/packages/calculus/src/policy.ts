import { type ConnectionPolicy, compareCanonicalJson } from "@lighthouse/protocol";

export interface AuthorizationRequest {
  publisher: string;
  profile: string;
  domain: string;
  action: string;
  context: string;
  claimMediaType: string;
  purpose: string;
  audience: string;
  at: string;
  evidence: string[];
  attestations: string[];
}

export type AuthorizationDecision =
  | { allowed: true; ruleId: string }
  | {
      allowed: false;
      code: "EXPLICIT_DENY" | "NO_MATCHING_ALLOW" | "OUTSIDE_VALIDITY";
      ruleId?: string;
    };

type PolicyRule = ConnectionPolicy["payload"]["rules"][number];

function patternScore(pattern: string, value: string): number | undefined {
  if (pattern === value) return 2;
  if (pattern.endsWith("*") && value.startsWith(pattern.slice(0, -1))) return 1;
  return undefined;
}

function selectorScore(patterns: string[], value: string): number | undefined {
  let highest: number | undefined;
  for (const pattern of patterns) {
    const score = patternScore(pattern, value);
    if (score !== undefined && (highest === undefined || score > highest)) highest = score;
  }
  return highest;
}

function ruleScore(rule: PolicyRule, request: AuthorizationRequest): number | undefined {
  const values: Array<[string[], string]> = [
    [rule.publishers, request.publisher],
    [rule.profiles, request.profile],
    [rule.domains, request.domain],
    [rule.actions, request.action],
    [rule.contexts, request.context],
    [rule.claimMediaTypes, request.claimMediaType],
    [rule.purposes, request.purpose],
    [rule.audiences, request.audience],
  ];
  let score = 0;
  for (const [patterns, value] of values) {
    const dimension = selectorScore(patterns, value);
    if (dimension === undefined) return undefined;
    score += dimension;
  }
  if (!rule.requiredEvidence.every((item) => request.evidence.includes(item))) return undefined;
  if (!rule.requiredAttestations.every((item) => request.attestations.includes(item))) {
    return undefined;
  }
  return score;
}

function isActive(rule: PolicyRule, at: number): boolean {
  return Date.parse(rule.validFrom) <= at && at <= Date.parse(rule.validUntil);
}

export function evaluateConnectionPolicy(
  policy: ConnectionPolicy,
  request: AuthorizationRequest,
): AuthorizationDecision {
  const structuralMatches = policy.payload.rules.flatMap((rule) => {
    const score = ruleScore(rule, request);
    return score === undefined ? [] : [{ rule, score }];
  });
  if (structuralMatches.length === 0) {
    return { allowed: false, code: "NO_MATCHING_ALLOW" };
  }

  const at = Date.parse(request.at);
  const activeMatches = Number.isNaN(at)
    ? []
    : structuralMatches.filter(({ rule }) => isActive(rule, at));
  if (activeMatches.length === 0) {
    return { allowed: false, code: "OUTSIDE_VALIDITY" };
  }

  activeMatches.sort((left, right) => {
    if (left.score !== right.score) return right.score - left.score;
    if (left.rule.effect !== right.rule.effect) return left.rule.effect === "deny" ? -1 : 1;
    return compareCanonicalJson(left.rule.id, right.rule.id);
  });
  const highestScore = activeMatches[0]?.score;
  const winner =
    activeMatches.find(({ rule, score }) => score === highestScore && rule.effect === "deny") ??
    activeMatches[0];

  if (winner?.rule.effect === "allow") {
    return { allowed: true, ruleId: winner.rule.id };
  }
  return {
    allowed: false,
    code: "EXPLICIT_DENY",
    ...(winner === undefined ? {} : { ruleId: winner.rule.id }),
  };
}
