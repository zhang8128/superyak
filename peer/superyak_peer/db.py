"""Private SQLite store. Each operation owns a connection and transaction."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
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
from .common import encode, Problem
from .peer_store import PeerStore, PEER_SCHEMA
from .dispatch import DispatchGate

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL, salt BLOB NOT NULL, password_hash BLOB NOT NULL, is_admin INTEGER NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS account_corrections(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL REFERENCES users(id), old_name TEXT NOT NULL, new_name TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES users(id), created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), csrf TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts(key TEXT PRIMARY KEY, count INTEGER NOT NULL, reset REAL NOT NULL);
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

class Store(PeerStore, Auth, Spaces, Layers, Files, Chats, AccessRequests, Ships, Tickets, Instructions, Inbox, Briefs, Presence, SystemAuthor, RoomClaims):
    def __init__(self, data_dir: Path, *, clock=time.time, share_link_file=None):
        self.data_dir = Path(data_dir).absolute()
        self.clock = clock
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
            db.executescript(SCHEMA + PEER_SCHEMA + ACCESS_SCHEMA + SHIP_SCHEMA + TICKET_SCHEMA + INBOX_SCHEMA + BRIEF_SCHEMA + PRESENCE_SCHEMA + SYSTEM_SCHEMA + CLAIM_SCHEMA)
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
        self._ensure_system_author()  # after the migration, where users.kind surely exists (spec S11)

    def _check_paths(self):
        for path in (self.data_dir, *self.data_dir.parents):
            # macOS /var is a system alias; reject symlinked task state itself.
            if path == self.data_dir and path.is_symlink():
                raise ValueError('Symlinked state is not allowed')
        for name in ('peer.sqlite3', 'peer.sqlite3-wal', 'peer.sqlite3-shm', 'peer.sqlite3-journal'):
            if (self.data_dir / name).is_symlink():
                raise ValueError('Symlinked state is not allowed')

    @contextmanager
    def transaction(self):
        with self.dispatch_gate:
            with self._transaction() as db:
                yield db

    @contextmanager
    def _transaction(self):
        self._check_paths()
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except UnicodeError:
            db.rollback()
            raise Problem(400, 'Text must be valid UTF-8') from None
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

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
