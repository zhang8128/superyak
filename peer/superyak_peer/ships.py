"""Ships: agent accounts (users.kind='ship') owned by a person, with scoped bearer keys."""
import hmac
import re
import secrets
from .auth import token_hash, public_user
from .common import Problem, require, text, uid

DOCKING_LIFETIME = 600
DOCKING_HOURLY_LIMIT = 20
UNCOLLECTED_KEY_LIFETIME = 3600
SHIP_NAME = re.compile(r'[a-z][a-z0-9-]{1,31}')
CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'

SHIP_SCHEMA = '''
CREATE TABLE IF NOT EXISTS ship_keys(id TEXT PRIMARY KEY, ship_id TEXT NOT NULL REFERENCES users(id), key_hash TEXT UNIQUE NOT NULL, created REAL NOT NULL, last_used REAL, revoked REAL);
CREATE TABLE IF NOT EXISTS dockings(id TEXT PRIMARY KEY, code_hash TEXT UNIQUE NOT NULL, secret_hash TEXT NOT NULL, ship_name TEXT NOT NULL, machine TEXT NOT NULL, status TEXT NOT NULL, owner_id TEXT REFERENCES users(id), ship_id TEXT REFERENCES users(id), key TEXT, created REAL NOT NULL, expires REAL NOT NULL);
'''


class Ships:
    def _new_ship(self, db, username, name, owner_id):
        # Ships never sign in: the random password is discarded and login rejects kind='ship'.
        user = self._create_user(db, username, name, secrets.token_urlsafe(48))
        db.execute("UPDATE users SET kind='ship',owner_id=? WHERE id=?", (owner_id, user['id']))
        return public_user(db.execute('SELECT * FROM users WHERE id=?', (user['id'],)).fetchone())

    def _new_ship_key(self, db, ship_id):
        key = secrets.token_urlsafe(32)
        db.execute('INSERT INTO ship_keys(id,ship_id,key_hash,created) VALUES(?,?,?,?)', (uid(), ship_id, token_hash(key), self.clock()))
        return key

    def create_station_ship(self, username, name):
        """Trusted local CLI only: the station's resident ship has no owner."""
        with self.transaction() as db:
            return self._new_ship(db, username, name, None)

    def issue_ship_key(self, ship_id):
        """Trusted local CLI only. Earlier keys stay valid until revoked."""
        with self.transaction() as db:
            require(db.execute("SELECT id FROM users WHERE id=? AND kind='ship'", (ship_id,)).fetchone())
            return self._new_ship_key(db, ship_id)

    def ship_for_key(self, key):
        if not isinstance(key, str) or not 0 < len(key) <= 128:
            raise Problem(401, 'Invalid ship key')
        with self.transaction() as db:
            row = db.execute(
                "SELECT users.* FROM ship_keys JOIN users ON users.id=ship_keys.ship_id WHERE key_hash=? AND revoked IS NULL AND users.kind='ship'",
                (token_hash(key),),
            ).fetchone()
            if not row:
                raise Problem(401, 'Invalid ship key')
            db.execute('UPDATE ship_keys SET last_used=? WHERE key_hash=?', (self.clock(), token_hash(key)))
            return public_user(row)

    def revoke_presented_key(self, key):
        with self.transaction() as db:
            if not db.execute('UPDATE ship_keys SET revoked=? WHERE key_hash=? AND revoked IS NULL', (self.clock(), token_hash(key or ''))).rowcount:
                raise Problem(401, 'Invalid ship key')
            return {'ok': True}

    def _person(self, db, actor):
        row = require(db.execute('SELECT * FROM users WHERE id=?', (actor,)).fetchone())
        if row['kind'] != 'person' or row['activation_pending']:
            raise Problem(403, 'Only people can do this')
        return row

    def _expire_uncollected(self, db, now):
        # A confirmed key nobody collected within an hour is revoked and forgotten.
        for row in db.execute('SELECT id,key FROM dockings WHERE key IS NOT NULL AND created<?', (now - UNCOLLECTED_KEY_LIFETIME,)).fetchall():
            db.execute('UPDATE ship_keys SET revoked=? WHERE key_hash=? AND revoked IS NULL', (now, token_hash(row['key'])))
            db.execute("UPDATE dockings SET key=NULL,status='expired' WHERE id=?", (row['id'],))

    def start_docking(self, ship_name, machine):
        if not isinstance(ship_name, str) or not SHIP_NAME.fullmatch(ship_name):
            raise Problem(400, 'Ship names are 2-32 lowercase letters, digits or dashes, starting with a letter')
        text(machine, 'machine', 100)
        with self.transaction() as db:
            now = self.clock()
            self._expire_uncollected(db, now)
            if db.execute('SELECT count(*) FROM dockings WHERE created>?', (now - 3600,)).fetchone()[0] >= DOCKING_HOURLY_LIMIT:
                raise Problem(429, 'Too many docking attempts; try again later')
            key, secret = uid(), secrets.token_urlsafe(32)
            code = ''.join(secrets.choice(CODE_ALPHABET) for _ in range(8))
            expires = now + DOCKING_LIFETIME
            db.execute(
                "INSERT INTO dockings(id,code_hash,secret_hash,ship_name,machine,status,created,expires) VALUES(?,?,?,?,?,'waiting',?,?)",
                (key, token_hash(code), token_hash(secret), ship_name, machine, now, expires),
            )
            return {'id': key, 'code': code, 'secret': secret, 'expires': expires}

    def _waiting_docking(self, db, code):
        if not isinstance(code, str) or len(code) > 16:
            raise Problem(404, 'This docking code is unknown, used or expired')
        row = db.execute('SELECT * FROM dockings WHERE code_hash=?', (token_hash(code.strip().upper()),)).fetchone()
        if not row or row['status'] != 'waiting' or row['expires'] <= self.clock():
            raise Problem(404, 'This docking code is unknown, used or expired')
        return row

    def docking_preview(self, actor, code):
        with self.transaction() as db:
            self._person(db, actor)
            row = self._waiting_docking(db, code)
            mine = db.execute("SELECT 1 FROM users WHERE username=? AND kind='ship' AND owner_id=?", (row['ship_name'], actor)).fetchone()
            return {'id': row['id'], 'ship_name': row['ship_name'], 'machine': row['machine'], 'expires': row['expires'], 'redock': bool(mine)}

    def confirm_docking(self, actor, docking_id, code):
        with self.transaction() as db:
            self._person(db, actor)
            row = self._waiting_docking(db, code)
            if row['id'] != docking_id:
                raise Problem(404, 'This docking code is unknown, used or expired')
            ship = db.execute('SELECT * FROM users WHERE username=?', (row['ship_name'],)).fetchone()
            if ship is not None and (ship['kind'] != 'ship' or ship['owner_id'] != actor):
                raise Problem(409, 'That ship name is taken; dock again with another name')
            if ship is None:
                ship_id = self._new_ship(db, row['ship_name'], row['ship_name'].replace('-', ' ').title(), actor)['id']
            else:
                ship_id = ship['id']
                db.execute('UPDATE ship_keys SET revoked=? WHERE ship_id=? AND revoked IS NULL', (self.clock(), ship_id))
            key = self._new_ship_key(db, ship_id)
            db.execute("UPDATE dockings SET status='confirmed',owner_id=?,ship_id=?,key=? WHERE id=?", (actor, ship_id, key, row['id']))
            return public_user(db.execute('SELECT * FROM users WHERE id=?', (ship_id,)).fetchone())

    def docking_status(self, docking_id, secret):
        """Docking script view; the confirmed key is released exactly once."""
        with self.transaction() as db:
            now = self.clock()
            self._expire_uncollected(db, now)
            row = db.execute('SELECT * FROM dockings WHERE id=?', (docking_id,)).fetchone()
            if not row or not isinstance(secret, str) or not hmac.compare_digest(token_hash(secret), row['secret_hash']):
                raise Problem(404, 'Not found')
            result = {'status': 'expired' if row['status'] == 'waiting' and row['expires'] <= now else row['status']}
            if row['key']:
                result |= {'key': row['key'], 'ship': public_user(db.execute('SELECT * FROM users WHERE id=?', (row['ship_id'],)).fetchone())}
                db.execute("UPDATE dockings SET key=NULL,status='collected' WHERE id=?", (docking_id,))
            return result
