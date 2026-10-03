"""Engram CLI — administrative commands for federation."""

import argparse
import contextlib
import io
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

import store_identity
from federation import InstanceRegistry, SignalBus, sync_genome

ENGRAM_DIR = Path(os.environ.get("ENGRAM_HOME", Path.home())) / ".engram"
AGENT_NAME_RE = re.compile(r"agent-[a-z][a-z0-9-]{0,62}\Z")


def fork_instance(name: str, engram_dir: Path | None = None, from_source: str = "genome"):
    """Fork a new instance from the genome or another instance."""
    if engram_dir is None:
        engram_dir = ENGRAM_DIR

    # Determine source DB
    if from_source == "genome":
        source_db = engram_dir / "genome" / "graph.db"
    else:
        source_db = engram_dir / "instances" / from_source / "graph.db"

    if not source_db.exists():
        print(f"Error: source database not found at {source_db}", file=sys.stderr)
        sys.exit(1)

    inst_dir = engram_dir / "instances" / name
    inst_dir.mkdir(parents=True, exist_ok=True)
    inst_db = inst_dir / "graph.db"

    if inst_db.exists():
        print(f"Error: instance '{name}' already exists at {inst_db}", file=sys.stderr)
        sys.exit(1)

    # Safe copy via SQLite backup API (handles WAL correctly)
    src = sqlite3.connect(str(source_db))
    dst = sqlite3.connect(str(inst_db))
    try:
        src.backup(dst)
        # A fork is a different store from the moment it exists: it gets its
        # own identity and remembers the source's. A source that predates
        # identity is named by the id its own migration will derive; the
        # source itself is never written.
        source_instance_id = store_identity.effective_id(src)
        instance_id = store_identity.stamp_fork(dst, source_instance_id)
        dst.commit()
    finally:
        src.close()
        dst.close()

    # Register
    reg = InstanceRegistry(engram_dir / "instances.json")
    reg.register(name, inst_db, forked_from=from_source, instance_id=instance_id,
                 forked_from_instance_id=source_instance_id)
    print(f"Forked instance '{name}' from {from_source} → {inst_db}")
    return {"instance": name, "path": str(inst_db), "forked_from": from_source}


def drop_instance(name: str, engram_dir: Path | None = None):
    """Remove an instance and clean up signals."""
    if engram_dir is None:
        engram_dir = ENGRAM_DIR
    import shutil

    reg = InstanceRegistry(engram_dir / "instances.json")
    info = reg.get(name)
    if not info:
        print(f"Error: instance '{name}' not found", file=sys.stderr)
        sys.exit(1)

    # Remove database directory
    inst_dir = engram_dir / "instances" / name
    if inst_dir.exists():
        shutil.rmtree(inst_dir)

    # Clean up the dropped instance's reader receipts.
    signals_db = engram_dir / "signals.db"
    if signals_db.exists():
        bus = SignalBus(signals_db)
        bus.conn.execute("DELETE FROM reads WHERE instance = ?", (name,))
        bus.conn.commit()
        bus.close()

    # Unregister
    reg.remove(name)
    print(f"Dropped instance '{name}'")
    return {"instance": name, "dropped": True}


def list_instances(engram_dir: Path | None = None):
    """List all registered instances."""
    if engram_dir is None:
        engram_dir = ENGRAM_DIR

    reg = InstanceRegistry(engram_dir / "instances.json")
    instances = reg.list()
    if not instances:
        print("No instances registered.")
        return {"instances": {}}

    for name, info in instances.items():
        print(f"  {name}: forked from {info['forked_from']} at {info['forked_at']}")
    return {"instances": instances}


def _create_store(path: Path, seed_path: Path | None = None) -> str | None:
    """Create a full-schema store once; existing stores are never opened."""
    from storage import Storage

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.touch(exist_ok=False)
    except FileExistsError:
        return None
    store = None
    try:
        store = Storage(str(path))
        instance_id = store.instance_identity()["instance_id"]
        if seed_path is not None:
            sync_genome(str(seed_path), store)
        return instance_id
    except BaseException:
        if store is not None:
            store.close()
            store = None
        for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
            candidate.unlink(missing_ok=True)
        raise
    finally:
        if store is not None:
            store.close()


def agent_create(name: str, seed: str = "empty", engram_dir: Path | None = None) -> dict:
    """Create an independent agent store, optionally seeded from genome core."""
    if not AGENT_NAME_RE.fullmatch(name):
        raise ValueError("name must match agent-[a-z][a-z0-9-]{0,62}")
    if seed not in ("empty", "genome-core"):
        raise ValueError("seed must be empty or genome-core")
    root = engram_dir if engram_dir is not None else ENGRAM_DIR
    path = root / "instances" / name / "graph.db"
    result = {"instance": name, "path": str(path), "created": False, "seed": seed}
    if path.exists():
        return result
    seed_path = root / "genome" / "graph.db" if seed == "genome-core" else None
    if seed_path is not None and not seed_path.is_file():
        raise FileNotFoundError(f"source database not found at {seed_path}")
    instance_id = _create_store(path, seed_path)
    if instance_id is None:
        return result
    InstanceRegistry(root / "instances.json").register(
        name, path, forked_from="genome" if seed_path else "empty", instance_id=instance_id,
    )
    result["created"] = True
    return result


def house_init(engram_dir: Path | None = None) -> dict:
    """Initialize the local published house; do not change policy or serve it."""
    root = engram_dir if engram_dir is not None else ENGRAM_DIR
    path = root / "instances" / "lighthouse" / "graph.db"
    created = False if path.exists() else _create_store(path) is not None
    return {"path": str(path), "created": created}


class _JSONArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def main():
    parser = _JSONArgumentParser(prog="engram", description="Engram federation CLI")
    sub = parser.add_subparsers(dest="command")

    fork_p = sub.add_parser("fork", help="Fork a new instance from genome or another instance")
    fork_p.add_argument("name", help="Instance name")
    fork_p.add_argument("--from", dest="from_source", default="genome",
                        help="Source to fork from: 'genome' (default) or another instance name")

    drop_p = sub.add_parser("drop", help="Remove an instance")
    drop_p.add_argument("name", help="Instance name")

    sub.add_parser("list", help="List all instances")

    create_p = sub.add_parser("agent-create", help="Create an independent agent memory store")
    create_p.add_argument("name")
    create_p.add_argument("--seed", choices=("empty", "genome-core"), default="empty")
    sub.add_parser("house-init", help="Initialize the local published house")
    shared_p = sub.add_parser("shared", help="Read published shares without modifying the house")
    shared_p.add_argument("--audience", required=True)
    shared_p.add_argument("--query")
    shared_p.add_argument("--after")
    shared_p.add_argument("--limit", type=int, default=20)

    try:
        args = parser.parse_args()
        if args.command in ("fork", "drop", "list"):
            # Keep the administrative Python helpers' historical prose for
            # callers, while the CLI has one machine-readable stdout object.
            captured_error = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(captured_error):
                try:
                    if args.command == "fork":
                        result = fork_instance(args.name, from_source=args.from_source)
                    elif args.command == "drop":
                        result = drop_instance(args.name)
                    else:
                        result = list_instances()
                except SystemExit as exc:
                    raise ValueError(captured_error.getvalue().strip() or "command failed") from exc
        elif args.command == "agent-create":
            result = agent_create(args.name, args.seed)
        elif args.command == "house-init":
            result = house_init()
        elif args.command == "shared":
            from sharing import read_shared
            result = read_shared(
                ENGRAM_DIR / "instances" / "lighthouse" / "graph.db",
                audience=args.audience, query=args.query, after=args.after, limit=args.limit,
            )
        else:
            raise ValueError("a command is required")
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
