"""Station inbox (docs/superpowers/specs/2026-10-08-station-inbox-design.md): a read cursor per ship and name, kept on
the station. Positions are the ids of 'chat.message' events, which both local posts and federated members' replies
emit. Reading never moves a cursor; advancing is explicit and only goes forward, so a reader that shows part of a
page loses nothing."""
import json
import re
from .common import Problem, require

READS_PER_MINUTE = 60
CURSOR_NAME = re.compile(r'[A-Za-z0-9._:-]{1,100}')

INBOX_SCHEMA = '''
CREATE TABLE IF NOT EXISTS read_cursors(ship_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL, position INTEGER NOT NULL, updated REAL NOT NULL, PRIMARY KEY(ship_id, name));
'''


def cursor_name(value):
    name = 'default' if value is None else value
    if not isinstance(name, str) or not CURSOR_NAME.fullmatch(name):
        raise Problem(400, 'A cursor name is 1-100 letters, digits, dots, colons, dashes or underscores')
    return name


class Inbox:
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
        """The cursor's position. A new name starts where the ship has read furthest; a first cursor starts at 0."""
        row = db.execute('SELECT position FROM read_cursors WHERE ship_id=? AND name=?', (actor, name)).fetchone()
        if row:
            return row['position']
        start = db.execute('SELECT MAX(position) FROM read_cursors WHERE ship_id=?', (actor,)).fetchone()[0] or 0
        db.execute('INSERT INTO read_cursors VALUES(?,?,?,?)', (actor, name, start, self.clock()))
        return start

    def _inbox_author(self, db, author_id):
        if ':' not in author_id:
            row = db.execute('SELECT id,username,name,kind,owner_id FROM users WHERE id=?', (author_id,)).fetchone()
            return dict(row) if row else {'id': author_id, 'username': None, 'name': None, 'kind': 'unknown', 'owner_id': None}
        peer, actor = author_id.split(':', 1)
        contact = db.execute('SELECT name FROM remote_contacts WHERE peer_id=? AND user_id=?', (peer, actor)).fetchone()
        return {'id': author_id, 'username': None, 'name': contact['name'] if contact else None, 'kind': 'remote', 'owner_id': None}

    def unread(self, actor, cursor=None, limit=30):
        name = cursor_name(cursor)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise Problem(400, 'limit is a whole number from 1 to 100')
        with self.transaction() as db:
            self._inbox_ship(db, actor)
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
                messages.append({'event_id': row['id'], 'message_id': found['id'], 'room_id': row['resource_id'],
                                 'room_title': row['title'], 'body': found['body'], 'created': found['created'],
                                 'author': self._inbox_author(db, found['author_id']), 'mentions_me': bool(mentioned),
                                 'reply_to': None, 'source': sources[row['resource_id']].get(found['id'])})
        return {'cursor': name, 'position': position, 'more': len(rows) > limit, 'messages': messages}

    def advance(self, actor, cursor=None, to=None):
        name = cursor_name(cursor)
        if type(to) is not int:
            raise Problem(400, 'to is the event id of a message')
        with self.transaction() as db:
            self._inbox_ship(db, actor)
            if not db.execute("SELECT 1 FROM events WHERE id=? AND kind='chat.message'", (to,)).fetchone():
                raise Problem(400, 'to is not the event id of a message')
            position = max(self._cursor(db, actor, name), to)
            db.execute('UPDATE read_cursors SET position=?, updated=? WHERE ship_id=? AND name=?', (position, self.clock(), actor, name))
        return {'cursor': name, 'position': position}
