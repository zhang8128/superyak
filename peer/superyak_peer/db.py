"""Private SQLite store. Each operation owns a connection and transaction."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from .auth import Auth
from .spaces import Spaces
from .layers import Layers
from .files import Files
from .chats import Chats
from .access_requests import AccessRequests, ACCESS_SCHEMA
from .ships import Ships, SHIP_SCHEMA
from .tickets import Tickets, TICKET_SCHEMA
from .instructions import Instructions
from .inbox import Inbox, INBOX_SCHEMA
from .briefs import Briefs, BRIEF_SCHEMA
from .presence import Presence, PRESENCE_SCHEMA
from .system_author import SystemAuthor, SYSTEM_SCHEMA
from .room_claims import RoomClaims, CLAIM_SCHEMA
from .room_board import RoomBoard, BOARD_SCHEMA
from .breakouts import Breakouts, BREAKOUT_SCHEMA
from .signatures import Signatures, SIGNATURE_SCHEMA
from .grants import Grants, GRANT_SCHEMA
from .moderators import Moderators, MODERATE_SCHEMA
from .members import Members
from .lessons import Lessons, LESSON_SCHEMA
from .imprints import Imprints, IMPRINT_SCHEMA
from .room_cloud import RoomCloud, ROOM_CLOUD_SCHEMA
from .connector import Connector, OAUTH_SCHEMA
from .connector_reads import ConnectorReads, READS_SCHEMA
from .common import encode, Problem
from .peer_store import PeerStore, PEER_SCHEMA
from .dispatch import DispatchGate

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL, salt BLOB NOT NULL, password_hash BLOB NOT NULL, is_admin INTEGER NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS account_corrections(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL REFERENCES users(id), old_name TEXT NOT NULL, new_name TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES users(id), created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), csrf TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts(key TEXT PRIMARY KEY, count INTEGER NOT NULL, reset REAL NOT NULL);
CREATE INDEX IF NOT EXISTS login_attempts_reset ON login_attempts(reset);
CREATE TABLE IF NOT EXISTS login_devices(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires REAL NOT NULL, failures INTEGER NOT NULL DEFAULT 0, failure_reset REAL NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0, attempt_reset REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS invitations(token_hash TEXT PRIMARY KEY, creator_id TEXT NOT NULL REFERENCES users(id), expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS account_activations(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS account_role_changes(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL REFERENCES users(id), actor_id TEXT NOT NULL REFERENCES users(id), old_role TEXT, new_role TEXT NOT NULL, role_version INTEGER NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS spaces(id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL, kind TEXT NOT NULL, version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS space_members(space_id TEXT NOT NULL REFERENCES spaces(id), user_id TEXT NOT NULL REFERENCES users(id), PRIMARY KEY(space_id,user_id));
CREATE TABLE IF NOT EXISTS layers(id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), version INTEGER NOT NULL, resource_version INTEGER NOT NULL DEFAULT 0, draft TEXT NOT NULL, active_revision INTEGER);
CREATE TABLE IF NOT EXISTS layer_revisions(layer_id TEXT NOT NULL REFERENCES layers(id), revision INTEGER NOT NULL, draft_version INTEGER NOT NULL, snapshot TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(layer_id,revision));
CREATE TABLE IF NOT EXISTS files(id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL, media_type TEXT NOT NULL, digest TEXT NOT NULL, size INTEGER NOT NULL, content BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS rooms(id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), title TEXT NOT NULL, epoch INTEGER NOT NULL, linked_room_id TEXT REFERENCES rooms(id));
CREATE TABLE IF NOT EXISTS room_activity(room_id TEXT PRIMARY KEY REFERENCES rooms(id), created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS room_members(room_id TEXT NOT NULL REFERENCES rooms(id), user_id TEXT NOT NULL REFERENCES users(id), PRIMARY KEY(room_id,user_id));
CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY, room_id TEXT NOT NULL REFERENCES rooms(id), author_id TEXT NOT NULL REFERENCES users(id), client_message_id TEXT NOT NULL, body TEXT NOT NULL, epoch INTEGER NOT NULL, created REAL NOT NULL, UNIQUE(room_id,author_id,client_message_id));
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, resource_id TEXT NOT NULL, resource_version INTEGER NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL);
'''

JOURNAL_SIZE_LIMIT = 67108864  # store-wal-mode D2: a checkpointed WAL is cut back to 64 MB
_reading = threading.local()  # store-wal-mode D3: this thread's reading() depth

class Store(PeerStore, Auth, Spaces, Layers, Files, Chats, AccessRequests, Ships, Tickets, Instructions, Inbox, Briefs, Presence, SystemAuthor, RoomClaims, RoomBoard, Breakouts, Signatures, Grants, Moderators, Members, Lessons, Imprints, RoomCloud, Connector, ConnectorReads):
    _busy_until, _monotonic = None, staticmethod(time.monotonic)

    def __init__(self, data_dir: Path, *, clock=time.time, share_link_file=None, signing=True, busy_until=None,
                 monotonic=time.monotonic):
        """`busy_until`, a time on `monotonic`, bounds the lock waits in each transaction (the lessons query passes its
        budget's end): each statement waits at most the time left when its transaction connected, so a transaction
        with several blocking statements can wait a few times that. Without it, SQLite waits its 30 s."""
        self.data_dir = Path(data_dir).absolute()
        self.clock = clock
        self._busy_until, self._monotonic = busy_until, monotonic
        self.share_link_file = Path(share_link_file) if share_link_file else None
        self._check_paths()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.data_dir, 0o700)
        self.db_path = self.data_dir / 'peer.sqlite3'
        self.dispatch_gate = DispatchGate(self.data_dir / 'dispatch.lock')
        fd = os.open(self.db_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        os.chmod(self.db_path, 0o600)
        with self.transaction() as db:
            db.executescript(SCHEMA + PEER_SCHEMA + ACCESS_SCHEMA + SHIP_SCHEMA + TICKET_SCHEMA + INBOX_SCHEMA + BRIEF_SCHEMA + PRESENCE_SCHEMA + SYSTEM_SCHEMA + CLAIM_SCHEMA + BOARD_SCHEMA + BREAKOUT_SCHEMA + SIGNATURE_SCHEMA + GRANT_SCHEMA + MODERATE_SCHEMA + LESSON_SCHEMA + IMPRINT_SCHEMA + ROOM_CLOUD_SCHEMA + OAUTH_SCHEMA + READS_SCHEMA)
        # Additive migration preserves every existing identity and credential.
        with self.transaction() as db:
            columns = {row['name'] for row in db.execute('PRAGMA table_info(users)')}
            for name, default in [('is_super_admin', 0), ('role_version', 1), ('activation_pending', 0)]:
                if name not in columns:
                    db.execute(f'ALTER TABLE users ADD COLUMN {name} INTEGER NOT NULL DEFAULT {default}')
            for name, ddl in [('kind', "TEXT NOT NULL DEFAULT 'person'"), ('owner_id', 'TEXT REFERENCES users(id)')]:
                if name not in columns:
                    db.execute(f'ALTER TABLE users ADD COLUMN {name} {ddl}')
            request_columns = {row['name'] for row in db.execute('PRAGMA table_info(access_requests)')}
            for name in ('share_url', 'share_status'):
                if name not in request_columns:
                    db.execute(f'ALTER TABLE access_requests ADD COLUMN {name} TEXT')
            imprint_columns = {row['name'] for row in db.execute('PRAGMA table_info(imprint_requests)')}
            if 'removal_files' not in imprint_columns:  # store imprints, final review M1: hashes kept before a removal
                db.execute('ALTER TABLE imprint_requests ADD COLUMN removal_files TEXT')
            ticket_columns = {row['name'] for row in db.execute('PRAGMA table_info(tickets)')}
            if 'first_deferred' not in ticket_columns:  # ship-status fixes F3: the deferral a run resolved, on its ticket
                db.execute('ALTER TABLE tickets ADD COLUMN first_deferred REAL')
            device_columns = {row['name'] for row in db.execute('PRAGMA table_info(login_devices)')}
            for name in ('attempts', 'attempt_reset'):  # public route follow-up: a store from a3ade5e6 has the table without them
                if name not in device_columns:
                    db.execute(f'ALTER TABLE login_devices ADD COLUMN {name} {"INTEGER" if name == "attempts" else "REAL"} NOT NULL DEFAULT 0')
            # remote room fields: a received room stored before inbox_received existed gets a time once: the first start that finds it without one, this start's
            db.execute("INSERT OR IGNORE INTO inbox_received SELECT origin, resource_id, recipient, ? FROM inbox "
                       "WHERE kind='room' AND payload IS NOT NULL", (self.clock(),))
            if 'last_error' not in {row['name'] for row in db.execute('PRAGMA table_info(outbox)')}:  # federation pull (spec §7)
                db.execute('ALTER TABLE outbox ADD COLUMN last_error TEXT')
            # federation pull (spec §7, check 3 MF2): pairings made before the upgrade, and stores restored from older copies,
            # get their delivery row at every start, so they keep sending. A card that isn't JSON gets none (plan nit 4).
            db.execute("INSERT OR IGNORE INTO peer_delivery(peer_id, mode, failures) SELECT peer_id, "
                       "COALESCE(json_extract(card, '$.delivery'), 'push'), 0 FROM peers WHERE json_valid(card)")
        self._ensure_system_author()  # after the migration, where users.kind surely exists (spec S11)
        self._ensure_connector_key()  # the remote connector's client-id key (spec revision 4, D18)
        self._backfill_brief_history()  # ship briefs S5: after the schema, at every start
        if signing:  # G4a: the door and the station commands that never sign hold no key, check none and backfill nothing
            self._load_station_identity()  # spec A step 3, G4: a station that can't load its identity doesn't start
            self._backfill_revision_signatures()  # G5: after the schema, at every start
            self._backfill_revocation_signatures()  # spec A step 3, G12: what the restore reconcile revoked

    def _check_paths(self):
        for path in (self.data_dir, *self.data_dir.parents):
            # macOS /var is a system alias; reject symlinked task state itself.
            if path == self.data_dir and path.is_symlink():
                raise ValueError('Symlinked state is not allowed')
        for name in ('peer.sqlite3', 'peer.sqlite3-wal', 'peer.sqlite3-shm', 'peer.sqlite3-journal'):
            if (self.data_dir / name).is_symlink():
                raise ValueError('Symlinked state is not allowed')

    @contextmanager
    def transaction(self, *, wait=None):
        """The one way to write: the dispatch gate, then BEGIN IMMEDIATE. `wait` bounds this call's SQLite lock wait
        (health's 3 s); without it the Store's rule holds (30 s, or `busy_until`). Refused inside reading()."""
        if self.in_reading():
            raise RuntimeError('a write inside reading(): a gate-free snapshot never writes')
        with self.dispatch_gate:
            with self._transaction(wait) as db:
                yield db

    def _wait(self, wait=None):
        if wait is not None:
            return wait
        return 30 if self._busy_until is None else max(0.001, min(30, self._busy_until - self._monotonic()))

    @contextmanager
    def _transaction(self, wait=None):
        self._check_paths()
        db = sqlite3.connect(self.db_path, timeout=self._wait(wait))
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute(f'PRAGMA journal_size_limit={JOURNAL_SIZE_LIMIT}')
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except UnicodeError:
            db.rollback()
            raise Problem(400, 'Text must be valid UTF-8') from None
        except Problem as refused:
            db.commit() if refused.keep else db.rollback()
            raise
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def in_reading(self):
        """Whether this thread is inside reading() now."""
        return getattr(_reading, 'depth', 0) > 0

    @contextmanager
    def reading(self):
        """Store-wal-mode D3: one consistent snapshot that cannot write. In WAL mode it takes neither the dispatch gate
        nor SQLite's write lock, so a pure read never waits for a write and no write waits for it; in any other mode it is
        the gate plus a deferred BEGIN, as safe as a transaction. It refuses, in both modes, a thread that holds the gate
        or is already inside reading(), and transaction() refuses inside it. Never hold it across an await or in a yield
        dependency: its thread-local state and, in rollback mode, the gate belong to the thread that entered it."""
        if self.in_reading():  # first, so a nested reading() says so in both modes (in rollback mode the outer holds the gate)
            raise RuntimeError('reading() inside reading(): one snapshot at a time')
        if self.dispatch_gate.held():
            raise RuntimeError('reading() inside the dispatch gate: a gated caller reads in its own transaction')
        self._check_paths()
        db = sqlite3.connect(self.db_path, timeout=self._wait())
        gated = False
        try:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA foreign_keys=ON')
            db.execute(f'PRAGMA journal_size_limit={JOURNAL_SIZE_LIMIT}')
            if db.execute('PRAGMA journal_mode').fetchone()[0] != 'wal':
                self.dispatch_gate.__enter__()
                gated = True
                db.execute(f'PRAGMA busy_timeout={int(self._wait() * 1000)}')  # the wait counted after the gate
            db.execute('BEGIN')
            _reading.depth = getattr(_reading, 'depth', 0) + 1
            try:
                yield db
            except UnicodeError:
                raise Problem(400, 'Text must be valid UTF-8') from None
            finally:
                _reading.depth -= 1
        finally:
            try:
                if db.in_transaction:
                    db.rollback()
                db.close()
            finally:
                if gated:
                    self.dispatch_gate.__exit__(None, None, None)

    def emit(self, db, kind, resource_id, resource_version, payload=None):
        """Append an event inside the caller's resource transaction."""
        cursor = db.execute('INSERT INTO events(kind,resource_id,resource_version,payload,created) VALUES(?,?,?,?,?)',
                            (kind, resource_id, resource_version, encode(payload or {}), self.clock()))
        return cursor.lastrowid

    def events_since(self, after_id=0, limit=100):
        """Trusted worker API; events are never an unfiltered browser feed."""
        with self.transaction() as db:
            rows = db.execute('SELECT * FROM events WHERE id>? ORDER BY id LIMIT ?', (after_id, min(1000, max(1, limit)))).fetchall()
            return [{**dict(r), 'payload': json.loads(r['payload'])} for r in rows]
