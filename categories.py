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
from datetime import datetime, timezone

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
