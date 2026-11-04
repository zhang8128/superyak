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


def policy(path, actions=("recall", "read", "inject_context"), *, publisher="why", weight=1, issuer="engram", valid_until="2027-01-01T00:00:00Z"):
    rule = dict(id="chosen", effect="allow", publishers=[f"urn:engram:{publisher}"],
                profiles=["urn:lighthouse:profile:engram-recall-trace"], domains=["memory.recall"],
                actions=list(actions), contexts=["memory/technical"],
                claimMediaTypes=["application/vnd.engram.recall-rank-claim+json"],
                purposes=["session-recall"], audiences=["self"],
                validFrom="2026-01-01T00:00:00Z", validUntil=valid_until,
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
    result = neighbors.neighbor_arm(**args)
    assert result["diagnostics"][0] == {"code": "NO_MATCHING_ALLOW"}
    assert calls == []


def test_expired_rule_says_outside_validity(crossing):
    args, calls, _, _ = crossing
    policy(args["policy_path"], valid_until="2026-06-01T00:00:00Z")
    result = neighbors.neighbor_arm(**args)
    assert result["degraded"] is True
    assert result["diagnostics"] == [{"code": "OUTSIDE_VALIDITY"},
                                     {"publisher": "urn:engram:why", "code": "OUTSIDE_VALIDITY"}]
    assert calls == []


def test_no_matching_allow_names_each_publisher(crossing):
    args, calls, _, _ = crossing
    args["publishers"] = ["other"]
    result = neighbors.neighbor_arm(**args)
    assert result["diagnostics"] == [{"code": "NO_MATCHING_ALLOW"},
                                     {"publisher": "urn:engram:other", "code": "NO_MATCHING_ALLOW"}]
    assert calls == []


def test_mixed_denials_give_rules_denied_with_both(crossing):
    args, calls, _, _ = crossing
    policy(args["policy_path"], valid_until="2026-06-01T00:00:00Z")
    args["publishers"] = ["why", "other"]
    result = neighbors.neighbor_arm(**args)
    assert result["diagnostics"][0] == {"code": "RECEIVER_RULES_DENIED"}
    assert result["diagnostics"][1:] == [{"publisher": "urn:engram:why", "code": "OUTSIDE_VALIDITY"},
                                         {"publisher": "urn:engram:other", "code": "NO_MATCHING_ALLOW"}]
    assert calls == []


def test_attach_neighbors_degrades_on_denied_rules(tmp_path, monkeypatch):
    denied = neighbors._empty("OUTSIDE_VALIDITY")
    monkeypatch.setattr(neighbors, "neighbor_arm", lambda **kw: denied)
    monkeypatch.setattr(neighbors, "context_ref", lambda c: CONTEXT)
    instance = tmp_path / ".engram" / "instances" / "engram"
    instance.mkdir(parents=True)
    monkeypatch.setattr(neighbors, "load_settings", lambda p: {})
    (instance / "graph.db").write_text("")
    storage = type("S", (), {"db_path": instance / "graph.db"})()
    response = neighbors.attach_neighbors(dict(recall_id="r"), query="q", context_id="memory/technical",
                                          purpose="session-recall", storage=storage, session_id="s",
                                          receiver="engram", engram_home=tmp_path)
    assert response["degraded"] == ["neighbors"]


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


def test_no_context_is_inert(tmp_path, monkeypatch):
    def fail(**kw): raise AssertionError("must not consult")
    monkeypatch.setattr(neighbors, "neighbor_arm", fail)
    response = {"results": [{"id": "local", "score": 0.7}], "recall_id": "r", "margin": {"gap": 0.2}}
    original = deepcopy(response)
    neighbors.attach_neighbors(response, query="query", context_id=None, purpose="session-recall",
                               storage=Log(), session_id="s", receiver="engram", engram_home=tmp_path)
    assert response == original


@pytest.mark.parametrize("receiver, code", [("engram", "RECEIVER_DISABLED"), (None, "NO_RECEIVER")])
def test_an_asked_neighbor_that_cannot_be_reached_says_so(tmp_path, monkeypatch, receiver, code):
    """A recall that names a lighthouse context but reaches no neighbor says so (Rio Grande's Engram test,
    2026-11-03): local results alone, returned silently, would let a ship think it searched shared memory."""
    def fail(**kw): raise AssertionError("must not consult")
    monkeypatch.setattr(neighbors, "neighbor_arm", fail)
    response = {"results": [{"id": "local", "score": 0.7}], "recall_id": "r", "margin": {"gap": 0.2}}
    neighbors.attach_neighbors(response, query="query", context_id="memory/technical", purpose="session-recall",
                               storage=Log(), session_id="s", receiver=receiver, engram_home=tmp_path)
    assert response["results"] == [{"id": "local", "score": 0.7}]
    assert response["neighbors"]["diagnostics"] == [{"code": code}]
    assert response["neighbors"]["delivered"] == [] and "neighbors" in response["degraded"]


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
    upstream = Path(os.environ.get(
        "LIGHTHOUSE_REPO", Path(__file__).resolve().parents[2] / "lighthouse"
    )) / "schemas/connection-policy.schema.json"
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


# ---------------------------------------------------------------- ship home and crossing plan, Task 11: remote publishers
# (P14, P15, P19's asking seam, B5). A remote publisher is asked only through `ask`, the function with the store host's
# call shape; today attach_neighbors binds lighthouse_client.ask_crossing to the receiver's crossing.sock.

import socketserver
import tempfile
import threading
import time
from pathlib import Path

PEER = "c" * 64
SHIP = "d" * 32
SHIP_REF = f"urn:superyak:{PEER}:ship:{SHIP}"
INSTANCE = "2f1c8a64-3b7e-4d2a-9c11-5e8f0a7b6c3d"
REMOTE_TEXT = "A remote memory, shared by its own ship and read across peers."


def remote_policy(path, *, local=("recall", "read", "inject_context"), remote=("recall", "read", "inject_context")):
    """The receiver's policy: `local` actions for urn:engram:why and `remote` ones for the remote ship's exact ref."""
    def rule(rule_id, publisher, actions):
        return dict(id=rule_id, effect="allow", publishers=[publisher],
                    profiles=["urn:lighthouse:profile:engram-recall-trace"], domains=["memory.recall"],
                    actions=list(actions), contexts=["memory/technical"],
                    claimMediaTypes=["application/vnd.engram.recall-rank-claim+json"], purposes=["session-recall"],
                    audiences=["self"], validFrom="2026-01-01T00:00:00Z", validUntil="2027-01-01T00:00:00Z",
                    requiredEvidence=[], requiredAttestations=[])
    rules = ([rule("local", "urn:engram:why", local)] if local else []) + (
        [rule("remote", SHIP_REF, remote)] if remote else [])
    artifact = dict(protocolVersion="0.1", kind="ConnectionPolicy", id="urn:policy:receiver",
                    issuedAt="2026-01-01T00:00:00Z", issuer="urn:engram:engram",
                    payloadMediaType="application/vnd.lighthouse.connection-policy+json", payload={"rules": rules},
                    extensions={})
    artifact["digest"] = artifact_digest(artifact)
    path.write_text(json.dumps(artifact))


def remote_answer(request):
    frame = request["frame"]
    if frame["kind"] == "recall":
        return {"ok": True, "frame": dict(
            protocolVersion="0.1", kind="recall_result", turnId="remote-turn", queryDigest=content_digest(frame["query"]),
            context=frame["context"], decision=ALLOW, disclosureId="remote-trace",
            candidates=[dict(memoryId="m9", rank=1, layer="episode", lane="work", audiences=["commons"],
                             contentDigest=content_digest(REMOTE_TEXT))])}
    return {"ok": True, "frame": dict(protocolVersion="0.1", kind="read_result", disclosureId="remote-read",
                                      items=[dict(memoryId="m9", content=REMOTE_TEXT, audiences=["commons"],
                                                  decision=ALLOW)])}


class FakeCrossingSocket:
    """A peer's crossing.sock: one line in, one line out per connection. It records each request and answers with
    `answer(request)`, after `delay` seconds."""

    def __init__(self):
        self.folder = Path(tempfile.mkdtemp(prefix="x"))
        self.path = self.folder / "crossing.sock"
        self.requests, self.answer, self.delay = [], remote_answer, 0
        sock = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                request = json.loads(self.rfile.readline())
                sock.requests.append(request)
                time.sleep(sock.delay)
                reply = sock.answer(request)
                self.wfile.write(reply if isinstance(reply, bytes) else (canonical_json(reply) + "\n").encode())

        self.server = socketserver.ThreadingUnixStreamServer(str(self.path), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def remote(tmp_path):
    """neighbor_arm's arguments with one remote publisher (and no local one) behind a fake crossing.sock, asked
    through ask_crossing as attach_neighbors binds it."""
    import functools
    from lighthouse_client import ask_crossing
    sock = FakeCrossingSocket()
    path = tmp_path / "policy.json"
    remote_policy(path, local=())
    log = Log()
    log.db_path = str(tmp_path / "graph.db")  # remote deliveries are recorded beside the store (Task 12)
    args = dict(query="private query", context=deepcopy(CONTEXT), purpose="session-recall", k=1, storage=log,
                session_id="s", recall_id="local-turn", receiver="engram", publishers=[], socket_path=None,
                policy_path=path, now=lambda: NOW,
                remote_publishers=[dict(peer_id=PEER, ship=SHIP, context="memory/technical")],
                receiver_ship="e" * 32, receiver_instance=INSTANCE,
                ask=functools.partial(ask_crossing, socket_path=sock.path))
    yield args, sock
    sock.close()


def test_a_remote_item_is_delivered_with_its_ref(remote):
    args, sock = remote
    result = neighbors.neighbor_arm(**args)
    assert [i["content"] for i in result["delivered"]] == [REMOTE_TEXT]
    assert result["delivered"][0]["publisher"] == SHIP_REF and result["degraded"] is False
    assert [r["frame"]["kind"] for r in sock.requests] == ["recall", "read"]
    recall, read = sock.requests
    assert (recall["receiver_instance"], recall["receiver_ship"], recall["destination"], recall["publisher_ship"]) == (
        INSTANCE, "e" * 32, PEER, SHIP)
    assert recall["frame"]["k"] == 20 and read["frame"]["turnId"] == "remote-turn"
    assert 100 <= recall["deadline_ms"] <= 2000


def test_the_receipt_keeps_each_reads_disclosure_id(remote):
    args, sock = remote
    neighbors.neighbor_arm(**args)
    receipt = args["storage"].entries[0]["context"]["receipt"]
    validate_receipt(receipt)
    assert receipt["extensions"]["engram:readDisclosures"] == [{"publisher": SHIP_REF, "disclosureId": "remote-read"}]
    assert receipt["extensions"]["engram:traceSnapshots"][0]["disclosureId"] == "remote-trace"


def test_the_local_reads_disclosure_id_is_kept_too(crossing):
    args, calls, content, _ = crossing
    neighbors.neighbor_arm(**args)
    receipt = args["storage"].entries[0]["context"]["receipt"]
    assert receipt["extensions"]["engram:readDisclosures"] == [{"publisher": "urn:engram:why",
                                                                "disclosureId": "disclosure-2"}]


def test_a_remote_publisher_is_never_asked_when_the_receiver_denies_recall(remote):
    args, sock = remote
    remote_policy(args["policy_path"], local=(), remote=("read", "inject_context"))
    result = neighbors.neighbor_arm(**args)
    assert sock.requests == [] and result["delivered"] == []


def test_a_remote_publisher_is_never_read_when_the_receiver_denies_inject_context(remote):
    args, sock = remote
    remote_policy(args["policy_path"], local=(), remote=("recall", "read"))
    result = neighbors.neighbor_arm(**args)
    assert [r["frame"]["kind"] for r in sock.requests] == ["recall"] and result["delivered"] == []


def test_a_slow_remote_publisher_past_the_deadline_delivers_nothing_and_is_degraded(remote):
    args, sock = remote
    sock.delay = 1.0
    started = time.monotonic()
    result = neighbors.neighbor_arm(**{**args, "timeout_s": 0.4})
    assert time.monotonic() - started < 1.5
    assert result["delivered"] == [] and result["degraded"] is True
    assert {"publisher": SHIP_REF, "code": "TIMEOUT"} in result["diagnostics"]


@pytest.mark.parametrize("code", ["REFUSED_403", "REFUSED_429", "NOT_HOSTED", "NOT_PAIRED", "BAD_ANSWER", "UNAVAILABLE"])
def test_a_refusing_remote_publisher_is_in_diagnostics_by_its_ref(remote, code):
    args, sock = remote
    sock.answer = lambda request: {"ok": False, "code": code}
    result = neighbors.neighbor_arm(**args)
    assert result["delivered"] == [] and result["degraded"] is True
    assert {"publisher": SHIP_REF, "code": code} in result["diagnostics"]


def test_another_contexts_remote_publisher_is_never_asked(remote):
    args, sock = remote
    args["remote_publishers"] = [dict(peer_id=PEER, ship=SHIP, context="memory/other")]
    assert neighbors.neighbor_arm(**args) is None
    assert sock.requests == []


def test_with_only_remote_publishers_no_lighthouse_client_is_built(remote, monkeypatch):
    """B5: no local publisher and no socket_path, so no LighthouseClient; the remote one is asked and delivers."""
    args, sock = remote

    def built(*a, **k):
        raise AssertionError("a LighthouseClient was built with no local publisher")
    monkeypatch.setattr(neighbors, "LighthouseClient", built)
    assert [i["content"] for i in neighbors.neighbor_arm(**args)["delivered"]] == [REMOTE_TEXT]


def test_with_only_remote_publishers_and_their_recall_denied_it_answers_as_all_denied_local_does(remote, crossing):
    """B5: `attempted` is set by a remote publisher whose recall grant passed, as by a local one, so an all-denied
    remote configuration answers as an all-denied local one: today an empty result naming the decision code."""
    args, sock = remote
    remote_policy(args["policy_path"], local=(), remote=())
    remote_result = neighbors.neighbor_arm(**args)
    local_args = crossing[0]
    policy(local_args["policy_path"], actions=())
    local_result = neighbors.neighbor_arm(**local_args)
    assert remote_result["delivered"] == local_result["delivered"] == [] and sock.requests == []
    assert remote_result["diagnostics"][0] == local_result["diagnostics"][0] == {"code": "NO_MATCHING_ALLOW"}
    assert remote_result["diagnostics"][1] == {"publisher": SHIP_REF, "code": "NO_MATCHING_ALLOW"}


def test_a_recording_ask_with_no_socket_delivers_so_the_caller_can_be_swapped(remote, monkeypatch):
    """P19, condition 1: neighbor_arm reaches a remote publisher only through `ask`, never a socket of its own."""
    import lighthouse_client
    args, sock = remote
    asked = []

    def ask(receiver_instance, receiver_ship, publisher, frame, deadline_ms):
        asked.append((receiver_instance, receiver_ship, publisher, frame["kind"]))
        return remote_answer({"frame": frame})["frame"]

    def no_client(*a, **k):
        raise AssertionError("neighbor_arm opened a CrossingClient itself")
    monkeypatch.setattr(lighthouse_client, "CrossingClient", no_client)
    result = neighbors.neighbor_arm(**{**args, "ask": ask})
    assert [i["content"] for i in result["delivered"]] == [REMOTE_TEXT]
    assert asked == [(INSTANCE, "e" * 32, SHIP_REF, "recall"), (INSTANCE, "e" * 32, SHIP_REF, "read")]
    assert sock.requests == []


def test_with_no_ask_a_remote_publisher_is_no_asker_and_no_socket_is_opened(remote, monkeypatch):
    import lighthouse_client
    args, sock = remote
    monkeypatch.setattr(lighthouse_client, "CrossingClient",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("a socket was opened")))
    result = neighbors.neighbor_arm(**{**args, "ask": None})
    assert result["delivered"] == [] and result["degraded"] is True
    assert {"publisher": SHIP_REF, "code": "NO_ASKER"} in result["diagnostics"]
    assert sock.requests == []


def test_attach_neighbors_asks_with_the_stores_instance_and_ship_outside_any_transaction(tmp_path, monkeypatch):
    from storage import Storage
    instance = tmp_path / ".engram" / "instances" / "engram"
    instance.mkdir(parents=True)
    remote_policy(instance / "policy.json", local=())
    (instance / "lighthouse-receiver.toml").write_text(
        'enabled = true\npublishers = []\npolicy_path = "policy.json"\ncrossing_socket = "../../peer/crossing.sock"\n'
        f'receiver_ship = "{"e" * 32}"\n[[remote_publishers]]\npeer_id = "{PEER}"\nship = "{SHIP}"\n'
        'context = "memory/technical"\n')
    storage = Storage(str(instance / "graph.db"))
    asked = []

    def ask_crossing(receiver_instance, receiver_ship, publisher, frame, deadline_ms, *, socket_path):
        asked.append((receiver_instance, receiver_ship, publisher, socket_path, storage.conn.in_transaction))
        return remote_answer({"frame": frame})["frame"]
    monkeypatch.setattr(neighbors, "ask_crossing", ask_crossing)
    try:
        response = neighbors.attach_neighbors({"results": [], "recall_id": "r"}, query="rivers",
                                              context_id="memory/technical", purpose="session-recall", storage=storage,
                                              session_id="s", receiver="engram", engram_home=tmp_path)
        instance_id = storage.instance_identity()["instance_id"]
    finally:
        storage.close()
    assert [i["content"] for i in response["neighbors"]["delivered"]] == [REMOTE_TEXT]
    assert asked and all(a == (instance_id, "e" * 32, SHIP_REF, (tmp_path / ".engram" / "peer" / "crossing.sock"), False)
                         for a in asked)


def write_settings(tmp_path, text):
    path = tmp_path / "receiver.toml"
    path.write_text(text)
    return path


REMOTE_TABLE = f'[[remote_publishers]]\npeer_id = "{PEER}"\nship = "{SHIP}"\ncontext = "memory/technical"\n'
REMOTE_TOP = f'enabled = true\npublishers = []\npolicy_path = "p.json"\ncrossing_socket = "c.sock"\nreceiver_ship = "{"e" * 32}"\n'


def test_settings_take_remote_publishers_with_their_socket_and_ship(tmp_path):
    from lighthouse_receiver_config import load_settings
    settings = load_settings(write_settings(tmp_path, REMOTE_TOP + REMOTE_TABLE))
    assert settings["publishers"] == [] and settings["socket_path"] is None
    assert settings["remote_publishers"] == [dict(peer_id=PEER, ship=SHIP, context="memory/technical")]
    assert settings["crossing_socket"] == (tmp_path / "c.sock").resolve() and settings["receiver_ship"] == "e" * 32
    local = load_settings(write_settings(tmp_path, 'enabled = true\npublishers = ["why"]\nsocket_path = "s"\n'
                                                   'policy_path = "p.json"\n'))
    assert local["remote_publishers"] == [] and local["crossing_socket"] is None and local["receiver_ship"] is None


@pytest.mark.parametrize("text", [
    REMOTE_TOP + REMOTE_TABLE.replace('context = "memory/technical"\n', 'context = "memory/technical"\nweight = 2\n'),
    REMOTE_TOP + REMOTE_TABLE.replace(PEER, "C" * 64),
    REMOTE_TOP + REMOTE_TABLE.replace(PEER, PEER[:-1]),
    REMOTE_TOP + REMOTE_TABLE.replace(SHIP, "has space"),
    REMOTE_TOP + REMOTE_TABLE.replace('"memory/technical"', '"../escape"'),
    REMOTE_TOP.replace('crossing_socket = "c.sock"\n', "") + REMOTE_TABLE,
    REMOTE_TOP.replace(f'receiver_ship = "{"e" * 32}"\n', "") + REMOTE_TABLE,
    REMOTE_TOP + REMOTE_TABLE + REMOTE_TABLE,
    REMOTE_TOP.replace("publishers = []", 'publishers = ["a", "b", "c", "d", "e", "f", "g", "h"]').replace(
        'policy_path', 'socket_path = "s"\npolicy_path') + REMOTE_TABLE,
    'enabled = true\npublishers = []\npolicy_path = "p.json"\n',
    'enabled = true\npublishers = ["why"]\npolicy_path = "p.json"\n',
], ids=["unknown key", "upper peer", "short peer", "bad ship", "bad context", "no socket", "no ship", "duplicate",
        "nine in all", "none at all", "local without socket_path"])
def test_bad_remote_settings_fail_closed(tmp_path, text):
    from lighthouse_receiver_config import load_settings
    with pytest.raises(ValueError):
        load_settings(write_settings(tmp_path, text))
