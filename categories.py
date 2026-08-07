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
import sqlite3
import struct
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Iterator, Literal, Mapping

logger = logging.getLogger("engram.categories")


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

CREATE TABLE IF NOT EXISTS cat_snapshots (
    id TEXT PRIMARY KEY,
    epoch_id TEXT REFERENCES cat_epochs(id),
    active_cell_ids_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cat_boundaries_boundary ON cat_boundaries(boundary_id);
CREATE INDEX IF NOT EXISTS idx_cat_weight_latest
    ON cat_weight_observations(cell_id, context_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cat_rewrite_members_cell ON cat_rewrite_members(cell_id);
CREATE INDEX IF NOT EXISTS idx_cat_epoch_parents_parent ON cat_epoch_parents(parent_id);
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
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _content_hash(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()


class EvolvingCategoryStore:
    """An isolated, append-only store for evolving category structures."""

    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._ensure_schema()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    def _ensure_schema(self) -> None:
        self._connection.executescript(_EVOLVING_SCHEMA)
        for table in _IMMUTABLE_TABLES:
            self._connection.executescript(
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
                """
            )
        try:
            self._connection.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS cat_vectors "
                "USING vec0(cell_id TEXT PRIMARY KEY, embedding float[768])"
            )
        except sqlite3.OperationalError:
            pass
        self._connection.execute(
            "INSERT OR IGNORE INTO cat_schema_version (version, applied_at) VALUES (1, ?)",
            (_now_iso(),),
        )
        self._connection.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run writes atomically without committing an enclosing transaction."""
        if self._connection.in_transaction:
            savepoint = f"cat_write_{uuid.uuid4().hex}"
            self._connection.execute(f"SAVEPOINT {savepoint}")
            try:
                yield self._connection
            except Exception:
                self._connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                self._connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            else:
                self._connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            return

        self._connection.execute("BEGIN")
        try:
            yield self._connection
        except Exception:
            self._connection.rollback()
            raise
        else:
            self._connection.commit()

    def append_event(
        self, kind: str, payload: Mapping[str, object], *, event_id: str | None = None
    ) -> str:
        identifier = event_id or str(uuid.uuid4())
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO cat_events (id, kind, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (identifier, kind, _canonical_json(payload), _now_iso()),
            )
        return identifier

    def create_context(
        self, features: Mapping[str, object], *, context_id: str | None = None
    ) -> str:
        features_json = _canonical_json(features)
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT id FROM cat_contexts WHERE features_json = ?", (features_json,)
            ).fetchone()
            if existing:
                return str(existing["id"])
            identifier = context_id or str(uuid.uuid4())
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
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO cat_cells
                    (id, dimension, content, context_id, payload_json, content_hash,
                     created_event_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft.id,
                    draft.dimension,
                    draft.content,
                    draft.context_id,
                    _canonical_json(draft.payload),
                    _content_hash(draft.content),
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
        return row is not None and row["dimension"] in (0, 1)

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
        with self.transaction() as connection:
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
