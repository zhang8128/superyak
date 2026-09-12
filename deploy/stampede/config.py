"""Bounded configuration for the Stampede3 campaign launcher."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any


MAX_CONFIG_BYTES = 64 * 1024
MAX_NODES = 4
MAX_WALLTIME_SECONDS = 12 * 60 * 60

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_LOGIN = re.compile(
    r"(?:[A-Za-z0-9][A-Za-z0-9_.-]{0,63}@)?"
    r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\Z"
)
_MODEL_VALUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,255}\Z")
_WALLTIME = re.compile(r"(?:(?P<days>[0-9]{1,2})-)?(?P<hours>[0-9]{1,2}):"
                       r"(?P<minutes>[0-9]{2}):(?P<seconds>[0-9]{2})\Z")

_DEFAULTS: dict[str, Any] = {
    "version": 1,
    "login": "",
    "account": "",
    "partition": "pvc",
    "nodes": 4,
    "walltime": "12:00:00",
    "run_id": "",
    "remote_subdir": "superyak",
    "model": "Qwen/Qwen3-8B",
    "model_revision": "main",
    "backend": "auto",
    "cell_seconds": 5400,
    "populations": [32, 128],
    "concurrency": [4, 16],
    "community_population": 64,
    "seed": 20260912,
    "max_turns": 12,
    "max_calls_per_cell": 2048,
    "max_prompt_chars": 32000,
    "max_output_tokens": 512,
    "request_timeout_s": 120,
    "data_mode": "synthetic",
}


class ConfigError(ValueError):
    """A bounded, user-facing configuration error."""


def default_config() -> dict[str, Any]:
    """Return an independent copy of the version-one defaults."""
    return json.loads(json.dumps(_DEFAULTS))


def _plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _bounded_int(config: dict, key: str, minimum: int, maximum: int) -> None:
    value = config[key]
    if not _plain_int(value) or not minimum <= value <= maximum:
        raise ConfigError(f"{key} must be an integer from {minimum} to {maximum}")


def _safe_name(value: object, key: str, *, empty: bool = False) -> None:
    if not isinstance(value, str) or (not value and not empty):
        raise ConfigError(f"{key} must be a safe non-empty string")
    if value and not _NAME.fullmatch(value):
        raise ConfigError(f"{key} contains unsafe characters")


def _validate_walltime(value: object) -> None:
    if not isinstance(value, str) or (match := _WALLTIME.fullmatch(value)) is None:
        raise ConfigError("walltime must use HH:MM:SS or D-HH:MM:SS")
    days = int(match.group("days") or 0)
    hours = int(match.group("hours"))
    minutes = int(match.group("minutes"))
    seconds = int(match.group("seconds"))
    if minutes >= 60 or seconds >= 60:
        raise ConfigError("walltime minutes and seconds must be below 60")
    total = ((days * 24 + hours) * 60 + minutes) * 60 + seconds
    if total < 60 or total > MAX_WALLTIME_SECONDS:
        raise ConfigError("walltime must be between 00:01:00 and 12:00:00")


def _validate_remote_subdir(value: object) -> None:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ConfigError("remote_subdir must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(
        part in {"", ".", ".."} or not _NAME.fullmatch(part) for part in path.parts
    ):
        raise ConfigError("remote_subdir must contain only safe relative path segments")


def _validate_int_list(config: dict, key: str, *, maximum: int) -> None:
    value = config[key]
    if (
        not isinstance(value, list)
        or not value
        or len(value) > 8
        or any(not _plain_int(item) or not 1 <= item <= maximum for item in value)
        or len(set(value)) != len(value)
    ):
        raise ConfigError(f"{key} must be a unique non-empty list of bounded integers")


def validate_config(raw: dict[str, Any], *, require_launch: bool = False) -> dict[str, Any]:
    """Merge defaults and validate all values that cross local boundaries."""
    if not isinstance(raw, dict):
        raise ConfigError("configuration must be a JSON object")
    unknown = sorted(set(raw) - set(_DEFAULTS))
    if unknown:
        raise ConfigError(f"unknown configuration keys: {', '.join(unknown)}")
    config = default_config()
    config.update(raw)

    if config["version"] != 1 or isinstance(config["version"], bool):
        raise ConfigError("version must be 1")
    login = config["login"]
    if not isinstance(login, str) or (login and not _LOGIN.fullmatch(login)):
        raise ConfigError("login contains unsafe characters")
    if require_launch and not login:
        raise ConfigError("login is required for deployment")
    _safe_name(config["account"], "account", empty=not require_launch)
    _safe_name(config["partition"], "partition")
    _safe_name(config["run_id"], "run_id", empty=True)
    _validate_remote_subdir(config["remote_subdir"])
    _bounded_int(config, "nodes", 1, MAX_NODES)
    _validate_walltime(config["walltime"])

    for key in ("model", "model_revision"):
        value = config[key]
        if (
            not isinstance(value, str)
            or not _MODEL_VALUE.fullmatch(value)
            or value.startswith("/")
            or ".." in PurePosixPath(value).parts
        ):
            raise ConfigError(f"{key} must be a bounded hub identifier")
    _safe_name(config["backend"], "backend")
    if config["backend"] not in {"auto", "vllm", "sycl"}:
        raise ConfigError("backend must be auto, vllm, or sycl")

    _bounded_int(config, "cell_seconds", 1, MAX_WALLTIME_SECONDS)
    _validate_int_list(config, "populations", maximum=1024)
    _validate_int_list(config, "concurrency", maximum=64)
    _bounded_int(config, "community_population", 0, 1024)
    _bounded_int(config, "seed", 0, 2**31 - 1)
    _bounded_int(config, "max_turns", 1, 100)
    _bounded_int(config, "max_calls_per_cell", 1, 1_000_000)
    _bounded_int(config, "max_prompt_chars", 1024, 1_000_000)
    _bounded_int(config, "max_output_tokens", 1, 8192)
    _bounded_int(config, "request_timeout_s", 1, 900)
    if config["data_mode"] != "synthetic":
        raise ConfigError("data_mode must be synthetic for the bundled campaign")
    return config


def load_config(path: str | Path, *, require_launch: bool = False) -> dict[str, Any]:
    """Load bounded UTF-8 JSON and return a validated configuration."""
    config_path = Path(path)
    try:
        with config_path.open("rb") as stream:
            content = stream.read(MAX_CONFIG_BYTES + 1)
    except OSError as error:
        raise ConfigError(f"cannot read configuration: {config_path}") from error
    if len(content) > MAX_CONFIG_BYTES:
        raise ConfigError("configuration exceeds 64 KiB")
    try:
        raw = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ConfigError("configuration must be valid UTF-8 JSON") from error
    return validate_config(raw, require_launch=require_launch)


def resolve_run_id(config: dict[str, Any]) -> str:
    """Use an explicit ID or derive a stable ID for identical launch settings."""
    if config["run_id"]:
        return config["run_id"]
    identity = {key: config[key] for key in sorted(config) if key != "run_id"}
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:12]
    return f"stampede-{digest}"
