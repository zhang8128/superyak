from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

import neighbors
from lighthouse_protocol import artifact_digest, canonical_json, content_digest
from lighthouse_receipts import validate_receipt

CONTEXT = {"id": "memory/technical", "path": ["memory", "technical"]}
NOW = datetime(2026, 9, 6, tzinfo=timezone.utc)
ALLOW = {"effect": "allow", "ruleId": "publisher-rule", "code": None}


def policy(path, actions=("recall", "read", "inject_context"), *, publisher="why", weight=1, issuer="engram"):
    rule = dict(id="chosen", effect="allow", publishers=[f"urn:engram:{publisher}"],
                profiles=["urn:lighthouse:profile:engram-recall-trace"], domains=["memory.recall"],
                actions=list(actions), contexts=["memory/technical"],
                claimMediaTypes=["application/vnd.engram.recall-rank-claim+json"],
                purposes=["session-recall"], audiences=["self"],
                validFrom="2026-01-01T00:00:00Z", validUntil="2027-01-01T00:00:00Z",
                requiredEvidence=[], requiredAttestations=[])
    artifact = dict(protocolVersion="0.1", kind="ConnectionPolicy", id="urn:policy:receiver",
                    issuedAt="2026-01-01T00:00:00Z", issuer=f"urn:engram:{issuer}",
                    payloadMediaType="application/vnd.lighthouse.connection-policy+json", payload={"rules": [rule] if actions else []},
                    extensions={"engram:weight": {f"urn:engram:{publisher}": weight}})
    artifact["digest"] = artifact_digest(artifact)
    path.write_text(json.dumps(artifact))
    return artifact


class Log:
    def __init__(self): self.entries = []
    def add_log_entry(self, **kw): self.entries.append(kw)


@pytest.fixture
def crossing(tmp_path, monkeypatch):
    path = tmp_path / "policy.json"
    policy(path)
    calls = []
    content = "A privately authored, explicitly shared bridge memory."
    def call(self, frame, *, deadline=None):
        calls.append(frame)
        if frame["kind"] == "recall":
            return dict(protocolVersion="0.1", kind="recall_result", turnId="publisher-turn",
                        queryDigest=content_digest(frame["query"]), context=frame["context"],
                        candidates=[dict(memoryId="m1", rank=1, layer="episode", lane="personal",
                                         audiences=["commons"], contentDigest=content_digest(content))],
                        decision=ALLOW, disclosureId="disclosure-1")
        return dict(protocolVersion="0.1", kind="read_result", disclosureId="disclosure-2",
                    items=[dict(memoryId="m1", content=content, audiences=["commons"], decision=ALLOW)])
    monkeypatch.setattr(neighbors.LighthouseClient, "call", call)
    args = dict(query="private query", context=deepcopy(CONTEXT), purpose="session-recall", k=1,
                storage=Log(), session_id="s", recall_id="local-turn", receiver="engram",
                publishers=["why"], socket_path=tmp_path / "s.sock", policy_path=path, now=lambda: NOW)
    return args, calls, content, call


def test_crossing_has_reproducible_content_free_receipt(crossing):
    args, calls, content, _ = crossing
    result = neighbors.neighbor_arm(**args)
    assert [c["kind"] for c in calls] == ["recall", "read"]
    assert result["delivered"][0]["content"] == content
    assert result["delivered"][0]["lane"] == "personal"
    assert calls[1]["turnId"] == "publisher-turn"
    receipt = args["storage"].entries[0]["context"]["receipt"]
    validate_receipt(receipt)
    assert receipt["payload"]["injected"] is True
    assert receipt["payload"]["sources"][0]["policyDecision"]["ruleId"] == "chosen"
    snapshot = receipt["extensions"]["engram:traceSnapshots"][0]
    assert receipt["payload"]["sources"][0]["storeDigest"] == content_digest(canonical_json(snapshot))
    assert args["query"] not in json.dumps(receipt)
    assert content not in json.dumps(receipt)


@pytest.mark.parametrize("actions", [(), ("read", "inject_context")])
def test_recall_permission_precedes_query(crossing, actions):
    args, calls, _, _ = crossing
    policy(args["policy_path"], actions=actions)
    assert neighbors.neighbor_arm(**args) is None
    assert calls == []


@pytest.mark.parametrize("actions", [("recall",), ("recall", "read"), ("recall", "inject_context")])
def test_independent_delivery_permissions(crossing, actions):
    args, calls, _, _ = crossing
    policy(args["policy_path"], actions=actions)
    result = neighbors.neighbor_arm(**args)
    assert [c["kind"] for c in calls] == ["recall"]
    assert result["delivered"] == []
    assert args["storage"].entries[0]["context"]["receipt"]["payload"]["injected"] is False


def test_local_revocation_during_read_prevents_delivery(crossing, monkeypatch):
    args, _, _, call = crossing
    def revoke(self, frame, **kw):
        result = call(self, frame, **kw)
        if frame["kind"] == "read": policy(args["policy_path"], actions=("recall", "read"))
        return result
    monkeypatch.setattr(neighbors.LighthouseClient, "call", revoke)
    assert neighbors.neighbor_arm(**args)["delivered"] == []


def test_receipt_write_failure_suppresses_content(crossing):
    args, _, content, _ = crossing
    def fail(**kw): raise OSError("disk full")
    args["storage"].add_log_entry = fail
    result = neighbors.neighbor_arm(**args)
    assert result["delivered"] == []
    assert result["degraded"] is True
    assert content not in json.dumps(result)


def test_partial_unavailable_has_no_fabricated_digest(crossing, monkeypatch):
    args, calls, _, call = crossing
    policy(args["policy_path"], publisher="*")
    args["publishers"] = ["missing", "why"]
    def partial(self, frame, **kw):
        if frame["publisher"] == "missing": raise neighbors.NeighborUnavailable("UNAVAILABLE")
        return call(self, frame, **kw)
    monkeypatch.setattr(neighbors.LighthouseClient, "call", partial)
    result = neighbors.neighbor_arm(**args)
    assert len(result["delivered"]) == 1
    receipt = args["storage"].entries[0]["context"]["receipt"]
    assert [s["publisher"] for s in receipt["payload"]["sources"]] == ["urn:engram:why"]
    unavailable = receipt["extensions"]["engram:unavailableSources"]
    assert unavailable[0]["publisher"] == "urn:engram:missing"
    assert "storeDigest" not in unavailable[0]
    assert set(c["publisher"] for c in calls) == {"why"}


@pytest.mark.parametrize("change", ["issuer", "weight", "shape", "digest"])
def test_invalid_policy_stops_before_query(crossing, change):
    args, calls, _, _ = crossing
    artifact = policy(args["policy_path"])
    if change == "issuer": artifact["issuer"] = "urn:engram:stranger"
    if change == "weight": artifact["extensions"]["engram:weight"]["urn:engram:why"] = -1
    if change == "shape": artifact["payload"]["rules"][0]["contexts"] = "memory/technical"
    artifact["digest"] = artifact_digest(artifact)
    if change == "digest": artifact["digest"]["value"] = "0" * 64
    args["policy_path"].write_text(json.dumps(artifact))
    result = neighbors.neighbor_arm(**args)
    assert result["degraded"] is True
    assert calls == []


def test_no_config_or_context_is_inert(tmp_path, monkeypatch):
    def fail(**kw): raise AssertionError("must not consult")
    monkeypatch.setattr(neighbors, "neighbor_arm", fail)
    for context in (None, "memory/technical"):
        response = {"results": [{"id": "local", "score": 0.7}], "recall_id": "r", "margin": {"gap": 0.2}}
        original = deepcopy(response)
        neighbors.attach_neighbors(response, query="query", context_id=context, purpose="session-recall",
                                   storage=Log(), session_id="s", receiver="engram", engram_home=tmp_path)
        assert response == original


def test_receiver_can_weight_peers_without_transitive_discovery(crossing, monkeypatch):
    args, calls, _, call = crossing
    artifact = policy(args["policy_path"], weight=1)
    second = deepcopy(artifact["payload"]["rules"][0])
    second.update(id="prefer-mike", publishers=["urn:engram:mike"])
    artifact["extensions"]["engram:weight"]["urn:engram:mike"] = 2
    artifact["payload"]["rules"].append(second)
    artifact["digest"] = artifact_digest(artifact)
    args["policy_path"].write_text(json.dumps(artifact))
    args["publishers"] = ["why", "mike"]
    result = neighbors.neighbor_arm(**args)
    assert result["selected"][0]["publisher"] == "urn:engram:mike"
    assert result["selected"][0]["score"] == pytest.approx(2 / 61)
    assert result["delivered"][0]["publisher"] == "urn:engram:mike"
    assert set(c["publisher"] for c in calls) == {"why", "mike"}


def test_revocation_after_trace_prevents_read(crossing, monkeypatch):
    args, calls, _, call = crossing
    def revoke(self, frame, **kw):
        reply = call(self, frame, **kw)
        policy(args["policy_path"], actions=())
        return reply
    monkeypatch.setattr(neighbors.LighthouseClient, "call", revoke)
    assert neighbors.neighbor_arm(**args)["delivered"] == []
    assert [c["kind"] for c in calls] == ["recall"]


def test_context_mismatch_is_unavailable_and_never_read(crossing, monkeypatch):
    args, calls, _, call = crossing
    def mismatch(self, frame, **kw):
        reply = call(self, frame, **kw)
        reply["context"] = {"id": "memory/other", "path": ["memory", "other"]}
        return reply
    monkeypatch.setattr(neighbors.LighthouseClient, "call", mismatch)
    result = neighbors.neighbor_arm(**args)
    assert result["delivered"] == []
    assert result["diagnostics"][0]["code"] == "CONTEXT_MISMATCH"
    receipt = args["storage"].entries[0]["context"]["receipt"]
    assert receipt["extensions"]["engram:diagnostics"] == result["diagnostics"]
    assert [c["kind"] for c in calls] == ["recall"]


def test_config_paths_are_relative_and_store_identity_is_checked(tmp_path, monkeypatch):
    instance = tmp_path / ".engram" / "instances" / "engram"
    instance.mkdir(parents=True)
    (instance / "lighthouse-receiver.toml").write_text(
        'enabled = true\npublishers = ["why"]\nsocket_path = "../../lighthouse.sock"\npolicy_path = "policy.json"\n')
    log = Log()
    log.db_path = str(instance / "graph.db")
    calls = []
    def arm(**kw): calls.append(kw); return None
    monkeypatch.setattr(neighbors, "neighbor_arm", arm)
    kw = dict(query="rivers", context_id="memory/technical", purpose="session-recall", storage=log,
              session_id="s", receiver="engram", engram_home=tmp_path)
    response = {"results": [], "recall_id": "r"}
    neighbors.attach_neighbors(response, **kw)
    assert calls[0]["socket_path"] == tmp_path / ".engram" / "lighthouse.sock"
    assert calls[0]["policy_path"] == instance / "policy.json"
    log.db_path = str(tmp_path / ".engram" / "graph.db")
    neighbors.attach_neighbors(response, **kw)
    assert len(calls) == 1
    assert response["degraded"] == ["neighbors"]


@pytest.mark.parametrize("text", [
    'enabled = true\npublishers = ["../escape"]',
    'enabled = true\npublishers = ["why", "why"]',
    'enabled = true\npublishers = ["why"]\nlimit = 50',
    'enabled = true\npublishers = ["why"]\ntimeout_s = inf',
])
def test_invalid_config_fails_closed(tmp_path, text):
    from lighthouse_receiver_config import load_settings
    path = tmp_path / "receiver.toml"
    path.write_text(text)
    with pytest.raises(ValueError): load_settings(path)


def test_receiver_policy_matches_vendored_lighthouse_schema(crossing):
    import os
    from pathlib import Path
    from lighthouse_receiver_config import load_receiver_policy
    args, _, _, _ = crossing
    loaded = load_receiver_policy(args["policy_path"], "engram")
    assert loaded.issuer == "urn:engram:engram"
    upstream = Path(os.environ.get("LIGHTHOUSE_REPO", Path.home() / "Projects/lighthouse")) / "schemas/connection-policy.schema.json"
    if not upstream.is_file():
        pytest.skip("optional sibling Lighthouse kit unavailable; set LIGHTHOUSE_REPO")
    assert (Path(__file__).resolve().parents[1] / "schemas/lighthouse/connection-policy.schema.json").read_bytes() == upstream.read_bytes()


@pytest.mark.parametrize("change", ["date", "duplicate", "rule_extension"])
def test_strict_policy_rejects_ambiguous_or_nonstandard_grants(crossing, change):
    args, calls, _, _ = crossing
    artifact = policy(args["policy_path"])
    if change == "date": artifact["payload"]["rules"][0]["validFrom"] = "2026-01-01"
    if change == "rule_extension": artifact["payload"]["rules"][0]["extensions"] = {"engram:weight": 1}
    artifact["digest"] = artifact_digest(artifact)
    text = json.dumps(artifact)
    if change == "duplicate": text = text.replace('"effect": "allow"', '"effect": "deny", "effect": "allow"')
    args["policy_path"].write_text(text)
    assert neighbors.neighbor_arm(**args)["degraded"] is True
    assert calls == []


@pytest.mark.parametrize("revoke_first", [False, True])
def test_content_budget_follows_rank_after_revocation(crossing, monkeypatch, revoke_first):
    args, _, _, _ = crossing
    policy(args["policy_path"], publisher="*")
    args.update(publishers=["why", "mike"], k=2)
    content = "x" * 20000
    def call(self, frame, **kw):
        publisher = frame["publisher"]
        if frame["kind"] == "recall":
            return dict(protocolVersion="0.1", kind="recall_result", turnId=publisher,
                        queryDigest=content_digest(frame["query"]), context=frame["context"],
                        decision=ALLOW, disclosureId="d1",
                        candidates=[dict(memoryId="m1", rank=20 if publisher == "why" else 1,
                                         layer="episode", lane="work", audiences=["commons"],
                                         contentDigest=content_digest(content))])
        if revoke_first and publisher == "mike":
            policy(args["policy_path"], publisher="mike")
        return dict(protocolVersion="0.1", kind="read_result", disclosureId="d2",
                    items=[dict(memoryId="m1", content=content, audiences=["commons"], decision=ALLOW)])
    monkeypatch.setattr(neighbors.LighthouseClient, "call", call)
    result = neighbors.neighbor_arm(**args)
    assert result["selected"][0]["publisher"] == "urn:engram:mike"
    assert [i["publisher"] for i in result["delivered"]] == ["urn:engram:mike"]
