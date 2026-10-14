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
UNREAD_FROM = '''FROM events
    JOIN room_members ON room_members.room_id=events.resource_id AND room_members.user_id=?
    JOIN rooms ON rooms.id=events.resource_id
    WHERE events.kind='chat.message' AND events.id>? AND json_extract(events.payload,'$.author_id')!=?'''
# Breakouts S6: what breakouts=mentions leaves out, a breakout message that doesn't mention the reader.
NOISE = '''events.resource_id IN (SELECT room_id FROM breakouts) AND NOT EXISTS (SELECT 1 FROM mentions
    WHERE mentions.message_id=json_extract(events.payload,'$.message_id') AND mentions.user_id=?)'''

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


def breakout_filter(value):
    """Breakouts S6: the opt-in `breakouts=mentions`; without it, unread is exactly today's (R10)."""
    if value not in (None, 'mentions'):
        raise Problem(400, 'breakouts is mentions, or left out')
    return value == 'mentions'


def with_earlier_noise(earlier, later):
    """A wait with breakouts=mentions passes noise at each check, so its answer counts what every check passed."""
    if 'breakout_counts' in later:
        for room, n in earlier['breakout_counts'].items():
            later['breakout_counts'][room] = later['breakout_counts'].get(room, 0) + n
        later['breakout_titles'] = {**earlier['breakout_titles'], **later['breakout_titles']}
    return later


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

    def unread(self, actor, cursor=None, limit=30, counted=True, breakouts=False):
        """breakouts: breakouts=mentions (breakouts S6). The page then holds only what the session shows: breakout
        messages that don't mention the reader are left out, counted in breakout_counts, and passed."""
        name = cursor_name(cursor)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise Problem(400, 'limit is a whole number from 1 to 100')
        with self.transaction() as db:
            self._inbox_ship(db, actor)
            if counted:  # a wait's later checks don't count: a wait is one read
                self._inbox_budget(actor)
            position = self._cursor(db, actor, name)
            shown_only = f' AND NOT ({NOISE})' if breakouts else ''
            rows = db.execute(f'SELECT events.id, events.resource_id, events.payload, rooms.title {UNREAD_FROM}{shown_only} '
                              'ORDER BY events.id LIMIT ?', (actor, position, actor, *([actor] if breakouts else []), limit + 1)).fetchall()
            if breakouts:
                position, counts, titles = self._left_out(db, actor, name, position, rows[:limit])
            messages, sources, breakout_rooms, asked = [], {}, set(), []
            for row in rows[:limit]:
                payload = json.loads(row['payload'])
                found = (db.execute('SELECT * FROM messages WHERE id=?', (payload['message_id'],)).fetchone()
                         or db.execute('SELECT * FROM peer_messages WHERE id=?', (payload['message_id'],)).fetchone())
                if not found:
                    continue
                mentioned = db.execute('SELECT 1 FROM mentions WHERE message_id=? AND user_id=?', (found['id'], actor)).fetchone()
                if row['resource_id'] not in sources:  # labelled exactly as get_room labels them (spec A)
                    sources[row['resource_id']] = self._sources(db, row['resource_id'])
                    if self._breakout(db, row['resource_id']) is not None:
                        breakout_rooms.add(row['resource_id'])
                        self._breakout_closed(db, row['resource_id'])  # S4: saved on first sight, deferrals dropped
                item = {'event_id': row['id'], 'message_id': found['id'], 'room_id': row['resource_id'],
                        'room_title': row['title'], 'body': found['body'], 'created': found['created'],
                        'author': self._inbox_author(db, found['author_id']), 'mentions_me': bool(mentioned),
                        'reply_to': self._reply_to(db, found['id']), 'source': sources[row['resource_id']].get(found['id'])}
                if row['resource_id'] in breakout_rooms:  # breakouts S6: only a breakout's items carry the key
                    item['breakout'] = True
                messages.append(item)
                if mentioned:
                    asked.append(found['id'])
            waiting = set(self._waiting_deferrals(db, actor, asked))  # R26, once per page, after any breakout closed
            for item in messages:
                if item['message_id'] in waiting:
                    item['deferred'] = {'author_verified': item['author'], 'would_be': 'read'}
            on_watch = self._session_on_writable_watch(db, actor, name)  # R26: the line asks for answers; only a writable watch takes them
        got = {'cursor': name, 'position': position, 'more': len(rows) > limit, 'messages': messages}
        if on_watch:  # R35: present only when it has something to say, so an old client sees today's keys
            got['on_watch'] = True
        if breakouts:
            got['breakout_counts'], got['breakout_titles'] = counts, titles
        return got

    def _left_out(self, db, actor, name, position, page):
        """Breakouts S6: the breakout messages a breakouts=mentions page leaves out, up to its last message (all of
        them when the page is empty), counted per room with the room's title. Those before the page's first message
        are passed here, so the cursor never stops in front of noise; the rest are passed when the reader advances
        through the page, as it does past any message it showed. Returns (position, counts, titles)."""
        bound = page[-1]['id'] if page else None
        rows = db.execute(f'SELECT events.id, events.resource_id, rooms.title {UNREAD_FROM} AND {NOISE}'
                          + ('' if bound is None else ' AND events.id<=?') + ' ORDER BY events.id',
                          (actor, position, actor, actor, *([] if bound is None else [bound]))).fetchall()
        counts, titles = {}, {}
        for row in rows:
            counts[row['resource_id']] = counts.get(row['resource_id'], 0) + 1
            titles[row['resource_id']] = row['title']
        passed = [row['id'] for row in rows if not page or row['id'] < page[0]['id']]
        if passed:
            position = passed[-1]
            db.execute('UPDATE read_cursors SET position=?, updated=? WHERE ship_id=? AND name=?', (position, self.clock(), actor, name))
        for room in counts:
            self._breakout_closed(db, room)  # S4: saved on first sight
        return position, counts, titles

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
