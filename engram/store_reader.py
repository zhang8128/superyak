"""Read-only survey and sequential reading of an Engram store.

For inspecting a store before it is ever opened normally, for example one
ported from another machine. Normal opening runs migrations, genome/inbox
sync and sleep maintenance (decay, prune, compression); nothing here does.

Every connection uses SQLite ``mode=ro`` plus ``query_only`` and never loads
extensions, so vec0 tables are listed but not queried. Column sets are
introspected, so stores written by older schemas are read as they are.

``--immutable`` additionally skips locking and side-file creation for an
archived copy with no concurrent writer. It ignores any ``-wal`` contents,
so a store with a non-empty ``-wal`` should instead be read without it.

Reading is chronological and paged (``read``, ``passages``) rather than
retrieval by relevance: a store is read one entry at a time, in order.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION = re.compile(r"^(\d+)_.*\.sql$")
_EPISODE_FIELDS = (
    "id", "session_id", "created_at", "episode_type", "source", "lane",
    "core", "dormant", "content_hash", "context", "content",
)


def connect(path: str | Path, immutable: bool = False) -> sqlite3.Connection:
    """Open ``path`` read-only; refuse a missing file rather than create it."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(str(p))
    uri = f"file:{p.resolve()}?mode=ro"
    if immutable:
        uri += "&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def file_facts(path: Path) -> dict:
    """Size and hash of a database and whichever WAL side files exist."""
    facts = {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
    for suffix in ("-wal", "-shm"):
        side = path.with_name(path.name + suffix)
        if side.is_file():
            facts[suffix.lstrip("-")] = {"bytes": side.stat().st_size, "sha256": sha256_file(side)}
    return facts


def _tables(conn: sqlite3.Connection) -> dict[str, bool]:
    """Map table name to whether it is virtual."""
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return {r["name"]: (r["sql"] or "").upper().startswith("CREATE VIRTUAL") for r in rows}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f'PRAGMA table_info("{table}")')}


def _schema(conn: sqlite3.Connection, tables: dict[str, bool]) -> dict:
    available = sorted(
        int(m.group(1)) for f in MIGRATIONS_DIR.iterdir() if (m := _MIGRATION.match(f.name))
    )
    applied = []
    if "schema_version" in tables:
        applied = sorted(
            r[0] for r in conn.execute("SELECT version FROM schema_version")
        )
    return {
        "applied": applied,
        "pending": [v for v in available if v not in applied],
        "unknown": [v for v in applied if v not in available],
    }


def _breakdown(conn: sqlite3.Connection, table: str, column: str) -> dict[str, int]:
    rows = conn.execute(
        f'SELECT "{column}" AS k, COUNT(*) AS n FROM "{table}" GROUP BY k ORDER BY n DESC'
    ).fetchall()
    return {str(r["k"]): r["n"] for r in rows}


def survey_graph(conn: sqlite3.Connection) -> dict:
    tables = _tables(conn)
    counts = {
        name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        for name, virtual in tables.items()
        if not virtual
    }
    out = {
        "kind": "engram",
        "schema": _schema(conn, tables),
        "row_counts": counts,
        "virtual_tables": sorted(n for n, v in tables.items() if v),
    }
    if "episodes" in tables:
        cols = _columns(conn, "episodes")
        span = conn.execute(
            "SELECT MIN(created_at), MAX(created_at), COUNT(DISTINCT session_id) FROM episodes"
        ).fetchone()
        episodes = {"first": span[0], "last": span[1], "sessions": span[2]}
        for col in ("source", "episode_type", "lane", "core"):
            if col in cols:
                episodes[f"by_{col}"] = _breakdown(conn, "episodes", col)
        out["episodes"] = episodes
    return out


def survey_reader(conn: sqlite3.Connection) -> dict:
    tables = _tables(conn)
    counts = {
        name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        for name, virtual in tables.items()
        if not virtual
    }
    span = conn.execute(
        "SELECT MIN(created_at), MAX(created_at), COUNT(DISTINCT session_id) FROM reactions"
    ).fetchone()
    return {
        "kind": "reader",
        "row_counts": counts,
        "reactions": {"first": span[0], "last": span[1], "sessions": span[2]},
    }


def survey(path: str | Path, immutable: bool = False) -> dict:
    p = Path(path)
    facts = file_facts(p)
    conn = connect(p, immutable)
    try:
        tables = _tables(conn)
        if "episodes" in tables:
            body = survey_graph(conn)
        elif "reactions" in tables:
            body = survey_reader(conn)
        else:
            body = {"kind": "unknown", "row_counts": {
                n: conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0]
                for n, v in tables.items() if not v
            }}
        body["changes"] = conn.total_changes
    finally:
        conn.close()
    return {"file": facts, **body}


def sessions(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT session_id, COUNT(*) AS episodes,
               MIN(created_at) AS first, MAX(created_at) AS last
        FROM episodes GROUP BY session_id ORDER BY first, session_id
        """
    ).fetchall()
    return [dict(r) for r in rows]


def read_episodes(
    conn: sqlite3.Connection,
    session: str | None = None,
    source: str | None = None,
    start: int = 0,
    limit: int = 1,
) -> list[dict]:
    """Episodes in (created_at, id) order, whatever columns this schema has."""
    cols = _columns(conn, "episodes")
    fields = [f for f in _EPISODE_FIELDS if f in cols]
    where, params = [], []
    if session is not None:
        where.append("session_id = ?")
        params.append(session)
    if source is not None and "source" in cols:
        where.append("source = ?")
        params.append(source)
    sql = "SELECT " + ", ".join(f'"{f}"' for f in fields) + " FROM episodes"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at, id LIMIT ? OFFSET ?"
    rows = conn.execute(sql, (*params, limit, start)).fetchall()
    return [{"position": start + i, **dict(r)} for i, r in enumerate(rows)]


def read_passages(
    conn: sqlite3.Connection,
    session: str | None = None,
    start: int = 0,
    limit: int = 1,
) -> list[dict]:
    """Reader passage/reaction pairs, session by session in reading order."""
    cols = _columns(conn, "reactions")
    fields = [f for f in ("session_id", "position", "created_at", "passage", "reaction") if f in cols]
    sql = "SELECT " + ", ".join(f'"{f}"' for f in fields) + " FROM reactions"
    params: list = []
    if session is not None:
        sql += " WHERE session_id = ?"
        params.append(session)
    sql += (
        " ORDER BY (SELECT MIN(created_at) FROM reactions r2"
        " WHERE r2.session_id = reactions.session_id), session_id, position"
        " LIMIT ? OFFSET ?"
    )
    rows = conn.execute(sql, (*params, limit, start)).fetchall()
    return [{"index": start + i, **dict(r)} for i, r in enumerate(rows)]


def _print_entries(entries: list[dict], text_fields: tuple[str, ...]) -> None:
    for e in entries:
        meta = {k: v for k, v in e.items() if k not in text_fields and v is not None}
        print("── " + "  ".join(f"{k}={v}" for k, v in meta.items()))
        for f in text_fields:
            if e.get(f) is not None:
                print(f"\n[{f}]\n{e[f]}")
        print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="engram-read-store", description=__doc__.splitlines()[0])
    parser.add_argument("--immutable", action="store_true", help="archived copy; ignores -wal")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("survey", help="hashes, schema versions, counts, date ranges")
    p.add_argument("paths", nargs="+")

    p = sub.add_parser("sessions", help="episode sessions in chronological order")
    p.add_argument("db")

    for name, help_ in (("read", "episodes in chronological order"),
                        ("passages", "reader.db passages and reactions in order")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("db")
        p.add_argument("--session")
        p.add_argument("--start", type=int, default=0)
        p.add_argument("--limit", type=int, default=1)
        if name == "read":
            p.add_argument("--source")

    args = parser.parse_args(argv)
    try:
        if args.command == "survey":
            result = [survey(path, args.immutable) for path in args.paths]
            print(json.dumps(result if len(result) > 1 else result[0], indent=2))
            return 0
        conn = connect(args.db, args.immutable)
        try:
            if args.command == "sessions":
                result = sessions(conn)
            elif args.command == "read":
                result = read_episodes(conn, args.session, args.source, args.start, args.limit)
            else:
                result = read_passages(conn, args.session, args.start, args.limit)
        finally:
            conn.close()
    except (FileNotFoundError, sqlite3.Error) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.json or args.command == "sessions":
        print(json.dumps(result, indent=2))
    elif args.command == "read":
        _print_entries(result, ("content",))
    else:
        _print_entries(result, ("passage", "reaction"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
