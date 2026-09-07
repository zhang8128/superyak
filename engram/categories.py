"""∞-category structure for engram.

Cells at every level: objects (memories), morphisms (applications),
2-morphisms (cross-domain transfers), and up. Composition witnesses
structural similarity rather than enforcing equality.

Schema: one table, one vector table. Level 0 cells reference existing
memories. Higher cells reference lower cells as source/target.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import stat
import struct
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fractions import Fraction
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Callable, Iterable, Iterator, Literal, Mapping

logger = logging.getLogger("engram.categories")

MAX_CATEGORY_EVENT_PAYLOAD_BYTES = 1024 * 1024
MAX_CATEGORY_CONTEXT_BYTES = 256 * 1024
MAX_CATEGORY_CELL_CONTENT_BYTES = 1024 * 1024
MAX_CATEGORY_CELL_PAYLOAD_BYTES = 256 * 1024
MAX_CATEGORY_IDENTIFIER_BYTES = 4096
MAX_CATEGORY_POLICY_VERSION_BYTES = 1024
_SQLITE_WRITE_RESERVATION_BYTES = 24 * 1024
_SQLITE_SIDECAR_GROWTH_BYTES = 64 * 1024
_CATEGORY_VECTOR_SCHEMA_LOGICAL_ROWS = 12
_REWRITE_DISPOSITION_EVENT_KINDS = frozenset(
    {
        "rewrite_proposed",
        "rewrite_committed",
        "rewrite_rejected",
        "rewrite_superseded",
    }
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pack_embedding(embedding: list[float]) -> bytes:
    return struct.pack(f"<{len(embedding)}f", *embedding)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS cells (
    id TEXT PRIMARY KEY,
    level INTEGER NOT NULL DEFAULT 0,
    source_id TEXT,
    target_id TEXT,
    content TEXT NOT NULL,
    context TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    accessed_at TEXT,
    access_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_cells_level ON cells(level);
CREATE INDEX IF NOT EXISTS idx_cells_source ON cells(source_id);
CREATE INDEX IF NOT EXISTS idx_cells_target ON cells(target_id);
"""


class CategoryStore:
    """Storage for ∞-category cells with vector search."""

    def __init__(self, conn: sqlite3.Connection, dimension: int = 768):
        self._conn = conn
        self._conn.row_factory = sqlite3.Row
        self._dim = dimension
        self._ensure_schema()

    def _ensure_schema(self):
        self._conn.executescript(_SCHEMA)
        try:
            self._conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS cell_vectors "
                f"USING vec0(embedding float[{self._dim}])"
            )
        except sqlite3.OperationalError:
            pass
        self._conn.commit()

    def add_cell(
        self,
        content: str,
        level: int = 0,
        source_id: str | None = None,
        target_id: str | None = None,
        context: dict | None = None,
        embedding: list[float] | None = None,
    ) -> str:
        cell_id = str(uuid.uuid4())
        now = _now_iso()
        self._conn.execute(
            "INSERT INTO cells (id, level, source_id, target_id, content, context, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cell_id, level, source_id, target_id, content,
             json.dumps(context or {}), now),
        )
        if embedding:
            rowid = self._conn.execute(
                "SELECT rowid FROM cells WHERE id = ?", (cell_id,)
            ).fetchone()[0]
            self._conn.execute(
                "INSERT INTO cell_vectors (rowid, embedding) VALUES (?, ?)",
                (rowid, _pack_embedding(embedding)),
            )
        self._conn.commit()
        return cell_id

    def compose(
        self,
        f_id: str,
        g_id: str,
        content: str,
        context: dict | None = None,
        embedding: list[float] | None = None,
    ) -> str:
        """Compose two cells. Result level = max(source levels) + 1."""
        f = self.get_cell(f_id)
        g = self.get_cell(g_id)
        if not f or not g:
            raise ValueError("Both cells must exist to compose")
        level = max(f["level"], g["level"]) + 1
        return self.add_cell(
            content=content,
            level=level,
            source_id=f_id,
            target_id=g_id,
            context=context,
            embedding=embedding,
        )

    def get_cell(self, cell_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM cells WHERE id = ?", (cell_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["context"] = json.loads(d["context"]) if d["context"] else {}
        return d

    def touch(self, cell_id: str):
        self._conn.execute(
            "UPDATE cells SET accessed_at = ?, access_count = access_count + 1 "
            "WHERE id = ?",
            (_now_iso(), cell_id),
        )
        self._conn.commit()

    def morphisms_from(self, cell_id: str, level: int | None = None) -> list[dict]:
        if level is not None:
            rows = self._conn.execute(
                "SELECT * FROM cells WHERE source_id = ? AND level = ?",
                (cell_id, level),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM cells WHERE source_id = ?", (cell_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def morphisms_to(self, cell_id: str, level: int | None = None) -> list[dict]:
        if level is not None:
            rows = self._conn.execute(
                "SELECT * FROM cells WHERE target_id = ? AND level = ?",
                (cell_id, level),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM cells WHERE target_id = ?", (cell_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def search(
        self,
        embedding: list[float],
        level: int | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Vector search across cells, optionally filtered by level."""
        rows = self._conn.execute(
            "SELECT rowid, distance FROM cell_vectors "
            "WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
            (_pack_embedding(embedding), limit * 3 if level is not None else limit),
        ).fetchall()

        results = []
        for row in rows:
            cell = self._conn.execute(
                "SELECT * FROM cells WHERE rowid = ?", (row[0],)
            ).fetchone()
            if not cell:
                continue
            if level is not None and cell["level"] != level:
                continue
            d = dict(cell)
            d["context"] = json.loads(d["context"]) if d["context"] else {}
            d["distance"] = row[1]
            results.append(d)
            if len(results) >= limit:
                break
        return results

    def cells_at_level(self, level: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM cells WHERE level = ? ORDER BY created_at DESC",
            (level,),
        ).fetchall()
        return [dict(r) for r in rows]

    def richness(self, cell_id: str) -> int:
        """Count total morphisms (all levels) touching this cell.
        Higher richness = more connected = more worth preserving."""
        count = self._conn.execute(
            "SELECT COUNT(*) FROM cells WHERE source_id = ? OR target_id = ?",
            (cell_id, cell_id),
        ).fetchone()[0]
        return count

    def stats(self) -> dict:
        total = self._conn.execute("SELECT COUNT(*) FROM cells").fetchone()[0]
        by_level = self._conn.execute(
            "SELECT level, COUNT(*) FROM cells GROUP BY level ORDER BY level"
        ).fetchall()
        return {
            "total_cells": total,
            "by_level": {row[0]: row[1] for row in by_level},
        }


@dataclass(frozen=True)
class Boundary:
    """One ordered source or target boundary reference for a cell."""

    side: Literal["source", "target"]
    position: int
    cell_id: str


@dataclass(frozen=True)
class CellDraft:
    """The immutable contents used to create a category cell."""

    id: str
    dimension: int
    content: str
    boundaries: tuple[Boundary, ...] = ()
    context_id: str | None = None
    payload: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WeightVector:
    """An observed, unaggregated valuation of a cell."""

    relevance: float
    evidence: float
    recency: float
    affect: float
    adoption: float
    novelty: float
    cost: float


@dataclass(frozen=True)
class ArchivePressure:
    """The archive's current capacity stage, based on its on-disk footprint."""

    state: Literal["normal", "derived_blocked", "writes_blocked"]
    used_bytes: int
    quota_bytes: int


class CategoryQuotaExceeded(RuntimeError):
    """Raised when an append-only category write would exceed the archive quota."""


class _DerivedArchiveWriteSkipped(RuntimeError):
    """Internal signal used to turn a derived high-water write into an explicit skip."""


class _DerivedWriteConnection:
    """Connection proxy whose commit status is resolved when the context exits."""

    __slots__ = ("_connection", "committed")

    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection
        self.committed = False

    def __getattr__(self, name: str):
        return getattr(self._connection, name)


_EVOLVING_SCHEMA = """
CREATE TABLE IF NOT EXISTS cat_schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cat_events (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cat_contexts (
    id TEXT PRIMARY KEY,
    features_json TEXT NOT NULL UNIQUE,
    content_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cat_cells (
    id TEXT PRIMARY KEY,
    dimension INTEGER NOT NULL CHECK (dimension >= 0),
    content TEXT NOT NULL,
    context_id TEXT REFERENCES cat_contexts(id),
    payload_json TEXT NOT NULL DEFAULT '{}',
    content_hash TEXT NOT NULL,
    created_event_id TEXT REFERENCES cat_events(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cat_boundaries (
    cell_id TEXT NOT NULL REFERENCES cat_cells(id),
    side TEXT NOT NULL CHECK (side IN ('source','target')),
    position INTEGER NOT NULL CHECK (position >= 0),
    boundary_id TEXT NOT NULL REFERENCES cat_cells(id),
    PRIMARY KEY (cell_id, side, position)
);

CREATE TABLE IF NOT EXISTS cat_weight_observations (
    id TEXT PRIMARY KEY,
    cell_id TEXT NOT NULL REFERENCES cat_cells(id),
    context_id TEXT REFERENCES cat_contexts(id),
    relevance REAL NOT NULL CHECK (relevance BETWEEN 0 AND 1),
    evidence REAL NOT NULL CHECK (evidence BETWEEN 0 AND 1),
    recency REAL NOT NULL CHECK (recency BETWEEN 0 AND 1),
    affect REAL NOT NULL CHECK (affect BETWEEN -1 AND 1),
    adoption REAL NOT NULL CHECK (adoption BETWEEN 0 AND 1),
    novelty REAL NOT NULL CHECK (novelty BETWEEN 0 AND 1),
    cost REAL NOT NULL CHECK (cost BETWEEN 0 AND 1),
    evidence_event_id TEXT REFERENCES cat_events(id),
    policy_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cat_rewrites (
    id TEXT PRIMARY KEY,
    context_id TEXT REFERENCES cat_contexts(id),
    created_event_id TEXT REFERENCES cat_events(id),
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cat_pending_rewrites (
    rewrite_id TEXT PRIMARY KEY
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS cat_rewrite_members (
    rewrite_id TEXT NOT NULL REFERENCES cat_rewrites(id),
    role TEXT NOT NULL CHECK (role IN ('input','output','witness','evidence')),
    position INTEGER NOT NULL CHECK (position >= 0),
    cell_id TEXT REFERENCES cat_cells(id),
    external_id TEXT,
    PRIMARY KEY (rewrite_id, role, position),
    CHECK ((cell_id IS NULL) != (external_id IS NULL))
);

CREATE TABLE IF NOT EXISTS cat_epochs (
    id TEXT PRIMARY KEY,
    rewrite_id TEXT REFERENCES cat_rewrites(id),
    created_event_id TEXT REFERENCES cat_events(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cat_epoch_parents (
    epoch_id TEXT NOT NULL REFERENCES cat_epochs(id),
    position INTEGER NOT NULL CHECK (position >= 0),
    parent_id TEXT NOT NULL REFERENCES cat_epochs(id),
    PRIMARY KEY (epoch_id, position)
);

CREATE TABLE IF NOT EXISTS cat_epoch_members (
    epoch_id TEXT NOT NULL REFERENCES cat_epochs(id),
    position INTEGER NOT NULL CHECK (position >= 0),
    cell_id TEXT NOT NULL REFERENCES cat_cells(id),
    PRIMARY KEY (epoch_id, position),
    UNIQUE (epoch_id, cell_id)
);

CREATE TABLE IF NOT EXISTS cat_snapshots (
    id TEXT PRIMARY KEY,
    epoch_id TEXT REFERENCES cat_epochs(id),
    active_cell_ids_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cat_boundaries_boundary ON cat_boundaries(boundary_id);
CREATE INDEX IF NOT EXISTS idx_cat_events_rewrite_disposition
    ON cat_events(json_extract(payload_json, '$.rewrite_id'))
    WHERE kind IN ('rewrite_proposed','rewrite_committed',
                   'rewrite_rejected','rewrite_superseded');
CREATE INDEX IF NOT EXISTS idx_cat_weight_latest
    ON cat_weight_observations(cell_id, context_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cat_rewrite_members_cell ON cat_rewrite_members(cell_id);
CREATE INDEX IF NOT EXISTS idx_cat_epoch_parents_parent ON cat_epoch_parents(parent_id);
CREATE INDEX IF NOT EXISTS idx_cat_epoch_members_cell ON cat_epoch_members(cell_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cat_epochs_rewrite_unique
    ON cat_epochs(rewrite_id) WHERE rewrite_id IS NOT NULL;

CREATE TRIGGER IF NOT EXISTS cat_events_pending_rewrite_proposed
AFTER INSERT ON cat_events
WHEN NEW.kind = 'rewrite_proposed'
 AND CASE WHEN json_valid(NEW.payload_json)
          THEN json_type(NEW.payload_json, '$.rewrite_id')
          ELSE NULL END = 'text'
BEGIN
    INSERT OR IGNORE INTO cat_pending_rewrites (rewrite_id)
    VALUES (json_extract(NEW.payload_json, '$.rewrite_id'));
END;

CREATE TRIGGER IF NOT EXISTS cat_events_pending_rewrite_terminal
AFTER INSERT ON cat_events
WHEN NEW.kind IN ('rewrite_committed','rewrite_rejected','rewrite_superseded')
 AND CASE WHEN json_valid(NEW.payload_json)
          THEN json_type(NEW.payload_json, '$.rewrite_id')
          ELSE NULL END = 'text'
BEGIN
    DELETE FROM cat_pending_rewrites
    WHERE rewrite_id = json_extract(NEW.payload_json, '$.rewrite_id');
END;
"""

_IMMUTABLE_TABLES = (
    "cat_schema_version",
    "cat_events",
    "cat_contexts",
    "cat_cells",
    "cat_boundaries",
    "cat_weight_observations",
    "cat_rewrites",
    "cat_rewrite_members",
    "cat_epochs",
    "cat_epoch_parents",
    "cat_epoch_members",
)

_CATEGORY_VECTOR_DDL = (
    "CREATE VIRTUAL TABLE cat_vectors "
    "USING vec0(cell_id TEXT PRIMARY KEY, embedding float[768])"
)


def _normalized_schema_sql(sql: str) -> str:
    """Compare DDL deterministically without changing quoted SQL literals."""
    result: list[str] = []
    quote: str | None = None
    pending_space = False
    for character in sql:
        if quote is None:
            if character.isspace():
                pending_space = bool(result)
                continue
            if pending_space:
                result.append(" ")
                pending_space = False
            result.append(character if character in "'\"`[" else character.lower())
            if character == "'":
                quote = "'"
            elif character == '"':
                quote = '"'
            elif character == "`":
                quote = "`"
            elif character == "[":
                quote = "]"
        else:
            result.append(character)
            if character == quote:
                quote = None
    return "".join(result).strip()


def _execute_schema_statements(connection: sqlite3.Connection, sql: str) -> None:
    statement = ""
    for line in sql.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            if statement.strip():
                connection.execute(statement)
            statement = ""
    if statement.strip():
        raise ValueError("incomplete schema statement")


def _install_immutability_triggers(connection: sqlite3.Connection) -> None:
    for table in _IMMUTABLE_TABLES:
        _execute_schema_statements(
            connection,
            f"""
            CREATE TRIGGER IF NOT EXISTS {table}_no_update
            BEFORE UPDATE ON {table}
            BEGIN
                SELECT RAISE(ABORT, '{table} is immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS {table}_no_delete
            BEFORE DELETE ON {table}
            BEGIN
                SELECT RAISE(ABORT, '{table} is immutable');
            END;
            """,
        )


def _core_schema_definitions(connection: sqlite3.Connection) -> tuple[tuple[str, str, str], ...]:
    rows = connection.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL"
    ).fetchall()
    return tuple(sorted((row[0], row[1], _normalized_schema_sql(row[2])) for row in rows))


@lru_cache(maxsize=1)
def _expected_core_schema_definitions() -> tuple[tuple[str, str, str], ...]:
    connection = sqlite3.connect(":memory:")
    try:
        _execute_schema_statements(connection, _EVOLVING_SCHEMA)
        _install_immutability_triggers(connection)
        return _core_schema_definitions(connection)
    finally:
        connection.close()


def _is_category_vector_object(name: object, table_name: object) -> bool:
    return any(
        isinstance(candidate, str)
        and (candidate == "cat_vectors" or candidate.startswith("cat_vectors_"))
        for candidate in (name, table_name)
    )


def _vector_schema_definitions(
    connection: sqlite3.Connection,
) -> tuple[tuple[str, str, str, str | None], ...]:
    """Return the complete sqlite-vec object layout, including implicit indexes."""
    rows = tuple(
        connection.execute("SELECT type, name, tbl_name, sql FROM sqlite_master")
    )
    has_vector_object = any(_is_category_vector_object(row[1], row[2]) for row in rows)
    if not has_vector_object:
        return ()
    definitions = (
        (
            str(row[0]),
            str(row[1]),
            str(row[2]),
            _normalized_schema_sql(row[3]) if row[3] is not None else None,
        )
        for row in rows
        if _is_category_vector_object(row[1], row[2]) or row[1] == "sqlite_sequence"
    )
    return tuple(sorted(definitions, key=lambda definition: definition[:3]))


_SUPPORTED_VECTOR_SCHEMA_DEFINITIONS = (
    ("index", "sqlite_autoindex_cat_vectors_info_1", "cat_vectors_info", None),
    ("index", "sqlite_autoindex_cat_vectors_rowids_1", "cat_vectors_rowids", None),
    (
        "index",
        "sqlite_autoindex_cat_vectors_vector_chunks00_1",
        "cat_vectors_vector_chunks00",
        None,
    ),
    (
        "table",
        "cat_vectors",
        "cat_vectors",
        "create virtual table cat_vectors using vec0(cell_id text primary key, "
        "embedding float[768])",
    ),
    (
        "table",
        "cat_vectors_chunks",
        "cat_vectors_chunks",
        'create table "cat_vectors_chunks"(chunk_id integer primary key '
        "autoincrement,size integer not null,validity blob not null,rowids blob not null)",
    ),
    (
        "table",
        "cat_vectors_info",
        "cat_vectors_info",
        'create table "cat_vectors_info" (key text primary key, value any)',
    ),
    (
        "table",
        "cat_vectors_rowids",
        "cat_vectors_rowids",
        'create table "cat_vectors_rowids"(rowid integer primary key '
        "autoincrement,id text unique not null,chunk_id integer,chunk_offset integer)",
    ),
    (
        "table",
        "cat_vectors_vector_chunks00",
        "cat_vectors_vector_chunks00",
        'create table "cat_vectors_vector_chunks00"(rowid primary key,vectors blob not null)',
    ),
    (
        "table",
        "sqlite_sequence",
        "sqlite_sequence",
        "create table sqlite_sequence(name,seq)",
    ),
)


def _expected_vector_schema_definitions() -> tuple[tuple[str, str, str, str | None], ...]:
    """Return the pinned sqlite-vec layout without loading an optional extension."""
    return _SUPPORTED_VECTOR_SCHEMA_DEFINITIONS


def is_supported_category_vector_ddl(sql: object) -> bool:
    """Recognize the pinned optional vector table from sqlite_master text alone."""
    return isinstance(sql, str) and _normalized_schema_sql(sql) == _normalized_schema_sql(
        _CATEGORY_VECTOR_DDL
    )


def _category_vector_schema_state(
    connection: sqlite3.Connection,
) -> Literal["absent", "current", "incoherent"]:
    actual = _vector_schema_definitions(connection)
    if not actual:
        return "absent"
    return "current" if actual == _expected_vector_schema_definitions() else "incoherent"


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _content_hash(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()


@contextmanager
def _staged_epoch_membership(
    connection: sqlite3.Connection,
    epoch_id: str,
    *,
    table_prefix: str,
    max_epochs: int,
    max_members: int,
    check_budget: Callable[[], None],
    resource_error: Callable[[], BaseException],
    load_root: Callable[[str, int, str, str | None], int],
) -> Iterator[tuple[str, int, int]]:
    """Yield one exact target state using last-consumer slot reuse.

    Discovery is iterative and file-backed. Materialization mutates a parent's
    slot only for its final consumer, so a linear history carries one state
    forward instead of copying every member for every epoch.
    """
    suffix = uuid.uuid4().hex
    nodes = f"{table_prefix}_nodes_{suffix}"
    edges = f"{table_prefix}_edges_{suffix}"
    edges_parent = f"{table_prefix}_edges_parent_{suffix}"
    schedule = f"{table_prefix}_schedule_{suffix}"
    work = f"{table_prefix}_work_{suffix}"
    members = f"{table_prefix}_members_{suffix}"
    connection.execute(
        f'CREATE TEMP TABLE "{nodes}" ('
        "epoch_id TEXT PRIMARY KEY, rewrite_id TEXT, created_event_id TEXT, "
        "color INTEGER NOT NULL, remaining_consumers INTEGER NOT NULL DEFAULT 0, "
        "slot_id INTEGER UNIQUE, member_count INTEGER NOT NULL DEFAULT 0"
        ") WITHOUT ROWID"
    )
    connection.execute(
        f'CREATE TEMP TABLE "{edges}" ('
        "child_id TEXT NOT NULL, position INTEGER NOT NULL, parent_id TEXT NOT NULL, "
        "PRIMARY KEY(child_id, position), UNIQUE(child_id, parent_id)"
        ") WITHOUT ROWID"
    )
    connection.execute(
        f'CREATE INDEX "{edges_parent}" ON "{edges}" (parent_id)'
    )
    connection.execute(
        f'CREATE TEMP TABLE "{schedule}" ('
        "ordinal INTEGER PRIMARY KEY, epoch_id TEXT NOT NULL UNIQUE)"
    )
    connection.execute(
        f'CREATE TEMP TABLE "{work}" ('
        "sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
        "epoch_id TEXT NOT NULL, exiting INTEGER NOT NULL)"
    )
    connection.execute(
        f'CREATE TEMP TABLE "{members}" ('
        "slot_id INTEGER NOT NULL, cell_id TEXT NOT NULL, "
        "PRIMARY KEY(slot_id, cell_id)) WITHOUT ROWID"
    )
    try:
        connection.execute(
            f'INSERT INTO temp."{work}" (epoch_id, exiting) VALUES (?, 0)',
            (epoch_id,),
        )
        discovered = 0
        ordinal = 0
        while True:
            check_budget()
            item = connection.execute(
                f'SELECT sequence, epoch_id, exiting FROM temp."{work}" '
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            if item is None:
                break
            connection.execute(
                f'DELETE FROM temp."{work}" WHERE sequence = ?', (item[0],)
            )
            current = str(item[1])
            node = connection.execute(
                f'SELECT color FROM temp."{nodes}" WHERE epoch_id = ?',
                (current,),
            ).fetchone()
            if int(item[2]):
                if node is None or int(node[0]) != 1:
                    continue
                connection.execute(
                    f'UPDATE temp."{nodes}" SET color = 2 WHERE epoch_id = ?',
                    (current,),
                )
                connection.execute(
                    f'INSERT INTO temp."{schedule}" VALUES (?, ?)',
                    (ordinal, current),
                )
                ordinal += 1
                continue
            if node is not None:
                if int(node[0]) == 1:
                    raise ValueError("epoch parents must stay acyclic")
                continue
            if discovered >= max_epochs:
                raise resource_error()
            epoch = connection.execute(
                "SELECT rewrite_id, created_event_id FROM cat_epochs WHERE id = ?",
                (current,),
            ).fetchone()
            if epoch is None:
                raise ValueError("epoch does not exist")
            connection.execute(
                f'INSERT INTO temp."{nodes}" '
                "(epoch_id, rewrite_id, created_event_id, color) VALUES (?, ?, ?, 1)",
                (current, epoch[0], epoch[1]),
            )
            discovered += 1
            connection.execute(
                f'INSERT INTO temp."{work}" (epoch_id, exiting) VALUES (?, 1)',
                (current,),
            )
            parents = tuple(
                (int(row[0]), str(row[1]))
                for row in connection.execute(
                    "SELECT position, parent_id FROM cat_epoch_parents "
                    "WHERE epoch_id = ? ORDER BY position DESC",
                    (current,),
                )
            )
            if len(parents) > 4:
                raise resource_error()
            for position, parent in parents:
                connection.execute(
                    f'INSERT INTO temp."{edges}" VALUES (?, ?, ?)',
                    (current, position, parent),
                )
                connection.execute(
                    f'INSERT INTO temp."{work}" (epoch_id, exiting) VALUES (?, 0)',
                    (parent,),
                )
        connection.execute(
            f'UPDATE temp."{nodes}" SET remaining_consumers = ('
            f'SELECT COUNT(*) FROM temp."{edges}" AS edge '
            f'WHERE edge.parent_id = epoch_id)'
        )

        next_slot = 0
        scheduled = connection.execute(
            f'SELECT epoch_id FROM temp."{schedule}" ORDER BY ordinal'
        )
        for scheduled_row in scheduled:
            check_budget()
            current = str(scheduled_row[0])
            node = connection.execute(
                f'SELECT rewrite_id, created_event_id FROM temp."{nodes}" '
                "WHERE epoch_id = ?",
                (current,),
            ).fetchone()
            parent_rows = tuple(
                connection.execute(
                    f'SELECT edge.parent_id, parent.slot_id, '
                    f'parent.remaining_consumers, parent.member_count '
                    f'FROM temp."{edges}" AS edge '
                    f'JOIN temp."{nodes}" AS parent '
                    f'ON parent.epoch_id = edge.parent_id '
                    f'WHERE edge.child_id = ? ORDER BY edge.position',
                    (current,),
                )
            )
            rewrite_id = node[0]
            reusable = next(
                (row for row in parent_rows if int(row[2]) == 1), None
            )
            if rewrite_id is None:
                if parent_rows:
                    raise ValueError("root epoch cannot have parents")
                slot_id = next_slot
                next_slot += 1
                member_count = load_root(
                    members,
                    slot_id,
                    current,
                    str(node[1]) if node[1] is not None else None,
                )
                if member_count > max_members:
                    raise resource_error()
            else:
                if not parent_rows:
                    raise ValueError("rewrite epoch requires a parent")
                if reusable is not None:
                    slot_id = int(reusable[1])
                    member_count = int(reusable[3])
                else:
                    slot_id = next_slot
                    next_slot += 1
                    member_count = 0
                for parent in parent_rows:
                    if parent is reusable:
                        continue
                    room = max_members - member_count
                    connection.execute(
                        f'INSERT OR IGNORE INTO temp."{members}" (slot_id, cell_id) '
                        f'SELECT ?, source.cell_id FROM temp."{members}" AS source '
                        "WHERE source.slot_id = ? ORDER BY source.cell_id LIMIT ?",
                        (slot_id, int(parent[1]), room + 1),
                    )
                    added = int(connection.execute("SELECT changes()").fetchone()[0])
                    member_count += added
                    if member_count > max_members:
                        raise resource_error()
                    check_budget()
                connection.execute(
                    f'DELETE FROM temp."{members}" WHERE slot_id = ? AND cell_id IN ('
                    "SELECT cell_id FROM cat_rewrite_members "
                    "WHERE rewrite_id = ? AND role = 'input')",
                    (slot_id, str(rewrite_id)),
                )
                member_count -= int(
                    connection.execute("SELECT changes()").fetchone()[0]
                )
                connection.execute(
                    f'INSERT OR IGNORE INTO temp."{members}" (slot_id, cell_id) '
                    "SELECT ?, cell_id FROM cat_rewrite_members "
                    "WHERE rewrite_id = ? AND role = 'output'",
                    (slot_id, str(rewrite_id)),
                )
                member_count += int(
                    connection.execute("SELECT changes()").fetchone()[0]
                )
                if member_count > max_members:
                    raise resource_error()

            if reusable is not None:
                connection.execute(
                    f'UPDATE temp."{nodes}" SET slot_id = NULL, member_count = 0 '
                    "WHERE epoch_id = ?",
                    (str(reusable[0]),),
                )
            connection.execute(
                f'UPDATE temp."{nodes}" SET slot_id = ?, member_count = ? '
                "WHERE epoch_id = ?",
                (slot_id, member_count, current),
            )
            for parent in parent_rows:
                parent_id = str(parent[0])
                connection.execute(
                    f'UPDATE temp."{nodes}" '
                    "SET remaining_consumers = remaining_consumers - 1 "
                    "WHERE epoch_id = ?",
                    (parent_id,),
                )
                remaining = int(
                    connection.execute(
                        f'SELECT remaining_consumers FROM temp."{nodes}" '
                        "WHERE epoch_id = ?",
                        (parent_id,),
                    ).fetchone()[0]
                )
                if remaining == 0 and parent is not reusable:
                    parent_slot = int(parent[1])
                    connection.execute(
                        f'DELETE FROM temp."{members}" WHERE slot_id = ?',
                        (parent_slot,),
                    )
                    connection.execute(
                        f'UPDATE temp."{nodes}" '
                        "SET slot_id = NULL, member_count = 0 WHERE epoch_id = ?",
                        (parent_id,),
                    )
            check_budget()

        target = connection.execute(
            f'SELECT slot_id, member_count FROM temp."{nodes}" WHERE epoch_id = ?',
            (epoch_id,),
        ).fetchone()
        if target is None or target[0] is None:
            raise ValueError("epoch reconstruction did not produce target state")
        yield members, int(target[0]), int(target[1])
    finally:
        for table in (members, work, schedule, edges, nodes):
            connection.execute(f'DROP TABLE IF EXISTS temp."{table}"')


class EvolvingCategoryStore:
    """An isolated, append-only store for evolving category structures."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        quota_bytes: int = 3_000_000_000_000,
        high_watermark_ratio: float = 0.90,
        size_provider: Callable[[Path], int | None] | None = None,
        protected_database_identities: Iterable[
            tuple[str | Path, tuple[int, int] | None]
        ] = (),
    ):
        if connection.in_transaction:
            raise ValueError(
                "cannot initialize EvolvingCategoryStore with an active transaction"
            )
        self._connection = connection
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA temp_store = FILE")
        if self._connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise RuntimeError("EvolvingCategoryStore requires foreign keys to be enabled")
        if size_provider is not None and not callable(size_provider):
            raise TypeError("size_provider must be callable")
        self._quota_bytes = quota_bytes
        self._high_watermark = self._validate_watermark(high_watermark_ratio)
        self._protected_database_identities = tuple(
            (
                Path(path).expanduser().resolve(strict=False),
                identity,
            )
            for path, identity in protected_database_identities
        )
        self._database_path, self._database_identity = self._main_database_identity()
        self.assert_database_isolated()
        self._size_provider = size_provider if size_provider is not None else self._default_size_provider
        self._transaction_reserved_bytes = 0
        self._reservation_tracking = False
        self._ensure_schema()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    @staticmethod
    def _validate_watermark(value: float) -> Fraction | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
        try:
            ratio = Fraction(str(value))
        except (ValueError, ZeroDivisionError):
            return None
        return ratio if 0 <= ratio <= 1 else None

    def _execute_complete_statements(self, sql: str) -> None:
        _execute_schema_statements(self._connection, sql)

    def _has_current_core_schema(self) -> bool:
        """Read-only fingerprint check accepting absent or exact optional vectors."""
        expected = _expected_core_schema_definitions()
        expected_names = {name for _kind, name, _sql in expected}
        try:
            rows = tuple(self._connection.execute(
                "SELECT type, name, sql FROM sqlite_master"
            ))
            if _category_vector_schema_state(self._connection) == "incoherent":
                return False
            for row in rows:
                name = str(row[1])
                if (
                    name.startswith("cat_")
                    and name not in expected_names
                    and not _is_category_vector_object(name, name)
                ):
                    return False
            actual = tuple(sorted(
                (row[0], row[1], _normalized_schema_sql(row[2]))
                for row in rows if row[2] is not None and row[1] in expected_names
            ))
            versions = tuple(
                row[0] for row in self._connection.execute(
                    "SELECT version FROM cat_schema_version ORDER BY version"
                )
            )
        except sqlite3.Error:
            return False
        return actual == expected and versions == (1,)

    def _pending_rewrite_projection_stats(self) -> tuple[int, int]:
        projection = self._connection.execute(
            """
            WITH ranked AS (
                SELECT
                    kind,
                    json_extract(payload_json, '$.rewrite_id') AS rewrite_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY json_extract(payload_json, '$.rewrite_id')
                        ORDER BY rowid DESC
                    ) AS disposition_rank
                FROM cat_events
                WHERE kind IN (
                    'rewrite_proposed', 'rewrite_committed',
                    'rewrite_rejected', 'rewrite_superseded'
                )
                  AND CASE WHEN json_valid(payload_json)
                           THEN json_type(payload_json, '$.rewrite_id')
                           ELSE NULL END = 'text'
            )
            SELECT COUNT(*),
                   COALESCE(SUM(length(CAST(ranked.rewrite_id AS BLOB))), 0)
            FROM ranked
            JOIN cat_rewrites AS rewrite ON rewrite.id = ranked.rewrite_id
            WHERE ranked.disposition_rank = 1
              AND ranked.kind = 'rewrite_proposed'
            """
        ).fetchone()
        return int(projection[0]), int(projection[1])

    def _rebuild_pending_rewrite_projection(self) -> None:
        """Rebuild the mutable startup index during a transactional schema upgrade."""
        self._connection.execute("DELETE FROM cat_pending_rewrites")
        self._connection.execute(
            """
            INSERT INTO cat_pending_rewrites (rewrite_id)
            WITH ranked AS (
                SELECT
                    kind,
                    json_extract(payload_json, '$.rewrite_id') AS rewrite_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY json_extract(payload_json, '$.rewrite_id')
                        ORDER BY rowid DESC
                    ) AS disposition_rank
                FROM cat_events
                WHERE kind IN (
                    'rewrite_proposed', 'rewrite_committed',
                    'rewrite_rejected', 'rewrite_superseded'
                )
                  AND CASE WHEN json_valid(payload_json)
                           THEN json_type(payload_json, '$.rewrite_id')
                           ELSE NULL END = 'text'
            )
            SELECT ranked.rewrite_id
            FROM ranked
            JOIN cat_rewrites AS rewrite ON rewrite.id = ranked.rewrite_id
            WHERE ranked.disposition_rank = 1
              AND ranked.kind = 'rewrite_proposed'
            """
        )

    def _ensure_schema(self) -> None:
        self.assert_database_isolated()
        if self._has_current_core_schema():
            self._provision_optional_vectors()
            return
        expected_names = {
            name for _kind, name, _sql in _expected_core_schema_definitions()
        }
        actual_names = {
            str(row[0])
            for row in self._connection.execute(
                "SELECT name FROM sqlite_master WHERE sql IS NOT NULL"
            )
        }
        missing_schema_rows = len(expected_names - actual_names)
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._transaction_reserved_bytes = self._outstanding_wal_bytes()
            self.assert_database_isolated()
            self._enforce_quota("immutable")
            if _category_vector_schema_state(self._connection) == "incoherent":
                raise RuntimeError("incoherent optional vector schema")
            self._admit_reservation(
                self._write_reservation(
                    row_count=max(1, missing_schema_rows)
                ),
                "immutable",
            )
            self._execute_complete_statements(_EVOLVING_SCHEMA)
            _install_immutability_triggers(self._connection)
            projected_rows, projected_bytes = self._pending_rewrite_projection_stats()
            if projected_rows:
                self._admit_reservation(
                    self._write_reservation_bytes(
                        projected_bytes, row_count=projected_rows
                    ),
                    "immutable",
                )
            self._rebuild_pending_rewrite_projection()
            self._connection.execute(
                "INSERT OR IGNORE INTO cat_schema_version (version, applied_at) VALUES (1, ?)",
                (_now_iso(),),
            )
            if not self._has_current_core_schema():
                raise RuntimeError("category schema is not an exact supported core schema")
            # A fresh database can grow while DDL is staged; reject it before
            # publication when the provider can observe that growth.
            self._enforce_quota("immutable")
            self.assert_database_isolated()
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        finally:
            self._transaction_reserved_bytes = 0
        self._provision_optional_vectors()

    def _provision_optional_vectors(self) -> None:
        """Best-effort derived provisioning; never upgrades a pressured reopen."""
        self.assert_database_isolated()
        vector_state = _category_vector_schema_state(self._connection)
        if vector_state == "current":
            return
        if vector_state == "incoherent":
            raise RuntimeError("incoherent optional vector schema")
        if self.pressure().state != "normal":
            return
        reservation = self._write_reservation(
            row_count=_CATEGORY_VECTOR_SCHEMA_LOGICAL_ROWS
        )
        try:
            with self.derived_transaction(
                reserved_bytes=reservation
            ) as connection:
                if connection is None:
                    return
                vector_state = _category_vector_schema_state(connection)
                if vector_state == "current":
                    return
                if vector_state == "incoherent":
                    raise RuntimeError("incoherent optional vector schema")
                connection.execute("SAVEPOINT cat_optional_vec")
                try:
                    connection.execute(_CATEGORY_VECTOR_DDL)
                except sqlite3.OperationalError as exc:
                    connection.execute("ROLLBACK TO SAVEPOINT cat_optional_vec")
                    if "no such module: vec0" not in str(exc).lower():
                        raise
                    return
                finally:
                    connection.execute("RELEASE SAVEPOINT cat_optional_vec")
                if _category_vector_schema_state(connection) != "current":
                    raise RuntimeError("incoherent optional vector schema")
        except CategoryQuotaExceeded:
            return

    def _main_database_identity(self) -> tuple[Path | None, tuple[int, int] | None]:
        row = self._connection.execute("PRAGMA database_list").fetchone()
        if row is None or not row[2] or row[2] == ":memory:":
            return None, None
        path = Path(str(row[2])).expanduser().resolve(strict=False)
        try:
            metadata = os.stat(path)
        except OSError:
            return path, None
        if not stat.S_ISREG(metadata.st_mode):
            return path, None
        return path, (metadata.st_dev, metadata.st_ino)

    def assert_database_isolated(self) -> None:
        """Reject canonical-path and existing-file aliases to protected stores."""
        database_path, database_identity = self._main_database_identity()
        if database_path is None:
            return
        for protected_path, protected_identity in self._protected_database_identities:
            if database_path == protected_path or (
                database_identity is not None
                and protected_identity is not None
                and database_identity == protected_identity
            ):
                raise ValueError("category v2 path aliases a protected database")
        self._database_path = database_path
        self._database_identity = database_identity

    @staticmethod
    def _regular_file_size(
        path: Path, identity: tuple[int, int] | None = None, *, required: bool = False
    ) -> int | None:
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        nofollow = hasattr(os, "O_NOFOLLOW")
        if nofollow:
            flags |= os.O_NOFOLLOW
        before = None
        if not nofollow:
            try:
                before = os.lstat(path)
            except FileNotFoundError:
                return None if required else 0
            except OSError:
                return None
            if not stat.S_ISREG(before.st_mode):
                return None
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError:
            return None if required else 0
        except OSError:
            return None
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                return None
            if before is not None:
                try:
                    after = os.lstat(path)
                except OSError:
                    return None
                if (
                    not stat.S_ISREG(after.st_mode)
                    or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
                    or (before.st_dev, before.st_ino) != (metadata.st_dev, metadata.st_ino)
                ):
                    return None
            if identity is not None and (metadata.st_dev, metadata.st_ino) != identity:
                return None
            return metadata.st_size
        finally:
            os.close(descriptor)

    def _default_size_provider(self, _path: Path) -> int | None:
        """Measure only this store's original DB file and named SQLite sidecars."""
        if self._database_path is None:
            return 0
        if self._database_identity is None:
            return None
        main_size = self._regular_file_size(
            self._database_path, self._database_identity, required=True
        )
        if main_size is None:
            return None
        total = main_size
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar_size = self._regular_file_size(
                Path(f"{self._database_path}{suffix}")
            )
            if sidecar_size is None:
                return None
            total += sidecar_size
        return total

    def _outstanding_wal_bytes(self) -> int:
        """Return WAL allocation that a commit may also copy into the main file."""
        if self._database_path is None:
            return 0
        wal_size = self._regular_file_size(Path(f"{self._database_path}-wal"))
        return int(wal_size) if wal_size is not None else 0

    def pressure(self) -> ArchivePressure:
        """Return capacity pressure without changing archive state.

        An unavailable or malformed measurement is hard pressure, preventing a
        failed capacity check from being treated as free space.
        """
        quota_is_valid = (
            isinstance(self._quota_bytes, int)
            and not isinstance(self._quota_bytes, bool)
            and self._quota_bytes > 0
        )
        ratio_is_valid = self._high_watermark is not None
        quota = self._quota_bytes if quota_is_valid else 0
        if not quota_is_valid or not ratio_is_valid:
            return ArchivePressure("writes_blocked", quota, quota)
        if self._database_path is None:
            return ArchivePressure("normal", 0, quota)
        try:
            used = self._size_provider(self._database_path)
        except Exception:
            used = None
        if not isinstance(used, int) or isinstance(used, bool) or used < 0:
            return ArchivePressure("writes_blocked", quota, quota)
        if used >= quota:
            return ArchivePressure("writes_blocked", used, quota)
        assert self._high_watermark is not None
        if used * self._high_watermark.denominator >= quota * self._high_watermark.numerator:
            return ArchivePressure("derived_blocked", used, quota)
        return ArchivePressure("normal", used, quota)

    def _enforce_quota(self, quota_class: Literal["immutable", "derived"]) -> None:
        pressure = self.pressure()
        if pressure.state == "writes_blocked":
            raise CategoryQuotaExceeded("category archive quota reached")
        if quota_class == "derived" and pressure.state == "derived_blocked":
            raise _DerivedArchiveWriteSkipped()

    def _admit_reservation(
        self,
        reserved_bytes: int,
        quota_class: Literal["immutable", "derived"],
    ) -> None:
        if type(reserved_bytes) is not int:
            raise TypeError("reserved_bytes must be an integer")
        if reserved_bytes < 0:
            raise ValueError("reserved_bytes must be non-negative")
        pressure = self.pressure()
        if pressure.state == "writes_blocked":
            raise CategoryQuotaExceeded("category archive quota reached")
        projected = pressure.used_bytes + self._transaction_reserved_bytes + reserved_bytes
        if quota_class == "derived":
            if pressure.state == "derived_blocked":
                raise _DerivedArchiveWriteSkipped()
            assert self._high_watermark is not None
            if (
                projected * self._high_watermark.denominator
                >= pressure.quota_bytes * self._high_watermark.numerator
            ):
                raise _DerivedArchiveWriteSkipped()
        if projected >= pressure.quota_bytes:
            raise CategoryQuotaExceeded("category archive quota reservation exceeded")
        self._transaction_reserved_bytes += reserved_bytes

    def _write_reservation_bytes(self, value_bytes: int, *, row_count: int) -> int:
        if type(value_bytes) is not int or value_bytes < 0:
            raise ValueError("value_bytes must be a non-negative integer")
        if type(row_count) is not int or row_count < 0:
            raise ValueError("row_count must be a non-negative integer")
        page_size = int(self._connection.execute("PRAGMA page_size").fetchone()[0])
        page_count = int(self._connection.execute("PRAGMA page_count").fetchone()[0])
        # A logical row can update the table plus three indexes/projections.
        # With only binary fanout, a database of ``page_count`` pages has at
        # most this many b-tree levels.  Rewriting and splitting each level is
        # bounded by two frames plus one root frame.
        btree_height = max(1, (page_count + 1).bit_length() - 1)
        structural_pages = max(16, 4 * (2 * btree_height + 1))
        sqlite_row_overhead = max(
            _SQLITE_WRITE_RESERVATION_BYTES,
            structural_pages * (page_size + 24),
        )
        # Values may be represented in the table and as keys in as many as
        # three indexes/projections.  Count all four copies rather than only
        # the caller's serialized representation.
        return (
            4 * value_bytes
            + row_count * sqlite_row_overhead
            + _SQLITE_SIDECAR_GROWTH_BYTES
        )

    def _write_reservation(self, *values: str | bytes, row_count: int = 1) -> int:
        value_bytes = sum(
            len(value if isinstance(value, bytes) else value.encode("utf-8"))
            for value in values
        )
        return self._write_reservation_bytes(value_bytes, row_count=row_count)

    def reserve_write(
        self,
        *values: str | bytes,
        row_count: int = 1,
        quota_class: Literal["immutable", "derived"] = "immutable",
    ) -> None:
        """Accumulate conservative growth inside the current write transaction."""
        if not self._connection.in_transaction or not self._reservation_tracking:
            raise RuntimeError("write reservation requires a store transaction")
        self._admit_reservation(
            self._write_reservation(*values, row_count=row_count), quota_class
        )

    def reserve_write_bytes(
        self,
        value_bytes: int,
        *,
        row_count: int = 1,
        quota_class: Literal["immutable", "derived"] = "immutable",
    ) -> None:
        """Reserve already-counted persisted bytes without allocating a buffer."""
        if not self._connection.in_transaction or not self._reservation_tracking:
            raise RuntimeError("write reservation requires a store transaction")
        self._admit_reservation(
            self._write_reservation_bytes(value_bytes, row_count=row_count),
            quota_class,
        )

    @staticmethod
    def _bounded_text(value: object, maximum: int, label: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{label} must be a string")
        if len(value.encode("utf-8")) > maximum:
            raise ValueError(f"{label} byte limit exceeded")
        return value

    @classmethod
    def _bounded_json(cls, value: object, maximum: int, label: str) -> str:
        try:
            serialized = _canonical_json(value)
        except (TypeError, ValueError, OverflowError, RecursionError) as exc:
            raise ValueError(f"{label} must be canonical JSON") from exc
        return cls._bounded_text(serialized, maximum, label)

    @contextmanager
    def transaction(
        self,
        *,
        immediate: bool = False,
        quota_class: Literal["immutable", "derived"] = "immutable",
        reserved_bytes: int = 0,
    ) -> Iterator[sqlite3.Connection]:
        """Run quota-protected writes without committing caller-owned work."""
        if quota_class not in ("immutable", "derived"):
            raise ValueError("quota_class must be 'immutable' or 'derived'")
        if type(reserved_bytes) is not int:
            raise TypeError("reserved_bytes must be an integer")
        if reserved_bytes < 0:
            raise ValueError("reserved_bytes must be non-negative")
        if self._connection.in_transaction:
            if not self._reservation_tracking:
                self._reservation_tracking = True
                self._transaction_reserved_bytes = self._outstanding_wal_bytes()
            prior_reservation = self._transaction_reserved_bytes
            savepoint = f"cat_write_{uuid.uuid4().hex}"
            self._connection.execute(f"SAVEPOINT {savepoint}")
            try:
                # This no-row statement obtains SQLite's writer reservation
                # before the size read, without changing caller-owned rows.
                self._connection.execute("DELETE FROM cat_snapshots WHERE 0")
                self._enforce_quota(quota_class)
                self._admit_reservation(reserved_bytes, quota_class)
                yield self._connection
                self._enforce_quota(quota_class)
            except Exception:
                self._transaction_reserved_bytes = prior_reservation
                self._connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                self._connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            else:
                try:
                    self._connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                except Exception:
                    try:
                        self._connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    finally:
                        self._connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                    raise
            return

        # Checking beneath SQLite's writer reservation prevents concurrent
        # writers from both admitting the same stale filesystem measurement.
        self._reservation_tracking = True
        self._transaction_reserved_bytes = 0
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._transaction_reserved_bytes = self._outstanding_wal_bytes()
            self._enforce_quota(quota_class)
            self._admit_reservation(reserved_bytes, quota_class)
            yield self._connection
            self._enforce_quota(quota_class)
        except Exception:
            self._connection.rollback()
            raise
        else:
            try:
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        finally:
            self._transaction_reserved_bytes = 0
            self._reservation_tracking = False

    @contextmanager
    def derived_transaction(
        self, *, reserved_bytes: int = 0
    ) -> Iterator[_DerivedWriteConnection | None]:
        """Yield a tracked connection, or ``None`` for an admission-time skip."""
        write: _DerivedWriteConnection | None = None
        try:
            with self.transaction(
                immediate=True,
                quota_class="derived",
                reserved_bytes=reserved_bytes,
            ) as connection:
                write = _DerivedWriteConnection(connection)
                yield write
        except _DerivedArchiveWriteSkipped:
            if write is None:
                yield None
            return
        assert write is not None
        write.committed = True

    def append_event(
        self, kind: str, payload: Mapping[str, object], *, event_id: str | None = None
    ) -> str:
        identifier = event_id or str(uuid.uuid4())
        identifier = self._bounded_text(
            identifier, MAX_CATEGORY_IDENTIFIER_BYTES, "event identifier"
        )
        kind = self._bounded_text(kind, 1024, "event kind")
        payload_json = self._bounded_json(
            payload, MAX_CATEGORY_EVENT_PAYLOAD_BYTES, "event payload"
        )
        if kind in _REWRITE_DISPOSITION_EVENT_KINDS:
            rewrite_id = payload.get("rewrite_id")
            if isinstance(rewrite_id, str):
                self._bounded_text(
                    rewrite_id,
                    MAX_CATEGORY_IDENTIFIER_BYTES,
                    "rewrite identifier",
                )
        reservation = self._write_reservation(
            identifier,
            kind,
            payload_json,
            row_count=2 if kind in _REWRITE_DISPOSITION_EVENT_KINDS else 1,
        )
        with self.transaction(reserved_bytes=reservation) as connection:
            connection.execute(
                "INSERT INTO cat_events (id, kind, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (identifier, kind, payload_json, _now_iso()),
            )
        return identifier

    def create_context(
        self, features: Mapping[str, object], *, context_id: str | None = None
    ) -> str:
        features_json = self._bounded_json(
            features, MAX_CATEGORY_CONTEXT_BYTES, "context features"
        )
        identifier = context_id or str(uuid.uuid4())
        identifier = self._bounded_text(
            identifier, MAX_CATEGORY_IDENTIFIER_BYTES, "context identifier"
        )
        reservation = self._write_reservation(identifier, features_json)
        with self.transaction(reserved_bytes=reservation) as connection:
            existing = connection.execute(
                "SELECT id FROM cat_contexts WHERE features_json = ?", (features_json,)
            ).fetchone()
            if existing:
                return str(existing["id"])
            connection.execute(
                """
                INSERT INTO cat_contexts (id, features_json, content_hash, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (identifier, features_json, _content_hash(features_json), _now_iso()),
            )
        return identifier

    def create_cell(self, draft: CellDraft, *, created_event_id: str | None = None) -> str:
        self._validate_cell(draft)
        identifier = self._bounded_text(
            draft.id, MAX_CATEGORY_IDENTIFIER_BYTES, "cell identifier"
        )
        content = self._bounded_text(
            draft.content, MAX_CATEGORY_CELL_CONTENT_BYTES, "cell content"
        )
        payload_json = self._bounded_json(
            draft.payload, MAX_CATEGORY_CELL_PAYLOAD_BYTES, "cell payload"
        )
        value_bytes = (
            len(identifier.encode("utf-8")) * (1 + len(draft.boundaries))
            + len(content.encode("utf-8"))
            + len(payload_json.encode("utf-8"))
            + sum(
                len(boundary.cell_id.encode("utf-8"))
                for boundary in draft.boundaries
            )
            + len((draft.context_id or "").encode("utf-8"))
            + len((created_event_id or "").encode("utf-8"))
        )
        reservation = self._write_reservation_bytes(
            value_bytes,
            row_count=1 + len(draft.boundaries),
        )
        with self.transaction(reserved_bytes=reservation) as connection:
            connection.execute(
                """
                INSERT INTO cat_cells
                    (id, dimension, content, context_id, payload_json, content_hash,
                     created_event_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    draft.dimension,
                    content,
                    draft.context_id,
                    payload_json,
                    _content_hash(content),
                    created_event_id,
                    _now_iso(),
                ),
            )
            for boundary in draft.boundaries:
                connection.execute(
                    """
                    INSERT INTO cat_boundaries (cell_id, side, position, boundary_id)
                    VALUES (?, ?, ?, ?)
                    """,
                    (draft.id, boundary.side, boundary.position, boundary.cell_id),
                )
        return draft.id

    def _validate_cell(self, draft: CellDraft) -> None:
        if draft.dimension < 0:
            raise ValueError("cell dimension must be non-negative")
        for boundary in draft.boundaries:
            if boundary.side not in ("source", "target") or boundary.position < 0:
                raise ValueError("cell boundaries require a side and non-negative position")
        if draft.dimension == 0:
            if draft.boundaries:
                raise ValueError("dimension-0 cell cannot have boundaries")
            return
        if draft.dimension != 1:
            return

        sources = [b for b in draft.boundaries if b.side == "source"]
        targets = [b for b in draft.boundaries if b.side == "target"]
        if (
            len(sources) != 1
            or len(targets) != 1
            or sources[0].position != 0
            or targets[0].position != 0
        ):
            raise ValueError("dimension-1 cell requires one source and one target boundary")
        for boundary in (*sources, *targets):
            row = self._connection.execute(
                "SELECT dimension FROM cat_cells WHERE id = ?", (boundary.cell_id,)
            ).fetchone()
            if row is None or row["dimension"] != 0:
                raise ValueError("dimension-1 cell requires zero-cell boundaries")

    def get_cell(self, cell_id: str) -> dict | None:
        row = self._connection.execute(
            "SELECT * FROM cat_cells WHERE id = ?", (cell_id,)
        ).fetchone()
        if row is None:
            return None
        cell = dict(row)
        cell["payload"] = json.loads(cell.pop("payload_json"))
        return cell

    def get_boundaries(
        self, cell_id: str, side: Literal["source", "target"] | None = None
    ) -> list[Boundary]:
        if side is None:
            rows = self._connection.execute(
                """
                SELECT side, position, boundary_id FROM cat_boundaries WHERE cell_id = ?
                ORDER BY CASE side WHEN 'source' THEN 0 ELSE 1 END, position
                """,
                (cell_id,),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT side, position, boundary_id FROM cat_boundaries
                WHERE cell_id = ? AND side = ? ORDER BY position
                """,
                (cell_id, side),
            ).fetchall()
        return [Boundary(row["side"], row["position"], row["boundary_id"]) for row in rows]

    def is_interpretable(self, cell_id: str) -> bool:
        row = self._connection.execute(
            "SELECT dimension FROM cat_cells WHERE id = ?", (cell_id,)
        ).fetchone()
        if row is None:
            return False
        if row["dimension"] in (0, 1):
            return True
        if row["dimension"] != 2:
            return False

        sources = self.get_boundaries(cell_id, "source")
        targets = self.get_boundaries(cell_id, "target")
        if (
            [boundary.position for boundary in sources] != list(range(len(sources)))
            or [boundary.position for boundary in targets] != list(range(len(targets)))
        ):
            return False
        try:
            source_endpoints = self.validate_path(
                boundary.cell_id for boundary in sources
            )
            target_endpoints = self.validate_path(
                boundary.cell_id for boundary in targets
            )
        except ValueError:
            return False
        return source_endpoints == target_endpoints

    def validate_path(self, cell_ids: Iterable[str]) -> tuple[str, str]:
        """Return endpoints for one nonempty composable path of 1-cells."""
        path = tuple(cell_ids)
        if not path:
            raise ValueError("a categorical path must be nonempty")

        endpoints: list[tuple[str, str]] = []
        for cell_id in path:
            row = self._connection.execute(
                "SELECT dimension FROM cat_cells WHERE id = ?", (cell_id,)
            ).fetchone()
            if row is None or row["dimension"] != 1:
                raise ValueError("a categorical path requires dimension-1 members")
            sources = self.get_boundaries(cell_id, "source")
            targets = self.get_boundaries(cell_id, "target")
            if len(sources) != 1 or len(targets) != 1:
                raise ValueError("a categorical path requires bounded dimension-1 members")
            endpoints.append((sources[0].cell_id, targets[0].cell_id))

        if any(left[1] != right[0] for left, right in zip(endpoints, endpoints[1:])):
            raise ValueError("categorical path members are not composable")
        return endpoints[0][0], endpoints[-1][1]

    def observe_weight(
        self,
        cell_id: str,
        context_id: str | None,
        weights: WeightVector,
        *,
        evidence_event_id: str | None = None,
        policy_version: str = "v1",
    ) -> str:
        identifier = str(uuid.uuid4())
        policy_version = self._bounded_text(
            policy_version,
            MAX_CATEGORY_POLICY_VERSION_BYTES,
            "weight policy version",
        )
        reservation = self._write_reservation(
            identifier, cell_id, context_id or "", policy_version
        )
        with self.transaction(reserved_bytes=reservation) as connection:
            connection.execute(
                """
                INSERT INTO cat_weight_observations
                    (id, cell_id, context_id, relevance, evidence, recency, affect,
                     adoption, novelty, cost, evidence_event_id, policy_version, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    cell_id,
                    context_id,
                    weights.relevance,
                    weights.evidence,
                    weights.recency,
                    weights.affect,
                    weights.adoption,
                    weights.novelty,
                    weights.cost,
                    evidence_event_id,
                    policy_version,
                    _now_iso(),
                ),
            )
        return identifier

    def latest_weight(self, cell_id: str, context_id: str | None) -> WeightVector | None:
        row = self._connection.execute(
            """
            SELECT relevance, evidence, recency, affect, adoption, novelty, cost
            FROM cat_weight_observations
            WHERE cell_id = ? AND context_id IS ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """,
            (cell_id, context_id),
        ).fetchone()
        if row is None:
            return None
        return WeightVector(
            row["relevance"],
            row["evidence"],
            row["recency"],
            row["affect"],
            row["adoption"],
            row["novelty"],
            row["cost"],
        )

    def close(self) -> None:
        self._connection.close()
