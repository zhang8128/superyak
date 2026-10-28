"""Engram federation — genome sync, inter-instance messaging, instance registry."""

import hashlib
import json
import os
import logging
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import store_identity

logger = logging.getLogger(__name__)


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

    def register(self, name: str, db_path: Path, forked_from: str,
                 instance_id: str | None = None,
                 forked_from_instance_id: str | None = None) -> None:
        entry = {
            "path": str(db_path),
            "forked_from": forked_from,
            "forked_at": _now_iso(),
        }
        # The store's own meta.instance_id is authoritative; these are a
        # convenience for listing, recorded when fork stamped them.
        if instance_id is not None:
            entry["instance_id"] = instance_id
        if forked_from_instance_id is not None:
            entry["forked_from_instance_id"] = forked_from_instance_id
        self._data[name] = entry
        self._save()

    def remove(self, name: str) -> None:
        self._data.pop(name, None)
        self._save()

    def list(self) -> dict:
        return dict(self._data)

    def get(self, name: str) -> dict | None:
        return self._data.get(name)


def sync_genome(genome_path: str, instance_storage, *, ledger=None) -> int:
    """Pull genome-core episodes not yet present in instance. Returns count synced.

    Each synced episode gets a new local id but keeps its provenance:
    ``origin_instance_id`` (the genome's store identity), ``origin_id`` and
    ``origin_created_at``. Episodes synced before provenance existed are
    matched by content hash and have it filled in; nothing else about them
    changes. The genome is only read.

    Note: Synced episodes are inserted without embeddings. The existing
    backfill_vectors step in server.py _init() runs after sync_genome and
    will embed any orphaned episodes (those without vectors).

    With a permissions ``ledger`` each synced episode is recorded as a kept copy of its genome episode before it
    is written (P 7.4, P25), so it carries the source's subjects. An episode whose copy cannot be recorded is not
    written; the next sync tries it again.
    """
    genome_conn = sqlite3.connect(genome_path)
    genome_conn.row_factory = sqlite3.Row

    try:
        if store_identity.is_imprint(genome_conn):
            raise store_identity.ImprintRefused("the genome is an imprint; imprints are never synced from")
        genome_instance_id = store_identity.effective_id(genome_conn)
        genome_rows = genome_conn.execute(
            "SELECT id, content, content_hash, source, created_at "
            "FROM episodes WHERE core >= 2"
        ).fetchall()
    finally:
        genome_conn.close()

    instance_id = instance_storage.instance_identity()["instance_id"] if ledger is not None else None
    synced = 0
    for row in genome_rows:
        origin = {
            "origin_instance_id": genome_instance_id,
            "origin_id": row["id"],
            "origin_created_at": row["created_at"],
        }
        existing = instance_storage.conn.execute(
            "SELECT id, episode_type, origin_id FROM episodes WHERE content_hash = ?",
            (row["content_hash"],)
        ).fetchone()
        if existing:
            if existing["episode_type"] == "genome_sync" and existing["origin_id"] is None:
                instance_storage.set_episode_origin(existing["id"], **origin)
            continue

        local_id = str(uuid.uuid4())
        if ledger is not None:
            try:
                ledger.record_copy(
                    f"mem:{instance_id}/episode/{local_id}", f"mem:{genome_instance_id}/episode/{row['id']}",
                    now=int(time.time()))
            except Exception as error:
                logger.warning("genome episode %s not synced: its copy could not be recorded: %s", row["id"], error)
                continue
        instance_storage.add_episode(
            id=local_id, session_id=None,
            content=row["content"], episode_type="genome_sync",
        )
        instance_storage.mark_core(local_id, tier=2)
        if row["source"]:
            instance_storage.set_episode_source(local_id, row["source"])
        instance_storage.set_episode_origin(local_id, **origin)
        synced += 1

    instance_storage.conn.commit()
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
