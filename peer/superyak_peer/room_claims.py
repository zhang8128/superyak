"""Room claims (spec S8): records in one local room, advisory and exclusive per key. The claim route posts the
announcement itself, in its own transaction, as the claimant, with kind `claim`. A claim blocks nothing but a second
claim on the same key in the same room (R18)."""
import re
import time
from .common import Problem, require, uid
from .ships import safe_line

CLAIM_KEY = re.compile(r'[a-z0-9][a-z0-9._:/!-]{0,99}')
CLAIM_DEFAULT_MINUTES = 240
CLAIM_MIN_MINUTES = 10
CLAIM_MAX_MINUTES = 1440
CLAIMS_PER_CLAIMANT = 20
CLAIMS_PER_ROOM = 100

CLAIM_SCHEMA = '''
CREATE TABLE IF NOT EXISTS claims(id TEXT PRIMARY KEY, room_id TEXT NOT NULL REFERENCES rooms(id), key TEXT NOT NULL, holder_id TEXT NOT NULL REFERENCES users(id), note TEXT NOT NULL DEFAULT '', created REAL NOT NULL, expires REAL NOT NULL, released REAL, released_by TEXT REFERENCES users(id));
CREATE INDEX IF NOT EXISTS claims_by_room ON claims(room_id, key);
'''


def claim_key(value):
    """R14: lowercased first, then 1-100 characters from [a-z0-9._:/!-], starting with a letter or digit."""
    key = value.lower() if isinstance(value, str) else None
    if key is None or not CLAIM_KEY.fullmatch(key):
        raise Problem(400, 'A claim key is 1-100 characters from a-z 0-9 . _ : / ! -, starting with a letter or digit, like spec:d7')
    return key


def until(seconds):
    return time.strftime('%H:%M UTC', time.gmtime(seconds))


class RoomClaims:
    def _active_claim(self, db, room_id, key, now):
        return db.execute('SELECT * FROM claims WHERE room_id=? AND key=? AND released IS NULL AND expires>?', (room_id, key, now)).fetchone()

    def _claim_json(self, db, claim_id):
        row = db.execute('SELECT claims.*, users.name AS holder_name FROM claims JOIN users ON users.id=claims.holder_id WHERE claims.id=?',
                         (claim_id,)).fetchone()
        return {'id': row['id'], 'room_id': row['room_id'], 'key': row['key'], 'holder_id': row['holder_id'],
                'holder_name': safe_line(row['holder_name'], 40), 'note': safe_line(row['note'], 200),
                'created': row['created'], 'expires': row['expires']}

    def _active_claims(self, db, room_id):
        ids = db.execute('SELECT id FROM claims WHERE room_id=? AND released IS NULL AND expires>? ORDER BY created, rowid',
                         (room_id, self.clock())).fetchall()
        return [self._claim_json(db, r['id']) for r in ids]

    def room_claims(self, actor, room_id):
        with self.transaction() as db:
            self._room(db, actor, room_id)
            return self._active_claims(db, room_id)

    def _post_claim(self, db, actor, room_id, body):
        """R17: the claim route's own message, posted as the claimant with kind `claim`, no mention rows and no reply_to.
        It counts against a ship's post budget (ships.py:318-323)."""
        self._ship_post_budget(db, actor)
        epoch = db.execute('SELECT epoch FROM rooms WHERE id=?', (room_id,)).fetchone()['epoch']
        message_id = uid()
        db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)', (message_id, room_id, actor, f'claim-{message_id}', body, epoch, self.clock()))
        db.execute("INSERT INTO message_kinds VALUES(?, 'claim')", (message_id,))
        self.emit(db, 'chat.message', room_id, epoch, {'message_id': message_id, 'author_id': actor})

    def claim(self, actor, room_id, key, note=None, minutes=None):
        """S8: claim a key in a local room, or renew your own claim on it: a new expiry, and the new note if one is
        given. Another member's active claim gets 409 with the holder's name, the note and the expiry."""
        if not isinstance(room_id, str) or ':' in room_id:
            raise Problem(400, 'Claims belong to rooms on this station')
        key = claim_key(key)
        if note is not None and (not isinstance(note, str) or len(note) > 200):
            raise Problem(400, 'A note is at most 200 characters')
        minutes = CLAIM_DEFAULT_MINUTES if minutes is None else minutes
        if type(minutes) is not int or not CLAIM_MIN_MINUTES <= minutes <= CLAIM_MAX_MINUTES:
            raise Problem(400, f'minutes is a whole number from {CLAIM_MIN_MINUTES} to {CLAIM_MAX_MINUTES}')
        self._refuse_live_ship_keys(note or '', 'note')
        with self.transaction() as db:
            self._room(db, actor, room_id)
            now = self.clock()
            held, expires = self._active_claim(db, room_id, key, now), now + minutes * 60
            if held is not None and held['holder_id'] != actor:
                holder = db.execute('SELECT name FROM users WHERE id=?', (held['holder_id'],)).fetchone()
                raise Problem(409, f'{safe_line(holder["name"], 40)} holds `{key}` until {until(held["expires"])}'
                              + (f': {safe_line(held["note"], 200)}' if held['note'] else ''))
            if held is not None:
                kept = held['note'] if note is None else note
                db.execute('UPDATE claims SET expires=?, note=? WHERE id=?', (expires, kept, held['id']))
                if kept != held['note']:
                    self._post_claim(db, actor, room_id, f'Renewed `{key}` until {until(expires)}' + (f': {safe_line(kept, 200)}' if kept else ''))
                return self._claim_json(db, held['id'])
            mine = db.execute('SELECT count(*) FROM claims WHERE holder_id=? AND released IS NULL AND expires>?', (actor, now)).fetchone()[0]
            if mine >= CLAIMS_PER_CLAIMANT:
                raise Problem(429, f'You hold {CLAIMS_PER_CLAIMANT} active claims; release one first')
            here = db.execute('SELECT count(*) FROM claims WHERE room_id=? AND released IS NULL AND expires>?', (room_id, now)).fetchone()[0]
            if here >= CLAIMS_PER_ROOM:
                raise Problem(429, f'This room already has {CLAIMS_PER_ROOM} active claims')
            claim_id = uid()
            db.execute('INSERT INTO claims(id,room_id,key,holder_id,note,created,expires) VALUES(?,?,?,?,?,?,?)',
                       (claim_id, room_id, key, actor, note or '', now, expires))
            self._post_claim(db, actor, room_id, f'Claimed `{key}` until {until(expires)}' + (f': {safe_line(note, 200)}' if note else ''))
            return self._claim_json(db, claim_id)

    def release(self, actor, room_id, key):
        """R16: by the holder, the holder's owner (for a ship) or the room's owner; 404 when nothing is held."""
        key = claim_key(key)
        with self.transaction() as db:
            room = self._room(db, actor, room_id)
            held = require(self._active_claim(db, room_id, key, self.clock()))
            holder = db.execute('SELECT id,name,owner_id FROM users WHERE id=?', (held['holder_id'],)).fetchone()
            if actor not in (holder['id'], holder['owner_id'], room['owner_id']):
                raise Problem(403, "Only the claim's holder, the holder's owner or the room's owner can release it")
            db.execute('UPDATE claims SET released=?, released_by=? WHERE id=?', (self.clock(), actor, held['id']))
            self._post_claim(db, actor, room_id, f'Released `{key}`' if actor == holder['id']
                             else f"Released {safe_line(holder['name'], 40)}'s claim on `{key}`")
            return {'released': key}
