"""Notepad — a traversable working reference graph.

Not memory. Not ambient context. A tool you pick up when you're coding.
Nodes are key-value notes with optional tags. Proximity (same session,
shared tags) is the graph — no explicit edges.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("engram.notepad")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_fts(query: str) -> str:
    """Make a query safe for FTS5 — strip special chars, join as prefix terms."""
    tokens = query.split()
    safe = [t.replace('"', '') for t in tokens if t and not all(c in '+-*"(){}[]^~:' for c in t)]
    safe = [t for t in safe if t]
    if not safe:
        return ""
    return " ".join(f'"{t}"' for t in safe)


class Notepad:
    """Key-value notes with FTS and co-session proximity."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self._ensure_schema()

    def _ensure_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS notes (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                tags JSON,
                session_id TEXT,
                accessed_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT DEFAULT 'open',
                depends_on TEXT,
                due TEXT
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
                key, value, tags,
                content=notes, content_rowid=rowid
            );

            CREATE TRIGGER IF NOT EXISTS notes_fts_insert AFTER INSERT ON notes BEGIN
                INSERT INTO notes_fts(rowid, key, value, tags)
                VALUES (new.rowid, new.key, new.value, new.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS notes_fts_delete AFTER DELETE ON notes BEGIN
                INSERT INTO notes_fts(notes_fts, rowid, key, value, tags)
                VALUES ('delete', old.rowid, old.key, old.value, old.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS notes_fts_update AFTER UPDATE ON notes BEGIN
                INSERT INTO notes_fts(notes_fts, rowid, key, value, tags)
                VALUES ('delete', old.rowid, old.key, old.value, old.tags);
                INSERT INTO notes_fts(rowid, key, value, tags)
                VALUES (new.rowid, new.key, new.value, new.tags);
            END;
        """)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")

        # Planner extension — add status, depends_on, due if missing
        try:
            self.conn.execute("SELECT status FROM notes LIMIT 0")
        except sqlite3.OperationalError:
            self.conn.execute("ALTER TABLE notes ADD COLUMN status TEXT DEFAULT 'open'")
            self.conn.execute("ALTER TABLE notes ADD COLUMN depends_on TEXT")
            self.conn.execute("ALTER TABLE notes ADD COLUMN due TEXT")
            self.conn.commit()

    def jot(self, key: str, value: str, tags: list[str] | None = None,
            session_id: str | None = None, status: str = "open",
            depends_on: str | None = None, due: str | None = None) -> dict:
        """Write or update a note."""
        now = _now_iso()
        tags_json = json.dumps(tags) if tags else None
        existing = self.conn.execute(
            "SELECT rowid FROM notes WHERE key = ?", (key,)
        ).fetchone()
        if existing:
            self.conn.execute(
                "UPDATE notes SET value = ?, tags = ?, session_id = ?, updated_at = ?, "
                "status = ?, depends_on = ?, due = ? "
                "WHERE key = ?",
                (value, tags_json, session_id, now, status, depends_on, due, key),
            )
        else:
            self.conn.execute(
                "INSERT INTO notes (key, value, tags, session_id, created_at, updated_at, "
                "status, depends_on, due) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (key, value, tags_json, session_id, now, now, status, depends_on, due),
            )
        self.conn.commit()
        return {"key": key, "value": value, "tags": tags, "status": status}

    def look(self, query: str, limit: int = 10, session_id: str | None = None) -> list[dict]:
        """Search notes by key, value, or tags. Returns matches + co-session neighbors."""
        results: dict[str, dict] = {}  # key -> note dict, preserves order

        # FTS search
        safe_query = _sanitize_fts(query)
        if safe_query:
            rows = self.conn.execute(
                "SELECT n.* FROM notes_fts f JOIN notes n ON f.rowid = n.rowid "
                "WHERE notes_fts MATCH ? ORDER BY bm25(notes_fts) LIMIT ?",
                (safe_query, limit),
            ).fetchall()
            for r in rows:
                note = dict(r)
                note["tags"] = json.loads(note["tags"]) if note["tags"] else []
                note["match"] = "direct"
                results[note["key"]] = note
                self._bump_access(note["key"])

        # Fallback: substring match on key if FTS found nothing
        if not results:
            rows = self.conn.execute(
                "SELECT * FROM notes WHERE key LIKE ? OR value LIKE ? "
                "ORDER BY accessed_count DESC LIMIT ?",
                (f"%{query}%", f"%{query}%", limit),
            ).fetchall()
            for r in rows:
                note = dict(r)
                note["tags"] = json.loads(note["tags"]) if note["tags"] else []
                note["match"] = "substring"
                results[note["key"]] = note
                self._bump_access(note["key"])

        # Co-session neighbors: notes jotted in the same session as any match
        neighbor_sessions = {
            n["session_id"] for n in results.values()
            if n.get("session_id")
        }
        if neighbor_sessions:
            placeholders = ", ".join("?" * len(neighbor_sessions))
            rows = self.conn.execute(
                f"SELECT * FROM notes WHERE session_id IN ({placeholders}) "
                "ORDER BY updated_at DESC LIMIT ?",
                (*neighbor_sessions, limit),
            ).fetchall()
            for r in rows:
                note = dict(r)
                if note["key"] not in results:
                    note["tags"] = json.loads(note["tags"]) if note["tags"] else []
                    note["match"] = "nearby"
                    results[note["key"]] = note

        return list(results.values())[:limit]

    def erase(self, key: str) -> bool:
        """Remove a note."""
        result = self.conn.execute("DELETE FROM notes WHERE key = ?", (key,))
        self.conn.commit()
        return result.rowcount > 0

    def _bump_access(self, key: str):
        self.conn.execute(
            "UPDATE notes SET accessed_count = accessed_count + 1 WHERE key = ?",
            (key,),
        )
        self.conn.commit()

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]

    def open_items(self, tag: str | None = None) -> list[dict]:
        """All notes with status 'open', ordered by due date (nulls last)."""
        if tag:
            rows = self.conn.execute(
                "SELECT * FROM notes WHERE status = 'open' AND tags LIKE ? "
                "ORDER BY CASE WHEN due IS NULL THEN 1 ELSE 0 END, due",
                (f'%"{tag}"%',),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM notes WHERE status = 'open' "
                "ORDER BY CASE WHEN due IS NULL THEN 1 ELSE 0 END, due",
            ).fetchall()
        return [self._note_dict(r) for r in rows]

    def deferred_items(self, tag: str | None = None) -> list[dict]:
        """All notes with status 'deferred'."""
        if tag:
            rows = self.conn.execute(
                "SELECT * FROM notes WHERE status = 'deferred' AND tags LIKE ? "
                "ORDER BY updated_at DESC",
                (f'%"{tag}"%',),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM notes WHERE status = 'deferred' ORDER BY updated_at DESC",
            ).fetchall()
        return [self._note_dict(r) for r in rows]

    def defer(self, key: str, reason: str | None = None) -> bool:
        """Set note status to deferred, optionally append reason."""
        now = _now_iso()
        if reason:
            self.conn.execute(
                "UPDATE notes SET status = 'deferred', "
                "value = value || '\n\nDeferred: ' || ?, updated_at = ? WHERE key = ?",
                (reason, now, key),
            )
        else:
            self.conn.execute(
                "UPDATE notes SET status = 'deferred', updated_at = ? WHERE key = ?",
                (now, key),
            )
        self.conn.commit()
        return self.conn.total_changes > 0

    def resolve(self, key: str) -> bool:
        """Set note status to done."""
        now = _now_iso()
        self.conn.execute(
            "UPDATE notes SET status = 'done', updated_at = ? WHERE key = ?",
            (now, key),
        )
        self.conn.commit()
        return self.conn.total_changes > 0

    def _note_dict(self, row) -> dict:
        """Convert a row to a note dict with parsed tags."""
        note = dict(row)
        note["tags"] = json.loads(note["tags"]) if note["tags"] else []
        return note

    def close(self):
        self.conn.close()
