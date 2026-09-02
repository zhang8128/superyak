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
from datetime import datetime
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


def _canonical_number(value: int | float) -> str:
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        raise ValueError("non-finite number is not JSON")
    if value == 0:
        return "0"

    sign = "-" if value < 0 else ""
    mantissa, separator, exponent_text = repr(abs(value)).lower().partition("e")
    exponent = int(exponent_text) if separator else 0
    whole, decimal_point, fraction = mantissa.partition(".")
    combined = whole + fraction if decimal_point else whole
    leading_zeroes = len(combined) - len(combined.lstrip("0"))
    digits = combined.lstrip("0").rstrip("0")
    decimal_position = len(whole) + exponent - leading_zeroes

    if 0 < decimal_position <= 21:
        if decimal_position >= len(digits):
            rendered = digits + "0" * (decimal_position - len(digits))
        else:
            rendered = (
                digits[:decimal_position]
                + "."
                + digits[decimal_position:]
            )
    elif -6 < decimal_position <= 0:
        rendered = "0." + "0" * (-decimal_position) + digits
    else:
        rendered = digits[0]
        if len(digits) > 1:
            rendered += "." + digits[1:]
        scientific_exponent = decimal_position - 1
        exponent_sign = "+" if scientific_exponent >= 0 else ""
        rendered += f"e{exponent_sign}{scientific_exponent}"
    return sign + rendered


def canonical_json(value: Any) -> str:
    _check_finite(value)
    encoder = json.JSONEncoder(
        ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    iterencode = json.encoder._make_iterencode(
        {},
        encoder.default,
        json.encoder.encode_basestring,
        encoder.indent,
        _canonical_number,
        encoder.key_separator,
        encoder.item_separator,
        encoder.sort_keys,
        encoder.skipkeys,
        False,
    )
    return "".join(iterencode(value, 0))


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


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _context_is_valid(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and _nonempty_string(value.get("id"))
        and isinstance(value.get("path"), list)
        and all(_nonempty_string(part) for part in value["path"])
    )


def _timestamp_is_valid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _required(frame: dict, fields: tuple[str, ...]) -> bool:
    return all(field in frame for field in fields)


def _nullable_id_is_valid(value: Any) -> bool:
    return value is None or _nonempty_string(value)


def _validate_recall(frame: dict) -> bool:
    return (
        _required(
            frame,
            (
                "receiver",
                "publisher",
                "context",
                "purpose",
                "audience",
                "query",
                "k",
                "at",
            ),
        )
        and _nonempty_string(frame["receiver"])
        and _nonempty_string(frame["publisher"])
        and _context_is_valid(frame["context"])
        and _nonempty_string(frame["purpose"])
        and frame["audience"] == "self"
        and isinstance(frame["query"], str)
        and isinstance(frame["k"], int)
        and not isinstance(frame["k"], bool)
        and frame["k"] > 0
        and _timestamp_is_valid(frame["at"])
    )


def _validate_recall_result(frame: dict) -> bool:
    return (
        _required(
            frame,
            (
                "turnId",
                "queryDigest",
                "context",
                "candidates",
                "decision",
                "disclosureId",
            ),
        )
        and _nonempty_string(frame["turnId"])
        and isinstance(frame["queryDigest"], dict)
        and _context_is_valid(frame["context"])
        and isinstance(frame["candidates"], list)
        and all(isinstance(candidate, dict) for candidate in frame["candidates"])
        and isinstance(frame["decision"], dict)
        and _nullable_id_is_valid(frame["disclosureId"])
    )


def _validate_read(frame: dict) -> bool:
    return (
        _required(
            frame,
            (
                "receiver",
                "publisher",
                "context",
                "purpose",
                "turnId",
                "memoryIds",
            ),
        )
        and _nonempty_string(frame["receiver"])
        and _nonempty_string(frame["publisher"])
        and _context_is_valid(frame["context"])
        and _nonempty_string(frame["purpose"])
        and _nonempty_string(frame["turnId"])
        and isinstance(frame["memoryIds"], list)
        and all(_nonempty_string(memory_id) for memory_id in frame["memoryIds"])
    )


def _validate_read_result(frame: dict) -> bool:
    return (
        _required(frame, ("items", "disclosureId"))
        and isinstance(frame["items"], list)
        and all(isinstance(item, dict) for item in frame["items"])
        and _nullable_id_is_valid(frame["disclosureId"])
    )


def _validate_error(frame: dict) -> bool:
    return (
        _required(frame, ("code", "detail"))
        and _nonempty_string(frame["code"])
        and isinstance(frame["detail"], str)
    )


_FRAME_VALIDATORS = {
    "recall": _validate_recall,
    "recall_result": _validate_recall_result,
    "read": _validate_read,
    "read_result": _validate_read_result,
    "error": _validate_error,
}


def validate_frame(frame: Any) -> dict:
    """Validate a decoded frame, raising the stable protocol error code."""
    if not isinstance(frame, dict):
        raise FrameError("MALFORMED_FRAME")
    version = frame.get("protocolVersion")
    if not isinstance(version, str):
        raise FrameError("MALFORMED_FRAME")
    if version != PROTOCOL_VERSION:
        raise FrameError("PROTOCOL_VERSION_MISMATCH")
    kind = frame.get("kind")
    if kind not in FRAME_KINDS:
        raise FrameError("MALFORMED_FRAME")
    if not _FRAME_VALIDATORS[kind](frame):
        raise FrameError("MALFORMED_FRAME")
    return frame


def encode(frame: dict) -> bytes:
    return (canonical_json(frame) + "\n").encode("utf-8")


def decode(line: bytes) -> dict:
    try:
        frame = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise FrameError("MALFORMED_FRAME") from error
    return validate_frame(frame)


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
