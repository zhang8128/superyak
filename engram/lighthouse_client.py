"""Bounded Lighthouse receiver transport and validation."""

from __future__ import annotations

import json
import math
import re
import socket
import time
from pathlib import Path

from lighthouse_protocol import FrameError, canonical_json, content_digest, encode, validate_frame
from sharing import validate_audience

MAX_FRAME_BYTES = 1024 * 1024
MAX_TIMEOUT_S = 10.0
MAX_CANDIDATES = 20
MAX_QUERY_CHARS = 4096
MAX_CONTENT_BYTES = 32 * 1024
MAX_PUBLISHERS = 8
_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")
_CANDIDATE_FIELDS = frozenset({
    "memoryId", "rank", "layer", "lane", "contentDigest", "audiences",
})
_REMOTE_CODES = frozenset({
    "PUBLISHER_UNAVAILABLE", "PROTOCOL_VERSION_MISMATCH", "MALFORMED_FRAME",
})


class NeighborUnavailable(RuntimeError):
    """A stable, content-free diagnostic suitable for a receiver receipt."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _finite_number(value) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise NeighborUnavailable("TIMEOUT")
    return remaining


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("non-finite JSON constant")


def _decode_reply(wire: bytes, expected_kind: str) -> dict:
    try:
        reply = json.loads(
            wire.decode("utf-8"), object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        validate_frame(reply)
        # Detect finite-number overflow (e.g. 1e999) and invalid Unicode too.
        encode(reply)
    except FrameError as exc:
        raise NeighborUnavailable(exc.code) from exc
    except (ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise NeighborUnavailable("MALFORMED_FRAME") from exc
    if reply["kind"] == "error":
        code = reply["code"]
        raise NeighborUnavailable(code if code in _REMOTE_CODES else "REMOTE_ERROR")
    if reply["kind"] != expected_kind:
        raise NeighborUnavailable("MALFORMED_FRAME")
    return reply


class LighthouseClient:
    """One request per connection, bounded by bytes and a monotonic deadline."""

    def __init__(self, socket_path, timeout_s: float = 2.0):
        if not _finite_number(timeout_s) or not 0 < timeout_s <= MAX_TIMEOUT_S:
            raise ValueError("INVALID_TIMEOUT")
        self.socket_path = Path(socket_path)
        self.timeout_s = float(timeout_s)

    def call(self, frame: dict, *, deadline: float | None = None) -> dict:
        end = time.monotonic() + self.timeout_s
        if deadline is not None:
            if not _finite_number(deadline):
                raise ValueError("INVALID_DEADLINE")
            end = min(end, deadline)
        _remaining(end)
        try:
            validate_frame(frame)
            expected_kind = {"recall": "recall_result", "read": "read_result"}[
                frame["kind"]
            ]
            if frame["kind"] == "recall":
                _require(len(frame["query"]) <= MAX_QUERY_CHARS, "QUERY_TOO_LARGE")
                _require(frame["k"] <= MAX_CANDIDATES, "INVALID_LIMIT")
            wire = encode(frame)
        except FrameError as exc:
            raise NeighborUnavailable(exc.code) from exc
        except (KeyError, ValueError, TypeError, RecursionError, OverflowError) as exc:
            raise NeighborUnavailable("MALFORMED_FRAME") from exc
        if len(wire) > MAX_FRAME_BYTES:
            raise NeighborUnavailable("FRAME_TOO_LARGE")
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(_remaining(end))
                connection.connect(str(self.socket_path))
                connection.settimeout(_remaining(end))
                connection.sendall(wire)
                data = bytearray()
                while True:
                    connection.settimeout(_remaining(end))
                    part = connection.recv(min(65536, MAX_FRAME_BYTES + 1 - len(data)))
                    if not part:
                        raise NeighborUnavailable("MALFORMED_FRAME")
                    data.extend(part)
                    if len(data) > MAX_FRAME_BYTES:
                        raise NeighborUnavailable("FRAME_TOO_LARGE")
                    if b"\n" in part:
                        if data.find(b"\n") != len(data) - 1:
                            raise NeighborUnavailable("MALFORMED_FRAME")
                        _remaining(end)
                        reply = _decode_reply(bytes(data), expected_kind)
                        _remaining(end)
                        return reply
        except TimeoutError as exc:
            raise NeighborUnavailable("TIMEOUT") from exc
        except OSError as exc:
            raise NeighborUnavailable("UNAVAILABLE") from exc


def _text(value) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        value.encode("utf-8")
    except UnicodeError:
        return False
    return True


def _require(condition, code: str) -> None:
    if not condition:
        raise NeighborUnavailable(code)


def _digest(value, code: str) -> dict:
    _require(
        isinstance(value, dict) and set(value) == {"algorithm", "value"}
        and value["algorithm"] == "sha256" and isinstance(value["value"], str)
        and _SHA256_HEX.fullmatch(value["value"]) is not None,
        code,
    )
    return {"algorithm": "sha256", "value": value["value"]}


def _decision(value, code: str) -> dict:
    _require(
        isinstance(value, dict) and set(value) == {"effect", "ruleId", "code"}
        and value["effect"] in ("allow", "deny")
        and (value["ruleId"] is None or _text(value["ruleId"])),
        code,
    )
    if value["effect"] == "allow":
        _require(value["code"] is None and _text(value["ruleId"]), code)
    else:
        _require(value["code"] in (
            "NO_MATCHING_ALLOW", "EXPLICIT_DENY", "OUTSIDE_VALIDITY",
        ), code)
    return {key: value[key] for key in ("effect", "ruleId", "code")}


def _context(value, code: str) -> dict:
    _require(
        isinstance(value, dict) and set(value) == {"id", "path"}
        and _text(value["id"]) and isinstance(value["path"], list)
        and all(_text(part) for part in value["path"]),
        code,
    )
    return {"id": value["id"], "path": list(value["path"])}


def _audiences(value, code: str, *, allow_empty: bool = False) -> list[str]:
    _require(isinstance(value, list) and (allow_empty or bool(value)), code)
    try:
        result = [validate_audience(item) for item in value]
    except (ValueError, TypeError) as exc:
        raise NeighborUnavailable(code) from exc
    _require(len(result) == len(set(result)), code)
    return sorted(result)


def _checked_reply(reply, kind: str) -> dict:
    try:
        validate_frame(reply)
    except FrameError as exc:
        raise NeighborUnavailable(exc.code) from exc
    except (ValueError, TypeError, RecursionError) as exc:
        raise NeighborUnavailable("MALFORMED_FRAME") from exc
    _require(reply["kind"] == kind, "MALFORMED_FRAME")
    return reply


def _rankings(candidates, code: str) -> list[dict]:
    _require(isinstance(candidates, list) and len(candidates) <= MAX_CANDIDATES, code)
    ids = {}
    ranks = set()
    checked = []
    for candidate in candidates:
        _require(
            isinstance(candidate, dict) and _text(candidate.get("memoryId"))
            and type(candidate.get("rank")) is int
            and 0 < candidate["rank"] <= 2**53 - 1,
            code,
        )
        digest = _digest(candidate.get("contentDigest"), code)
        memory_id, rank = candidate["memoryId"], candidate["rank"]
        if memory_id in ids:
            _require(ids[memory_id] == digest, "CONFLICTING_DIGEST")
            raise NeighborUnavailable(code)
        _require(rank not in ranks, code)
        ids[memory_id] = digest
        ranks.add(rank)
        checked.append({"memoryId": memory_id, "rank": rank, "contentDigest": digest})
    return checked


def validate_trace(
    reply: dict, *, publisher: str, query: str, context: dict, k: int,
) -> dict:
    """Bind a trace to this request and return detached, content-free evidence."""
    code = "INVALID_TRACE"
    _require(_text(publisher), code)
    _require(type(k) is int and 0 < k <= MAX_CANDIDATES, code)
    _require(isinstance(query, str) and len(query) <= MAX_QUERY_CHARS, code)
    try:
        expected_digest = content_digest(query)
    except UnicodeError as exc:
        raise NeighborUnavailable(code) from exc
    expected_context = _context(context, code)
    _checked_reply(reply, "recall_result")
    query_digest = _digest(reply["queryDigest"], code)
    _require(query_digest == expected_digest, "QUERY_MISMATCH")
    reply_context = _context(reply["context"], code)
    _require(reply_context == expected_context, "CONTEXT_MISMATCH")
    decision = _decision(reply["decision"], code)
    _require(_text(reply["turnId"]), code)
    disclosure = reply["disclosureId"]
    _require(disclosure is None or _text(disclosure), code)
    if decision["effect"] == "allow":
        _require(disclosure is not None, code)
    else:
        _require(reply["candidates"] == [], code)
    _require(len(reply["candidates"]) <= k, code)
    ranked = _rankings(reply["candidates"], code)
    candidates = []
    for original, rank in zip(reply["candidates"], ranked):
        _require(set(original) == _CANDIDATE_FIELDS, code)
        _require(original["layer"] in ("episode", "semantic"), code)
        _require(original["lane"] in ("personal", "work"), code)
        candidates.append({
            **rank, "layer": original["layer"], "lane": original["lane"],
            "audiences": _audiences(original["audiences"], code),
        })
    candidates.sort(key=lambda item: item["rank"])
    return {
        "publisher": publisher, "turnId": reply["turnId"], "queryDigest": query_digest,
        "context": reply_context, "candidates": candidates, "decision": decision,
        "disclosureId": disclosure,
    }


_PERMISSION_KEYS = {"laid_by", "allowed_by", "until", "receipt"}


def _permission(value, code: str) -> dict:
    """P 11's object, checked to its types and copied; any other member is refused."""
    _require(isinstance(value, dict) and set(value) == _PERMISSION_KEYS, code)
    _require(_text(value["laid_by"]) and _text(value["receipt"]), code)
    _require(value["until"] is None or _text(value["until"]), code)
    allowed = value["allowed_by"]
    _require(isinstance(allowed, list), code)
    for entry in allowed:
        _require(isinstance(entry, dict) and set(entry) == {"place", "records"} and _text(entry["place"])
                 and isinstance(entry["records"], list) and all(_text(r) for r in entry["records"]), code)
    return {"laid_by": value["laid_by"], "until": value["until"], "receipt": value["receipt"],
            "allowed_by": [{"place": e["place"], "records": list(e["records"])} for e in allowed]}


def validate_read(reply: dict, *, selected: list[dict]) -> list[dict]:
    """Deliver only selected, intact shares still allowed by the publisher."""
    code = "INVALID_READ"
    _checked_reply(reply, "read_result")
    _require(isinstance(selected, list) and len(selected) <= MAX_CANDIDATES, code)
    by_id = {}
    publishers = set()
    for entry in selected:
        _require(
            isinstance(entry, dict) and _text(entry.get("memoryId"))
            and _text(entry.get("publisher")) and entry.get("layer") in ("episode", "semantic")
            and entry.get("lane") in ("personal", "work"),
            code,
        )
        memory_id = entry["memoryId"]
        _require(memory_id not in by_id, code)
        publishers.add(entry["publisher"])
        by_id[memory_id] = {
            "publisher": entry["publisher"], "memoryId": memory_id,
            "layer": entry["layer"], "lane": entry["lane"],
            "contentDigest": _digest(entry.get("contentDigest"), code),
            "audiences": _audiences(entry.get("audiences"), code),
        }
    _require(len(publishers) <= 1, code)
    _require(len(reply["items"]) <= len(selected), code)
    _require(reply["disclosureId"] is None or _text(reply["disclosureId"]), code)
    seen = set()
    verified = []
    for item in reply["items"]:
        _require(isinstance(item, dict) and set(item) - {"permission"} == {"memoryId", "content", "audiences", "decision"}, code)
        memory_id = item["memoryId"]
        _require(_text(memory_id), code)
        _require(memory_id in by_id and memory_id not in seen, code)
        seen.add(memory_id)
        decision = _decision(item["decision"], code)
        permission = _permission(item["permission"], code) if "permission" in item else None
        audiences = _audiences(item["audiences"], code, allow_empty=True)
        content = item["content"]
        _require(content is None or isinstance(content, str), code)
        if content is None or decision["effect"] != "allow":
            continue
        _require(reply["disclosureId"] is not None and bool(audiences), code)
        entry = by_id[memory_id]
        _require(set(audiences) <= set(entry["audiences"]), code)
        try:
            size = len(content.encode("utf-8"))
        except UnicodeError as exc:
            raise NeighborUnavailable(code) from exc
        _require(size <= MAX_CONTENT_BYTES, "CONTENT_TOO_LARGE")
        _require(content_digest(content) == entry["contentDigest"], "CONTENT_DIGEST_MISMATCH")
        kept = {**entry, "content": content, "audiences": audiences, "decision": decision}
        if permission is not None:
            kept["permission"] = permission
        verified.append(kept)
    return verified


def fuse_traces(traces: dict[str, tuple[float, list[dict]]], k: int) -> list[dict]:
    """Weighted RRF over publisher-qualified IDs, matching the TypeScript kit."""
    _require(type(k) is int and 0 < k <= MAX_CANDIDATES, "INVALID_LIMIT")
    _require(isinstance(traces, dict) and len(traces) <= MAX_PUBLISHERS, "INVALID_TRACE")
    fused = []
    for publisher, trace in traces.items():
        _require(_text(publisher), "INVALID_TRACE")
        _require(isinstance(trace, (tuple, list)) and len(trace) == 2, "INVALID_TRACE")
        weight, candidates = trace
        _require(_finite_number(weight) and weight >= 0, "INVALID_WEIGHT")
        ranked = _rankings(candidates, "INVALID_TRACE")
        if weight == 0:
            continue
        for candidate in ranked:
            fused.append({
                "publisher": publisher, "memoryId": candidate["memoryId"],
                "contentDigest": candidate["contentDigest"],
                "score": weight / (60 + candidate["rank"]),
                "contributions": [{"publisher": publisher, "rank": candidate["rank"]}],
            })
    # JS compares canonical strings by UTF-16 code unit, not Python code point.
    fused.sort(key=lambda item: (
        -item["score"],
        canonical_json({"publisher": item["publisher"], "memoryId": item["memoryId"]})
        .encode("utf-16-be"),
    ))
    return fused[:k]
