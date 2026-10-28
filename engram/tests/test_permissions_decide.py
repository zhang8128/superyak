"""Task 5: subjects, required layers, need and the decision (P 6.3 to 6.5, refusal codes)."""
from datetime import datetime, timezone

from permissions import Cited, Refusal, decide, needs
from lighthouse_policy import Policy, PolicyRequest
from tests.permissions_support import (
    T, co_subject_world, copy_in_unregistered_house, dated_deny_use, e1_after_use_10, ended_allow_use,
    future_allow_use, legacy_refusal_use, nine_subjects_use, no_subject_use, object_in_unregistered_store,
    one_grant_backed_record, one_ref_two_houses, placement_without_source_instance_id, retired_subject_home_use,
    revoked_grant_use, silent_layer_use, sorted_actions, two_owner_imprint_use, unregistered_agent_use)


def test_u28_each_refusal_code():
    cases = {"UNKNOWN_REQUESTER": unregistered_agent_use, "RETIRED": retired_subject_home_use,
             "NO_LAYER": no_subject_use, "BOUND": nine_subjects_use, "DENIED": dated_deny_use,
             "EXPIRED": ended_allow_use, "GRANT_INVALID": revoked_grant_use, "NOT_YET": future_allow_use,
             "NO_ALLOW": silent_layer_use, "LEGACY_DENY": legacy_refusal_use}
    for code, build in cases.items():
        s, u, legacy = build()
        assert decide(s, u, legacy=legacy).refusal.code == code, code


def test_u28_expired_against_grant_invalid_against_not_yet_on_one_record():
    s, u = one_grant_backed_record(valid_from=T("2026-11-05"), valid_until=T("2026-11-20"))
    assert decide(s, u(at=T("2026-11-01"))).refusal.code == "NOT_YET"
    assert decide(s, u(at=T("2026-11-21"))).refusal.code == "EXPIRED"
    s2, u2 = one_grant_backed_record(revoked_grant=True)
    assert decide(s2, u2(at=T("2026-11-10"))).refusal.code == "GRANT_INVALID"


def test_u28_use_10_read_of_m4():
    s, read_m4 = e1_after_use_10()    # R1' covers m4 only through G1's membership; G1 revoked 2026-11-20
    assert decide(s, read_m4(T("2026-11-21"))).refusal == Refusal("GRANT_INVALID", "place:home/andy", "recall")
    assert decide(s, read_m4(T("2026-11-30"))).refusal == Refusal("EXPIRED", "place:home/andy", "recall")


def test_u28_a_co_subject_is_no_allow_when_registered_with_an_empty_home_and_no_layer_when_not():
    # P 7.4: "NO_ALLOW if they are registered with an empty home layer, NO_LAYER if not". person:amy sorts before
    # person:andy, so her home is the first layer in step 2's order either way.
    s, u = co_subject_world(register_amy=True)
    assert decide(s, u).refusal == Refusal("NO_ALLOW", "place:home/amy", "recall")
    s, u = co_subject_world(register_amy=False)
    assert decide(s, u).refusal == Refusal("NO_LAYER", "place:home/amy", "recall")   # her layer is `missing`


def test_u21_unregistered_store_no_source_and_unregistered_house_are_no_layer():
    for s, u in [object_in_unregistered_store(), placement_without_source_instance_id(),
                 copy_in_unregistered_house()]:
        assert decide(s, u).refusal.code == "NO_LAYER"


def test_u21_the_same_ref_in_two_houses_uses_each_house_place():
    s, at_home, at_clinic = one_ref_two_houses()   # the clinic's layer refuses imprint, the home's allows it
    assert decide(s, at_home).allowed and not decide(s, at_clinic).allowed


def rule(rid, effect, publishers, contexts):
    return {"id": rid, "effect": effect, "publishers": publishers, "profiles": ["pr"], "domains": ["d"],
            "actions": ["recall"], "contexts": contexts, "claimMediaTypes": ["m"], "purposes": ["u"],
            "audiences": ["self"], "validFrom": "2026-01-01T00:00:00Z", "validUntil": "2027-01-01T00:00:00Z",
            "requiredEvidence": [], "requiredAttestations": []}


def policy_artifact(rules):
    return {"issuer": "urn:lighthouse:t", "payload": {"rules": rules}}


def policy_request(publisher, context):
    return PolicyRequest(publisher=publisher, profile="pr", domain="d", action="recall", context_id=context,
                         claim_type="m", purpose="u", audience="self",
                         at=datetime(2026, 11, 2, tzinfo=timezone.utc))


def test_u1_most_specific_wins_is_not_monotone():
    a = rule("A", "allow", publishers=["urn:engram:*"], contexts=["memory/technical"])
    d = rule("D", "deny", publishers=["urn:engram:x"], contexts=["memory/*"])
    request = policy_request(publisher="urn:engram:x", context="memory/technical")
    assert Policy(policy_artifact([a, d])).decide(request).effect == "deny"
    narrowed = rule("A", "allow", publishers=["urn:engram:x"], contexts=["memory/technical"])
    assert Policy(policy_artifact([narrowed, d])).decide(request).effect == "allow"


def test_an_outside_layer_is_that_layers_whole_verdict():
    w, u = two_owner_imprint_use()     # sam's copy; Andy's home layer holds his own allows, none naming sam's store
    s = w.state()
    refusal = decide(s, u).refusal                                                    # the ledger layer alone
    assert (refusal.code, refusal.layer) == ("NO_ALLOW", "place:home/andy")
    d = decide(s, u, outside={"place:home/andy": lambda use, x: "allow"})
    assert d.allowed and [c for c in d.cited if c.layer == "place:home/andy"] == [
        Cited("place:home/andy", "outside", x, "allow", ()) for x in sorted_actions(needs(u))]
    w.deny("place:home/andy", audience=["commons"], actions=["imprint"])               # a ledger deny there
    assert decide(w.state(), u, outside={"place:home/andy": lambda use, x: "allow"}).allowed   # not read
    assert decide(s, u, outside={"place:home/andy": lambda use, x: "silent"}).refusal.code == "NO_ALLOW"
