"""Strict, bounded validation for owner-held local Lighthouse policies."""
from __future__ import annotations
import json
import math
from pathlib import Path
import jsonschema
from lighthouse_policy import Policy, PolicyError, _DIMENSIONS, _parse_rfc3339
from lighthouse_protocol import verify_artifact_digest
from resources import resource_path

_POLICY_VALIDATOR = jsonschema.Draft202012Validator(
    json.loads(resource_path("schemas/lighthouse/connection-policy.schema.json").read_text()),
    format_checker=jsonschema.FormatChecker(),
)


def bounded_read(path, cap):
    with Path(path).open("rb") as stream:
        data = stream.read(cap + 1)
    if len(data) > cap:
        raise ValueError("INPUT_TOO_LARGE")
    return data


def load_owned_policy(path, owner):
    """Validate all rule selectors before evaluating any query authorization."""
    try:
        artifact = json.loads(bounded_read(path, 262144), object_pairs_hook=_unique_members)
        _POLICY_VALIDATOR.validate(artifact)
        if (not isinstance(artifact, dict) or artifact.get("kind") != "ConnectionPolicy"
                or artifact.get("protocolVersion") != "0.1"
                or artifact.get("issuer") != f"urn:engram:{owner}"
                or not verify_artifact_digest(artifact)):
            raise ValueError()
        rules = artifact["payload"]["rules"]
        if not isinstance(rules, list) or len(rules) > 64:
            raise ValueError()
        seen = set()
        for rule in rules:
            if (not isinstance(rule, dict) or not isinstance(rule.get("id"), str)
                    or not 1 <= len(rule["id"]) <= 256 or rule["id"] in seen
                    or rule.get("effect") not in ("allow", "deny")):
                raise ValueError()
            seen.add(rule["id"])
            for key in [d[0] for d in _DIMENSIONS] + ["requiredEvidence", "requiredAttestations"]:
                values = rule.get(key, [] if key.startswith("required") else None)
                if (not isinstance(values, list) or len(values) > 64
                        or any(not isinstance(v, str) or not 1 <= len(v) <= 512 for v in values)):
                    raise ValueError()
            start, end = (_parse_rfc3339(rule.get(k)) for k in ("validFrom", "validUntil"))
            if start is None or end is None or start > end:
                raise ValueError()
        weights = artifact.get("extensions", {}).get("engram:weight", {})
        if not isinstance(weights, dict) or len(weights) > 64:
            raise ValueError()
        for publisher, weight in weights.items():
            if not publisher.startswith("urn:engram:") or len(publisher) > 256:
                raise ValueError()
            if type(weight) not in (int, float) or not math.isfinite(weight) or weight < 0:
                raise ValueError()
        return Policy(artifact)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError,
            RecursionError, jsonschema.ValidationError) as error:
        raise PolicyError("POLICY_INVALID") from error


def _unique_members(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_MEMBER")
        result[key] = value
    return result
