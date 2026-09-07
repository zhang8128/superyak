"""Receiver wire boundaries use real disposable Unix sockets."""

from __future__ import annotations

import copy
import hashlib
import json
import socket
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

import lighthouse_client
from lighthouse_protocol import encode, recall_frame


@pytest.fixture
def client_module():
    return lighthouse_client


CONTEXT = {"id": "memory/technical", "path": ["memory", "technical"]}
ALLOW = {"effect": "allow", "ruleId": "share", "code": None}
DENY = {"effect": "deny", "ruleId": None, "code": "NO_MATCHING_ALLOW"}


def digest(text):
    return {"algorithm": "sha256", "value": hashlib.sha256(text.encode()).hexdigest()}


def request():
    return recall_frame(
        receiver="receiver", publisher="publisher", context=copy.deepcopy(CONTEXT),
        purpose="session-recall", query="hello", k=2, at="2026-09-06T00:00:00Z",
    )


def candidate(memory_id="memory-1", rank=1, **changes):
    return {
        "memoryId": memory_id, "rank": rank, "layer": "episode", "lane": "personal",
        "contentDigest": digest("hello"), "audiences": ["commons"], **changes,
    }


def trace(**changes):
    return {
        "protocolVersion": "0.1", "kind": "recall_result", "turnId": "turn-1",
        "queryDigest": digest("hello"), "context": copy.deepcopy(CONTEXT),
        "candidates": [candidate()], "decision": dict(ALLOW),
        "disclosureId": "disclosure-1", **changes,
    }


@contextmanager
def scripted_peer(script):
    # macOS limits Unix paths to 104 bytes, shorter than pytest's temp hierarchy.
    with tempfile.TemporaryDirectory(prefix="lh-client-", dir="/tmp") as directory:
        path = Path(directory) / "socket"
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(path))
        listener.listen(1)
        listener.settimeout(2)
        errors = []

        def serve():
            try:
                with listener.accept()[0] as connection:
                    connection.settimeout(2)
                    script(connection)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Deadline/cap rejection intentionally closes the connection.
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        try:
            yield path
        finally:
            worker.join(timeout=3)
            listener.close()
            assert not worker.is_alive()
            assert errors == []


def receive_request(connection):
    data = bytearray()
    while not data.endswith(b"\n"):
        part = connection.recv(65536)
        if not part:
            raise AssertionError("client closed before sending request")
        data.extend(part)
        assert len(data) <= 1024 * 1024
    return json.loads(data)


def responding(wire, *, chunk_size=None, delay=0):
    def script(connection):
        receive_request(connection)
        for offset in range(0, len(wire), chunk_size or max(1, len(wire))):
            if delay:
                time.sleep(delay)
            connection.sendall(wire[offset:offset + (chunk_size or len(wire))])
    return script


def test_socket_roundtrip_and_fragmented_reply(client_module):
    sent = request()
    reply = trace()

    def script(connection):
        assert receive_request(connection) == sent
        for byte in encode(reply):
            connection.sendall(bytes([byte]))

    with scripted_peer(script) as path:
        assert client_module.LighthouseClient(path).call(sent) == reply


def test_absent_socket_has_stable_diagnostic(client_module, tmp_path):
    with pytest.raises(client_module.NeighborUnavailable) as error:
        client_module.LighthouseClient(tmp_path / "absent").call(request())
    assert error.value.code == "UNAVAILABLE"
    assert str(error.value) == "UNAVAILABLE"


@pytest.mark.parametrize("wire", [
    b"", b'{"protocolVersion":"0.1"}', b"not-json\n", b"\xff\n", b"[]\n",
    b'{"protocolVersion":"0.1","kind":[]}\n',
    b'{"protocolVersion":"0.1","kind":"error","code":"X","detail":"", "v":NaN}\n',
    b'{"protocolVersion":"0.1","kind":"error","code":"X","code":"Y","detail":""}\n',
])
def test_socket_rejects_truncated_or_malformed_frames(client_module, wire):
    with scripted_peer(responding(wire)) as path:
        with pytest.raises(client_module.NeighborUnavailable) as error:
            client_module.LighthouseClient(path).call(request())
    assert error.value.code == "MALFORMED_FRAME"


def test_socket_rejects_wrong_reply_kind(client_module):
    with scripted_peer(responding(encode({
        "protocolVersion": "0.1", "kind": "read_result", "items": [], "disclosureId": "d",
    }))) as path:
        with pytest.raises(client_module.NeighborUnavailable) as error:
            client_module.LighthouseClient(path).call(request())
    assert error.value.code == "MALFORMED_FRAME"


def test_socket_limits_incoming_frame(client_module):
    with scripted_peer(responding(b" " * (1024 * 1024 + 1))) as path:
        with pytest.raises(client_module.NeighborUnavailable) as error:
            client_module.LighthouseClient(path).call(request())
    assert error.value.code == "FRAME_TOO_LARGE"


def test_socket_accepts_exact_frame_cap(client_module):
    reply = trace(padding="")
    reply["padding"] = "x" * (1024 * 1024 - len(encode(reply)))
    with scripted_peer(responding(encode(reply))) as path:
        assert client_module.LighthouseClient(path).call(request()) == reply


def test_socket_limits_outgoing_frame_before_connect(client_module, tmp_path):
    sent = request()
    sent["padding"] = "x" * (1024 * 1024)
    with pytest.raises(client_module.NeighborUnavailable) as error:
        client_module.LighthouseClient(tmp_path / "absent").call(sent)
    assert error.value.code == "FRAME_TOO_LARGE"


def test_trickle_cannot_restart_total_deadline(client_module):
    with scripted_peer(responding(encode(trace()), chunk_size=1, delay=0.02)) as path:
        start = time.monotonic()
        with pytest.raises(client_module.NeighborUnavailable) as error:
            client_module.LighthouseClient(path, timeout_s=0.12).call(request())
        elapsed = time.monotonic() - start
    assert error.value.code == "TIMEOUT"
    assert 0.08 <= elapsed < 0.4


def test_absolute_deadline_shortens_call_timeout(client_module):
    with scripted_peer(responding(encode(trace()), delay=0.2)) as path:
        start = time.monotonic()
        with pytest.raises(client_module.NeighborUnavailable) as error:
            client_module.LighthouseClient(path, timeout_s=1).call(
                request(), deadline=start + 0.06,
            )
        elapsed = time.monotonic() - start
    assert error.value.code == "TIMEOUT"
    assert elapsed < 0.15


def test_blocked_send_uses_the_same_total_deadline(client_module):
    sent = request() | {"padding": "x" * (900 * 1024)}
    with scripted_peer(lambda connection: time.sleep(0.25)) as path:
        start = time.monotonic()
        with pytest.raises(client_module.NeighborUnavailable) as error:
            client_module.LighthouseClient(path, timeout_s=0.08).call(sent)
        elapsed = time.monotonic() - start
    assert error.value.code == "TIMEOUT"
    assert elapsed < 0.2


def test_absolute_deadline_cannot_extend_client_timeout(client_module):
    with scripted_peer(responding(encode(trace()), delay=0.2)) as path:
        start = time.monotonic()
        with pytest.raises(client_module.NeighborUnavailable) as error:
            client_module.LighthouseClient(path, timeout_s=0.05).call(
                request(), deadline=start + 10,
            )
        elapsed = time.monotonic() - start
    assert error.value.code == "TIMEOUT"
    assert elapsed < 0.15


@pytest.mark.parametrize("changes,code", [
    ({"query": "x" * 4097}, "QUERY_TOO_LARGE"),
    ({"k": 21}, "INVALID_LIMIT"),
])
def test_invalid_request_limits_are_rejected_before_connect(client_module, tmp_path, changes, code):
    with pytest.raises(client_module.NeighborUnavailable) as error:
        client_module.LighthouseClient(tmp_path / "absent").call(request() | changes)
    assert error.value.code == code


def test_expired_deadline_does_not_connect(client_module, tmp_path):
    with pytest.raises(client_module.NeighborUnavailable) as error:
        client_module.LighthouseClient(tmp_path / "absent").call(
            request(), deadline=time.monotonic() - 1,
        )
    assert error.value.code == "TIMEOUT"


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan"), float("inf"), 11])
def test_invalid_timeout_is_rejected(client_module, tmp_path, timeout):
    with pytest.raises(ValueError):
        client_module.LighthouseClient(tmp_path / "socket", timeout_s=timeout)


def test_untrusted_error_details_do_not_become_diagnostics(client_module):
    wire = encode({
        "protocolVersion": "0.1", "kind": "error", "code": "private content",
        "detail": "more private content",
    })
    with scripted_peer(responding(wire)) as path:
        with pytest.raises(client_module.NeighborUnavailable) as error:
            client_module.LighthouseClient(path).call(request())
    assert str(error.value) == "REMOTE_ERROR"


def validated_trace(client_module, reply, **changes):
    args = {"publisher": "publisher", "query": "hello", "context": CONTEXT, "k": 2}
    return client_module.validate_trace(reply, **(args | changes))


def test_trace_snapshot_is_content_free_canonical_and_detached(client_module):
    reply = trace(candidates=[candidate("second", 2, layer="semantic", lane="work"), candidate()])
    reply["query"] = "ignored private query text"
    snapshot = validated_trace(client_module, reply)
    assert set(snapshot) == {
        "publisher", "turnId", "queryDigest", "context", "candidates", "decision", "disclosureId",
    }
    assert snapshot["publisher"] == "publisher"
    assert [item["memoryId"] for item in snapshot["candidates"]] == ["memory-1", "second"]
    assert snapshot["candidates"][0]["lane"] == "personal"
    assert snapshot["candidates"][1]["layer"] == "semantic"
    reply["context"]["path"].append("changed")
    reply["candidates"][1]["contentDigest"]["value"] = "a" * 64
    reply["decision"]["effect"] = "deny"
    assert snapshot["context"] == CONTEXT
    assert snapshot["candidates"][0]["contentDigest"]["value"] == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )
    assert snapshot["decision"] == ALLOW


@pytest.mark.parametrize("changes,code", [
    ({"queryDigest": digest("different")}, "QUERY_MISMATCH"),
    ({"context": {"id": "memory/technical", "path": ["wrong"]}}, "CONTEXT_MISMATCH"),
    ({"context": {"id": "memory/other", "path": ["memory", "technical"]}}, "CONTEXT_MISMATCH"),
    ({"context": CONTEXT | {"text": "private"}}, "INVALID_TRACE"),
    ({"decision": ALLOW | {"content": "private"}}, "INVALID_TRACE"),
    ({"decision": {"effect": "allow"}}, "INVALID_TRACE"),
    ({"decision": ALLOW | {"code": "NO_MATCHING_ALLOW"}}, "INVALID_TRACE"),
    ({"decision": DENY}, "INVALID_TRACE"),
    ({"disclosureId": None}, "INVALID_TRACE"),
    ({"turnId": " "}, "MALFORMED_FRAME"),
])
def test_trace_rejects_unbound_or_malformed_metadata(client_module, changes, code):
    with pytest.raises(client_module.NeighborUnavailable) as error:
        validated_trace(client_module, trace(**changes))
    assert error.value.code == code


@pytest.mark.parametrize("changes", [
    {"rank": True}, {"rank": 0}, {"rank": -1}, {"rank": 1.0}, {"rank": 2**53},
    {"memoryId": ""}, {"memoryId": []}, {"layer": "instinct"}, {"layer": []},
    {"lane": "unknown"}, {"lane": None}, {"content": "embedded private content"},
    {"contentDigest": {"algorithm": "sha-256", "value": "a" * 64}},
    {"contentDigest": {"algorithm": "sha256", "value": "A" * 64}},
    {"contentDigest": {"algorithm": "sha256", "value": "g" * 64}},
    {"contentDigest": {"algorithm": "sha256", "value": "a" * 63}},
    {"contentDigest": digest("hello") | {"content": "hidden"}},
    {"audiences": []}, {"audiences": ["private"]}, {"audiences": ["group:"]},
    {"audiences": ["group:Wrong"]}, {"audiences": ["commons", "commons"]},
])
def test_trace_rejects_unsafe_candidates(client_module, changes):
    with pytest.raises(client_module.NeighborUnavailable) as error:
        validated_trace(client_module, trace(candidates=[candidate(**changes)]))
    assert error.value.code == "INVALID_TRACE"


@pytest.mark.parametrize("field", ["memoryId", "rank", "layer", "lane", "contentDigest", "audiences"])
def test_trace_requires_candidate_metadata(client_module, field):
    item = candidate()
    del item[field]
    with pytest.raises(client_module.NeighborUnavailable):
        validated_trace(client_module, trace(candidates=[item]))


@pytest.mark.parametrize("items", [
    [candidate(), candidate(rank=2)],
    [candidate(), candidate("different")],
    [candidate(), candidate(rank=2, contentDigest=digest("conflict"))],
    [candidate(str(i), i + 1) for i in range(3)],
])
def test_trace_rejects_duplicate_identity_rank_or_excess_candidates(client_module, items):
    with pytest.raises(client_module.NeighborUnavailable):
        validated_trace(client_module, trace(candidates=items))


def test_denied_trace_is_valid_evidence_with_no_candidates(client_module):
    snapshot = validated_trace(client_module, trace(candidates=[], decision=DENY, disclosureId=None))
    assert snapshot["decision"] == DENY
    assert snapshot["candidates"] == []


@pytest.mark.parametrize("args", [{"query": "x" * 4097}, {"k": 21}, {"k": True}, {"k": 0}])
def test_trace_enforces_query_and_candidate_limits(client_module, args):
    with pytest.raises(client_module.NeighborUnavailable):
        validated_trace(client_module, trace(), **args)


def selected(memory_id="memory-1", **changes):
    return candidate(memory_id) | {
        "publisher": "publisher", "audiences": ["commons", "group:team-1"],
    } | changes


def read_item(memory_id="memory-1", **changes):
    return {
        "memoryId": memory_id, "content": "hello", "audiences": ["commons", "group:team-1"],
        "decision": dict(ALLOW), **changes,
    }


def read_reply(items=None, **changes):
    return {
        "protocolVersion": "0.1", "kind": "read_result", "disclosureId": "read-disclosure",
        "items": [read_item()] if items is None else items, **changes,
    }


def test_read_verifies_content_and_preserves_selected_provenance(client_module):
    reply = read_reply()
    chosen = [selected(layer="semantic", lane="work")]
    items = client_module.validate_read(reply, selected=chosen)
    assert items == [{
        "publisher": "publisher", "memoryId": "memory-1", "content": "hello",
        "audiences": ["commons", "group:team-1"], "decision": ALLOW,
        "layer": "semantic", "lane": "work", "contentDigest": {
            "algorithm": "sha256",
            "value": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
        },
    }]
    chosen[0]["contentDigest"]["value"] = "a" * 64
    reply["items"][0]["audiences"].append("group:other")
    assert len(items[0]["audiences"]) == 2
    assert items[0]["contentDigest"]["value"].startswith("2cf24")


def test_read_does_not_deliver_missing_null_or_denied_items(client_module):
    reply = read_reply([
        read_item("null", content=None, audiences=[]),
        read_item("denied", content="hello", decision=DENY),
    ])
    assert client_module.validate_read(
        reply, selected=[selected("null"), selected("denied"), selected("absent")],
    ) == []


@pytest.mark.parametrize("items", [
    [read_item("not-requested")], [read_item(), read_item()],
    [read_item(content="changed")], [read_item(content=123)],
    [read_item(audiences=[])], [read_item(audiences=["self"])],
    [read_item(audiences=["group:bad/name"])], [read_item(audiences=[[]])],
    [read_item(decision=ALLOW | {"ruleId": 7})], [read_item(decision={"effect": "allow"})],
    [read_item(publisher="imposter")],
])
def test_read_rejects_unrequested_duplicate_mismatched_or_unsafe_items(client_module, items):
    with pytest.raises(client_module.NeighborUnavailable):
        client_module.validate_read(read_reply(items), selected=[selected()])


def test_read_checks_digest_of_utf8_content(client_module):
    text = "é" * 16384  # Exactly 32 KiB in UTF-8.
    assert client_module.validate_read(
        read_reply([read_item(content=text)]), selected=[selected(contentDigest=digest(text))],
    )[0]["content"] == text
    text += "é"
    with pytest.raises(client_module.NeighborUnavailable) as error:
        client_module.validate_read(
            read_reply([read_item(content=text)]), selected=[selected(contentDigest=digest(text))],
        )
    assert error.value.code == "CONTENT_TOO_LARGE"


def test_read_requires_publisher_disclosure_for_delivery(client_module):
    with pytest.raises(client_module.NeighborUnavailable):
        client_module.validate_read(read_reply(disclosureId=None), selected=[selected()])


@pytest.mark.parametrize("chosen", [
    [selected(), selected()],
    [selected("one"), selected("two", publisher="another")],
    [selected(contentDigest={"algorithm": "sha256", "value": "not-a-hash"})],
    [selected(layer="instinct")], [selected(lane=None)],
])
def test_read_rejects_ambiguous_or_malformed_selection(client_module, chosen):
    with pytest.raises(client_module.NeighborUnavailable):
        client_module.validate_read(read_reply(items=[]), selected=chosen)


def test_read_preserves_receiver_owned_publisher_urn(client_module):
    result = client_module.validate_read(
        read_reply(), selected=[selected(publisher="urn:engram:publisher")],
    )
    assert result[0]["publisher"] == "urn:engram:publisher"


def test_read_allows_audience_narrowing_but_rejects_widening(client_module):
    assert client_module.validate_read(
        read_reply([read_item(audiences=["commons"])]), selected=[selected()],
    )[0]["audiences"] == ["commons"]
    with pytest.raises(client_module.NeighborUnavailable):
        client_module.validate_read(read_reply(), selected=[selected(audiences=["commons"])])


def test_fusion_is_weighted_and_publisher_qualified(client_module):
    results = client_module.fuse_traces({
        "a": (1, [candidate("same", 1), candidate("second", 2)]),
        "b": (2, [candidate("same", 1)]),
        "zero": (0, [candidate("excluded", 1)]),
    }, 3)
    assert [(item["publisher"], item["memoryId"]) for item in results] == [
        ("b", "same"), ("a", "same"), ("a", "second"),
    ]
    assert results[0] == {
        "publisher": "b", "memoryId": "same", "contentDigest": digest("hello"),
        "score": 2 / 61, "contributions": [{"publisher": "b", "rank": 1}],
    }


def test_fusion_ties_match_typescript_canonical_identity_order(client_module):
    # Canonical MemoryRef objects compare memoryId first, using JS UTF-16 units.
    traces = {
        "a": (1, [candidate("z", 1)]),
        "b": (1, [candidate("a", 1)]),
        "c": (1, [candidate("\ue000", 1)]),
        "d": (1, [candidate("\U00010000", 1)]),
    }
    result = client_module.fuse_traces(traces, 4)
    assert [(item["publisher"], item["memoryId"]) for item in result] == [
        ("b", "a"), ("a", "z"), ("d", "\U00010000"), ("c", "\ue000"),
    ]
    assert client_module.fuse_traces(dict(reversed(list(traces.items()))), 4) == result
    assert client_module.fuse_traces(traces, 1) == result[:1]


@pytest.mark.parametrize("weight", [-1, True, float("nan"), float("inf"), "1", 10**1000])
def test_fusion_rejects_invalid_weights(client_module, weight):
    with pytest.raises(client_module.NeighborUnavailable):
        client_module.fuse_traces({"publisher": (weight, [candidate()])}, 1)


@pytest.mark.parametrize("items", [
    [candidate(), candidate(rank=2)],
    [candidate(), candidate("another")],
    [candidate(), candidate(rank=2, contentDigest=digest("conflict"))],
    [candidate(rank=True)], [candidate(rank=0)],
])
def test_fusion_rejects_duplicate_or_invalid_source_ranks(client_module, items):
    with pytest.raises(client_module.NeighborUnavailable):
        client_module.fuse_traces({"publisher": (1, items)}, 2)


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, 21])
def test_fusion_rejects_invalid_result_limits(client_module, limit):
    with pytest.raises(client_module.NeighborUnavailable):
        client_module.fuse_traces({"publisher": (1, [candidate()])}, limit)
