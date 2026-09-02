from __future__ import annotations

import json
from pathlib import Path

import pytest

from lighthouse_protocol import (
    artifact_digest,
    canonical_json,
    content_digest,
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
