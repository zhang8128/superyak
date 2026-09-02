from __future__ import annotations

import json
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
    recall_frame,
    verify_artifact_digest,
)

FIXTURES = Path(__file__).parent / "fixtures" / "lighthouse" / "policy"


def test_canonical_json_sorts_keys_and_strips_whitespace():
    assert canonical_json({"b": [1, {"z": None, "a": "é"}], "a": True}) == (
        '{"a":true,"b":[1,{"a":"é","z":null}]}'
    )


def test_canonical_json_rejects_non_finite():
    with pytest.raises(ValueError):
        canonical_json({"x": float("inf")})


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


def test_error_frame_shape():
    assert error_frame("PUBLISHER_UNAVAILABLE", "store locked") == {
        "protocolVersion": "0.1",
        "kind": "error",
        "code": "PUBLISHER_UNAVAILABLE",
        "detail": "store locked",
    }
