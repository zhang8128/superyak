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


def valid_publishers(publishers):
    return (isinstance(publishers, list) and 1 <= len(publishers) <= 8
            and all(isinstance(p, str) and NAME.fullmatch(p) for p in publishers)
            and len(set(publishers)) == len(publishers))


def load_settings(path):
    path = Path(path)
    if not path.exists():
        return None
    data = tomllib.loads(bounded_read(path, 16384).decode("utf-8"))
    if data.get("enabled") is False:
        return None
    if (data.get("enabled") is not True
            or set(data) - {"enabled", "publishers", "socket_path", "policy_path", "limit", "timeout_s"}
            or not valid_publishers(data.get("publishers"))):
        raise ValueError("INVALID_CONFIG")
    limit, timeout = data.get("limit", 1), data.get("timeout_s", 2.0)
    if type(limit) is not int or not 1 <= limit <= 5:
        raise ValueError("INVALID_CONFIG")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 10:
        raise ValueError("INVALID_CONFIG")
    for key in ("socket_path", "policy_path"):
        value = data.get(key)
        if not isinstance(value, str) or not value or len(value) > 4096:
            raise ValueError("INVALID_CONFIG")
        data[key] = (path.parent / value).resolve()
    return dict(publishers=data["publishers"], socket_path=data["socket_path"],
                policy_path=data["policy_path"], k=limit, timeout_s=timeout)


def load_receiver_policy(path, receiver):
    try:
        return load_owned_policy(path, receiver)
    except PolicyError as error:
        raise PolicyError("RECEIVER_POLICY_INVALID") from error
