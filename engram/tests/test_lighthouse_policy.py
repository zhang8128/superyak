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


@pytest.mark.parametrize("at, allowed", [
    (datetime(2026, 8, 30, tzinfo=timezone.utc), True),  # validFrom itself
    (datetime(2027, 8, 30, tzinfo=timezone.utc), True),  # validUntil itself: the window holds both ends
    (datetime(2027, 8, 30, 0, 0, 1, tzinfo=timezone.utc), False),
    (datetime(2026, 8, 29, 23, 59, 59, tzinfo=timezone.utc), False),
])
def test_a_rule_allows_at_both_ends_of_its_window(at, allowed):
    """validFrom <= at <= validUntil, as policy.ts has it: a rule allows at each end and refuses a second outside.
    The receiver's own window test walks the same edge on a source's clock (test_context_lighthouse); this pins it in
    the policy itself, so an end made exclusive fails here."""
    decision = load_policy(FIXTURES / "policies" / "workflow-policy.json").decide(base_request(at=at))
    assert (decision.effect == "allow") is allowed, decision
    if not allowed:
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


# Ship home and crossing plan, Task 8 (P12, S4, the plan re-check's item 1): a wildcard or prefix ALLOW never matches a
# remote ref (urn:superyak:...), while wildcard and prefix DENY rules still do. A deny wins only a specificity tie.

from lighthouse_policy import Policy

PEER = "a" * 64
REF = f"urn:superyak:{PEER}:store:2f1c8a64-3b7e-4d2a-9c11-5e8f0a7b6c3d"
AT = datetime(2026, 11, 3, tzinfo=timezone.utc)


def _rule(rule_id, effect, publishers, purposes=("session-recall",)):
    return {"id": rule_id, "effect": effect, "publishers": list(publishers),
            "profiles": ["urn:lighthouse:profile:engram-recall-trace"], "domains": ["memory.recall"],
            "actions": ["recall"], "contexts": ["memory/technical"],
            "claimMediaTypes": ["application/vnd.engram.recall-rank-claim+json"], "purposes": list(purposes),
            "audiences": ["self"], "validFrom": "2026-01-01T00:00:00Z", "validUntil": "2027-01-01T00:00:00Z"}


def _decide(rules, publisher=REF):
    policy = Policy({"issuer": "urn:engram:house", "payload": {"rules": rules}})
    return policy.decide(PolicyRequest(
        publisher=publisher, profile="urn:lighthouse:profile:engram-recall-trace", domain="memory.recall",
        action="recall", context_id="memory/technical", claim_type="application/vnd.engram.recall-rank-claim+json",
        purpose="session-recall", audience="self", at=AT))


@pytest.mark.parametrize("pattern", ["*", "urn:engram:*", "urn:superyak:*", f"urn:superyak:{PEER}:*",
                                     f"urn:superyak:{PEER}:store:*"])
def test_no_wildcard_or_prefix_allow_matches_a_remote_ref(pattern):
    assert _decide([_rule("wide", "allow", [pattern])]) == Decision("deny", None, "NO_MATCHING_ALLOW")


def test_only_an_exact_allow_matches_a_remote_ref():
    assert _decide([_rule("exact", "allow", [REF])]) == Decision("allow", "exact", None)
    assert _decide([_rule("exact", "allow", [REF])], publisher=REF[:-1] + "e").effect == "deny"


def test_local_prefix_matching_is_unchanged():
    assert _decide([_rule("wide", "allow", ["urn:engram:*"])], publisher="urn:engram:tardis").effect == "allow"
    assert _decide([_rule("any", "allow", ["*"])], publisher="urn:engram:tardis").effect == "allow"


@pytest.mark.parametrize("pattern", ["*", f"urn:superyak:{PEER}:*"])
def test_a_wildcard_deny_still_refuses_a_remote_ref(pattern):
    assert _decide([_rule("no", "deny", [pattern])]) == Decision("deny", "no", "EXPLICIT_DENY")


def test_an_exact_allow_beats_a_wildcard_deny_as_today():
    assert _decide([_rule("no", "deny", ["*"]), _rule("exact", "allow", [REF])]) == Decision("allow", "exact", None)


def test_a_wildcard_deny_wins_a_tie_with_an_exact_allow():
    """The plan re-check's item 1: a *-publisher deny with an exact purpose (1 + 2) ties an exact-ref allow with
    purposes [*] (2 + 1), and a deny wins a tie. Were denies disarmed too, the allow would win."""
    rules = [_rule("no", "deny", ["*"], purposes=["session-recall"]), _rule("exact", "allow", [REF], purposes=["*"])]
    assert _decide(rules) == Decision("deny", "no", "EXPLICIT_DENY")
