"""Local scrypt credentials, revocable sessions and atomic invitations."""
import hashlib
import hmac
import re
import secrets
import sqlite3
from .common import Problem, text, uid, require

def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()

def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)

def public_user(row):
    return {key: row[key] for key in ('id', 'username', 'name', 'is_admin', 'created')}

class Auth:
    def _create_user(self, db, username, name, password, is_admin=False):
        if not isinstance(username, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{1,63}', username):
            raise Problem(400, 'Invalid username')
        text(name, 'name')
        text(password, 'password', 1024)
        if len(password) < 12:
            raise Problem(400, 'Use at least 12 characters for your password')
        salt = secrets.token_bytes(16)
        key = uid()
        try:
            db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?)', (key, username, name, salt, password_hash(password, salt), int(is_admin), self.clock()))
        except sqlite3.IntegrityError:
            raise Problem(409, 'Username unavailable') from None
        return public_user(db.execute('SELECT * FROM users WHERE id=?', (key,)).fetchone())

    def create_user(self, username, name, password, *, is_admin=False):
        """Trusted provisioning only; no public registration route."""
        with self.transaction() as db:
            return self._create_user(db, username, name, password, is_admin)

    def rename_user(self, actor, name):
        text(name, 'name')
        with self.transaction() as db:
            current = require(db.execute('SELECT * FROM users WHERE id=?', (actor,)).fetchone())
            if current['name'] == name:
                return public_user(current)
            db.execute('UPDATE users SET name=? WHERE id=?', (name, actor))
            db.execute(
                'INSERT INTO account_corrections(user_id,old_name,new_name,actor_id,created) VALUES(?,?,?,?,?)',
                (actor, current['name'], name, actor, self.clock()),
            )
            return public_user(db.execute('SELECT * FROM users WHERE id=?', (actor,)).fetchone())

    def account_corrections(self, actor):
        """Return only the signed-in account's real, append-only name changes."""
        with self.transaction() as db:
            require(db.execute('SELECT id FROM users WHERE id=?', (actor,)).fetchone())
            return [dict(row) for row in db.execute(
                'SELECT id,user_id,old_name,new_name,actor_id,created FROM account_corrections WHERE user_id=? ORDER BY id',
                (actor,),
            )]

    def login(self, username, password, source):
        text(username, 'username', 64)
        text(password, 'password', 1024)
        # Commit failed attempts before raising; source budget prevents username rotation.
        failure = None
        result = None
        with self.transaction() as db:
            now = self.clock()
            keys = ['user:' + username, 'source:' + source]
            attempts = [db.execute('SELECT * FROM login_attempts WHERE key=?', (key,)).fetchone() for key in keys]
            if any(row and row['reset'] > now and row['count'] >= limit for row, limit in zip(attempts, [8, 40])):
                failure = Problem(429, 'Too many attempts; try again later')
            else:
                row = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
                candidate = password_hash(password, row['salt'] if row else b'\0' * 16)
                valid = hmac.compare_digest(candidate, row['password_hash'] if row else b'\0' * 32)
                if not valid:
                    for key, attempt in zip(keys, attempts):
                        count = attempt['count'] + 1 if attempt and attempt['reset'] > now else 1
                        reset = attempt['reset'] if attempt and attempt['reset'] > now else now + 300
                        db.execute('INSERT OR REPLACE INTO login_attempts VALUES(?,?,?)', (key, count, reset))
                    failure = Problem(401, 'Invalid username or password')
                else:
                    db.execute('DELETE FROM login_attempts WHERE key=?', (keys[0],))
                    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                    db.execute('INSERT INTO sessions VALUES(?,?,?,?)', (token_hash(token), row['id'], csrf, now + 86400))
                    result = {'user': public_user(row), 'csrf_token': csrf, 'token': token}
        if failure:
            raise failure
        return result

    def session(self, token):
        with self.transaction() as db:
            row = db.execute('SELECT users.*, sessions.csrf FROM sessions JOIN users ON users.id=sessions.user_id WHERE token_hash=? AND expires>?', (token_hash(token or ''), self.clock())).fetchone()
            if not row:
                raise Problem(401, 'Sign in required')
            return {**public_user(row), 'csrf_token': row['csrf']}

    def logout(self, token):
        with self.transaction() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (token_hash(token or ''),))

    def _admin(self, db, actor):
        row = require(db.execute('SELECT is_admin FROM users WHERE id=?', (actor,)).fetchone())
        if not row['is_admin']:
            raise Problem(403, 'Account owner required')

    def accounts(self, actor):
        with self.transaction() as db:
            self._admin(db, actor)
            return [public_user(r) for r in db.execute('SELECT * FROM users ORDER BY created,id')]

    def invite(self, actor, expires_in=86400):
        if type(expires_in) is not int or not 60 <= expires_in <= 604800:
            raise Problem(400, 'Invalid invitation lifetime')
        with self.transaction() as db:
            self._admin(db, actor)
            token = secrets.token_urlsafe(32)
            expires = self.clock() + expires_in
            db.execute('INSERT INTO invitations(token_hash,creator_id,expires) VALUES(?,?,?)', (token_hash(token), actor, expires))
            return {'id': token_hash(token), 'token': token, 'expires': expires}

    def redeem(self, token, username, name, password):
        text(token, 'invitation', 128)
        with self.transaction() as db:
            invite = db.execute('SELECT * FROM invitations WHERE token_hash=? AND used=0 AND expires>?', (token_hash(token), self.clock())).fetchone()
            if not invite:
                raise Problem(400, 'Invitation unavailable')
            user = self._create_user(db, username, name, password)
            db.execute('UPDATE invitations SET used=1 WHERE token_hash=?', (token_hash(token),))
            return user
