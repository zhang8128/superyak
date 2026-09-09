from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from lighthouse_protocol import (
    FrameError,
    artifact_digest,
    canonical_json,
    content_digest,
    decode,
    encode,
    error_frame,
    read_frame,
    read_result_frame,
    recall_frame,
    recall_result_frame,
    verify_artifact_digest,
)

FIXTURES = Path(__file__).parent / "fixtures" / "lighthouse" / "policy"

_VALID_FRAMES = {
    "recall": {
        "protocolVersion": "0.1",
        "kind": "recall",
        "receiver": "engram",
        "publisher": "why",
        "context": {"id": "memory/technical", "path": ["memory", "technical"]},
        "purpose": "session-recall",
        "audience": "self",
        "query": "rivers",
        "k": 5,
        "at": "2026-09-01T00:00:00Z",
    },
    "recall_result": {
        "protocolVersion": "0.1",
        "kind": "recall_result",
        "turnId": "turn-1",
        "queryDigest": {"algorithm": "sha256", "value": "a" * 64},
        "context": {"id": "memory/technical", "path": ["memory", "technical"]},
        "candidates": [{"memoryId": "m1"}],
        "decision": {"effect": "allow", "ruleId": "allow-1", "code": None},
        "disclosureId": None,
    },
    "read": {
        "protocolVersion": "0.1",
        "kind": "read",
        "receiver": "engram",
        "publisher": "why",
        "context": {"id": "memory/technical", "path": ["memory", "technical"]},
        "purpose": "session-recall",
        "turnId": "turn-1",
        "memoryIds": ["m1"],
    },
    "read_result": {
        "protocolVersion": "0.1",
        "kind": "read_result",
        "items": [{"memoryId": "m1"}],
        "disclosureId": "disclosure-1",
    },
    "error": {
        "protocolVersion": "0.1",
        "kind": "error",
        "code": "MALFORMED_FRAME",
        "detail": "invalid frame",
    },
}

_REQUIRED_FIELDS = {
    "recall": (
        "protocolVersion",
        "kind",
        "receiver",
        "publisher",
        "context",
        "purpose",
        "audience",
        "query",
        "k",
        "at",
    ),
    "recall_result": (
        "protocolVersion",
        "kind",
        "turnId",
        "queryDigest",
        "context",
        "candidates",
        "decision",
        "disclosureId",
    ),
    "read": (
        "protocolVersion",
        "kind",
        "receiver",
        "publisher",
        "context",
        "purpose",
        "turnId",
        "memoryIds",
    ),
    "read_result": ("protocolVersion", "kind", "items", "disclosureId"),
    "error": ("protocolVersion", "kind", "code", "detail"),
}


def _assert_malformed(frame):
    with pytest.raises(FrameError) as error:
        decode((json.dumps(frame) + "\n").encode("utf-8"))
    assert error.value.code == "MALFORMED_FRAME"


def test_canonical_json_sorts_keys_and_strips_whitespace():
    assert canonical_json({"b": [1, {"z": None, "a": "é"}], "a": True}) == (
        '{"a":true,"b":[1,{"a":"é","z":null}]}'
    )


def test_canonical_json_sorts_nested_keys_by_utf16_code_units():
    assert canonical_json({
        "values": {"\ue000": 1, "\U00010000": 2},
        "array": [{"\ue000": "bmp", "\U00010000": "supplementary"}],
    }) == (
        '{"array":[{"\U00010000":"supplementary","\ue000":"bmp"}],'
        '"values":{"\U00010000":2,"\ue000":1}}'
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1.0, "1"),
        (-0.0, "0"),
        (333333333.33333329, "333333333.3333333"),
        (1e20, "100000000000000000000"),
        (1e21, "1e+21"),
        (1e-6, "0.000001"),
        (1e-7, "1e-7"),
    ],
)
def test_canonical_json_uses_ecmascript_number_spelling(value, expected):
    assert canonical_json(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (10**20, "100000000000000000000"),
        (10**21, "1e+21"),
        (-(10**21), "-1e+21"),
        (2**53, "9007199254740992"),
        (2**68, "295147905179352830000"),
        (10**21 + 131072, "1.0000000000000001e+21"),
    ],
)
def test_canonical_json_uses_ecmascript_spelling_for_exact_integers(
    value, expected
):
    assert canonical_json({"value": value}) == f'{{"value":{expected}}}'


def test_canonical_json_rejects_integer_outside_binary64_precision():
    with pytest.raises(ValueError, match="exact binary64"):
        canonical_json(2**53 + 1)


def test_canonical_json_preserves_container_and_type_errors():
    circular = []
    circular.append(circular)
    with pytest.raises(ValueError, match="Circular reference detected"):
        canonical_json(circular)
    with pytest.raises(TypeError):
        canonical_json(object())


def test_canonical_json_rejects_non_finite():
    with pytest.raises(ValueError):
        canonical_json({"x": float("inf")})


def test_artifact_digest_matches_lighthouse_for_integral_float_extension():
    policy = {
        "kind": "ConnectionPolicy",
        "protocolVersion": "0.1",
        "id": "urn:policy:engram",
        "issuedAt": "2026-09-01T00:00:00Z",
        "issuer": "urn:engram:engram",
        "payloadMediaType": "application/vnd.lighthouse.connection-policy+json",
        "payload": {
            "rules": [
                {
                    "id": "allow-lighthouse",
                    "effect": "allow",
                    "publishers": ["urn:engram:lighthouse"],
                    "profiles": [
                        "urn:lighthouse:profile:engram-recall-trace"
                    ],
                    "domains": ["memory.recall"],
                    "actions": ["recall", "read", "inject_context"],
                    "contexts": ["memory/technical"],
                    "claimMediaTypes": [
                        "application/vnd.engram.recall-rank-claim+json"
                    ],
                    "purposes": ["session-recall"],
                    "audiences": ["self"],
                    "validFrom": "2026-01-01T00:00:00Z",
                    "validUntil": "2026-10-15T00:00:00Z",
                    "requiredEvidence": [],
                    "requiredAttestations": [],
                }
            ]
        },
        "extensions": {
            "engram:weight": {"urn:engram:lighthouse": 1.0}
        },
    }

    assert artifact_digest(policy) == {
        "algorithm": "sha-256",
        "value": "de44dc86720a2554dfe5535ec6fe017851f0262e225418edc9bceb9fdb006f5a",
    }


def test_artifact_digest_reproduces_lighthouse_reference_policy():
    policy = json.loads(
        (FIXTURES / "policies" / "workflow-policy.json").read_text()
    )
    assert artifact_digest(policy) == policy["digest"]
    assert verify_artifact_digest(policy) is True


def test_verify_rejects_tampered_artifact():
    policy = json.loads(
        (FIXTURES / "policies" / "workflow-policy.json").read_text()
    )
    policy["issuer"] = "urn:lighthouse:someone-else"
    assert verify_artifact_digest(policy) is False


def test_content_digest_label_is_sha256_without_hyphen():
    assert content_digest("abc") == {
        "algorithm": "sha256",
        "value": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    }


def test_recall_frame_round_trips():
    frame = recall_frame(
        receiver="engram",
        publisher="why",
        context={
            "id": "memory/technical",
            "path": ["memory", "technical"],
        },
        purpose="session-recall",
        query="rivers",
        k=5,
        at="2026-09-01T00:00:00+00:00",
    )
    assert frame["kind"] == "recall"
    assert frame["protocolVersion"] == "0.1"
    assert frame["audience"] == "self"
    assert decode(encode(frame)) == frame
    assert encode(frame).endswith(b"\n")
    assert encode(frame).count(b"\n") == 1


def test_read_frame_carries_ids_and_turn():
    frame = read_frame(
        receiver="engram",
        publisher="why",
        context={
            "id": "memory/technical",
            "path": ["memory", "technical"],
        },
        purpose="session-recall",
        turn_id="t1",
        memory_ids=["m1", "m2"],
    )
    assert frame["memoryIds"] == ["m1", "m2"]
    assert frame["turnId"] == "t1"


def test_decode_rejects_bad_json_and_wrong_version():
    with pytest.raises(FrameError) as err:
        decode(b"{not json\n")
    assert err.value.code == "MALFORMED_FRAME"

    with pytest.raises(FrameError) as err:
        decode(b'{"protocolVersion":"9.9","kind":"recall"}\n')
    assert err.value.code == "PROTOCOL_VERSION_MISMATCH"

    with pytest.raises(FrameError) as err:
        decode(b'{"protocolVersion":"0.1","kind":"dance"}\n')
    assert err.value.code == "MALFORMED_FRAME"


@pytest.mark.parametrize("kind", tuple(_VALID_FRAMES))
def test_decode_accepts_every_complete_frame_kind(kind):
    frame = deepcopy(_VALID_FRAMES[kind])
    assert decode(encode(frame)) == frame


@pytest.mark.parametrize(
    ("kind", "field"),
    [
        (kind, field)
        for kind, fields in _REQUIRED_FIELDS.items()
        for field in fields
    ],
)
def test_decode_rejects_missing_required_field_for_every_kind(kind, field):
    frame = deepcopy(_VALID_FRAMES[kind])
    del frame[field]
    _assert_malformed(frame)


@pytest.mark.parametrize(
    ("kind", "field", "invalid"),
    [
        ("recall", "protocolVersion", 1),
        ("recall", "kind", 1),
        ("recall", "receiver", ""),
        ("recall", "publisher", ""),
        ("recall", "context", []),
        ("recall", "purpose", 1),
        ("recall", "audience", "public"),
        ("recall", "query", 1),
        ("recall", "k", True),
        ("recall", "k", 0),
        ("recall", "at", "not-a-timestamp"),
        ("recall_result", "turnId", ""),
        ("recall_result", "queryDigest", []),
        ("recall_result", "context", []),
        ("recall_result", "candidates", [1]),
        ("recall_result", "decision", []),
        ("recall_result", "disclosureId", 1),
        ("read", "receiver", ""),
        ("read", "publisher", ""),
        ("read", "context", []),
        ("read", "purpose", 1),
        ("read", "turnId", ""),
        ("read", "memoryIds", [1]),
        ("read", "memoryIds", [""]),
        ("read_result", "items", ["not-an-item"]),
        ("read_result", "disclosureId", 1),
        ("error", "code", ""),
        ("error", "detail", None),
    ],
)
def test_decode_rejects_wrong_field_types_and_empty_identities(
    kind, field, invalid
):
    frame = deepcopy(_VALID_FRAMES[kind])
    frame[field] = invalid
    _assert_malformed(frame)


@pytest.mark.parametrize(
    "context",
    [
        {},
        {"id": "memory/technical"},
        {"path": ["memory", "technical"]},
        {"id": "", "path": ["memory"]},
        {"id": "memory/technical", "path": "memory/technical"},
        {"id": "memory/technical", "path": ["memory", 1]},
        {"id": "memory/technical", "path": ["memory", ""]},
    ],
)
def test_decode_rejects_invalid_context_shape(context):
    frame = deepcopy(_VALID_FRAMES["recall"])
    frame["context"] = context
    _assert_malformed(frame)


@pytest.mark.parametrize("k", [-1, 1.5, "1", None])
def test_decode_requires_positive_non_bool_integer_k(k):
    frame = deepcopy(_VALID_FRAMES["recall"])
    frame["k"] = k
    _assert_malformed(frame)


def test_wrong_version_precedes_payload_validation():
    with pytest.raises(FrameError) as error:
        decode(b'{"protocolVersion":"9.9","kind":"recall"}\n')
    assert error.value.code == "PROTOCOL_VERSION_MISMATCH"


@pytest.mark.parametrize("disclosure_id", [None, "disclosure-1"])
def test_result_frames_accept_nullable_disclosure_id(disclosure_id):
    recall_result = recall_result_frame(
        turn_id="turn-1",
        query_digest={"algorithm": "sha256", "value": "a" * 64},
        context={"id": "memory/technical", "path": ["memory", "technical"]},
        candidates=[],
        decision={"effect": "allow", "ruleId": "allow-1", "code": None},
        disclosure_id=disclosure_id,
    )
    read_result = read_result_frame(items=[], disclosure_id=disclosure_id)
    assert decode(encode(recall_result)) == recall_result
    assert decode(encode(read_result)) == read_result


def test_error_frame_shape():
    assert error_frame("PUBLISHER_UNAVAILABLE", "store locked") == {
        "protocolVersion": "0.1",
        "kind": "error",
        "code": "PUBLISHER_UNAVAILABLE",
        "detail": "store locked",
    }
