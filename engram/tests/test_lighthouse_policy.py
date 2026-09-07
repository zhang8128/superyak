from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lighthouse_policy import Decision, PolicyError, PolicyRequest, load_policy

FIXTURES = Path(__file__).parent / "fixtures" / "lighthouse" / "policy"


def request_from_json(data: dict) -> PolicyRequest:
    return PolicyRequest(
        publisher=data["publisher"],
        profile=data["profile"],
        domain=data["domain"],
        action=data["action"],
        context_id=data["context"],
        claim_type=data["claimMediaType"],
        purpose=data["purpose"],
        audience=data["audience"],
        at=datetime.fromisoformat(data["at"].replace("Z", "+00:00")),
        evidence=tuple(data.get("evidence", [])),
        attestations=tuple(data.get("attestations", [])),
    )


def test_vendored_fixtures_match_typescript_decisions():
    cases = sorted((FIXTURES / "requests").glob("*.json"))
    assert len(cases) == 16
    for request_path in cases:
        case = json.loads(request_path.read_text())
        expected = json.loads(
            (FIXTURES / "decisions" / request_path.name).read_text()
        )
        policy_path = FIXTURES / "policies" / case["policy"]
        if not policy_path.is_file():
            policy_path = policy_path.with_suffix(".json")
        policy = load_policy(policy_path)
        decision = policy.decide(request_from_json(case["request"])).to_lighthouse()
        assert decision == expected["decision"], request_path.name


def test_load_policy_rejects_digest_mismatch(tmp_path):
    policy = json.loads(
        (FIXTURES / "policies" / "workflow-policy.json").read_text()
    )
    policy["issuer"] = "tampered"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(policy))
    with pytest.raises(PolicyError) as err:
        load_policy(path)
    assert err.value.code == "DIGEST_MISMATCH"


def test_load_policy_missing_file():
    with pytest.raises(PolicyError) as err:
        load_policy(Path("/nonexistent/policy.json"))
    assert err.value.code == "POLICY_NOT_FOUND"


def base_request(**overrides) -> PolicyRequest:
    fields = dict(
        publisher="urn:lighthouse:trusted-crew",
        profile="urn:lighthouse:profile:hyper-modules",
        domain="personal.memory",
        action="recall",
        context_id="workflow/orders",
        claim_type="application/vnd.hyper.dependency-claim+json",
        purpose="debugging",
        audience="self",
        at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    fields.update(overrides)
    return PolicyRequest(**fields)


def test_no_structural_match_is_no_matching_allow():
    policy = load_policy(FIXTURES / "policies" / "workflow-policy.json")
    decision = policy.decide(base_request(publisher="urn:lighthouse:stranger"))
    assert decision == Decision("deny", None, "NO_MATCHING_ALLOW")


def test_outside_validity():
    policy = load_policy(FIXTURES / "policies" / "workflow-policy.json")
    decision = policy.decide(
        base_request(at=datetime(2030, 1, 1, tzinfo=timezone.utc))
    )
    assert decision.code == "OUTSIDE_VALIDITY"


def test_deny_wins_specificity_tie(tmp_path):
    from lighthouse_protocol import artifact_digest

    def rule(rid: str, effect: str) -> dict:
        return {
            "id": rid,
            "effect": effect,
            "publishers": ["p"],
            "profiles": ["pr"],
            "domains": ["d"],
            "actions": ["recall"],
            "contexts": ["c"],
            "claimMediaTypes": ["m"],
            "purposes": ["u"],
            "audiences": ["self"],
            "validFrom": "2026-01-01T00:00:00Z",
            "validUntil": "2027-01-01T00:00:00Z",
            "requiredEvidence": [],
            "requiredAttestations": [],
        }

    artifact = {
        "kind": "ConnectionPolicy",
        "protocolVersion": "0.1",
        "id": "urn:policy:t",
        "issuedAt": "2026-08-30T12:00:00Z",
        "issuer": "urn:lighthouse:t",
        "payloadMediaType": "application/vnd.lighthouse.connection-policy+json",
        "payload": {"rules": [rule("a-allow", "allow"), rule("b-deny", "deny")]},
    }
    artifact["digest"] = artifact_digest(artifact)
    path = tmp_path / "tie.json"
    path.write_text(json.dumps(artifact))
    policy = load_policy(path)
    decision = policy.decide(
        base_request(
            publisher="p",
            profile="pr",
            domain="d",
            context_id="c",
            claim_type="m",
            purpose="u",
        )
    )
    assert decision == Decision("deny", "b-deny", "EXPLICIT_DENY")


def test_prefix_selector_scores_below_exact(tmp_path):
    from lighthouse_protocol import artifact_digest

    def rule(rid: str, effect: str, publishers: list[str]) -> dict:
        return {
            "id": rid,
            "effect": effect,
            "publishers": publishers,
            "profiles": ["pr"],
            "domains": ["d"],
            "actions": ["recall"],
            "contexts": ["c"],
            "claimMediaTypes": ["m"],
            "purposes": ["u"],
            "audiences": ["self"],
            "validFrom": "2026-01-01T00:00:00Z",
            "validUntil": "2027-01-01T00:00:00Z",
            "requiredEvidence": [],
            "requiredAttestations": [],
        }

    artifact = {
        "kind": "ConnectionPolicy",
        "protocolVersion": "0.1",
        "id": "urn:policy:t",
        "issuedAt": "2026-08-30T12:00:00Z",
        "issuer": "urn:lighthouse:t",
        "payloadMediaType": "application/vnd.lighthouse.connection-policy+json",
        "payload": {
            "rules": [
                rule("deny-all-urn", "deny", ["urn:*"]),
                rule("allow-exact", "allow", ["urn:p"]),
            ]
        },
    }
    artifact["digest"] = artifact_digest(artifact)
    path = tmp_path / "prefix.json"
    path.write_text(json.dumps(artifact))
    decision = load_policy(path).decide(
        base_request(
            publisher="urn:p",
            profile="pr",
            domain="d",
            context_id="c",
            claim_type="m",
            purpose="u",
        )
    )
    assert decision == Decision("allow", "allow-exact", None)
