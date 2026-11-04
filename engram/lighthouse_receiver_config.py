"""Bounded, explicit receiver settings; nothing here discovers or grants peers."""
from __future__ import annotations

import math
from pathlib import Path
import re
import tomllib


from lighthouse_validation import bounded_read, load_owned_policy
from lighthouse_policy import PolicyError

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


def context_ref(context_id):
    if not isinstance(context_id, str) or len(context_id) > 512:
        raise ValueError("INVALID_CONTEXT")
    parts = context_id.split("/")
    if not parts or any(not SEGMENT.fullmatch(part) for part in parts):
        raise ValueError("INVALID_CONTEXT")
    return {"id": context_id, "path": parts}


MAX_PUBLISHERS = 8                       # local and remote together (lighthouse_client.MAX_PUBLISHERS)
PEER_ID = re.compile(r"[0-9a-f]{64}\Z")
PARTICIPANT = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")   # a peer card's participant id
REMOTE_KEYS = frozenset({"peer_id", "ship", "context"})
SETTINGS_KEYS = frozenset({"enabled", "publishers", "socket_path", "policy_path", "limit", "timeout_s",
                           "remote_publishers", "crossing_socket", "receiver_ship"})


def valid_publishers(publishers, *, allow_empty=False):
    return (isinstance(publishers, list) and (0 if allow_empty else 1) <= len(publishers) <= MAX_PUBLISHERS
            and all(isinstance(p, str) and NAME.fullmatch(p) for p in publishers)
            and len(set(publishers)) == len(publishers))


def valid_remote_publishers(remotes):
    """Ship home and crossing plan P14: each exactly `peer_id` (64 hex), `ship` (a participant id) and `context` (a
    context id), with no two naming the same ship of the same peer."""
    if not isinstance(remotes, list) or len(remotes) > MAX_PUBLISHERS:
        return False
    seen = set()
    for remote in remotes:
        if not isinstance(remote, dict) or set(remote) != REMOTE_KEYS:
            return False
        if not (isinstance(remote["peer_id"], str) and PEER_ID.fullmatch(remote["peer_id"])
                and isinstance(remote["ship"], str) and PARTICIPANT.fullmatch(remote["ship"])):
            return False
        try:
            context_ref(remote["context"])
        except ValueError:
            return False
        key = (remote["peer_id"], remote["ship"])
        if key in seen:
            return False
        seen.add(key)
    return True


def _path(path, value):
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError("INVALID_CONFIG")
    return (path.parent / value).resolve()


def load_settings(path):
    """The receiver's settings, or None when absent or disabled. Local `publishers` need `socket_path`; remote ones
    (`[[remote_publishers]]`, P14) need `crossing_socket` and `receiver_ship`, and `publishers` may then be empty.
    Local and remote together are 1 to 8. Remote publishers carry no weight: weights stay local (P14)."""
    path = Path(path)
    if not path.exists():
        return None
    data = tomllib.loads(bounded_read(path, 16384).decode("utf-8"))
    if data.get("enabled") is False:
        return None
    remotes = data.get("remote_publishers", [])
    if (data.get("enabled") is not True or set(data) - SETTINGS_KEYS
            or not valid_publishers(data.get("publishers"), allow_empty=bool(remotes))
            or not valid_remote_publishers(remotes)
            or not 1 <= len(data["publishers"]) + len(remotes) <= MAX_PUBLISHERS):
        raise ValueError("INVALID_CONFIG")
    limit, timeout = data.get("limit", 1), data.get("timeout_s", 2.0)
    if type(limit) is not int or not 1 <= limit <= 5:
        raise ValueError("INVALID_CONFIG")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 10:
        raise ValueError("INVALID_CONFIG")
    socket_path = _path(path, data.get("socket_path")) if data["publishers"] else None
    crossing_socket, receiver_ship = None, None
    if remotes:
        crossing_socket = _path(path, data.get("crossing_socket"))
        receiver_ship = data.get("receiver_ship")
        if not isinstance(receiver_ship, str) or not PARTICIPANT.fullmatch(receiver_ship):
            raise ValueError("INVALID_CONFIG")
    return dict(publishers=data["publishers"], socket_path=socket_path,
                policy_path=_path(path, data.get("policy_path")), k=limit, timeout_s=timeout,
                remote_publishers=[dict(r) for r in remotes], crossing_socket=crossing_socket,
                receiver_ship=receiver_ship)


def load_receiver_policy(path, receiver):
    try:
        return load_owned_policy(path, receiver)
    except PolicyError as error:
        raise PolicyError("RECEIVER_POLICY_INVALID") from error
