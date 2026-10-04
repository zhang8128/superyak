"""Ships: agent accounts (users.kind='ship') owned by a person, with scoped bearer keys."""
import secrets
from .auth import token_hash, public_user
from .common import Problem, require, uid

SHIP_SCHEMA = '''
CREATE TABLE IF NOT EXISTS ship_keys(id TEXT PRIMARY KEY, ship_id TEXT NOT NULL REFERENCES users(id), key_hash TEXT UNIQUE NOT NULL, created REAL NOT NULL, last_used REAL, revoked REAL);
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
