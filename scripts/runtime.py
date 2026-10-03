#!/usr/bin/env python3
"""Canonical Superyak launcher and read-only installation status."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import socket
import sqlite3
import sys
import tempfile
import tomllib


MAX_CONFIG_BYTES = 16_384
MAX_RECEIPT_BYTES = 65_536
MAX_DATABASE_SNAPSHOT_BYTES = 512 * 1024 * 1024
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
SOURCE_ROOT = Path(__file__).resolve().parent.parent
ENGRAM_ROOT = SOURCE_ROOT / "engram"
INTERPRETER = ENGRAM_ROOT / ".venv" / "bin" / "python"


class RuntimeConfigurationError(ValueError):
    """A bounded, user-facing installation error."""


class SnapshotLimitError(OSError):
    """The private status snapshot exceeded its fixed byte budget."""


def _bounded_text(path: Path, limit: int = MAX_CONFIG_BYTES) -> str:
    try:
        with path.open("rb") as stream:
            content = stream.read(limit + 1)
    except FileNotFoundError as error:
        raise RuntimeConfigurationError(f"configuration does not exist: {path}") from error
    except OSError as error:
        raise RuntimeConfigurationError(
            f"configuration cannot be read: {path} ({type(error).__name__})"
        ) from error
    if len(content) > limit:
        raise RuntimeConfigurationError(f"configuration is too large: {path}")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RuntimeConfigurationError(f"configuration is not UTF-8: {path}") from error


def _load_runtime_config(path: Path) -> tuple[Path, str, Path | None]:
    try:
        text = _bounded_text(path)
    except RuntimeConfigurationError as error:
        raise RuntimeConfigurationError(f"runtime {error}") from error
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        raise RuntimeConfigurationError(
            f"runtime configuration is invalid JSON: {path}"
        ) from error
    if not isinstance(raw, dict):
        raise RuntimeConfigurationError("runtime configuration must be a JSON object")
    memory_value = raw.get("memory_home")
    if not isinstance(memory_value, str) or not memory_value:
        raise RuntimeConfigurationError("runtime configuration needs memory_home")
    memory_home = Path(memory_value)
    if not memory_home.is_absolute():
        raise RuntimeConfigurationError("memory_home must be an absolute path")
    if not memory_home.is_dir():
        raise RuntimeConfigurationError(
            f"memory_home is not an existing directory: {memory_home}"
        )
    instance = raw.get("default_instance")
    if not isinstance(instance, str) or not NAME.fullmatch(instance):
        raise RuntimeConfigurationError(
            "default_instance must be a valid named instance"
        )
    embedder_value = raw.get("embedder_socket")
    if embedder_value is None:
        return memory_home, instance, None
    if not isinstance(embedder_value, str) or not Path(embedder_value).is_absolute():
        raise RuntimeConfigurationError("embedder_socket must be an absolute path")
    return memory_home, instance, Path(embedder_value)


def _valid_publishers(value: object) -> bool:
    return (
        isinstance(value, list)
        and 1 <= len(value) <= 8
        and all(isinstance(item, str) and NAME.fullmatch(item) for item in value)
        and len(set(value)) == len(value)
    )


def _parse_toml(path: Path) -> dict:
    try:
        value = tomllib.loads(_bounded_text(path))
    except tomllib.TOMLDecodeError as error:
        raise RuntimeConfigurationError(f"invalid TOML configuration: {path}") from error
    if not isinstance(value, dict):
        raise RuntimeConfigurationError(f"invalid TOML configuration: {path}")
    return value


def _parseable_json(path: Path) -> bool:
    try:
        return isinstance(json.loads(_bounded_text(path)), dict)
    except (RuntimeConfigurationError, json.JSONDecodeError):
        return False


def _publisher_socket_path(
    config_path: Path, memory_home: Path, socket_value: str | None
) -> Path:
    path = (
        Path(socket_value)
        if socket_value is not None
        else memory_home / ".engram" / "lighthouse.sock"
    )
    if not path.is_absolute():
        path = config_path.parent / path
    return path.resolve()


def _git_directory(source_root: Path) -> Path | None:
    marker = source_root / ".git"
    if marker.is_dir():
        return marker
    if not marker.is_file():
        return None
    try:
        line = _bounded_text(marker, 4096).strip()
    except RuntimeConfigurationError:
        return None
    if not line.startswith("gitdir: "):
        return None
    directory = Path(line.removeprefix("gitdir: "))
    if not directory.is_absolute():
        directory = (source_root / directory).resolve()
    return directory


def _configured_revision(source_root: Path) -> str | None:
    git_dir = _git_directory(source_root)
    if git_dir is None:
        return None
    try:
        head = _bounded_text(git_dir / "HEAD", 4096).strip()
    except RuntimeConfigurationError:
        return None
    if re.fullmatch(r"[0-9a-fA-F]{40,64}", head):
        return head.lower()
    if not head.startswith("ref: "):
        return None
    ref = head.removeprefix("ref: ")
    if not re.fullmatch(r"refs/[A-Za-z0-9._/-]+", ref) or ".." in ref:
        return None
    roots = [git_dir]
    try:
        common = _bounded_text(git_dir / "commondir", 4096).strip()
    except RuntimeConfigurationError:
        common = ""
    if common:
        common_dir = Path(common)
        if not common_dir.is_absolute():
            common_dir = (git_dir / common_dir).resolve()
        roots.append(common_dir)
    for root in roots:
        try:
            revision = _bounded_text(root / ref, 4096).strip()
        except RuntimeConfigurationError:
            continue
        if re.fullmatch(r"[0-9a-fA-F]{40,64}", revision):
            return revision.lower()
    for root in roots:
        try:
            packed = _bounded_text(root / "packed-refs", MAX_CONFIG_BYTES)
        except RuntimeConfigurationError:
            continue
        for line in packed.splitlines():
            fields = line.split(" ", 1)
            if len(fields) == 2 and fields[1] == ref and re.fullmatch(
                r"[0-9a-fA-F]{40,64}", fields[0]
            ):
                return fields[0].lower()
    return None


def _project_binding(default_instance: str) -> tuple[Path, str | None, str, str | None]:
    project_root = Path(os.environ.get("ENGRAM_PROJECT_ROOT", os.getcwd())).resolve()
    path = project_root / ".engram" / "config.toml"
    if not path.is_file():
        return project_root, None, default_instance, None
    try:
        raw = _parse_toml(path)
    except RuntimeConfigurationError:
        return project_root, None, default_instance, "invalid project configuration"
    override = raw.get("instance")
    if override is None:
        return project_root, None, default_instance, None
    if not isinstance(override, str) or not NAME.fullmatch(override):
        return project_root, None, default_instance, "invalid project instance"
    return project_root, override, override, None


def _database_path(memory_home: Path, instance: str) -> tuple[Path, Path, bool]:
    requested = memory_home / ".engram" / "instances" / instance / "graph.db"
    if requested.is_file():
        return requested, requested, False
    legacy = memory_home / ".engram" / "graph.db"
    if legacy.is_file():
        return legacy, requested, True
    return requested, requested, False


def _receiver_status(instance_dir: Path) -> tuple[dict, Path | None, list[str]]:
    errors: list[str] = []
    settings_path = instance_dir / "lighthouse-receiver.toml"
    base = {"config": str(settings_path), "publishers": []}
    if not settings_path.is_file():
        return {**base, "state": "disabled"}, None, errors
    try:
        settings = _parse_toml(settings_path)
    except RuntimeConfigurationError:
        return {
            **base,
            "state": "invalid",
            "error": "invalid receiver configuration",
        }, None, ["receiver configuration is invalid"]
    if settings.get("enabled") is False:
        return {**base, "state": "disabled"}, None, errors
    publishers = settings.get("publishers")
    socket_value = settings.get("socket_path")
    policy_value = settings.get("policy_path")
    limit = settings.get("limit", 1)
    timeout = settings.get("timeout_s", 2.0)
    if (
        settings.get("enabled") is not True
        or set(settings)
        - {
            "enabled",
            "publishers",
            "socket_path",
            "policy_path",
            "limit",
            "timeout_s",
        }
        or not _valid_publishers(publishers)
        or not isinstance(socket_value, str)
        or not socket_value
        or not isinstance(policy_value, str)
        or not policy_value
        or type(limit) is not int
        or not 1 <= limit <= 5
        or type(timeout) not in (int, float)
        or not math.isfinite(timeout)
        or not 0 < timeout <= 10
    ):
        return {
            **base,
            "state": "invalid",
            "error": "invalid receiver configuration",
        }, None, ["receiver configuration is invalid"]
    socket_path = (settings_path.parent / socket_value).resolve()
    policy_path = (settings_path.parent / policy_value).resolve()
    policy_parseable = _parseable_json(policy_path)
    status = {
        **base,
        "state": "enabled" if policy_parseable else "invalid",
        "publishers": publishers,
        "policy": {"path": str(policy_path), "parseable": policy_parseable},
    }
    if not policy_parseable:
        status["error"] = "receiver policy is missing or not parseable"
        errors.append("receiver policy is unavailable")
    return status, socket_path, errors


def _publisher_status(memory_home: Path) -> tuple[dict, Path | None, list[str]]:
    errors: list[str] = []
    config_path = memory_home / ".engram" / "lighthouse-daemon.toml"
    base = {"config": str(config_path), "publishers": []}
    if not config_path.is_file():
        return {**base, "state": "missing"}, None, ["publisher configuration is missing"]
    try:
        config = _parse_toml(config_path)
    except RuntimeConfigurationError:
        return {
            **base,
            "state": "invalid",
            "error": "invalid publisher configuration",
        }, None, ["publisher configuration is invalid"]
    publishers = config.get("publishers")
    socket_value = config.get("socket")
    if not _valid_publishers(publishers) or (
        socket_value is not None
        and (not isinstance(socket_value, str) or not socket_value)
    ):
        return {
            **base,
            "state": "invalid",
            "error": "invalid publisher configuration",
        }, None, ["publisher configuration is invalid"]
    socket_path = _publisher_socket_path(config_path, memory_home, socket_value)
    resources = []
    available = True
    for publisher in publishers:
        directory = memory_home / ".engram" / "instances" / publisher
        database = directory / "graph.db"
        policy = directory / "lighthouse-policy.json"
        parseable = _parseable_json(policy)
        resource = {
            "name": publisher,
            "database": {"path": str(database), "available": database.is_file()},
            "policy": {"path": str(policy), "parseable": parseable},
        }
        resources.append(resource)
        if not database.is_file() or not parseable:
            available = False
    if not available:
        errors.append("one or more publisher resources are unavailable")
    return {
        **base,
        "state": "available" if available else "unavailable",
        "publishers": publishers,
        "resources": resources,
    }, socket_path, errors


def _socket_status(path: Path | None) -> tuple[dict, bool]:
    if path is None:
        return {"path": None, "connected": False, "error": "not configured"}, False
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(0.25)
    try:
        client.connect(str(path))
    except (OSError, ValueError):
        return {
            "path": str(path),
            "connected": False,
            "error": "connection unavailable",
        }, False
    finally:
        client.close()
    return {"path": str(path), "connected": True}, True


def _file_identity(path: Path) -> tuple[int, int, int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def _copy_bounded(source: Path, destination: Path, budget: int) -> int:
    copied = 0
    with source.open("rb") as input_stream, destination.open("xb") as output_stream:
        while chunk := input_stream.read(min(1024 * 1024, budget - copied + 1)):
            copied += len(chunk)
            if copied > budget:
                raise SnapshotLimitError
            output_stream.write(chunk)
    return copied


def _receipt_from_snapshot(database: Path) -> tuple[dict | None, str | None]:
    connection = None
    try:
        connection = sqlite3.connect(str(database), timeout=0.25)
        connection.execute("PRAGMA query_only = ON")
        row = connection.execute(
            "SELECT timestamp, substr(context, 1, ?), length(context) "
            "FROM memory_log WHERE event_type = ? "
            "ORDER BY timestamp DESC, rowid DESC LIMIT 1",
            (MAX_RECEIPT_BYTES + 1, "lighthouse_receipt"),
        ).fetchone()
        if row is None:
            return None, None
        if row[2] is None or row[2] > MAX_RECEIPT_BYTES:
            return None, "latest Lighthouse receipt metadata is too large"
        context = json.loads(row[1])
        receipt = context.get("receipt") if isinstance(context, dict) else None
        receipt_id = receipt.get("id") if isinstance(receipt, dict) else None
        if not isinstance(receipt_id, str) or not receipt_id:
            return None, "latest Lighthouse receipt metadata is invalid"
        return {"id": receipt_id, "timestamp": row[0]}, None
    except (sqlite3.Error, json.JSONDecodeError, TypeError):
        return None, "Lighthouse receipt metadata query failed"
    finally:
        if connection is not None:
            connection.close()


def _latest_receipt(database: Path) -> tuple[dict | None, str | None]:
    if not database.is_file():
        return None, None
    wal = Path(str(database) + "-wal")
    try:
        with tempfile.TemporaryDirectory(prefix="superyak-status-") as directory:
            temporary_root = Path(directory)
            for attempt in range(3):
                snapshot_dir = temporary_root / str(attempt)
                snapshot_dir.mkdir()
                snapshot = snapshot_dir / "graph.db"
                snapshot_wal = Path(str(snapshot) + "-wal")
                try:
                    database_before = _file_identity(database)
                    wal_before = _file_identity(wal)
                    expected_size = (database_before[2] if database_before else 0) + (
                        wal_before[2] if wal_before else 0
                    )
                    if expected_size > MAX_DATABASE_SNAPSHOT_BYTES:
                        return None, "database snapshot exceeds status byte limit"
                    copied = _copy_bounded(
                        database, snapshot, MAX_DATABASE_SNAPSHOT_BYTES
                    )
                    if wal_before is not None:
                        _copy_bounded(
                            wal,
                            snapshot_wal,
                            MAX_DATABASE_SNAPSHOT_BYTES - copied,
                        )
                    database_after = _file_identity(database)
                    wal_after = _file_identity(wal)
                except SnapshotLimitError:
                    return None, "database snapshot exceeds status byte limit"
                except OSError:
                    continue
                if database_before == database_after and wal_before == wal_after:
                    return _receipt_from_snapshot(snapshot)
    except OSError:
        return None, "Lighthouse receipt snapshot failed"
    return None, "database changed during status inspection"


def _status(
    memory_home: Path, default_instance: str, embedder_socket: Path | None = None
) -> int:
    errors: list[str] = []
    project_root, project_override, instance, project_error = _project_binding(
        default_instance
    )
    if project_error:
        errors.append(project_error)
    database, requested_database, legacy_fallback = _database_path(
        memory_home, instance
    )
    database_available = database.is_file()
    if not database_available:
        errors.append("selected instance database is missing")
    instance_dir = memory_home / ".engram" / "instances" / instance
    if legacy_fallback:
        receiver = {
            "config": str(instance_dir / "lighthouse-receiver.toml"),
            "state": "disabled",
            "publishers": [],
            "reason": "named instance database is unavailable; using legacy database",
        }
        receiver_socket = None
        errors.append("receiver is disabled while using the legacy database")
    else:
        receiver, receiver_socket, receiver_errors = _receiver_status(instance_dir)
        errors.extend(receiver_errors)
        if receiver["state"] == "disabled":
            errors.append("receiver is disabled")
    publisher, publisher_socket, publisher_errors = _publisher_status(memory_home)
    errors.extend(publisher_errors)
    if receiver["state"] == "enabled":
        unavailable_publishers = sorted(
            set(receiver["publishers"]) - set(publisher["publishers"])
        )
        if unavailable_publishers:
            receiver["unavailable_publishers"] = unavailable_publishers
            errors.append("one or more receiver publishers are unavailable")
    socket_path = receiver_socket or publisher_socket
    socket_report, socket_connected = _socket_status(socket_path)
    if not socket_connected:
        errors.append("publisher socket is unavailable")
    if embedder_socket is None:
        embedder = {"path": None, "configured": False}
    else:
        embedder, embedder_connected = _socket_status(embedder_socket)
        embedder["configured"] = True
        if not embedder_connected:
            errors.append("embedder socket is unavailable")
    receipt, receipt_error = _latest_receipt(database)
    if receipt_error:
        errors.append(receipt_error)
    interpreter_available = INTERPRETER.is_file() and os.access(INTERPRETER, os.X_OK)
    if not interpreter_available:
        errors.append("configured interpreter is unavailable")
    required_scripts = [
        ENGRAM_ROOT / "server.py",
        ENGRAM_ROOT / "hooks" / "wake.py",
        ENGRAM_ROOT / "hooks" / "nudge.py",
        ENGRAM_ROOT / "hooks" / "sleep.py",
        ENGRAM_ROOT / "lighthouse_daemon.py",
    ]
    missing_scripts = [str(path) for path in required_scripts if not path.is_file()]
    if missing_scripts:
        errors.append("one or more configured source scripts are unavailable")
    report = {
        "ok": not errors,
        "source": {
            "path": str(SOURCE_ROOT),
            "configured_revision": _configured_revision(SOURCE_ROOT),
        },
        "interpreter": {
            "path": str(INTERPRETER),
            "available": interpreter_available,
        },
        "memory_home": {"path": str(memory_home), "available": memory_home.is_dir()},
        "instance": {
            "configured_default": default_instance,
            "project_override": project_override,
            "project_root": str(project_root),
            "name": instance,
            "database": str(database),
            "available": database_available,
            **(
                {
                    "requested_database": str(requested_database),
                    "legacy_fallback": True,
                }
                if legacy_fallback
                else {}
            ),
        },
        "receiver": receiver,
        "publisher": publisher,
        "socket": socket_report,
        "embedder": embedder,
        "latest_lighthouse_receipt": receipt,
        "errors": errors,
    }
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


def _command_argv(
    command: str, hook: str | None, memory_home: Path, embedder_socket: Path | None = None
) -> list[str]:
    if command == "mcp":
        return [str(ENGRAM_ROOT / "server.py")]
    if command == "hook":
        return [str(ENGRAM_ROOT / "hooks" / f"{hook}.py")]
    if command == "publisher":
        daemon_config = memory_home / ".engram" / "lighthouse-daemon.toml"
        if not daemon_config.is_file():
            raise RuntimeConfigurationError(
                f"publisher configuration does not exist: {daemon_config}"
            )
        config = _parse_toml(daemon_config)
        socket_value = config.get("socket")
        if not _valid_publishers(config.get("publishers")) or (
            socket_value is not None
            and (not isinstance(socket_value, str) or not socket_value)
        ):
            raise RuntimeConfigurationError(
                f"invalid publisher configuration: {daemon_config}"
            )
        socket_path = _publisher_socket_path(
            daemon_config, memory_home, socket_value
        )
        return [
            str(ENGRAM_ROOT / "lighthouse_daemon.py"),
            "--config",
            str(daemon_config),
            "--socket",
            str(socket_path),
        ]
    if command == "embedder":
        if embedder_socket is None:
            raise RuntimeConfigurationError(
                "runtime configuration needs embedder_socket to run the embedder"
            )
        return [str(ENGRAM_ROOT / "embedder_service.py"), "--socket", str(embedder_socket)]
    raise RuntimeConfigurationError(f"unsupported command: {command}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="superyak-runtime")
    parser.add_argument(
        "--config",
        default=os.environ.get(
            "SUPERYAK_RUNTIME_CONFIG",
            str(Path.home() / ".config" / "superyak" / "runtime.json"),
        ),
        help="explicit runtime JSON configuration",
    )
    parser.add_argument("--instance", help="override the configured default instance")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("mcp")
    hook = commands.add_parser("hook")
    hook.add_argument("hook", choices=("wake", "nudge", "sleep"))
    commands.add_parser("publisher")
    commands.add_parser("embedder")
    commands.add_parser("status")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        memory_home, configured_instance, embedder_socket = _load_runtime_config(
            Path(args.config)
        )
        instance = args.instance or configured_instance
        if not NAME.fullmatch(instance):
            raise RuntimeConfigurationError("instance must be a valid named instance")
        if args.command == "status":
            return _status(memory_home, instance, embedder_socket)
        if not INTERPRETER.is_file() or not os.access(INTERPRETER, os.X_OK):
            raise RuntimeConfigurationError(
                f"configured interpreter is unavailable: {INTERPRETER}"
            )
        if args.command in ("mcp", "hook"):
            _, _, effective_instance, project_error = _project_binding(instance)
            if project_error:
                raise RuntimeConfigurationError(project_error)
            database, _, _ = _database_path(memory_home, effective_instance)
            if not database.is_file():
                raise RuntimeConfigurationError(
                    "memory database does not exist for the effective instance: "
                    f"{database}"
                )
        command = _command_argv(
            args.command, getattr(args, "hook", None), memory_home, embedder_socket
        )
        target = Path(command[0])
        if not target.is_file():
            raise RuntimeConfigurationError(f"configured source script is unavailable: {target}")
        environment = os.environ.copy()
        environment["ENGRAM_HOME"] = str(memory_home)
        environment["ENGRAM_DEFAULT_INSTANCE"] = instance
        if embedder_socket is not None:
            # Every Engram process shares one model instead of loading its own.
            environment["ENGRAM_EMBEDDER_SOCKET"] = str(embedder_socket)
        os.execve(str(INTERPRETER), [str(INTERPRETER), *command], environment)
    except RuntimeConfigurationError as error:
        message = str(error)
        if args.command == "status":
            print(json.dumps({"ok": False, "error": message}, sort_keys=True))
        else:
            print(f"superyak-runtime: {message}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
