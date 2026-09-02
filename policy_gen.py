"""Generate receiver ConnectionPolicy artifacts from group membership."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from lighthouse_protocol import artifact_digest


_NAME = re.compile(r"[a-z][a-z0-9-]{0,63}")


def load_groups(path: Path) -> dict[str, list[str]]:
    """Load and validate a ``groups.toml`` membership mapping."""
    try:
        document = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError("invalid groups file") from error

    groups = document.get("groups")
    if not isinstance(groups, dict):
        raise ValueError("invalid groups file")

    result: dict[str, list[str]] = {}
    for name, group in groups.items():
        if not isinstance(name, str) or _NAME.fullmatch(name) is None:
            raise ValueError("invalid group name")
        if not isinstance(group, dict):
            raise ValueError("invalid group")
        members = group.get("members")
        if (
            not isinstance(members, list)
            or not members
            or not all(
                isinstance(member, str) and _NAME.fullmatch(member) is not None
                for member in members
            )
        ):
            raise ValueError("invalid group members")
        result[name] = list(members)
    return result


def audiences_for_instance(
    groups: dict[str, list[str]], instance: str
) -> list[str]:
    """Return commons followed by the instance's group audiences."""
    joined = sorted(
        f"group:{group}" for group, members in groups.items() if instance in members
    )
    return ["commons", *joined]


def build_receiver_policy(
    *,
    instance: str,
    publisher: str,
    groups: dict[str, list[str]],
    issued_at: str,
    valid_from: str,
    valid_until: str,
) -> dict:
    """Build and seal a receiver policy for one publisher."""
    artifact = {
        "kind": "ConnectionPolicy",
        "protocolVersion": "0.1",
        "id": f"urn:policy:{instance}-receiver",
        "issuedAt": issued_at,
        "issuer": f"urn:engram:{instance}",
        "payloadMediaType": "application/vnd.lighthouse.connection-policy+json",
        "payload": {
            "rules": [
                {
                    "id": f"allow-{publisher}-recall-read-inject",
                    "effect": "allow",
                    "publishers": [f"urn:engram:{publisher}"],
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
                    "validFrom": valid_from,
                    "validUntil": valid_until,
                    "requiredEvidence": [],
                    "requiredAttestations": [],
                }
            ]
        },
        "extensions": {
            "engram:audiences": audiences_for_instance(groups, instance)
        },
    }
    artifact["digest"] = artifact_digest(artifact)
    return artifact


def write_receiver_policy(path: Path, artifact: dict) -> str:
    """Write a policy deterministically and return its digest value."""
    Path(path).write_text(
        json.dumps(artifact, sort_keys=True, indent=1), encoding="utf-8"
    )
    return artifact["digest"]["value"]
