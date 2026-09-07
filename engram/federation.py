"""Engram federation — genome sync, inter-instance messaging, instance registry."""

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SignalBus:
    """Append-only message queue backed by a shared SQLite database."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        # Always use DELETE journal — this db is shared across Docker bind
        # mounts where WAL silently breaks (shm mapping fails without error).
        self.conn.execute("PRAGMA journal_mode=DELETE")
        self.conn.execute("PRAGMA busy_timeout=10000")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._create_schema()

    def _create_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                from_instance TEXT NOT NULL,
                to_instance TEXT,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                in_reply_to TEXT,
                content_hash TEXT,
                seen_by TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_to ON messages(to_instance);
            CREATE INDEX IF NOT EXISTS idx_messages_type ON messages(type);
            CREATE INDEX IF NOT EXISTS idx_messages_reply ON messages(in_reply_to);
        """)
        self.conn.execute("PRAGMA journal_mode=DELETE")
        self.conn.execute("PRAGMA busy_timeout=10000")
        self.conn.execute("PRAGMA synchronous=NORMAL")

    def send(self, from_instance: str, to_instance: str | None,
             msg_type: str, content: str, in_reply_to: str | None = None) -> str:
        """Send a message. to_instance=None for broadcast. Returns message id."""
        msg_id = str(uuid.uuid4())
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        self.conn.execute(
            "INSERT INTO messages (id, from_instance, to_instance, type, content, "
            "in_reply_to, content_hash, seen_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, '{}', ?)",
            (msg_id, from_instance, to_instance, msg_type, content,
             in_reply_to, content_hash, _now_iso()),
        )
        self.conn.commit()
        return msg_id

    def inbox(self, instance: str) -> list[dict]:
        """Get unseen messages for this instance (directed or broadcast).
        Excludes messages from self (broadcasts shouldn't echo back)."""
        rows = self.conn.execute(
            "SELECT * FROM messages "
            "WHERE (to_instance = ? OR to_instance IS NULL) "
            "AND from_instance != ? "
            "AND seen_by NOT LIKE ? "
            "ORDER BY created_at",
            (instance, instance, f'%"{instance}"%'),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_seen(self, message_id: str, instance: str) -> None:
        """Mark a message as seen by an instance."""
        row = self.conn.execute(
            "SELECT seen_by FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
        if not row:
            return
        seen = json.loads(row["seen_by"])
        seen[instance] = _now_iso()
        self.conn.execute(
            "UPDATE messages SET seen_by = ? WHERE id = ?",
            (json.dumps(seen), message_id),
        )
        self.conn.commit()

    def archive_old(self, retention_days: int = 30) -> int:
        """Delete old fully-seen messages past retention period."""
        cursor = self.conn.execute(
            "DELETE FROM messages WHERE created_at < datetime('now', '-' || ? || ' days') "
            "AND seen_by != '{}'",
            (retention_days,),
        )
        self.conn.commit()
        return cursor.rowcount

    def close(self):
        self.conn.close()


class InstanceRegistry:
    """Manages ~/.engram/instances.json with atomic writes."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {}

    def _save(self):
        """Atomic write — temp file + rename."""
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        tmp.rename(self.path)

    def register(self, name: str, db_path: Path, forked_from: str) -> None:
        self._data[name] = {
            "path": str(db_path),
            "forked_from": forked_from,
            "forked_at": _now_iso(),
        }
        self._save()

    def remove(self, name: str) -> None:
        self._data.pop(name, None)
        self._save()

    def list(self) -> dict:
        return dict(self._data)

    def get(self, name: str) -> dict | None:
        return self._data.get(name)


def sync_genome(genome_path: str, instance_storage) -> int:
    """Pull genome-core episodes not yet present in instance. Returns count synced.

    Note: Synced episodes are inserted without embeddings. The existing
    backfill_vectors step in server.py _init() runs after sync_genome and
    will embed any orphaned episodes (those without vectors).
    """
    genome_conn = sqlite3.connect(genome_path)
    genome_conn.row_factory = sqlite3.Row

    genome_rows = genome_conn.execute(
        "SELECT id, content, content_hash, source, created_at "
        "FROM episodes WHERE core >= 2"
    ).fetchall()

    synced = 0
    for row in genome_rows:
        existing = instance_storage.conn.execute(
            "SELECT 1 FROM episodes WHERE content_hash = ?",
            (row["content_hash"],)
        ).fetchone()
        if existing:
            continue

        local_id = str(uuid.uuid4())
        instance_storage.add_episode(
            id=local_id, session_id=None,
            content=row["content"], episode_type="genome_sync",
        )
        instance_storage.mark_core(local_id, tier=2)
        if row["source"]:
            instance_storage.set_episode_source(local_id, row["source"])
        synced += 1

    instance_storage.conn.commit()
    genome_conn.close()
    return synced


def process_inbox(bus: SignalBus, instance_name: str, storage) -> int:
    """Process unseen messages for this instance. Returns count processed."""
    messages = bus.inbox(instance_name)
    processed = 0

    for msg in messages:
        ep_id = str(uuid.uuid4())
        source_tag = f"signal/{msg['from_instance']}"
        content = f"[{msg['type']}] {msg['content']}"

        storage.add_episode(
            id=ep_id, session_id=None,
            content=content, episode_type="signal",
        )
        storage.set_episode_source(ep_id, source_tag)
        bus.mark_seen(msg["id"], instance_name)
        processed += 1

    storage.conn.commit()
    return processed
