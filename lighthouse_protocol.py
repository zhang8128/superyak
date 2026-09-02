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


class FrameError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def encode(frame: dict) -> bytes:
    return (canonical_json(frame) + "\n").encode("utf-8")


def decode(line: bytes) -> dict:
    try:
        frame = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise FrameError("MALFORMED_FRAME") from error
    if not isinstance(frame, dict) or frame.get("kind") not in FRAME_KINDS:
        raise FrameError("MALFORMED_FRAME")
    if frame.get("protocolVersion") != PROTOCOL_VERSION:
        raise FrameError("PROTOCOL_VERSION_MISMATCH")
    return frame


def _base(kind: str) -> dict:
    return {"protocolVersion": PROTOCOL_VERSION, "kind": kind}


def recall_frame(
    *,
    receiver: str,
    publisher: str,
    context: dict,
    purpose: str,
    query: str,
    k: int,
    at: str,
) -> dict:
    return {
        **_base("recall"),
        "receiver": receiver,
        "publisher": publisher,
        "context": context,
        "purpose": purpose,
        "audience": "self",
        "query": query,
        "k": int(k),
        "at": at,
    }


def recall_result_frame(
    *,
    turn_id: str,
    query_digest: dict,
    context: dict,
    candidates: list[dict],
    decision: dict,
    disclosure_id: str | None,
) -> dict:
    return {
        **_base("recall_result"),
        "turnId": turn_id,
        "queryDigest": query_digest,
        "context": context,
        "candidates": candidates,
        "decision": decision,
        "disclosureId": disclosure_id,
    }


def read_frame(
    *,
    receiver: str,
    publisher: str,
    context: dict,
    purpose: str,
    turn_id: str,
    memory_ids: list[str],
) -> dict:
    return {
        **_base("read"),
        "receiver": receiver,
        "publisher": publisher,
        "context": context,
        "purpose": purpose,
        "turnId": turn_id,
        "memoryIds": list(memory_ids),
    }


def read_result_frame(*, items: list[dict], disclosure_id: str | None) -> dict:
    return {
        **_base("read_result"),
        "items": items,
        "disclosureId": disclosure_id,
    }


def error_frame(code: str, detail: str = "") -> dict:
    return {**_base("error"), "code": code, "detail": detail}
