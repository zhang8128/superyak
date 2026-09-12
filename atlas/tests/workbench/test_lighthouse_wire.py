"""Wire invariants and independent Lighthouse policy decision fixtures."""

from copy import deepcopy
import importlib
import json

import pytest


@pytest.fixture
def wire():
    return importlib.import_module("workbench.lighthouse_wire")


ISSUER = "urn:atlas:lab"
TIME = "2026-09-07T00:00:00Z"
REF = {"id": "urn:atlas:research", "version": "1.0.0"}


def payload(kind):
    if kind == "LighthouseDescriptor":
        return dict(name="Atlas", protocolVersions=["0.1"], profiles=[REF],
                    actions=["read"], artifactEndpoints=[{"kind": "Snapshot", "locator": "snapshot.json"}])
    if kind == "ConnectionPolicy":
        return {"rules": []}
    common = dict(profile=REF, signature=REF, context={"id": "research", "path": ["research"]})
    if kind == "Snapshot":
        return common | dict(model={"items": []}, lineage=[])
    return common | dict(sentenceMediaType="application/vnd.atlas.record-claim+json",
                         sentence={"id": "claim-1"}, snapshotDigests=[], provenance=[])


def test_canonicalization_matches_ecmascript_utf16_order_and_known_digest(wire):
    assert wire.canonical_json({"\ue000": 1, "😀": 2, "a": "é\n"}) == '{"a":"é\\n","😀":2,"\ue000":1}'
    assert wire.digest({}) == {"algorithm": "sha-256", "value": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"}


@pytest.mark.parametrize("value", [1.0, float("nan"), 2**53, -(2**53), {1: "x"}, (1,), object()])
def test_unsupported_json_values_fail_explicitly(wire, value):
    with pytest.raises(ValueError):
        wire.canonical_json(value)


def test_cycles_are_rejected(wire):
    value = []
    value.append(value)
    with pytest.raises(ValueError):
        wire.canonical_json(value)


@pytest.mark.parametrize("kind", ["LighthouseDescriptor", "Snapshot", "Claim", "ConnectionPolicy"])
def test_supported_artifacts_validate_and_detect_payload_tampering(wire, kind):
    artifact = wire.seal(kind, ISSUER, ISSUER + ":artifact", TIME, payload(kind))
    assert wire.verify(artifact, kind) == artifact
    artifact["issuedAt"] = "2026-09-08T00:00:00Z"
    with pytest.raises(ValueError):
        wire.verify(artifact)


def test_extensions_are_preserved_and_attestations_excluded_from_digest(wire):
    artifact = wire.seal("Snapshot", ISSUER, ISSUER + ":s", TIME, payload("Snapshot"))
    artifact["extensions"] = {"atlas:extra": {"a": 1}}
    artifact["digest"] = wire.digest({k: v for k, v in artifact.items() if k != "digest"})
    artifact["attestations"] = [{"algorithm": "test", "keyId": "key", "signature": "sig"}]
    assert wire.verify(artifact)["extensions"] == artifact["extensions"]


@pytest.mark.parametrize("change", [
    {"extra": True}, {"kind": "Unknown"}, {"issuer": "not a URI"},
    {"issuedAt": "2026-09-07T00:00:00"}, {"issuedAt": "2026-02-30T00:00:00Z"},
    {"issuedAt": "2026-09-07 00:00:00+00:00"},
    {"issuedAt": "2026-09-07T00:00:00+00:60"},
    {"digest": {"algorithm": "sha256", "value": "0" * 64}},
    {"extensions": {"unnamespaced": 1}},
])
def test_strict_envelope_rejects_invalid_members_even_after_resealing(wire, change):
    artifact = wire.seal("Snapshot", ISSUER, ISSUER + ":s", TIME, payload("Snapshot"))
    artifact.update(change)
    if "digest" not in change:
        artifact["digest"] = wire.digest({k: v for k, v in artifact.items() if k != "digest"})
    with pytest.raises(ValueError):
        wire.verify(artifact)


@pytest.mark.parametrize("kind,field,value", [
    ("Snapshot", "profile", {"id": "urn:p", "version": "1", "extra": 1}),
    ("Snapshot", "context", {"id": "r", "path": [1]}),
    ("Snapshot", "lineage", [{"algorithm": "sha-256", "value": "bad"}]),
    ("Claim", "provenance", ["paper URL"]),
    ("Claim", "validUntil", "yesterday"),
    ("LighthouseDescriptor", "artifactEndpoints", [{"kind": "Unknown", "locator": "file"}]),
    ("ConnectionPolicy", "rules", [{"id": "incomplete"}]),
])
def test_strict_nested_payload_validation(wire, kind, field, value):
    body = payload(kind)
    body[field] = value
    with pytest.raises(ValueError):
        wire.seal(kind, ISSUER, ISSUER + ":a", TIME, body)


def test_expected_kind_is_enforced(wire):
    artifact = wire.seal("Snapshot", ISSUER, ISSUER + ":s", TIME, payload("Snapshot"))
    with pytest.raises(ValueError):
        wire.verify(artifact, "Claim")


def test_descriptor_uses_native_media_type(wire):
    # packages/conformance/src/reference.ts emits this descriptor media type.
    artifact = wire.seal("LighthouseDescriptor", ISSUER, ISSUER + ":d", TIME, payload("LighthouseDescriptor"))
    assert artifact["payloadMediaType"] == "application/vnd.lighthouse.descriptor+json"


def test_request_requires_native_fields(wire):
    policy = wire.seal("ConnectionPolicy", ISSUER, ISSUER + ":p", TIME, payload("ConnectionPolicy"))
    with pytest.raises(ValueError):
        wire.authorize(policy, {"context_id": "research"})


# Copied from Lighthouse fixtures/policy-conformance at Superyak 8b52581.
OFFICIAL = json.loads('{"policies":{"local-city":{"digest":{"algorithm":"sha-256","value":"f7b72e7f5b29c601d97b11b77a8cd841d5493b50576e76f1a098f8ad46944ffb"},"id":"urn:policy:local-city","issuedAt":"2026-09-01T00:00:00Z","issuer":"urn:lighthouse:engram","kind":"ConnectionPolicy","payload":{"rules":[{"actions":["recall","read","inject_context"],"audiences":["self"],"claimMediaTypes":["application/vnd.engram.recall-rank-claim+json"],"contexts":["memory/technical"],"domains":["memory.recall"],"effect":"allow","id":"allow-why-technical","profiles":["urn:lighthouse:profile:engram-recall-trace"],"publishers":["urn:lighthouse:why"],"purposes":["session-recall"],"requiredAttestations":[],"requiredEvidence":[],"validFrom":"2026-09-01T00:00:00Z","validUntil":"2026-10-01T00:00:00Z"},{"actions":["recall"],"audiences":["self"],"claimMediaTypes":["application/vnd.engram.recall-rank-claim+json"],"contexts":["memory/technical"],"domains":["memory.recall"],"effect":"allow","id":"allow-blocks-recall","profiles":["urn:lighthouse:profile:engram-recall-trace"],"publishers":["urn:lighthouse:blocks"],"purposes":["session-recall"],"requiredAttestations":[],"requiredEvidence":[],"validFrom":"2026-09-01T00:00:00Z","validUntil":"2026-10-01T00:00:00Z"},{"actions":["inject_context"],"audiences":["self"],"claimMediaTypes":["application/vnd.engram.recall-rank-claim+json"],"contexts":["memory/technical"],"domains":["memory.recall"],"effect":"deny","id":"deny-blocks-inject","profiles":["urn:lighthouse:profile:engram-recall-trace"],"publishers":["urn:lighthouse:blocks"],"purposes":["session-recall"],"requiredAttestations":[],"requiredEvidence":[],"validFrom":"2026-09-01T00:00:00Z","validUntil":"2026-10-01T00:00:00Z"},{"actions":["recall"],"audiences":["self"],"claimMediaTypes":["application/vnd.engram.recall-rank-claim+json"],"contexts":["memory/*"],"domains":["memory.recall"],"effect":"deny","id":"deny-gil-memory-prefix","profiles":["urn:lighthouse:profile:engram-recall-trace"],"publishers":["urn:lighthouse:gil"],"purposes":["session-recall"],"requiredAttestations":[],"requiredEvidence":[],"validFrom":"2026-09-01T00:00:00Z","validUntil":"2026-10-01T00:00:00Z"},{"actions":["recall"],"audiences":["self"],"claimMediaTypes":["application/vnd.engram.recall-rank-claim+json"],"contexts":["memory/technical"],"domains":["memory.recall"],"effect":"allow","id":"allow-gil-technical-exact","profiles":["urn:lighthouse:profile:engram-recall-trace"],"publishers":["urn:lighthouse:gil"],"purposes":["session-recall"],"requiredAttestations":[],"requiredEvidence":[],"validFrom":"2026-09-01T00:00:00Z","validUntil":"2026-10-01T00:00:00Z"},{"actions":["recall"],"audiences":["self"],"claimMediaTypes":["application/vnd.engram.recall-rank-claim+json"],"contexts":["memory/technical"],"domains":["memory.recall"],"effect":"allow","id":"allow-agi-technical","profiles":["urn:lighthouse:profile:engram-recall-trace"],"publishers":["urn:lighthouse:agi"],"purposes":["session-recall"],"requiredAttestations":[],"requiredEvidence":[],"validFrom":"2026-09-01T00:00:00Z","validUntil":"2026-10-01T00:00:00Z"},{"actions":["recall"],"audiences":["self"],"claimMediaTypes":["application/vnd.engram.recall-rank-claim+json"],"contexts":["memory/technical"],"domains":["memory.recall"],"effect":"deny","id":"deny-agi-technical","profiles":["urn:lighthouse:profile:engram-recall-trace"],"publishers":["urn:lighthouse:agi"],"purposes":["session-recall"],"requiredAttestations":[],"requiredEvidence":[],"validFrom":"2026-09-01T00:00:00Z","validUntil":"2026-10-01T00:00:00Z"}]},"payloadMediaType":"application/vnd.lighthouse.connection-policy+json","protocolVersion":"0.1"}},"cases":[{"name":"action-derive","policy":"local-city","request":{"publisher":"urn:lighthouse:blocks","profile":"urn:lighthouse:profile:engram-recall-trace","domain":"memory.recall","action":"derive","context":"memory/technical","claimMediaType":"application/vnd.engram.recall-rank-claim+json","purpose":"session-recall","audience":"self","at":"2026-09-15T00:00:00Z","evidence":[],"attestations":[]},"expected":{"decision":{"allowed":false,"code":"NO_MATCHING_ALLOW"},"policy":"local-city","request":"action-derive"}},{"name":"action-inject-context","policy":"local-city","request":{"publisher":"urn:lighthouse:blocks","profile":"urn:lighthouse:profile:engram-recall-trace","domain":"memory.recall","action":"inject_context","context":"memory/technical","claimMediaType":"application/vnd.engram.recall-rank-claim+json","purpose":"session-recall","audience":"self","at":"2026-09-15T00:00:00Z","evidence":[],"attestations":[]},"expected":{"decision":{"allowed":false,"code":"EXPLICIT_DENY","ruleId":"deny-blocks-inject"},"policy":"local-city","request":"action-inject-context"}},{"name":"action-read","policy":"local-city","request":{"publisher":"urn:lighthouse:blocks","profile":"urn:lighthouse:profile:engram-recall-trace","domain":"memory.recall","action":"read","context":"memory/technical","claimMediaType":"application/vnd.engram.recall-rank-claim+json","purpose":"session-recall","audience":"self","at":"2026-09-15T00:00:00Z","evidence":[],"attestations":[]},"expected":{"decision":{"allowed":false,"code":"NO_MATCHING_ALLOW"},"policy":"local-city","request":"action-read"}},{"name":"action-recall","policy":"local-city","request":{"publisher":"urn:lighthouse:blocks","profile":"urn:lighthouse:profile:engram-recall-trace","domain":"memory.recall","action":"recall","context":"memory/technical","claimMediaType":"application/vnd.engram.recall-rank-claim+json","purpose":"session-recall","audience":"self","at":"2026-09-15T00:00:00Z","evidence":[],"attestations":[]},"expected":{"decision":{"allowed":true,"ruleId":"allow-blocks-recall"},"policy":"local-city","request":"action-recall"}},{"name":"action-reshare","policy":"local-city","request":{"publisher":"urn:lighthouse:blocks","profile":"urn:lighthouse:profile:engram-recall-trace","domain":"memory.recall","action":"reshare","context":"memory/technical","claimMediaType":"application/vnd.engram.recall-rank-claim+json","purpose":"session-recall","audience":"self","at":"2026-09-15T00:00:00Z","evidence":[],"attestations":[]},"expected":{"decision":{"allowed":false,"code":"NO_MATCHING_ALLOW"},"policy":"local-city","request":"action-reshare"}},{"name":"action-retain","policy":"local-city","request":{"publisher":"urn:lighthouse:blocks","profile":"urn:lighthouse:profile:engram-recall-trace","domain":"memory.recall","action":"retain","context":"memory/technical","claimMediaType":"application/vnd.engram.recall-rank-claim+json","purpose":"session-recall","audience":"self","at":"2026-09-15T00:00:00Z","evidence":[],"attestations":[]},"expected":{"decision":{"allowed":false,"code":"NO_MATCHING_ALLOW"},"policy":"local-city","request":"action-retain"}},{"name":"action-suggest","policy":"local-city","request":{"publisher":"urn:lighthouse:blocks","profile":"urn:lighthouse:profile:engram-recall-trace","domain":"memory.recall","action":"suggest","context":"memory/technical","claimMediaType":"application/vnd.engram.recall-rank-claim+json","purpose":"session-recall","audience":"self","at":"2026-09-15T00:00:00Z","evidence":[],"attestations":[]},"expected":{"decision":{"allowed":false,"code":"NO_MATCHING_ALLOW"},"policy":"local-city","request":"action-suggest"}},{"name":"deny-wins-specificity-tie","policy":"local-city","request":{"publisher":"urn:lighthouse:agi","profile":"urn:lighthouse:profile:engram-recall-trace","domain":"memory.recall","action":"recall","context":"memory/technical","claimMediaType":"application/vnd.engram.recall-rank-claim+json","purpose":"session-recall","audience":"self","at":"2026-09-15T00:00:00Z","evidence":[],"attestations":[]},"expected":{"decision":{"allowed":false,"code":"EXPLICIT_DENY","ruleId":"deny-agi-technical"},"policy":"local-city","request":"deny-wins-specificity-tie"}},{"name":"exact-beats-prefix","policy":"local-city","request":{"publisher":"urn:lighthouse:gil","profile":"urn:lighthouse:profile:engram-recall-trace","domain":"memory.recall","action":"recall","context":"memory/technical","claimMediaType":"application/vnd.engram.recall-rank-claim+json","purpose":"session-recall","audience":"self","at":"2026-09-15T00:00:00Z","evidence":[],"attestations":[]},"expected":{"decision":{"allowed":true,"ruleId":"allow-gil-technical-exact"},"policy":"local-city","request":"exact-beats-prefix"}},{"name":"explicit-deny","policy":"local-city","request":{"publisher":"urn:lighthouse:blocks","profile":"urn:lighthouse:profile:engram-recall-trace","domain":"memory.recall","action":"inject_context","context":"memory/technical","claimMediaType":"application/vnd.engram.recall-rank-claim+json","purpose":"session-recall","audience":"self","at":"2026-09-15T00:00:00Z","evidence":[],"attestations":[]},"expected":{"decision":{"allowed":false,"code":"EXPLICIT_DENY","ruleId":"deny-blocks-inject"},"policy":"local-city","request":"explicit-deny"}},{"name":"no-matching-allow","policy":"local-city","request":{"publisher":"urn:lighthouse:claw","profile":"urn:lighthouse:profile:engram-recall-trace","domain":"memory.recall","action":"recall","context":"memory/technical","claimMediaType":"application/vnd.engram.recall-rank-claim+json","purpose":"session-recall","audience":"self","at":"2026-09-15T00:00:00Z","evidence":[],"attestations":[]},"expected":{"decision":{"allowed":false,"code":"NO_MATCHING_ALLOW"},"policy":"local-city","request":"no-matching-allow"}},{"name":"non-transitive-claw","policy":"local-city","request":{"publisher":"urn:lighthouse:claw","profile":"urn:lighthouse:profile:engram-recall-trace","domain":"memory.recall","action":"read","context":"memory/technical","claimMediaType":"application/vnd.engram.recall-rank-claim+json","purpose":"session-recall","audience":"self","at":"2026-09-15T00:00:00Z","evidence":[],"attestations":[]},"expected":{"decision":{"allowed":false,"code":"NO_MATCHING_ALLOW"},"policy":"local-city","request":"non-transitive-claw"}},{"name":"outside-validity","policy":"local-city","request":{"publisher":"urn:lighthouse:why","profile":"urn:lighthouse:profile:engram-recall-trace","domain":"memory.recall","action":"recall","context":"memory/technical","claimMediaType":"application/vnd.engram.recall-rank-claim+json","purpose":"session-recall","audience":"self","at":"2026-12-01T00:00:00Z","evidence":[],"attestations":[]},"expected":{"decision":{"allowed":false,"code":"OUTSIDE_VALIDITY"},"policy":"local-city","request":"outside-validity"}},{"name":"prefix-deny-applies","policy":"local-city","request":{"publisher":"urn:lighthouse:gil","profile":"urn:lighthouse:profile:engram-recall-trace","domain":"memory.recall","action":"recall","context":"memory/personal","claimMediaType":"application/vnd.engram.recall-rank-claim+json","purpose":"session-recall","audience":"self","at":"2026-09-15T00:00:00Z","evidence":[],"attestations":[]},"expected":{"decision":{"allowed":false,"code":"EXPLICIT_DENY","ruleId":"deny-gil-memory-prefix"},"policy":"local-city","request":"prefix-deny-applies"}}]}')


@pytest.mark.parametrize("case", OFFICIAL["cases"], ids=lambda case: case["name"])
def test_official_policy_decisions(wire, case):
    assert wire.authorize(OFFICIAL["policies"][case["policy"]], case["request"]) == case["expected"]["decision"]


def test_policy_evidence_and_attestations_are_required(wire):
    case = next(c for c in OFFICIAL["cases"] if c["name"] == "action-recall")
    policy = deepcopy(OFFICIAL["policies"][case["policy"]])
    rule = next(r for r in policy["payload"]["rules"] if r["id"] == case["expected"]["decision"]["ruleId"])
    rule["requiredEvidence"] = ["paper"]
    rule["requiredAttestations"] = ["reviewer"]
    policy = wire.seal("ConnectionPolicy", ISSUER, ISSUER + ":p", TIME, {"rules": [rule]})
    request = deepcopy(case["request"])
    assert wire.authorize(policy, request) == {"allowed": False, "code": "NO_MATCHING_ALLOW"}
    request.update(evidence=["paper"], attestations=["reviewer"])
    assert wire.authorize(policy, request) == {"allowed": True, "ruleId": rule["id"]}


@pytest.mark.parametrize("mutation", ["duplicate", "backwards", "empty", "wildcard", "unknown"])
def test_malformed_policy_rules_rejected(wire, mutation):
    rule = deepcopy(next(iter(OFFICIAL["policies"].values()))["payload"]["rules"][0])
    rules = [rule]
    if mutation == "duplicate": rules.append(deepcopy(rule))
    if mutation == "backwards": rule["validUntil"] = "2000-01-01T00:00:00Z"
    if mutation == "empty": rule["publishers"] = []
    if mutation == "wildcard": rule["publishers"] = ["urn:*:invalid"]
    if mutation == "unknown": rule["extra"] = True
    with pytest.raises(ValueError):
        wire.seal("ConnectionPolicy", ISSUER, ISSUER + ":p", TIME, {"rules": rules})


def test_policy_time_precision_matches_native_milliseconds(wire):
    case = next(c for c in OFFICIAL["cases"] if c["name"] == "action-recall")
    policy = deepcopy(OFFICIAL["policies"][case["policy"]])
    rule = next(r for r in policy["payload"]["rules"] if r["id"] == "allow-blocks-recall")
    rule.update(validFrom="2026-09-15T00:00:00.000Z", validUntil="2026-09-15T00:00:00.000Z")
    policy = wire.seal("ConnectionPolicy", ISSUER, ISSUER + ":p", TIME, {"rules": [rule]})
    request = case["request"] | {"at": "2026-09-15T00:00:00.0009Z"}
    assert wire.authorize(policy, request) == {"allowed": True, "ruleId": rule["id"]}
