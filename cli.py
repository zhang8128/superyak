"""Engram CLI — administrative commands for federation."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from federation import InstanceRegistry, SignalBus

ENGRAM_DIR = Path.home() / ".engram"


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
    src.backup(dst)
    src.close()
    dst.close()

    # Register
    reg = InstanceRegistry(engram_dir / "instances.json")
    reg.register(name, inst_db, forked_from=from_source)
    print(f"Forked instance '{name}' from {from_source} → {inst_db}")


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

    # Clean up signals.db — remove dropped instance from seen_by tracking
    signals_db = engram_dir / "signals.db"
    if signals_db.exists():
        bus = SignalBus(signals_db)
        rows = bus.conn.execute("SELECT id, seen_by FROM messages").fetchall()
        for row in rows:
            seen = json.loads(row["seen_by"])
            if name in seen:
                del seen[name]
                bus.conn.execute(
                    "UPDATE messages SET seen_by = ? WHERE id = ?",
                    (json.dumps(seen), row["id"])
                )
        bus.conn.commit()
        bus.close()

    # Unregister
    reg.remove(name)
    print(f"Dropped instance '{name}'")


def list_instances(engram_dir: Path | None = None):
    """List all registered instances."""
    if engram_dir is None:
        engram_dir = ENGRAM_DIR

    reg = InstanceRegistry(engram_dir / "instances.json")
    instances = reg.list()
    if not instances:
        print("No instances registered.")
        return

    for name, info in instances.items():
        print(f"  {name}: forked from {info['forked_from']} at {info['forked_at']}")


def main():
    parser = argparse.ArgumentParser(prog="engram", description="Engram federation CLI")
    sub = parser.add_subparsers(dest="command")

    fork_p = sub.add_parser("fork", help="Fork a new instance from genome or another instance")
    fork_p.add_argument("name", help="Instance name")
    fork_p.add_argument("--from", dest="from_source", default="genome",
                        help="Source to fork from: 'genome' (default) or another instance name")

    drop_p = sub.add_parser("drop", help="Remove an instance")
    drop_p.add_argument("name", help="Instance name")

    sub.add_parser("list", help="List all instances")

    args = parser.parse_args()
    if args.command == "fork":
        fork_instance(args.name, from_source=args.from_source)
    elif args.command == "drop":
        drop_instance(args.name)
    elif args.command == "list":
        list_instances()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
