"""Generate publisher-held ConnectionPolicy artifacts from group membership."""

from __future__ import annotations

import json
import re
import tomllib
from datetime import datetime, timedelta, timezone
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
        if name == "outside-home":
            raise ValueError("group name outside-home is reserved")
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


RULE_PROFILES = ["urn:lighthouse:profile:engram-recall-trace"]
RULE_CLAIMS = ["application/vnd.engram.recall-rank-claim+json"]


def remote_grant(
    ref: str,
    audiences: list[str],
    *,
    context: str,
    purpose: str,
    valid_from: str,
    valid_until: str,
) -> tuple[dict, list[str]]:
    """Ship home and crossing plan P24: the one allow rule and the `engram:audiences` entry for a remote store, by its
    exact ref (no wildcard ever allows one, lighthouse_policy._pattern_score). Every remote grant goes through here, so
    the ref is checked against REMOTE_STORE_REF and each audience by validate_audience. Returns (rule, audiences)."""
    from sharing import REMOTE_STORE_REF, validate_audience
    if not isinstance(ref, str) or not REMOTE_STORE_REF.fullmatch(ref):
        raise ValueError("a remote grant names one store ref, urn:superyak:<peer id>:store:<instance id>")
    if not isinstance(audiences, (list, tuple)) or not audiences:
        raise ValueError("a remote grant names at least one audience")
    checked = [validate_audience(a) for a in audiences]
    if len(set(checked)) != len(checked):
        raise ValueError("an audience is named twice")
    peer, instance = ref.removeprefix("urn:superyak:").split(":store:")
    rule = {
        "id": f"remote:{peer[:12]}:{instance}",
        "effect": "allow",
        "publishers": [ref],
        "profiles": list(RULE_PROFILES),
        "domains": ["memory.recall"],
        "actions": ["recall", "read"],
        "contexts": [context],
        "claimMediaTypes": list(RULE_CLAIMS),
        "purposes": [purpose],
        "audiences": ["self"],
        "validFrom": valid_from,
        "validUntil": valid_until,
        "requiredEvidence": [],
        "requiredAttestations": [],
    }
    return rule, checked


def build_publisher_policy(
    *,
    publisher: str,
    receivers: list[str],
    groups: dict[str, list[str]],
    issued_at: str,
    valid_from: str,
    valid_until: str,
    remote_receivers: dict[str, list[str]] | None = None,
    remote_context: str = "memory/technical",
) -> dict:
    """Build and seal one publisher's grants for its receivers, and for each remote store ref in `remote_receivers`
    (ref -> audiences) an exact-ref rule and its audience entry, made by remote_grant."""
    ordered_receivers = sorted(receivers)
    rules = [
        {
            "id": f"allow-{receiver}-recall-read",
            "effect": "allow",
            "publishers": [f"urn:engram:{receiver}"],
            "profiles": ["urn:lighthouse:profile:engram-recall-trace"],
            "domains": ["memory.recall"],
            "actions": ["recall", "read"],
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
        for receiver in ordered_receivers
    ]
    artifact = {
        "kind": "ConnectionPolicy",
        "protocolVersion": "0.1",
        "id": f"urn:policy:{publisher}-publisher",
        "issuedAt": issued_at,
        "issuer": f"urn:engram:{publisher}",
        "payloadMediaType": "application/vnd.lighthouse.connection-policy+json",
        "payload": {"rules": rules},
        "extensions": {
            "engram:audiences": {
                f"urn:engram:{receiver}": audiences_for_instance(groups, receiver)
                for receiver in ordered_receivers
            }
        },
    }
    for ref, audiences in sorted((remote_receivers or {}).items()):
        rule, checked = remote_grant(ref, audiences, context=remote_context, purpose="session-recall",
                                     valid_from=valid_from, valid_until=valid_until)
        artifact["payload"]["rules"].append(rule)
        artifact["extensions"]["engram:audiences"][ref] = checked
    artifact["digest"] = artifact_digest(artifact)
    return artifact


def write_receiver_policy(path: Path, artifact: dict) -> str:
    """Write a policy deterministically and return its digest value."""
    Path(path).write_text(
        json.dumps(artifact, sort_keys=True, indent=1), encoding="utf-8"
    )
    return artifact["digest"]["value"]


# ---------------------------------------------------------------- grant-remote (P24, S6; "an expiry someone will see")

GRANT_DAYS, GRANT_MAX_DAYS = 90, 366


def _rfc3339(when: datetime) -> str:
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _until(text: str | None, now: datetime) -> datetime:
    """`--until` (a date or RFC 3339 UTC), or 90 days from now; never more than 366 days from now."""
    if text is None:
        return now + timedelta(days=GRANT_DAYS)
    try:
        when = (datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc) if "T" not in text
                else datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        raise ValueError("--until is a date (YYYY-MM-DD) or an RFC 3339 time") from None
    when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    if when <= now:
        raise ValueError("--until is in the past")
    if when - now > timedelta(days=GRANT_MAX_DAYS):
        raise ValueError(f"a remote grant ends at most {GRANT_MAX_DAYS} days from now")
    return when


def grant_remote(engram_home: Path, house: str, ref: str, *, context: str, audiences: list[str], purpose: str,
                 until: str | None = None, now: datetime | None = None) -> dict:
    """Add one remote grant to a live publisher policy, `instances/<house>/lighthouse-policy.json`, read with
    load_owned_policy. An flock on the policy file is held for the whole edit, so two runs can't interleave; a ref
    already granted, by a rule or an audience entry, is refused, not replaced. The result is re-digested, loaded with
    load_owned_policy from a file beside the policy, the old file kept as `.bak`, and the new one renamed into place.
    Returns the rule added."""
    import fcntl
    import os
    import shutil
    from lighthouse_validation import load_owned_policy
    now = now or datetime.now(timezone.utc)
    path = Path(engram_home) / ".engram" / "instances" / house / "lighthouse-policy.json"
    rule, checked = remote_grant(ref, audiences, context=context, purpose=purpose, valid_from=_rfc3339(now),
                                 valid_until=_rfc3339(_until(until, now)))
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("another grant-remote is editing this policy; try again") from None
        if os.fstat(fd).st_ino != os.stat(path, follow_symlinks=False).st_ino:
            raise ValueError("the policy was replaced while this run waited; try again")
        policy = load_owned_policy(path, house)
        artifact = json.loads(json.dumps(policy.artifact))
        mapping = artifact.setdefault("extensions", {}).setdefault("engram:audiences", {})
        if ref in mapping or any(ref in (r.get("publishers") or ()) or r.get("id") == rule["id"]
                                 for r in artifact["payload"]["rules"]):
            raise ValueError(f"{ref} is granted already in {house}; it is never replaced here")
        artifact["payload"]["rules"].append(rule)
        mapping[ref] = checked
        artifact.pop("digest", None)
        artifact["digest"] = artifact_digest(artifact)
        staged = path.with_name(path.name + ".new")
        staged.write_text(json.dumps(artifact, sort_keys=True, indent=1), encoding="utf-8")
        try:
            load_owned_policy(staged, house)
            shutil.copyfile(path, path.with_name(path.name + ".bak"))
            os.replace(staged, path)
        finally:
            staged.unlink(missing_ok=True)
    finally:
        os.close(fd)
    return rule


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os
    import sys
    parser = argparse.ArgumentParser(prog="python -m policy_gen")
    commands = parser.add_subparsers(dest="command", required=True)
    g = commands.add_parser("grant-remote", help="grant one remote store, by its exact ref, in a house's policy")
    g.add_argument("--engram-home", type=Path, default=Path(os.environ.get("ENGRAM_HOME") or Path.home()))
    g.add_argument("--house", required=True)
    g.add_argument("--ref", required=True, help="urn:superyak:<peer id>:store:<instance id>")
    g.add_argument("--context", required=True)
    g.add_argument("--audience", action="append", required=True)
    g.add_argument("--purpose", required=True)
    g.add_argument("--until", help=f"a date or RFC 3339 time; default {GRANT_DAYS} days, at most {GRANT_MAX_DAYS}")
    args = parser.parse_args(argv)
    try:
        rule = grant_remote(args.engram_home, args.house, args.ref, context=args.context, audiences=args.audience,
                            purpose=args.purpose, until=args.until)
    except Exception as error:  # noqa: BLE001 - a refusal says why and writes nothing
        print(f"refused: {getattr(error, 'code', None) or error}", file=sys.stderr)
        return 1
    print(f"Granted {args.ref} in {args.house} as rule {rule['id']}, from {rule['validFrom']} until {rule['validUntil']}. "
          "Record that date where a person will see it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
