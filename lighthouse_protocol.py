"""Lighthouse wire primitives for the local city.

Canonical JSON matches the TypeScript kit's canonicalization. Artifact
digests cover the envelope without ``digest`` and ``attestations`` and use
the ``sha-256`` label; content digests use ``sha256`` as required by the
Engram recall profile.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

PROTOCOL_VERSION = "0.1"
FRAME_KINDS = frozenset(
    {"recall", "recall_result", "read", "read_result", "error"}
)


def _check_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite number is not JSON")
    if isinstance(value, dict):
        for item in value.values():
            _check_finite(item)
    elif isinstance(value, list):
        for item in value:
            _check_finite(item)


def canonical_json(value: Any) -> str:
    _check_finite(value)
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def artifact_digest(artifact: dict) -> dict:
    content = {
        key: value
        for key, value in artifact.items()
        if key not in ("digest", "attestations")
    }
    return {
        "algorithm": "sha-256",
        "value": hashlib.sha256(
            canonical_json(content).encode("utf-8")
        ).hexdigest(),
    }


def verify_artifact_digest(artifact: dict) -> bool:
    expected = artifact.get("digest")
    if not isinstance(expected, dict) or expected.get("algorithm") != "sha-256":
        return False
    return artifact_digest(artifact)["value"] == expected.get("value")


def content_digest(text: str) -> dict:
    return {
        "algorithm": "sha256",
        "value": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
