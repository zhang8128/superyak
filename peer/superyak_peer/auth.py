"""Local scrypt credentials, revocable sessions and atomic invitations."""
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
from .common import Problem, text, uid, require

def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()

def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)

# Public route spec 3, the holds: (limit, window in seconds). A pair is a username from one source; a device is a
# browser's known-device token, whose failures count against it instead of holds 1-3.
PAIR_HOLD, SOURCE_HOLD, USER_HOLD, DEVICE_HOLD = (8, 300), (40, 300), (30, 3600), (8, 300)
DEVICE_LIFETIME = 180 * 86400
DEVICES_PER_USER = 20


def login_source(host, public):
    """Public route spec 3: the bucket a sign-in's failures count in. A public source is its IPv6 /64 or its full
    IPv4 address; a tailnet source is its full address, so tailnet nodes never share one. IPv4-mapped addresses are
    unmapped first. A source that isn't an IP address is public and its own bucket."""
    try:
        address = ipaddress.ip_address(host)
    except (TypeError, ValueError):
        return str(host)
    if address.version == 6 and address.ipv4_mapped:
        address = address.ipv4_mapped
    if public and address.version == 6:
        return str(ipaddress.IPv6Network((int(address) >> 64 << 64, 64)))
    return str(address)


def attempts_key(*parts):
    """A login_attempts key: a JSON array such as ["user-source", source, username], unambiguous for any username."""
    return json.dumps(parts)


def public_user(row):
    return {key: row[key] for key in ('id', 'username', 'name', 'is_admin', 'is_super_admin', 'role_version', 'activation_pending', 'created', 'kind', 'owner_id')}


def account_role(row):
    return 'super_admin' if row['is_super_admin'] else 'admin' if row['is_admin'] else 'participant'


def validate_password(password):
    text(password, 'password', 1024)
    if len(password) < 12:
        raise Problem(400, 'Use at least 12 characters for your password')

class Auth:
    def _create_user(self, db, username, name, password, is_admin=False):
        if not isinstance(username, str) or len(username) > 254 or not (
            re.fullmatch(r'[a-z0-9][a-z0-9_.-]{1,63}', username)
            or re.fullmatch(r'[a-z0-9][a-z0-9._+\-]{0,63}@[a-z0-9][a-z0-9.\-]*\.[a-z]{2,63}', username)
        ):
            raise Problem(400, 'Invalid username')
        text(name, 'name')
        validate_password(password)
        salt = secrets.token_bytes(16)
        key = uid()
        try:
            db.execute('INSERT INTO users(id,username,name,salt,password_hash,is_admin,created) VALUES(?,?,?,?,?,?,?)', (key, username, name, salt, password_hash(password, salt), int(is_admin), self.clock()))
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

    def _known_device(self, db, device, username, now):
        """The device row for a superyak_device token that is unexpired and belongs to username, or None: a cookie for
        another user, an expired one or a made-up one exempts nothing."""
        if not isinstance(device, str) or not 0 < len(device) <= 128 or not isinstance(username, str):
            return None
        return db.execute('SELECT login_devices.* FROM login_devices JOIN users ON users.id=login_devices.user_id '
                          'WHERE token_hash=? AND expires>? AND users.username=?', (token_hash(device), now, username)).fetchone()

    def device_is_valid(self, device, username):
        """Public route spec 3: whether a superyak_device token is valid for username, read without writing. It picks
        the known browsers' sign-in lane; Store.login checks again in its own transaction."""
        with self.transaction() as db:
            return self._known_device(db, device, username, self.clock()) is not None

    def _device_signed_in(self, db, user_id, device, now):
        """After a success: the presented token's row, kept and extended (its failures reset), or a new token's row.
        Expired rows go, and a user keeps at most DEVICES_PER_USER, the oldest going first. Returns the token."""
        if device is not None and db.execute('UPDATE login_devices SET expires=?, failures=0, failure_reset=0 WHERE token_hash=?',
                                             (now + DEVICE_LIFETIME, token_hash(device))).rowcount:
            return device
        device = secrets.token_urlsafe(32)
        db.execute('DELETE FROM login_devices WHERE expires<=?', (now,))
        db.execute('INSERT INTO login_devices(token_hash,user_id,expires) VALUES(?,?,?)', (token_hash(device), user_id, now + DEVICE_LIFETIME))
        db.execute('DELETE FROM login_devices WHERE user_id=? AND token_hash NOT IN '
                   '(SELECT token_hash FROM login_devices WHERE user_id=? ORDER BY expires DESC LIMIT ?)', (user_id, user_id, DEVICES_PER_USER))
        return device

    def login(self, username, password, source, *, public=True, device=None):
        """Public route spec 3, reserve first. Step 1 deletes expired counters, then refuses a held attempt (429,
        without hashing) or counts it in every applicable counter, which reserves it. Step 2 hashes outside any
        transaction, the dummy hash for an unknown name, so a 401 takes as long either way. Step 3 re-reads the user,
        since an activation can change the hash in between: a failure keeps the reservation as the counted failure,
        a success deletes the pair's counter and gives the others back. The answers are today's: 401 for a wrong name
        or password, 429 when held, the same for unknown and known names.
        `device` is the browser's superyak_device cookie. One valid for username exempts it from holds 1-3: its
        failures count against its own token instead. A success returns the token to set, the same one extended or a
        new one."""
        text(username, 'username', 254)
        text(password, 'password', 1024)
        bucket = login_source(source, public)
        holds = {attempts_key('user-source', bucket, username): PAIR_HOLD, attempts_key('source', bucket): SOURCE_HOLD}
        if public:  # hold 3 counts and holds public sign-ins only
            holds[attempts_key('user', username)] = USER_HOLD
        held, reserved = False, {}
        with self.transaction() as db:
            now = self.clock()
            db.execute('DELETE FROM login_attempts WHERE reset<=?', (now,))
            known = self._known_device(db, device, username, now)
            if known is not None:
                failures = known['failures'] if known['failure_reset'] > now else 0
                held = failures >= DEVICE_HOLD[0]
                if not held:
                    holds, reset = {}, known['failure_reset'] if known['failure_reset'] > now else now + DEVICE_HOLD[1]
                    db.execute('UPDATE login_devices SET failures=?, failure_reset=? WHERE token_hash=?', (failures + 1, reset, known['token_hash']))
            rows = {key: db.execute('SELECT count,reset FROM login_attempts WHERE key=?', (key,)).fetchone() for key in holds}
            if held or any(rows[key] and rows[key]['count'] >= limit for key, (limit, _) in holds.items()):
                held = True
            else:
                for key, (_, window) in holds.items():
                    count, reserved[key] = (rows[key]['count'] + 1, rows[key]['reset']) if rows[key] else (1, now + window)
                    db.execute('INSERT OR REPLACE INTO login_attempts VALUES(?,?,?)', (key, count, reserved[key]))
                user = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        if held:  # committed: the expired rows stay deleted
            raise Problem(429, 'Too many attempts; try again later')
        salt, stored = (user['salt'], user['password_hash']) if user else (b'\0' * 16, b'\0' * 32)
        matches = hmac.compare_digest(password_hash(password, salt), stored)
        result = None
        with self.transaction() as db:
            current = db.execute('SELECT * FROM users WHERE id=?', (user['id'],)).fetchone() if user else None
            if (matches and current and current['salt'] == salt and current['password_hash'] == stored
                    and not current['activation_pending'] and current['kind'] == 'person'):
                keys = list(reserved)  # the pair's first; none for a known browser, which reserved on its token only
                if keys:
                    db.execute('DELETE FROM login_attempts WHERE key=?', (keys[0],))
                for key in keys[1:]:  # given back only within the window it was reserved in, and never below zero
                    db.execute('UPDATE login_attempts SET count=max(count-1,0) WHERE key=? AND reset=?', (key, reserved[key]))
                if not public:  # recovery: a tailnet sign-in clears the username's public hold
                    db.execute('DELETE FROM login_attempts WHERE key=?', (attempts_key('user', username),))
                now, token, csrf = self.clock(), secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                db.execute('INSERT INTO sessions VALUES(?,?,?,?)', (token_hash(token), current['id'], csrf, now + 86400))
                result = {'user': public_user(current), 'csrf_token': csrf, 'token': token,
                          'device': self._device_signed_in(db, current['id'], device if known is not None else None, now)}
        if result is None:
            raise Problem(401, 'Invalid username or password')
        return result

    def session(self, token):
        with self.transaction() as db:
            row = db.execute('SELECT users.*, sessions.csrf FROM sessions JOIN users ON users.id=sessions.user_id WHERE token_hash=? AND expires>?', (token_hash(token or ''), self.clock())).fetchone()
            if not row or row['activation_pending'] or row['kind'] != 'person':
                raise Problem(401, 'Sign in required')
            return {**public_user(row), 'csrf_token': row['csrf']}

    def session_is_valid(self, token):
        """Public route spec 2: the lookup `session` does, answered True or False. It writes nothing; the route's own
        check still runs afterwards."""
        if not isinstance(token, str):
            return False
        with self.transaction() as db:
            row = db.execute('SELECT users.activation_pending, users.kind FROM sessions JOIN users ON users.id=sessions.user_id WHERE token_hash=? AND expires>?', (token_hash(token), self.clock())).fetchone()
        return row is not None and not row['activation_pending'] and row['kind'] == 'person'

    def logout(self, token):
        with self.transaction() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (token_hash(token or ''),))

    def _admin(self, db, actor):
        row = require(db.execute('SELECT is_admin,activation_pending FROM users WHERE id=?', (actor,)).fetchone())
        if not row['is_admin'] or row['activation_pending']:
            raise Problem(403, 'Admin required')

    def _super_admin(self, db, actor):
        row = require(db.execute('SELECT is_super_admin,activation_pending FROM users WHERE id=?', (actor,)).fetchone())
        if not row['is_super_admin'] or row['activation_pending']:
            raise Problem(403, 'Super admin required')

    def bootstrap_super_admin(self, username, name, activation_file, *, renew_activation=False):
        """Trusted local CLI only. Reserve the first super admin and a private claim."""
        path = Path(activation_file)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'w') as stream, self.transaction() as db:
                existing = db.execute('SELECT * FROM users WHERE is_super_admin=1').fetchall()
                if renew_activation:
                    if len(existing) != 1 or not existing[0]['activation_pending'] or existing[0]['username'] != username or existing[0]['name'] != name:
                        raise Problem(409, 'Renewal requires the same pending first super admin')
                    user = public_user(existing[0])
                    db.execute('UPDATE account_activations SET used=1 WHERE user_id=?', (user['id'],))
                else:
                    if existing:
                        raise Problem(409, 'A super admin already exists; ask them to grant rights or renew their pending activation')
                    user = self._create_user(db, username, name, secrets.token_urlsafe(48), True)
                    db.execute('UPDATE users SET is_super_admin=1,activation_pending=1 WHERE id=?', (user['id'],))
                    db.execute('INSERT INTO account_role_changes(user_id,actor_id,old_role,new_role,role_version,created) VALUES(?,?,NULL,?,?,?)', (user['id'], user['id'], 'super_admin', 1, self.clock()))
                token, expires = secrets.token_urlsafe(32), self.clock() + 604800
                db.execute('INSERT INTO account_activations(token_hash,user_id,expires) VALUES(?,?,?)', (token_hash(token), user['id'], expires))
                json.dump({'user_id': user['id'], 'username': username, 'name': name, 'token': token, 'expires': expires}, stream, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
                result = public_user(db.execute('SELECT * FROM users WHERE id=?', (user['id'],)).fetchone())
            return result
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    def change_account_role(self, actor, user_id, role, expected_version):
        if role not in ('participant', 'admin', 'super_admin') or type(expected_version) is not int or expected_version < 1:
            raise Problem(400, 'Choose a valid role and saved version')
        with self.transaction() as db:
            self._super_admin(db, actor)
            current = require(db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone())
            if current['kind'] != 'person':
                raise Problem(400, 'Ships cannot hold account roles')
            if current['role_version'] != expected_version:
                raise Problem(409, 'Account rights changed; refresh and review them again')
            if current['activation_pending']:
                raise Problem(409, 'This account must finish activation first')
            if role == 'super_admin' and (self.data_dir / 'demo-marker.json').exists() and current['username'] in {'patient', 'family', 'doctor', 'organizer'}:
                raise Problem(400, 'Fictional demo accounts cannot be super admins')
            old_role = account_role(current)
            if old_role == role:
                return public_user(current)
            if old_role == 'super_admin' and role != 'super_admin':
                count = db.execute('SELECT count(*) FROM users WHERE is_super_admin=1 AND activation_pending=0').fetchone()[0]
                if count <= 1:
                    raise Problem(409, 'Keep at least one active super admin')
            version = expected_version + 1
            db.execute('UPDATE users SET is_admin=?,is_super_admin=?,role_version=? WHERE id=?', (int(role != 'participant'), int(role == 'super_admin'), version, user_id))
            if role == 'participant':
                db.execute('UPDATE invitations SET used=1 WHERE creator_id=? AND used=0', (user_id,))
            db.execute('INSERT INTO account_role_changes(user_id,actor_id,old_role,new_role,role_version,created) VALUES(?,?,?,?,?,?)', (user_id, actor, old_role, role, version, self.clock()))
            return public_user(db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone())

    def account_role_changes(self, actor):
        with self.transaction() as db:
            self._super_admin(db, actor)
            return [dict(row) for row in db.execute('SELECT * FROM account_role_changes ORDER BY id DESC LIMIT 100')]

    def accounts(self, actor):
        with self.transaction() as db:
            self._admin(db, actor)
            return [public_user(r) for r in db.execute("SELECT * FROM users WHERE kind='person' ORDER BY created,id")]

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
            activation = db.execute('SELECT * FROM account_activations WHERE token_hash=? AND used=0 AND expires>?', (token_hash(token), self.clock())).fetchone()
            if activation:
                current = require(db.execute('SELECT * FROM users WHERE id=?', (activation['user_id'],)).fetchone())
                if not current['activation_pending'] or username != current['username'] or name != current['name']:
                    raise Problem(400, 'Use the name and username on your activation invitation')
                validate_password(password)
                salt = secrets.token_bytes(16)
                db.execute('UPDATE users SET salt=?,password_hash=?,activation_pending=0 WHERE id=?', (salt, password_hash(password, salt), current['id']))
                db.execute('UPDATE account_activations SET used=1 WHERE token_hash=?', (token_hash(token),))
                return public_user(db.execute('SELECT * FROM users WHERE id=?', (current['id'],)).fetchone())
            invite = db.execute('SELECT * FROM invitations WHERE token_hash=? AND used=0 AND expires>?', (token_hash(token), self.clock())).fetchone()
            if not invite:
                raise Problem(400, 'Invitation unavailable')
            user = self._create_user(db, username, name, password)
            db.execute('UPDATE invitations SET used=1 WHERE token_hash=?', (token_hash(token),))
            return user
