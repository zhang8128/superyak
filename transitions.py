"""TransitionGraph — weighted Markov chain primitive.

A standalone module with zero dependencies on prism or engram internals.
Only stdlib + sqlite3.
"""

import hashlib
import sqlite3
from datetime import datetime, timezone
from typing import Optional

WEIGHT_CAP = 10.0


def _node_id(label: str) -> str:
    """SHA-256 hash of label, first 16 hex chars."""
    return hashlib.sha256(label.encode()).hexdigest()[:16]


def _now_iso() -> str:
    """Current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


class TransitionGraph:
    """Weighted directed graph of label transitions backed by SQLite.

    Edges are (from_node, to_node, context) triples. Each edge has a
    count (raw recordings) and a weight (capped, decayable float).

    Supports:
    - Context gating: edges are isolated by context string.
    - Decay: multiply all weights by a rate < 1.0.
    - Pruning: remove edges below a weight threshold.
    - Weight cap: no edge weight exceeds WEIGHT_CAP.
    """

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS nodes (
                id        TEXT PRIMARY KEY,
                label     TEXT NOT NULL UNIQUE,
                level     INTEGER NOT NULL DEFAULT 0,
                components TEXT,
                metadata  TEXT
            );

            CREATE TABLE IF NOT EXISTS transitions (
                id        TEXT PRIMARY KEY,
                from_node TEXT NOT NULL REFERENCES nodes(id),
                to_node   TEXT NOT NULL REFERENCES nodes(id),
                context   TEXT NOT NULL DEFAULT '',
                level     INTEGER NOT NULL DEFAULT 0,
                count     INTEGER NOT NULL DEFAULT 0,
                weight    REAL NOT NULL DEFAULT 0.0,
                last_seen TEXT NOT NULL,
                UNIQUE(from_node, to_node, context)
            );
        """)
        self._conn.commit()

    def register_node(
        self,
        label: str,
        level: int = 0,
        components: Optional[str] = None,
    ) -> str:
        """Register a node by label; return its id. Idempotent."""
        node_id = _node_id(label)
        self._conn.execute(
            """
            INSERT OR IGNORE INTO nodes (id, label, level, components)
            VALUES (?, ?, ?, ?)
            """,
            (node_id, label, level, components),
        )
        self._conn.commit()
        return node_id

    def record(
        self,
        from_label: str,
        to_label: str,
        context: Optional[str] = None,
    ) -> None:
        """Record a transition from from_label to to_label.

        Registers both nodes if needed. Upserts the transition edge,
        incrementing count and weight (capped at WEIGHT_CAP).
        """
        ctx = context or ""
        from_id = self.register_node(from_label)
        to_id = self.register_node(to_label)
        edge_id = _node_id(f"{from_id}:{to_id}:{ctx}")
        now = _now_iso()

        self._conn.execute(
            """
            INSERT INTO transitions (id, from_node, to_node, context, count, weight, last_seen)
            VALUES (?, ?, ?, ?, 1, 1.0, ?)
            ON CONFLICT(from_node, to_node, context) DO UPDATE SET
                count     = count + 1,
                weight    = MIN(weight + 1.0, ?),
                last_seen = excluded.last_seen
            """,
            (edge_id, from_id, to_id, ctx, now, WEIGHT_CAP),
        )
        self._conn.commit()

    def next_weights(
        self,
        from_label: str,
        context: Optional[str] = None,
    ) -> dict:
        """Return {to_label: weight} for edges leaving from_label.

        If context is provided, only edges with that exact context are
        returned. If None, all edges regardless of context are returned.
        """
        from_id = _node_id(from_label)

        if context is not None:
            rows = self._conn.execute(
                """
                SELECT n.label AS to_label, t.weight
                FROM transitions t
                JOIN nodes n ON n.id = t.to_node
                WHERE t.from_node = ? AND t.context = ?
                """,
                (from_id, context),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT n.label AS to_label, t.weight
                FROM transitions t
                JOIN nodes n ON n.id = t.to_node
                WHERE t.from_node = ?
                """,
                (from_id,),
            ).fetchall()

        return {row["to_label"]: row["weight"] for row in rows}

    def decay(self, rate: float = 0.95) -> None:
        """Multiply all transition weights by rate."""
        self._conn.execute("UPDATE transitions SET weight = weight * ?", (rate,))
        self._conn.commit()

    def prune(self, threshold: float = 0.05) -> None:
        """Delete transitions whose weight is below threshold."""
        self._conn.execute(
            "DELETE FROM transitions WHERE weight < ?", (threshold,)
        )
        self._conn.commit()

    def all_transitions(self) -> list:
        """Return all transitions with human-readable labels (for debugging)."""
        rows = self._conn.execute(
            """
            SELECT fn.label AS from_label, tn.label AS to_label,
                   t.context, t.count, t.weight, t.last_seen
            FROM transitions t
            JOIN nodes fn ON fn.id = t.from_node
            JOIN nodes tn ON tn.id = t.to_node
            ORDER BY fn.label, tn.label, t.context
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()
