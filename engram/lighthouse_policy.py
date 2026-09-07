"""Lighthouse ConnectionPolicy evaluation in Python.

This mirrors the Lighthouse kit: exact selectors score two points,
``*``-suffixed prefix selectors score one, evidence and attestations are
required subsets, and deny wins a specificity tie. Policy is directional,
deny-by-default, and never transitive.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from lighthouse_protocol import canonical_json, verify_artifact_digest

_DIMENSIONS = (
    ("publishers", "publisher"),
    ("profiles", "profile"),
    ("domains", "domain"),
    ("actions", "action"),
    ("contexts", "context_id"),
    ("claimMediaTypes", "claim_type"),
    ("purposes", "purpose"),
    ("audiences", "audience"),
)


class PolicyError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PolicyRequest:
    publisher: str
    profile: str
    domain: str
    action: str
    context_id: str
    claim_type: str
    purpose: str
    audience: str
    at: datetime
    evidence: tuple[str, ...] = ()
    attestations: tuple[str, ...] = ()


@dataclass(frozen=True)
class Decision:
    effect: str
    rule_id: str | None
    code: str | None

    def to_lighthouse(self) -> dict:
        if self.effect == "allow":
            return {"allowed": True, "ruleId": self.rule_id}
        result: dict = {"allowed": False, "code": self.code}
        if self.rule_id is not None:
            result["ruleId"] = self.rule_id
        return result

    def to_json(self) -> dict:
        """Return the wire and receipt shape, preserving explicit nulls."""
        return {"effect": self.effect, "ruleId": self.rule_id, "code": self.code}


def _parse_rfc3339(text: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _pattern_score(pattern: str, value: str) -> int | None:
    if pattern == value:
        return 2
    if pattern.endswith("*") and value.startswith(pattern[:-1]):
        return 1
    return None


def _selector_score(patterns: list[str], value: str) -> int | None:
    best: int | None = None
    for pattern in patterns:
        score = _pattern_score(pattern, value)
        if score is not None and (best is None or score > best):
            best = score
    return best


def _rule_score(rule: dict, request: PolicyRequest) -> int | None:
    total = 0
    for rule_key, request_key in _DIMENSIONS:
        score = _selector_score(rule[rule_key], getattr(request, request_key))
        if score is None:
            return None
        total += score
    if not all(
        item in request.evidence for item in rule.get("requiredEvidence", [])
    ):
        return None
    if not all(
        item in request.attestations
        for item in rule.get("requiredAttestations", [])
    ):
        return None
    return total


class Policy:
    def __init__(self, artifact: dict):
        self.artifact = artifact
        self.issuer = artifact["issuer"]
        self.rules: list[dict] = list(artifact["payload"]["rules"])

    def rule(self, rule_id: str) -> dict | None:
        return next((rule for rule in self.rules if rule["id"] == rule_id), None)

    def decide(self, request: PolicyRequest) -> Decision:
        structural: list[tuple[dict, int]] = []
        for rule in self.rules:
            score = _rule_score(rule, request)
            if score is not None:
                structural.append((rule, score))
        if not structural:
            return Decision("deny", None, "NO_MATCHING_ALLOW")

        at = (
            request.at
            if request.at.tzinfo
            else request.at.replace(tzinfo=timezone.utc)
        )
        active: list[tuple[dict, int]] = []
        for rule, score in structural:
            start = _parse_rfc3339(rule["validFrom"])
            end = _parse_rfc3339(rule["validUntil"])
            if start is not None and end is not None and start <= at <= end:
                active.append((rule, score))
        if not active:
            return Decision("deny", None, "OUTSIDE_VALIDITY")

        active.sort(
            key=lambda item: (
                -item[1],
                0 if item[0]["effect"] == "deny" else 1,
                canonical_json(item[0]["id"]),
            )
        )
        winner = active[0][0]
        if winner["effect"] == "allow":
            return Decision("allow", winner["id"], None)
        return Decision("deny", winner["id"], "EXPLICIT_DENY")


def load_policy(path: Path) -> Policy:
    path = Path(path)
    if not path.is_file():
        raise PolicyError("POLICY_NOT_FOUND")
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PolicyError("POLICY_INVALID") from error
    if (
        not isinstance(artifact, dict)
        or artifact.get("kind") != "ConnectionPolicy"
        or artifact.get("protocolVersion") != "0.1"
        or not isinstance(artifact.get("payload"), dict)
        or not isinstance(artifact["payload"].get("rules"), list)
    ):
        raise PolicyError("POLICY_INVALID")
    if not verify_artifact_digest(artifact):
        raise PolicyError("DIGEST_MISMATCH")
    return Policy(artifact)
