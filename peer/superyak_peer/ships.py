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
POSTS_PER_MINUTE = 30
MENTION = re.compile(r'(?<![\w@])@([a-z0-9][a-z0-9_.-]{1,63})', re.IGNORECASE)
# A name shown as code, in double quotes or on a quoted line is talked about, not addressed. Each span
# stops at its own opening mark too, so unclosed marks cannot make one message cost quadratic time.
NOT_ADDRESSED = re.compile(r'```[\s\S]*?(?:```|\Z)|`[^`\n]*`|"[^"\n]*"|“[^“”\n]*”|^[ \t]*>[^\n]*', re.MULTILINE)
# A ship key is secrets.token_urlsafe(32): 43 URL-safe characters. Every such token standing on its own is a candidate,
# so a key is caught however it is quoted (JSON, a Bearer header, a URL parameter).
KEY_TOKEN = re.compile(r'(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])')

SHIP_SCHEMA = '''
CREATE TABLE IF NOT EXISTS ship_keys(id TEXT PRIMARY KEY, ship_id TEXT NOT NULL REFERENCES users(id), key_hash TEXT UNIQUE NOT NULL, created REAL NOT NULL, last_used REAL, revoked REAL);
CREATE TABLE IF NOT EXISTS dockings(id TEXT PRIMARY KEY, code_hash TEXT UNIQUE NOT NULL, secret_hash TEXT NOT NULL, ship_name TEXT NOT NULL, machine TEXT NOT NULL, status TEXT NOT NULL, owner_id TEXT REFERENCES users(id), ship_id TEXT REFERENCES users(id), key TEXT, created REAL NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS mentions(seq INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT NOT NULL REFERENCES messages(id), room_id TEXT NOT NULL REFERENCES rooms(id), user_id TEXT NOT NULL REFERENCES users(id), UNIQUE(message_id,user_id));
'''


def safe_line(value, limit=80):
    """Text from outside the station (an anonymous access-request name, a person's display name, a docking
    machine) as one short display line. Odo posts station notices in Ops, and a posted '@serenity' would start
    a run on that ship's machine, so no '@' survives; control characters and newlines cannot start a new line."""
    value = ''.join(c if c.isprintable() else ' ' for c in str(value))
    return ' '.join(value.split()).replace('@', '(at)')[:limit].rstrip()


class Ships:
    def _new_ship(self, db, username, name, owner_id):
        # Ships never sign in: the random password is discarded and login rejects kind='ship'.
        user = self._create_user(db, username, name, secrets.token_urlsafe(48))
        db.execute("UPDATE users SET kind='ship',owner_id=? WHERE id=?", (owner_id, user['id']))
        return public_user(db.execute('SELECT * FROM users WHERE id=?', (user['id'],)).fetchone())

    def _live_ship_key_in(self, db, body):
        """True when body holds a token that is a live ship key. Uses the caller's db and opens no transaction."""
        candidates = {token_hash(m.group(0)) for m in KEY_TOKEN.finditer(body)} if isinstance(body, str) else set()
        if not candidates:
            return False
        return bool(candidates & {row['key_hash'] for row in db.execute('SELECT key_hash FROM ship_keys WHERE revoked IS NULL')})

    def _refuse_live_ship_keys(self, body, what='message'):
        """A room is history that many readers keep, so a message carrying a live ship key is refused before anything
        is written or sent to another peer. The refusal never repeats the key."""
        if not (isinstance(body, str) and KEY_TOKEN.search(body)):
            return
        with self.transaction() as db:
            live = self._live_ship_key_in(db, body)
        if live:
            done = 'saved' if what == 'brief' else 'posted'
            raise Problem(422, f'This {what} contains a live ship key, so it was not {done}. Treat that key as exposed: '
                               'its ship should revoke it and dock again.')

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
            return self._confirm_docking_row(db, actor, row)

    def _confirm_docking_row(self, db, actor, row):
        """Shared by the browser confirmation and the station host's trusted CLI."""
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

    def station_pending(self):
        """Trusted local operator only: waiting dockings and pending access requests."""
        with self.transaction() as db:
            now = self.clock()
            dockings = [{'kind': 'docking', **dict(r)} for r in db.execute(
                "SELECT id,ship_name,machine,created,expires FROM dockings WHERE status='waiting' AND expires>? ORDER BY created", (now,))]
            requests = [{'kind': 'access', **dict(r)} for r in db.execute(
                "SELECT id,name,contact,note,created,expires FROM access_requests WHERE status='pending' AND expires>? ORDER BY created", (now,))]
            return dockings + requests

    def _operator(self, db, username):
        person = db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
        if person is None:
            raise Problem(404, f'No account named {username}')
        self._person(db, person['id'])
        return person['id']

    def _current_rooms(self, db, actor):
        return db.execute('SELECT id,title FROM rooms WHERE owner_id=? AND id NOT IN (SELECT linked_room_id FROM rooms WHERE linked_room_id IS NOT NULL) ORDER BY title,id', (actor,)).fetchall()

    def _wormhole_id(self, db):
        ship = db.execute("SELECT id FROM users WHERE username='wormhole' AND kind='ship'").fetchone()
        return ship['id'] if ship else None

    def station_rooms(self, username):
        """Trusted local operator only: the current rooms this person owns, with member usernames and whether
        the wormhole ship is in them. A room replaced by a linked one (added members) is not current."""
        with self.transaction() as db:
            actor, wormhole = self._operator(db, username), self._wormhole_id(db)
            rooms = []
            for room in self._current_rooms(db, actor):
                members = [r[0] for r in db.execute('SELECT users.username FROM room_members JOIN users ON users.id=room_members.user_id WHERE room_id=? ORDER BY users.username', (room['id'],))]
                bridged = wormhole is not None and db.execute('SELECT 1 FROM room_members WHERE room_id=? AND user_id=?', (room['id'], wormhole)).fetchone() is not None
                rooms.append({'id': room['id'], 'title': room['title'], 'members': members, 'bridged': bridged})
            return rooms

    def _earlier_bridged(self, db, actor, room, wormhole):
        """Rooms earlier in this room's linked chain, owned by the same person, that still have the wormhole ship:
        a replaced room keeps its members, so once the current room loses Wormhole the bridge would take it as current."""
        found, seen, key = [], set(), room['linked_room_id']
        while key and key not in seen:
            seen.add(key)
            row = db.execute('SELECT owner_id,linked_room_id FROM rooms WHERE id=?', (key,)).fetchone()
            if row is None:
                break
            if row['owner_id'] == actor and db.execute('SELECT 1 FROM room_members WHERE room_id=? AND user_id=?', (key, wormhole)).fetchone():
                found.append(key)
            key = row['linked_room_id']
        return found

    def station_bridge(self, username, prefix, bridge):
        """Trusted local operator only: add the wormhole ship to (or remove it from) a current room its owner
        names by a short id, through the station's own rules: adding members makes a new linked room. Unbridging
        also removes it from the earlier rooms that room replaced.
        Returns (room, changed); room is the new room after a bridge, the same room after an unbridge."""
        if not isinstance(prefix, str) or len(prefix.strip()) < 4:
            raise Problem(400, 'Give at least 4 characters of the short id')
        prefix = prefix.strip().lower()
        with self.transaction() as db:
            actor = self._operator(db, username)
            wormhole = self._wormhole_id(db)
            if wormhole is None:
                raise Problem(404, 'There is no wormhole ship on the station; create it first (create-ship --username wormhole)')
            matches = [r['id'] for r in self._current_rooms(db, actor) if r['id'].startswith(prefix)]
            if not matches:
                raise Problem(404, f'No room you own starts with {prefix}')
            if len(matches) > 1:
                raise Problem(409, f'{prefix} matches more than one room; give more characters')
            room = self._room(db, actor, matches[0])
            brief, revision = self._room_brief(db, room['id'])
            carry = revision if brief else None  # bridging is the same room continuing, so its brief comes along
            earlier = [] if bridge else self._earlier_bridged(db, actor, room, wormhole)
        if (wormhole in room['member_ids']) == bridge and not earlier:
            return room, False
        if bridge:
            try:
                new = self.add_participants(actor, room['id'], [wormhole], carry)
            except Problem as exc:
                if exc.status == 409 and carry is not None:  # the brief was saved between the read and the carry
                    raise Problem(409, 'The room brief changed while bridging; run station-bridge again') from exc
                raise
            return {**new, 'brief_carried': carry is not None}, True  # the operator tells Andy whether it came along
        for key in earlier:  # the earlier rooms first: if this stops halfway, the current room still shows bridged
            self.remove_participant(actor, key, wormhole)
        if wormhole in room['member_ids']:
            room = self.remove_participant(actor, room['id'], wormhole)
        return room, True

    def station_decide(self, username, prefix, approve):
        """Trusted local operator only: approve or refuse one pending item by a short id,
        acting as the named person. Returns (item, result); never returns keys or tokens."""
        if not isinstance(prefix, str) or len(prefix.strip()) < 4:
            raise Problem(400, 'Give at least 4 characters of the short id')
        prefix = prefix.strip().lower()
        matches = [item for item in self.station_pending() if item['id'].startswith(prefix)]
        if not matches:
            raise Problem(404, f'Nothing waiting starts with {prefix}')
        if len(matches) > 1:
            raise Problem(409, f'{prefix} matches more than one waiting item; give more characters')
        item = matches[0]
        with self.transaction() as db:
            actor = self._operator(db, username)
        if item['kind'] == 'access':
            return item, self.decide_access_request(actor, item['id'], approve)
        with self.transaction() as db:
            row = db.execute("SELECT * FROM dockings WHERE id=? AND status='waiting' AND expires>?", (item['id'], self.clock())).fetchone()
            if row is None:
                raise Problem(404, 'This docking request is no longer waiting')
            if not approve:
                db.execute("UPDATE dockings SET status='denied' WHERE id=?", (row['id'],))
                return item, None
            return item, self._confirm_docking_row(db, actor, row)

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

    def _record_mentions(self, db, room_id, message_id, body):
        addressed = NOT_ADDRESSED.sub(' ', body)
        names = list(dict.fromkeys(m.group(1).rstrip('._-').lower() for m in MENTION.finditer(addressed)))[:20]
        if not names:
            return
        marks = ','.join('?' * len(names))
        rows = db.execute(
            f'SELECT users.id FROM room_members JOIN users ON users.id=room_members.user_id WHERE room_members.room_id=? AND users.username IN ({marks})',
            (room_id, *names),
        ).fetchall()
        for row in rows:
            db.execute('INSERT OR IGNORE INTO mentions(message_id,room_id,user_id) VALUES(?,?,?)', (message_id, room_id, row['id']))

    def _ship_post_budget(self, db, actor):
        row = db.execute('SELECT kind FROM users WHERE id=?', (actor,)).fetchone()
        if row and row['kind'] == 'ship':
            recent = db.execute('SELECT count(*) FROM messages WHERE author_id=? AND created>?', (actor, self.clock() - 60)).fetchone()[0]
            if recent >= POSTS_PER_MINUTE:
                raise Problem(429, 'This ship is posting too fast; wait a minute')

    def mentions(self, actor, after=0, limit=50):
        if type(after) is not int or after < 0 or type(limit) is not int:
            raise Problem(400, 'Invalid mention cursor')
        with self.transaction() as db:
            rows = db.execute('''SELECT mentions.seq, messages.id AS message_id, messages.room_id, messages.body, messages.created,
                       authors.id AS author_id, authors.username, authors.name, authors.kind, authors.owner_id
                FROM mentions JOIN messages ON messages.id=mentions.message_id
                JOIN users AS authors ON authors.id=messages.author_id
                JOIN room_members ON room_members.room_id=mentions.room_id AND room_members.user_id=mentions.user_id
                WHERE mentions.user_id=? AND mentions.seq>? ORDER BY mentions.seq LIMIT ?''',
                (actor, after, min(100, max(1, limit)))).fetchall()
        return [{'seq': r['seq'], 'message_id': r['message_id'], 'room_id': r['room_id'], 'body': r['body'], 'created': r['created'],
                 'author': {'id': r['author_id'], 'username': r['username'], 'name': r['name'], 'kind': r['kind'], 'owner_id': r['owner_id']}}
                for r in rows]

    def ships(self, actor):
        with self.transaction() as db:
            person = self._person(db, actor)
            only_mine = '' if person['is_admin'] else ' AND ships.owner_id=?'
            rows = db.execute(f'''SELECT ships.*, owners.name AS owner_name,
                    (SELECT MAX(last_used) FROM ship_keys WHERE ship_id=ships.id) AS last_used,
                    (SELECT count(*) FROM ship_keys WHERE ship_id=ships.id AND revoked IS NULL) AS active_keys,
                    (SELECT machine FROM dockings WHERE ship_id=ships.id ORDER BY created DESC LIMIT 1) AS machine
                FROM users AS ships LEFT JOIN users AS owners ON owners.id=ships.owner_id
                WHERE ships.kind='ship'{only_mine} ORDER BY ships.created, ships.id''',
                () if person['is_admin'] else (actor,)).fetchall()
            return [public_user(r) | {k: r[k] for k in ('owner_name', 'last_used', 'active_keys', 'machine')} for r in rows]

    def revoke_ship(self, actor, ship_id):
        with self.transaction() as db:
            person = self._person(db, actor)
            ship = require(db.execute("SELECT * FROM users WHERE id=? AND kind='ship'", (ship_id,)).fetchone())
            if ship['owner_id'] != actor and not person['is_admin']:
                raise Problem(403, "Only the ship's owner or an admin can revoke it")
            db.execute('UPDATE ship_keys SET revoked=? WHERE ship_id=? AND revoked IS NULL', (self.clock(), ship_id))
            return {'id': ship_id, 'active_keys': 0}

    def station_notices(self):
        """Trusted local workers only (Odo): what to announce in Ops. No HTTP route exposes this.
        Every interpolated value goes through safe_line: the text is posted in a room, where it must not mention anyone."""
        with self.transaction() as db:
            now = self.clock()
            notices = [{'id': f'access-{r["id"]}', 'text': f'{safe_line(r["name"])} is asking to come aboard. Approve or deny under Connections → Access requests.'}
                       for r in db.execute("SELECT id,name FROM access_requests WHERE status='pending' AND expires>? ORDER BY created", (now,))]
            notices += [{'id': f'share-{r["id"]}', 'text': f'No Tailscale share link is set, so {safe_line(r["name"])} cannot reach the station yet. Share the Pi with them by hand, or run make station-share-link on the Pi.'}
                        for r in db.execute("SELECT id,name FROM access_requests WHERE share_status='missing' ORDER BY decided")]
            notices += [{'id': f'docked-{r["id"]}', 'text': f'{safe_line(r["ship"])} ({safe_line(r["owner"])}) docked from {safe_line(r["machine"])}. Room owners can add it to rooms.'}
                        for r in db.execute("""SELECT dockings.id, ships.name AS ship, owners.name AS owner, dockings.machine FROM dockings
                            JOIN users AS ships ON ships.id=dockings.ship_id JOIN users AS owners ON owners.id=dockings.owner_id
                            WHERE dockings.status IN ('confirmed','collected') ORDER BY dockings.created""")]
            return notices
