"""Station inbox (docs/superpowers/specs/2026-10-08-station-inbox-design.md): a read cursor per ship and name, kept on
the station. Positions are the ids of 'chat.message' events, which both local posts and federated members' replies
emit. Reading never moves a cursor; advancing is explicit and only goes forward, so a reader that shows part of a
page loses nothing."""
from contextlib import contextmanager
import json
import re
from .common import Problem, require

READS_PER_MINUTE = 60
CURSOR_IDLE_DAYS = 30
CURSORS_PER_SHIP = 100
MAX_WAIT = 25
WAITS_PER_SHIP = 2
CURSOR_NAME = re.compile(r'[A-Za-z0-9._:-]{1,100}')

INBOX_SCHEMA = '''
CREATE TABLE IF NOT EXISTS read_cursors(ship_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL, position INTEGER NOT NULL, updated REAL NOT NULL, PRIMARY KEY(ship_id, name));
CREATE TABLE IF NOT EXISTS message_replies(message_id TEXT PRIMARY KEY, reply_to TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS inbox_meta(key TEXT PRIMARY KEY, value INTEGER NOT NULL);
INSERT OR IGNORE INTO inbox_meta VALUES('epoch', (SELECT COALESCE(MAX(id), 0) FROM events WHERE kind='chat.message'));
CREATE INDEX IF NOT EXISTS events_kind_id ON events(kind, id);
CREATE INDEX IF NOT EXISTS events_kind_room_id ON events(kind, resource_id, id);
'''


def cursor_name(value):
    name = 'default' if value is None else value
    if not isinstance(name, str) or not CURSOR_NAME.fullmatch(name):
        raise Problem(400, 'A cursor name is 1-100 letters, digits, dots, colons, dashes or underscores')
    return name


def wait_seconds(value):
    if value is None:
        return 0
    if type(value) not in (int, float) or not 0 <= value <= MAX_WAIT:
        raise Problem(400, f'wait is a number of seconds from 0 to {MAX_WAIT}')
    return value


class Inbox:
    @contextmanager
    def inbox_wait_slot(self, actor):
        """At most two waits per ship. The slot is freed in finally, so a client that goes away mid-wait (the route
        is cancelled) never keeps one."""
        waits = self.__dict__.setdefault('_inbox_waits', {})
        if waits.get(actor, 0) >= WAITS_PER_SHIP:
            raise Problem(429, f'This ship already has {WAITS_PER_SHIP} waits open')
        waits[actor] = waits.get(actor, 0) + 1
        try:
            yield
        finally:
            waits[actor] -= 1

    def _inbox_ship(self, db, actor):
        row = require(db.execute('SELECT kind FROM users WHERE id=?', (actor,)).fetchone())
        if row['kind'] != 'ship':
            raise Problem(403, 'Only a ship key can do this')

    def _inbox_budget(self, actor):
        """Reads that don't wait are limited per ship, like posts. Kept in memory: a restart forgives the minute."""
        now, reads = self.clock(), self.__dict__.setdefault('_inbox_reads', {})
        recent = [t for t in reads.get(actor, []) if t > now - 60]
        if len(recent) >= READS_PER_MINUTE:
            raise Problem(429, 'This ship is reading too fast; wait a minute or use wait')
        reads[actor] = recent + [now]

    def _cursor(self, db, actor, name):
        """The cursor's position, touched so a cursor in use is never pruned. A new name starts where the ship has
        read furthest; a ship's first cursor starts at the inbox's epoch, the newest message when the station first
        installed the inbox, so a deploy never replays history (R11). Making a cursor prunes the ship's idle ones."""
        now = self.clock()
        row = db.execute('SELECT position FROM read_cursors WHERE ship_id=? AND name=?', (actor, name)).fetchone()
        if row:
            db.execute('UPDATE read_cursors SET updated=? WHERE ship_id=? AND name=?', (now, actor, name))
            return row['position']
        # Where the ship has read furthest, decided before anything is pruned; that cursor is never pruned, so a ship
        # idle for months, or one that made many names, never replays what it read (I4, R11).
        furthest = db.execute('SELECT name, position FROM read_cursors WHERE ship_id=? ORDER BY position DESC, updated DESC LIMIT 1',
                              (actor,)).fetchone()
        start = furthest['position'] if furthest else db.execute("SELECT value FROM inbox_meta WHERE key='epoch'").fetchone()[0]
        keep = furthest['name'] if furthest else None
        db.execute('DELETE FROM read_cursors WHERE ship_id=? AND updated<? AND name IS NOT ?', (actor, now - CURSOR_IDLE_DAYS * 86400, keep))
        over = db.execute('SELECT count(*) FROM read_cursors WHERE ship_id=?', (actor,)).fetchone()[0] - CURSORS_PER_SHIP + 1
        if over > 0:  # the least recently used go first
            db.execute('''DELETE FROM read_cursors WHERE rowid IN (SELECT rowid FROM read_cursors WHERE ship_id=? AND name IS NOT ?
                          ORDER BY updated LIMIT ?)''', (actor, keep, over))
        db.execute('INSERT INTO read_cursors VALUES(?,?,?,?)', (actor, name, start, now))
        return start

    def _inbox_author(self, db, author_id):
        if ':' not in author_id:
            row = db.execute('SELECT id,username,name,kind,owner_id FROM users WHERE id=?', (author_id,)).fetchone()
            return dict(row) if row else {'id': author_id, 'username': None, 'name': None, 'kind': 'unknown', 'owner_id': None}
        peer, actor = author_id.split(':', 1)
        contact = db.execute('SELECT name FROM remote_contacts WHERE peer_id=? AND user_id=?', (peer, actor)).fetchone()
        return {'id': author_id, 'username': None, 'name': contact['name'] if contact else None, 'kind': 'remote', 'owner_id': None}

    def unread(self, actor, cursor=None, limit=30, counted=True):
        name = cursor_name(cursor)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise Problem(400, 'limit is a whole number from 1 to 100')
        with self.transaction() as db:
            self._inbox_ship(db, actor)
            if counted:  # a wait's later checks don't count: a wait is one read
                self._inbox_budget(actor)
            position = self._cursor(db, actor, name)
            rows = db.execute('''SELECT events.id, events.resource_id, events.payload, rooms.title FROM events
                JOIN room_members ON room_members.room_id=events.resource_id AND room_members.user_id=?
                JOIN rooms ON rooms.id=events.resource_id
                WHERE events.kind='chat.message' AND events.id>? AND json_extract(events.payload,'$.author_id')!=?
                ORDER BY events.id LIMIT ?''', (actor, position, actor, limit + 1)).fetchall()
            messages, sources = [], {}
            for row in rows[:limit]:
                payload = json.loads(row['payload'])
                found = (db.execute('SELECT * FROM messages WHERE id=?', (payload['message_id'],)).fetchone()
                         or db.execute('SELECT * FROM peer_messages WHERE id=?', (payload['message_id'],)).fetchone())
                if not found:
                    continue
                mentioned = db.execute('SELECT 1 FROM mentions WHERE message_id=? AND user_id=?', (found['id'], actor)).fetchone()
                if row['resource_id'] not in sources:  # labelled exactly as get_room labels them (spec A)
                    sources[row['resource_id']] = self._sources(db, row['resource_id'])
                item = {'event_id': row['id'], 'message_id': found['id'], 'room_id': row['resource_id'],
                        'room_title': row['title'], 'body': found['body'], 'created': found['created'],
                        'author': self._inbox_author(db, found['author_id']), 'mentions_me': bool(mentioned),
                        'reply_to': self._reply_to(db, found['id']), 'source': sources[row['resource_id']].get(found['id'])}
                if mentioned and db.execute('SELECT 1 FROM deferrals WHERE ship_id=? AND message_id=?', (actor, found['id'])).fetchone():
                    item['deferred'] = {'author_verified': item['author'], 'would_be': 'read'}  # R26
                messages.append(item)
            on_watch = self._session_on_writable_watch(db, actor, name)  # R26: the line asks for answers; only a writable watch takes them
        got = {'cursor': name, 'position': position, 'more': len(rows) > limit, 'messages': messages}
        if on_watch:  # R35: present only when it has something to say, so an old client sees today's keys
            got['on_watch'] = True
        return got

    def _reply_to(self, db, message_id):
        row = db.execute('SELECT reply_to FROM message_replies WHERE message_id=?', (message_id,)).fetchone()
        return row['reply_to'] if row else None

    def _replies(self, db, room_id):
        """Every reply in a room, keyed by the replying message (local posts only carry the field)."""
        return {r['message_id']: r['reply_to'] for r in db.execute(
            'SELECT message_replies.* FROM message_replies JOIN messages ON messages.id=message_replies.message_id WHERE messages.room_id=?', (room_id,))}

    def _check_reply_to(self, db, room_id, reply_to):
        """A reply names a message in the same local room, a local post or a federated member's reply."""
        if not isinstance(reply_to, str) or not 0 < len(reply_to) <= 100:
            raise Problem(400, 'reply_to is the id of a message in this room')
        if not (db.execute('SELECT 1 FROM messages WHERE id=? AND room_id=?', (reply_to, room_id)).fetchone()
                or db.execute('SELECT 1 FROM peer_messages WHERE id=? AND room_id=?', (reply_to, room_id)).fetchone()):
            raise Problem(400, 'reply_to is not a message in this room')

    def advance(self, actor, cursor=None, to=None):
        name = cursor_name(cursor)
        if type(to) is not int or not 0 <= to < 2 ** 63:
            raise Problem(400, 'to is the event id of a message')
        with self.transaction() as db:
            self._inbox_ship(db, actor)
            self._inbox_budget(actor)
            if not db.execute('''SELECT 1 FROM events JOIN room_members ON room_members.room_id=events.resource_id AND room_members.user_id=?
                                 WHERE events.id=? AND events.kind='chat.message' ''', (actor, to)).fetchone():
                raise Problem(400, 'to is not the event id of a message in your rooms')
            position = max(self._cursor(db, actor, name), to)
            db.execute('UPDATE read_cursors SET position=?, updated=? WHERE ship_id=? AND name=?', (position, self.clock(), actor, name))
        return {'cursor': name, 'position': position}
