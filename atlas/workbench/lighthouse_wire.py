"""Strict offline Lighthouse 0.1 wire subset for Atlas publication views.

Only JSON safe integers are supported. Policies are local decisions, not
authentication or permission inherited from another publisher.
"""

from datetime import datetime
import hashlib
import hmac
import json
import re


KINDS = {"LighthouseDescriptor": "descriptor", "Snapshot": "snapshot",
         "Claim": "claim", "ConnectionPolicy": "connection-policy"}
ARTIFACT_KINDS = set(KINDS) | {"BridgeDescriptor", "TranslationWitness", "RecallReceipt"}
SELECTORS = {"publishers": "publisher", "profiles": "profile", "domains": "domain",
             "actions": "action", "contexts": "context", "claimMediaTypes": "claimMediaType",
             "purposes": "purpose", "audiences": "audience"}
URI = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:[^\s]+\Z")
TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]+)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])\Z")


def canonical_json(value):
    """Canonical JSON with ECMAScript UTF-16 member ordering; reject coercion."""
    active = set()

    def encode(item):
        if item is None or type(item) is bool:
            return json.dumps(item)
        if type(item) is int and abs(item) <= 2**53 - 1:
            return str(item)
        if type(item) is str:
            # JSON.stringify escapes unpaired surrogates, but leaves Unicode intact.
            return json.dumps(item, ensure_ascii=False).encode("utf-8", "backslashreplace").decode("utf-8")
        if type(item) not in (dict, list):
            raise ValueError("Expected JSON values with safe integers; floats are unsupported")
        if id(item) in active:
            raise ValueError("Circular JSON value")
        active.add(id(item))
        try:
            if type(item) is list:
                return "[" + ",".join(encode(member) for member in item) + "]"
            if any(type(key) is not str for key in item):
                raise ValueError("JSON object keys must be strings")
            keys = sorted(item, key=lambda key: key.encode("utf-16-be", "surrogatepass"))
            return "{" + ",".join(encode(key) + ":" + encode(item[key]) for key in keys) + "}"
        finally:
            active.remove(id(item))

    try:
        return encode(value)
    except RecursionError as error:
        raise ValueError("JSON nesting exceeds the supported depth") from error


def digest(value):
    return {"algorithm": "sha-256", "value": hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()}


def _object(value, required, optional=()):
    if type(value) is not dict or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ValueError("Missing or unknown object fields")


def _text(value):
    if type(value) is not str or not value:
        raise ValueError("Expected a nonempty string")


def _uri(value):
    _text(value)
    if not URI.fullmatch(value):
        raise ValueError("Expected a URI identifier")


def _array(value, validator, minimum=0):
    if type(value) is not list or len(value) < minimum:
        raise ValueError("Expected an array with sufficient entries")
    for member in value:
        validator(member)


def _time(value):
    _text(value)
    if not TIMESTAMP.fullmatch(value):
        raise ValueError("Expected an offset-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # The native evaluator uses Date.parse, whose precision is milliseconds.
        return parsed.replace(microsecond=(parsed.microsecond // 1000) * 1000)
    except ValueError as error:
        raise ValueError("Invalid calendar timestamp") from error


def _digest(value):
    _object(value, ("algorithm", "value"))
    if value["algorithm"] != "sha-256" or type(value["value"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", value["value"]):
        raise ValueError("Unsupported or malformed digest")


def _ref(value):
    _object(value, ("id", "version"), ("digest",))
    _uri(value["id"])
    _text(value["version"])
    if "digest" in value:
        _digest(value["digest"])


def _context(value):
    _object(value, ("id", "path"))
    _text(value["id"])
    _array(value["path"], _text)


def _selector(value):
    _text(value)
    if "*" in value and (not value.endswith("*") or "*" in value[:-1]):
        raise ValueError("Selectors support exact values or a single trailing wildcard")


def _rule(value):
    _object(value, {"id", "effect", "validFrom", "validUntil", "requiredEvidence", "requiredAttestations"} | SELECTORS.keys())
    _text(value["id"])
    if value["effect"] not in ("allow", "deny"):
        raise ValueError("Invalid policy effect")
    for key in SELECTORS:
        _array(value[key], _selector, 1)
    for key in ("requiredEvidence", "requiredAttestations"):
        _array(value[key], _text)
    if _time(value["validFrom"]) > _time(value["validUntil"]):
        raise ValueError("Policy validity interval is reversed")


def _endpoint(value):
    _object(value, ("kind", "locator"))
    if type(value["kind"]) is not str or value["kind"] not in ARTIFACT_KINDS:
        raise ValueError("Unknown endpoint artifact kind")
    _text(value["locator"])


def _payload(kind, value):
    if kind == "LighthouseDescriptor":
        _object(value, ("name", "protocolVersions", "profiles", "actions", "artifactEndpoints"))
        _text(value["name"])
        _array(value["protocolVersions"], _text, 1)
        _array(value["profiles"], _ref)
        _array(value["actions"], _text)
        _array(value["artifactEndpoints"], _endpoint)
    elif kind == "ConnectionPolicy":
        _object(value, ("rules",))
        _array(value["rules"], _rule)
        ids = [rule["id"] for rule in value["rules"]]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate policy rule ID")
    else:
        fields = {"profile", "signature", "context"}
        fields |= {"model", "lineage"} if kind == "Snapshot" else {"sentenceMediaType", "sentence", "snapshotDigests", "provenance"}
        _object(value, fields, ("validFrom", "validUntil") if kind == "Claim" else ())
        _ref(value["profile"])
        _ref(value["signature"])
        _context(value["context"])
        if kind == "Snapshot":
            _array(value["lineage"], _digest)
        else:
            _text(value["sentenceMediaType"])
            _array(value["snapshotDigests"], _digest)
            _array(value["provenance"], _digest)
            for key in ("validFrom", "validUntil"):
                if key in value:
                    _time(value[key])
            if "validFrom" in value and "validUntil" in value and _time(value["validFrom"]) > _time(value["validUntil"]):
                raise ValueError("Claim validity interval is reversed")


def verify(artifact, kind=None):
    """Validate the supported strict envelope, payload and digest; return it."""
    canonical_json(artifact)
    _object(artifact, ("kind", "protocolVersion", "id", "issuedAt", "issuer", "payloadMediaType", "payload", "digest"), ("extensions", "attestations"))
    actual_kind = artifact["kind"]
    if type(actual_kind) is not str or actual_kind not in KINDS or (kind is not None and actual_kind != kind):
        raise ValueError("Unexpected or unsupported artifact kind")
    if artifact["protocolVersion"] != "0.1":
        raise ValueError("Unsupported Lighthouse protocol version")
    _uri(artifact["id"])
    _uri(artifact["issuer"])
    _time(artifact["issuedAt"])
    if artifact["payloadMediaType"] != f"application/vnd.lighthouse.{KINDS[actual_kind]}+json":
        raise ValueError("Incorrect artifact payload media type")
    _payload(actual_kind, artifact["payload"])
    if "extensions" in artifact:
        if type(artifact["extensions"]) is not dict:
            raise ValueError("Extensions must be an object")
        for key in artifact["extensions"]:
            if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", key):
                raise ValueError("Extension keys must be namespaced")
    if "attestations" in artifact:
        def attestation(value):
            _object(value, ("algorithm", "keyId", "signature"))
            for member in value.values():
                _text(member)
        _array(artifact["attestations"], attestation)
    _digest(artifact["digest"])
    content = {key: value for key, value in artifact.items() if key not in ("digest", "attestations")}
    if not hmac.compare_digest(digest(content)["value"], artifact["digest"]["value"]):
        raise ValueError("Artifact digest mismatch")
    return artifact


def seal(kind, issuer, artifact_id, issued_at, payload):
    if type(kind) is not str or kind not in KINDS:
        raise ValueError("Unsupported artifact kind")
    artifact = dict(kind=kind, protocolVersion="0.1", id=artifact_id, issuedAt=issued_at,
                    issuer=issuer, payloadMediaType=f"application/vnd.lighthouse.{KINDS[kind]}+json", payload=payload)
    artifact["digest"] = digest(artifact)
    return verify(artifact)


def authorize(policy, request):
    """Native Lighthouse specificity, deny ties, evidence and inclusive windows."""
    verify(policy, "ConnectionPolicy")
    canonical_json(request)
    _object(request, set(SELECTORS.values()) | {"at", "evidence", "attestations"})
    for key in SELECTORS.values():
        _text(request[key])
    at = _time(request["at"])
    _array(request["evidence"], _text)
    _array(request["attestations"], _text)
    matches = []
    for rule in policy["payload"]["rules"]:
        scores = []
        for plural, singular in SELECTORS.items():
            value = request[singular]
            scores.append(max((2 if pattern == value else 1 if pattern.endswith("*") and value.startswith(pattern[:-1]) else 0
                               for pattern in rule[plural]), default=0))
        if not all(scores) or not set(rule["requiredEvidence"]) <= set(request["evidence"]) or not set(rule["requiredAttestations"]) <= set(request["attestations"]):
            continue
        matches.append((sum(scores), rule))
    if not matches:
        return {"allowed": False, "code": "NO_MATCHING_ALLOW"}
    active = [(score, rule) for score, rule in matches if _time(rule["validFrom"]) <= at <= _time(rule["validUntil"])]
    if not active:
        return {"allowed": False, "code": "OUTSIDE_VALIDITY"}
    active.sort(key=lambda pair: (-pair[0], pair[1]["effect"] != "deny", canonical_json(pair[1]["id"]).encode("utf-16-be", "surrogatepass")))
    winner = active[0][1]
    if winner["effect"] == "allow":
        return {"allowed": True, "ruleId": winner["id"]}
    return {"allowed": False, "ruleId": winner["id"], "code": "EXPLICIT_DENY"}
