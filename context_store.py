"""Instance-local conversation archive, separate from Engram's decaying memories."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid


class StoreConflict(RuntimeError):
    """A client event was reused or a prior execution needs reconciliation."""


class ThreadBusy(StoreConflict):
    """Another runtime currently owns this thread."""


class ArchiveSearchTimeout(sqlite3.OperationalError):
    """A bounded archive search stopped before its ranking was complete."""


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ContextStore:
    PREVIEW_CHARS = 8192
    MAX_EVENT_BYTES = 4_000_000
    MAX_ARTIFACT_BYTES = 16_000_000
    SEARCH_TIMEOUT_SECONDS = 0.05
    SEARCH_TERM_MATCH_LIMIT = 32

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.artifact_dir = self.path.parent / (self.path.stem + "-artifacts")
        self.artifact_dir.mkdir(exist_ok=True, mode=0o700)
        self.lock_dir = self.path.parent / (self.path.stem + "-locks")
        self.lock_dir.mkdir(exist_ok=True, mode=0o700)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            self.conn.close()
            raise StoreConflict(f"Unsupported context schema version {version}")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                thread TEXT NOT NULL, role TEXT NOT NULL, kind TEXT NOT NULL,
                content TEXT NOT NULL, metadata TEXT NOT NULL, turn_id TEXT,
                created REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS events_thread ON events(thread, seq);
            CREATE INDEX IF NOT EXISTS events_thread_kind ON events(thread, kind, seq);
            CREATE VIRTUAL TABLE IF NOT EXISTS event_search USING fts5(
                content, thread UNINDEXED, event_id UNINDEXED, tokenize='unicode61'
            );
            CREATE TABLE IF NOT EXISTS state (
                thread TEXT NOT NULL, key TEXT NOT NULL, content TEXT NOT NULL,
                source_id TEXT NOT NULL REFERENCES events(id), updated REAL NOT NULL,
                PRIMARY KEY(thread, key)
            );
            CREATE TABLE IF NOT EXISTS artifacts (
                thread TEXT NOT NULL, id TEXT NOT NULL, size INTEGER NOT NULL,
                PRIMARY KEY(thread, id)
            );
            CREATE INDEX IF NOT EXISTS artifacts_id ON artifacts(id);
            CREATE TABLE IF NOT EXISTS artifact_gc (id TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS turns (
                id TEXT PRIMARY KEY, thread TEXT NOT NULL, client_id TEXT NOT NULL,
                message_digest TEXT NOT NULL, status TEXT NOT NULL, result TEXT,
                error TEXT, created REAL NOT NULL, UNIQUE(thread, client_id)
            );
            CREATE TABLE IF NOT EXISTS manifests (
                id TEXT PRIMARY KEY, thread TEXT NOT NULL, data TEXT NOT NULL,
                created REAL NOT NULL
            );
            PRAGMA user_version=1;
        """)

    @contextmanager
    def _write(self):
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                raise

    @contextmanager
    def lease(self, thread: str):
        self._check_thread(thread)
        name = hashlib.sha256(thread.encode()).hexdigest()
        with (self.lock_dir / name).open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ThreadBusy("Thread is already processing a turn") from exc
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    @staticmethod
    def _check_thread(thread):
        if not isinstance(thread, str) or not thread or len(thread) > 128:
            raise ValueError("Thread ID must contain 1–128 characters")

    @contextmanager
    def _artifact_io(self):
        # Separate from SQLite: retain this lock across the committed pending
        # journal and the subsequent file/reference transaction. GC uses it too.
        with (self.lock_dir / "artifact-io").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _insert_event(self, thread, role, content, kind, event_id, turn_id, metadata):
        self._check_thread(thread)
        if role not in {"user", "assistant", "tool", "system"}:
            raise ValueError("Invalid archive role")
        if not isinstance(content, str) or len(content.encode()) > self.MAX_EVENT_BYTES:
            raise ValueError("Event exceeds archive byte limit; use a bounded artifact")
        encoded = _json(metadata or {})
        old = self.conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if old:
            if (old["thread"], old["role"], old["content"], old["kind"], old["metadata"]) != (thread, role, content, kind, encoded):
                raise StoreConflict("Event ID already records different content")
            return self._event_row(old)
        self.conn.execute("INSERT INTO events(id,thread,role,kind,content,metadata,turn_id,created) VALUES(?,?,?,?,?,?,?,?)", (event_id, thread, role, kind, content, encoded, turn_id, time.time()))
        if kind in {"message", "correction", "coding_observation", "coding_task"}:
            self.conn.execute("INSERT INTO event_search(content,thread,event_id) VALUES(?,?,?)", (content[:self.PREVIEW_CHARS], thread, event_id))
        return self._event_row(self.conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone())

    @staticmethod
    def _event_row(row):
        if row is None:
            return None
        result = dict(row)
        result["metadata"] = json.loads(result["metadata"])
        result["truncated"] = result.pop("full_length", len(result["content"])) > len(result["content"])
        return result

    def append(self, thread, role, content, *, kind="message", event_id=None, turn_id=None, metadata=None):
        with self._write():
            return self._insert_event(thread, role, content, kind, event_id or str(uuid.uuid4()), turn_id, metadata)

    def event(self, thread, event_id):
        with self._lock:
            return self._event_row(self.conn.execute("SELECT * FROM events WHERE thread=? AND id=?", (thread, event_id)).fetchone())

    def event_page(self, thread, event_id, offset=0, limit=4096):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 4096:
            raise ValueError("Invalid event page")
        with self._lock:
            row = self.conn.execute("SELECT id,role,kind,substr(content,?,?) AS content,length(content) AS length,metadata FROM events WHERE thread=? AND id=?", (offset + 1, limit, thread, event_id)).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "role": row["role"], "kind": row["kind"], "text": row["content"],
                "metadata": json.loads(row["metadata"]), "next_offset": offset + limit if offset + limit < row["length"] else None}

    def latest_event(self, thread, kind):
        """One exact original, independent of the searchable dialogue window."""
        with self._lock:
            return self._event_row(self.conn.execute("SELECT * FROM events WHERE thread=? AND kind=? ORDER BY seq DESC LIMIT 1", (thread, kind)).fetchone())

    def recent_kind(self, thread, kind, limit=8):
        """Bounded previews for task evidence; never load an entire transcript."""
        with self._lock:
            rows = self.conn.execute("SELECT id,seq,thread,role,kind,substr(content,1,?) AS content,length(content) AS full_length,metadata,turn_id,created FROM events WHERE thread=? AND kind=? ORDER BY seq DESC LIMIT ?", (self.PREVIEW_CHARS, thread, kind, max(0, min(int(limit), 32)))).fetchall()
        return [self._event_row(row) for row in reversed(rows)]

    def recent(self, thread, limit=12, *, completed_only=False):
        limit = max(0, min(int(limit), 100))
        completed = " AND (turn_id IS NULL OR EXISTS(SELECT 1 FROM turns t WHERE t.id=events.turn_id AND t.status='completed'))" if completed_only else ""
        with self._lock:
            rows = self.conn.execute("SELECT id,seq,thread,role,kind,substr(content,1,?) AS content,length(content) AS full_length,metadata,turn_id,created FROM events WHERE thread=? AND kind IN ('message','correction')" + completed + " ORDER BY seq DESC LIMIT ?", (self.PREVIEW_CHARS, thread, limit)).fetchall()
        return [self._event_row(row) for row in reversed(rows)]

    def search(self, thread, query, limit=12, *, completed_only=False, kinds=("message", "correction")):
        if not kinds or len(kinds) > 4 or any(k not in {"message", "correction", "coding_observation", "coding_task"} for k in kinds):
            raise ValueError("Invalid searchable event kinds")
        # Quote terms instead of accepting arbitrary FTS operators from source text.
        terms = list(dict.fromkeys(re.findall(r"[^\W_]+", query[:2000], re.UNICODE)))[:16]
        if not terms:
            return []
        completed = " AND (e.turn_id IS NULL OR EXISTS(SELECT 1 FROM turns t WHERE t.id=e.turn_id AND t.status='completed'))" if completed_only else ""
        with self._lock:
            kind_filter = " AND e.kind IN (" + ",".join("?" for _ in kinds) + ")"
            matching = " FROM event_search s JOIN events e ON e.id=s.event_id WHERE event_search MATCH ? AND s.thread=?" + kind_filter + completed
            deadline = time.monotonic() + self.SEARCH_TIMEOUT_SECONDS
            owns_snapshot = not self.conn.in_transaction
            if owns_snapshot:
                self.conn.execute("BEGIN")
            self.conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            try:
                # Classify each term with at most 33 eligible row IDs. Probing
                # in the index's natural order avoids ranking a common term's
                # whole posting list. The same thread/kind/completion filters
                # apply here and to the eventual result query.
                # Preserve the original query for <=512 eligible events, where
                # probing adds work without reducing a large ranking set. This
                # reads at most 513 eligible rows; filtered-out rows may also
                # be visited. The shared deadline guards that scan too.
                small_archive = self.conn.execute("SELECT 1 FROM events e WHERE e.thread=?" + kind_filter + completed + " LIMIT 1 OFFSET 512", (thread, *kinds)).fetchone() is None
                distinctive = list(terms) if small_archive else []
                for term in (() if small_archive else terms):
                    hits = self.conn.execute("SELECT s.rowid" + matching + " LIMIT ?", ('"' + term + '"', thread, *kinds, self.SEARCH_TERM_MATCH_LIMIT + 1)).fetchall()
                    if 0 < len(hits) <= self.SEARCH_TERM_MATCH_LIMIT:
                        distinctive.append(term)
                    if time.monotonic() >= deadline:
                        raise ArchiveSearchTimeout("Archive search deadline exceeded; retrieval is incomplete")
                # At most 16 * 32 eligible matches enter the ranked union.
                # Broad-only queries use recent matches, rather than spending
                # the whole deadline ranking repeated dialogue. This remains
                # a bounded recall sample, not exhaustive relevance ranking.
                match = " OR ".join('"' + term + '"' for term in (distinctive or terms))
                ordering = "bm25(event_search), e.seq DESC" if distinctive else "s.rowid DESC"
                rows = self.conn.execute("SELECT e.id,e.seq,e.thread,e.role,e.kind,substr(e.content,1,?) AS content,length(e.content) AS full_length,e.metadata,e.turn_id,created" + matching + " ORDER BY " + ordering + " LIMIT ?", (self.PREVIEW_CHARS, match, thread, *kinds, max(0, min(int(limit), 100)))).fetchall()
                if time.monotonic() >= deadline:
                    raise ArchiveSearchTimeout("Archive search deadline exceeded; retrieval is incomplete")
            except sqlite3.OperationalError as exc:
                if getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_INTERRUPT:
                    raise ArchiveSearchTimeout("Archive search deadline exceeded; retrieval is incomplete") from exc
                raise
            finally:
                # This connection also serves capture, corrections and other
                # threads; an expired search callback must never leak to them.
                self.conn.set_progress_handler(None, 0)
                if owns_snapshot:
                    self.conn.rollback()
        return [self._event_row(row) for row in rows]

    @staticmethod
    def _validate_state(key, content):
        if not isinstance(key, str) or not key or len(key) > 128 or not isinstance(content, str) or len(content.encode()) > 16_384:
            raise ValueError("Invalid or oversized state entry")

    def _set_state(self, thread, key, content, source_id):
        self._validate_state(key, content)
        source = self.conn.execute("SELECT role FROM events WHERE id=? AND thread=?", (source_id, thread)).fetchone()
        if source is None or source[0] != "user":
            raise StoreConflict("State requires an original user event in this thread")
        self.conn.execute("INSERT INTO state VALUES(?,?,?,?,?) ON CONFLICT(thread,key) DO UPDATE SET content=excluded.content,source_id=excluded.source_id,updated=excluded.updated", (thread, key, content, source_id, time.time()))

    def set_state(self, thread, key, content, source_id):
        with self._write():
            self._set_state(thread, key, content, source_id)

    def record_state(self, thread, key, content):
        self._validate_state(key, content)
        with self._write():
            event = self._insert_event(thread, "user", content, "correction", str(uuid.uuid4()), None, {})
            self._set_state(thread, key, content, event["id"])
            return {"source_id": event["id"], "key": key}

    def state(self, thread):
        with self._lock:
            return [dict(row) for row in self.conn.execute("SELECT * FROM state WHERE thread=? ORDER BY key LIMIT 101", (thread,))]

    def unpin(self, thread, key):
        with self._write():
            self.conn.execute("DELETE FROM state WHERE thread=? AND key=?", (thread, key))

    def put_artifact(self, thread, data: bytes):
        self._check_thread(thread)
        if len(data) > self.MAX_ARTIFACT_BYTES:
            raise ValueError("Artifact exceeds byte limit")
        digest = hashlib.sha256(data).hexdigest()
        target = self.artifact_dir / digest
        with self._artifact_io():
            with self._write():
                self.conn.execute("INSERT OR IGNORE INTO artifact_gc VALUES(?)", (digest,))
            with self._write():
                if not target.exists():
                    temporary = self.artifact_dir / (digest + ".pending")
                    fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(data)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, target)
                self.conn.execute("INSERT OR IGNORE INTO artifacts VALUES(?,?,?)", (thread, digest, len(data)))
                self.conn.execute("DELETE FROM artifact_gc WHERE id=?", (digest,))
        return digest

    def read_artifact(self, thread, artifact_id, offset=0, limit=8192):
        if not isinstance(offset, int) or not isinstance(limit, int) or offset < 0 or not 1 <= limit <= 65536:
            raise ValueError("Artifact page requires offset >= 0 and limit 1–65536")
        with self._lock:
            row = self.conn.execute("SELECT id FROM artifacts WHERE thread=? AND id=?", (thread, artifact_id)).fetchone()
            if row is None:
                raise KeyError("Artifact is unavailable in this thread")
            with (self.artifact_dir / row[0]).open("rb") as handle:
                handle.seek(offset)
                return handle.read(limit)

    def begin_turn(self, thread, client_id, message):
        self._check_thread(thread)
        digest = hashlib.sha256(message.encode()).hexdigest()
        with self._write():
            old = self.conn.execute("SELECT * FROM turns WHERE thread=? AND client_id=?", (thread, client_id)).fetchone()
            if old:
                if old["message_digest"] != digest:
                    raise StoreConflict("Client event ID belongs to a different message")
                if old["status"] != "completed":
                    raise StoreConflict(f"Prior turn is {old['status']}; inspect it before starting a new event")
                result = dict(old)
                result["result"] = json.loads(result["result"])
                return result
            turn_id = str(uuid.uuid4())
            self.conn.execute("INSERT INTO turns(id,thread,client_id,message_digest,status,created) VALUES(?,?,?,?,?,?)", (turn_id, thread, client_id, digest, "running", time.time()))
            self._insert_event(thread, "user", message, "message", turn_id + ":user", turn_id, {})
            return {"id": turn_id, "thread": thread, "status": "running", "result": None}

    def turn(self, turn_id):
        with self._lock:
            row = self.conn.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()
            return dict(row) if row else None

    def finish_turn(self, turn_id, result, assistant_text=None):
        with self._write():
            row = self.conn.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()
            if row is None or row["status"] != "running":
                raise StoreConflict("Turn is not running")
            if assistant_text is not None:
                self._insert_event(row["thread"], "assistant", assistant_text, "message", turn_id + ":assistant", turn_id, {})
            self.conn.execute("UPDATE turns SET status='completed',result=? WHERE id=?", (_json(result), turn_id))

    def fail_turn(self, turn_id, error, status="failed"):
        with self._write():
            self.conn.execute("UPDATE turns SET status=?,error=? WHERE id=? AND status='running'", (status, str(error)[:1000], turn_id))

    def save_manifest(self, thread, data):
        mid = str(uuid.uuid4())
        with self._write():
            self.conn.execute("INSERT INTO manifests VALUES(?,?,?,?)", (mid, thread, _json(data), time.time()))
        return mid

    def manifest(self, thread, manifest_id=None):
        with self._lock:
            if manifest_id:
                row = self.conn.execute("SELECT data FROM manifests WHERE thread=? AND id=?", (thread, manifest_id)).fetchone()
            else:
                row = self.conn.execute("SELECT data FROM manifests WHERE thread=? ORDER BY created DESC LIMIT 1", (thread,)).fetchone()
        return json.loads(row[0]) if row else None

    def forget_thread(self, thread):
        with self.lease(thread):
            with self._write():
                self.conn.execute("INSERT OR IGNORE INTO artifact_gc SELECT id FROM artifacts WHERE thread=?", (thread,))
                for table in ("state", "event_search", "events", "turns", "manifests", "artifacts"):
                    self.conn.execute(f"DELETE FROM {table} WHERE thread=?", (thread,))
            # Unlink only after the reference deletion has committed. A cleanup
            # failure leaves an unreferenced file, never a restored dangling row.
            while self.collect_artifacts():
                pass

    def collect_artifacts(self, limit=256):
        # A durable queue survives failed unlink/crashes; bounded batches avoid
        # scanning the entire archive or holding its write lease for the sweep.
        with self._artifact_io():
            with self._lock:
                pending = [r[0] for r in self.conn.execute("SELECT id FROM artifact_gc LIMIT ?", (max(1, min(int(limit), 256)),))]
            for digest in pending:
                with self._write():
                    if not self.conn.execute("SELECT 1 FROM artifacts WHERE id=? LIMIT 1", (digest,)).fetchone():
                        (self.artifact_dir / digest).unlink(missing_ok=True)
                    (self.artifact_dir / (digest + ".pending")).unlink(missing_ok=True)
                    self.conn.execute("DELETE FROM artifact_gc WHERE id=?", (digest,))
        return len(pending)

    def status(self, thread):
        with self._lock:
            events = self.conn.execute("SELECT count(*) FROM events WHERE thread=?", (thread,)).fetchone()[0]
            turns = [dict(row) for row in self.conn.execute("SELECT id,status,error FROM turns WHERE thread=? ORDER BY created DESC LIMIT 5", (thread,))]
        result = {"thread_id": thread, "events": events, "recent_turns": turns, "archive": str(self.path)}
        progress = self.latest_event(thread, "coding_progress")
        if progress:
            result["coding"] = json.loads(progress["content"])
        return result

    def close(self):
        with self._lock:
            self.conn.close()
