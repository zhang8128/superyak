"""Remote connector, Task 8: the four read-only tools and their receipts (spec "The tools", D11; "Receipts and revoking",
D4). Each tool builds its own result from the fields the spec lists and never passes a room object through. It reads
only rooms on this home that are in the grant's set, that the person is still a member of and that aren't marked,
checked at every read. Every call writes one receipt: room ids, never text and never an argument."""
import json
import secrets
import sqlite3
import time
from datetime import datetime, timezone

from .chats import SINCE_SQL
from .connector import ToolRefused

READS_SCHEMA = '''
CREATE TABLE IF NOT EXISTS connector_reads(id TEXT PRIMARY KEY, grant_id TEXT NOT NULL, person_id TEXT NOT NULL, app TEXT NOT NULL, at REAL NOT NULL, tool TEXT NOT NULL, rooms_read TEXT NOT NULL, rooms_refused TEXT NOT NULL, size INTEGER NOT NULL, outcome TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS connector_reads_by_grant ON connector_reads(grant_id, at);
'''
# connector_reads: one row per tools/call. `rooms_read` is a JSON list of room ids and `rooms_refused` a JSON list of
# {room, why}, a room recorded only when the person is in it; `outcome` is ok, refused or failed. It names its person and
# app (the redirect host) itself and has no foreign key to connector_grants, so a receipt whose grant a restore removed
# can still be shown on its own (Rio Grande and Tardis, on the restore design).

REFUSALS = {
    'marked': 'A member of this room keeps it away from cloud models.',
    'not_shared': "This room isn't shared with Claude. You can add it in Connected apps on your home.",
    'remote': 'This room is on another home. This connector reads rooms on this home only.',
    'no_such': 'No such room.',
}
TOO_LONG = 'This read took too long. Ask for less, such as a smaller limit.'
BAD_LIMIT = '`limit` must be a whole number from 1 to 100.'
BAD_CURSOR = 'Give at most one of `before` and `since`, each a whole number from an earlier result.'
TEXT_CAP = 100_000  # characters of a result's JSON (Claude takes about 150,000); cut at a message or room boundary
QUERY_SECONDS = 5  # SQLite's progress handler ends a connector query past this: it holds the store's lock while it runs
DEFAULT_LIMIT, MAX_LIMIT = 30, 100


def iso(when):
    """A time as ISO 8601 in UTC, to the second."""
    return datetime.fromtimestamp(when, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def size(value):
    """The characters a value takes as the result's JSON: what /mcp sends."""
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')))


def whole(value, low, high=None):
    """A whole number in range, never a bool or a float."""
    return type(value) is int and value >= low and (high is None or value <= high)


class _Seen:
    """What one call read and refused, for its receipt."""

    def __init__(self):
        self.read, self.refused = [], []

    def reading(self, room_id):
        if room_id not in self.read:
            self.read.append(room_id)


class ConnectorReads:
    def connector_call(self, grant, tool, args):
        """One tools/call for a grant as `bearer` gave it: the tool's result, or ToolRefused. The receipt is written in
        the read's own transaction; a call that fails or runs past QUERY_SECONDS rolls back, and its receipt is written
        in a fresh one."""
        seen, refusal = _Seen(), None
        try:
            with self.transaction() as db:
                deadline = time.monotonic() + QUERY_SECONDS
                db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
                try:
                    result = TOOLS[tool](self, db, grant, args, seen)
                except ToolRefused as refused:
                    refusal = refused
                finally:
                    db.set_progress_handler(None, 0)
                self._receipt(db, grant, tool, seen, 'refused' if refusal else 'ok',
                              len(str(refusal)) if refusal else size(result))
        except sqlite3.OperationalError as error:
            self._failed(grant, tool, seen)
            if 'interrupted' in str(error):
                raise ToolRefused(TOO_LONG) from None
            raise
        except Exception:
            self._failed(grant, tool, seen)
            raise
        if refusal is not None:
            raise refusal
        return result

    def _receipt(self, db, grant, tool, seen, outcome, length):
        row = db.execute('SELECT redirect_host FROM connector_grants WHERE id=?', (grant['grant_id'],)).fetchone()
        db.execute('INSERT INTO connector_reads VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (secrets.token_urlsafe(12), grant['grant_id'], grant['person_id'], row['redirect_host'] if row else '',
                    self.clock(), tool, json.dumps(seen.read), json.dumps(seen.refused), length, outcome))

    def _failed(self, grant, tool, seen):
        with self.transaction() as db:
            self._receipt(db, grant, tool, seen, 'failed', 0)

    # ---- which rooms a grant may read, asked again at every read (Tardis: filter at read time, never at consent) ----

    def _why_not(self, db, grant, room_id):
        """None when the grant may read this room now; else which refusal, in the spec's order of words."""
        if not isinstance(room_id, str) or not room_id or len(room_id) > 200:
            return 'no_such'
        if ':' in room_id:
            return 'remote'
        if db.execute('SELECT 1 FROM room_members WHERE room_id=? AND user_id=?',
                      (room_id, grant['person_id'])).fetchone() is None:
            return 'no_such'  # another person's room, a room the person left, or none: the same words
        if self._marked(db, room_id):
            return 'marked'
        if grant['rooms'] != '*' and room_id not in json.loads(grant['rooms']):
            return 'not_shared'
        return None

    def _readable(self, db, grant, room_id, seen):
        """The room id when the grant may read it, else ToolRefused, recorded by id only when the person is in it."""
        why = self._why_not(db, grant, room_id)
        if why is None:
            return room_id
        if why in ('marked', 'not_shared'):
            seen.refused.append({'room': room_id, 'why': why})
        raise ToolRefused(REFUSALS[why])

    def _activity(self, db, room_id):
        return max(db.execute('SELECT coalesce((SELECT created FROM room_activity WHERE room_id=?), 0), '
                              'coalesce((SELECT max(created) FROM messages WHERE room_id=?), 0), '
                              'coalesce((SELECT max(created) FROM peer_messages WHERE room_id=?), 0)',
                              (room_id, room_id, room_id)).fetchone())

    def _member_names(self, db, room_id):
        """Display names only: no username, person or peer id leaves the home (D11)."""
        names = [row[0] for row in db.execute('SELECT users.name FROM room_members JOIN users ON users.id=room_members.user_id '
                                              'WHERE room_members.room_id=?', (room_id,))]
        names += [row[0] for row in db.execute('SELECT remote_contacts.name FROM remote_room_members JOIN remote_contacts ON '
                                               'remote_contacts.id=remote_room_members.contact_id WHERE '
                                               'remote_room_members.room_id=?', (room_id,))]
        return sorted(names)

    # ---- the tools ----

    def _tool_rooms(self, db, grant, args, seen):
        """Each room the grant may read, a replaced room right after the room that continues it as one conversation,
        titled "earlier part of <title>"; the conversations most recent first; cut at a room boundary."""
        rows = db.execute('SELECT rooms.id, rooms.title FROM room_members JOIN rooms ON rooms.id=room_members.room_id '
                          'WHERE room_members.user_id=?', (grant['person_id'],)).fetchall()
        titles = {row['id']: row['title'] for row in rows if self._why_not(db, grant, row['id']) is None}
        chains = {}
        for room_id in titles:
            chains.setdefault(self._current_room(db, room_id) or room_id, []).append(room_id)
        conversations = []
        for head, rooms in chains.items():
            walked = self._rooms_back(db, head)
            ordered = [room for room in walked if room in rooms] + sorted(room for room in rooms if room not in walked)
            entries = [{'room': room, 'title': ('earlier part of ' if self._current_room(db, room) else '') + titles[room],
                        'members': self._member_names(db, room), 'activity': self._activity(db, room)} for room in ordered]
            conversations.append(entries)
        conversations.sort(key=lambda entries: (-max(entry['activity'] for entry in entries), entries[0]['room']))
        listed, used, truncated = [], size({'rooms': [], 'truncated': True}), False
        for entry in (entry for entries in conversations for entry in entries):
            shaped = {'room': entry['room'], 'title': entry['title'], 'members': entry['members'],
                      'last_activity': iso(entry['activity'])}
            used += size(shaped) + 1
            if used > TEXT_CAP:
                truncated = True
                break
            listed.append(shaped)
            seen.reading(entry['room'])
        return {'rooms': listed} | ({'truncated': True} if truncated else {})

    def _tool_read_room(self, db, grant, args, seen):
        """A window of one room's messages through chat paging: the newest `limit`, the `limit` before position
        `before`, or the oldest `limit` to arrive after event `since`. Cut at a message boundary at TEXT_CAP, with
        `truncated` and the cursor to continue from."""
        room_id = self._readable(db, grant, args.get('room'), seen)
        limit, before, since = args.get('limit', DEFAULT_LIMIT), args.get('before'), args.get('since')
        if not whole(limit, 1, MAX_LIMIT):
            raise ToolRefused(BAD_LIMIT)
        if (before is not None and since is not None) or not all(v is None or whole(v, 0) for v in (before, since)):
            raise ToolRefused(BAD_CURSOR)
        order = self._message_order(db, room_id)
        total, room_seq = len(order), self._room_seq(db, room_id)
        title = db.execute('SELECT title FROM rooms WHERE id=?', (room_id,)).fetchone()[0]
        brief = self._room_brief(db, room_id)[0]
        result = {'room': room_id, 'title': title, 'brief': brief['body'] if brief else None, 'messages': [],
                  'total': total, 'first_position': total, 'seq': room_seq, 'more': False}
        budget = TEXT_CAP - size(result | {'truncated': True, 'before': total})
        if since is None:
            end = total if before is None else before
            if end > total:
                raise ToolRefused(BAD_CURSOR)
            positions = list(range(max(0, end - limit), end))
            shaped = self._shaped(db, room_id, [order[i] for i in positions])
            kept = []
            for position, message in zip(reversed(positions), reversed(shaped)):  # the newest are kept
                budget -= size(message) + 1
                if budget < 0:
                    break
                kept.insert(0, (position, message))
            result.update(messages=[m for _, m in kept], first_position=kept[0][0] if kept else end,
                          more=bool(kept) and kept[0][0] > 0)
            if len(kept) < len(positions):
                result.update(truncated=True, before=kept[0][0] if kept else end)
        else:
            position = {message_id: i for i, (message_id, _) in enumerate(order)}
            arrived, more = [], False
            for event_id, message_id in db.execute(SINCE_SQL, (room_id, since)):
                if message_id not in position:
                    continue
                if len(arrived) == limit:
                    more = True
                    break
                arrived.append((event_id, position[message_id]))
            shaped = dict(zip((p for _, p in arrived), self._shaped(db, room_id, [order[p] for _, p in arrived])))
            kept, cut = [], False
            for event_id, at in arrived:  # the oldest to arrive are kept
                budget -= size(shaped[at]) + 1
                if budget < 0:
                    cut = True
                    break
                kept.append((event_id, at))
            positions = sorted(at for _, at in kept)
            result.update(messages=[shaped[at] for at in positions], first_position=positions[0] if positions else total,
                          more=more or cut, seq=kept[-1][0] if (more or cut) and kept else (since if cut else room_seq))
            if cut:
                result['truncated'] = True
        seen.reading(room_id)
        return result

    def _shaped(self, db, room_id, picked):
        """Messages as the tools give them: {id, author, author_kind, time, text, reply_to}, a display name for the
        author, `system` for the station's system author and `remote` for a member on a paired home."""
        rows, system = self._messages_of(db, room_id, picked), self.system_author_id(db)
        local = {row['author_id'] for row, (_, source) in zip(rows, picked) if source == 0}
        remote = {row['author_id'] for row, (_, source) in zip(rows, picked) if source == 1}
        people = {r['id']: (r['name'], r['kind']) for r in db.execute(
            f'SELECT id, name, kind FROM users WHERE id IN ({",".join("?" * len(local))})', tuple(local))} if local else {}
        contacts = {r['id']: r['name'] for r in db.execute(
            f'SELECT id, name FROM remote_contacts WHERE id IN ({",".join("?" * len(remote))})', tuple(remote))} if remote else {}
        shaped = []
        for row, (_, source) in zip(rows, picked):
            if source == 1:
                author, kind = contacts.get(row['author_id'], 'Someone on another home'), 'remote'
            else:
                name, kind = people.get(row['author_id'], ('Someone', 'person'))
                author, kind = name, 'system' if row['author_id'] == system else kind
            shaped.append({'id': row['id'], 'author': author, 'author_kind': kind, 'time': iso(row['created']),
                           'text': row['body'], 'reply_to': row.get('reply_to')})
        return shaped


TOOLS = {'rooms': ConnectorReads._tool_rooms, 'read_room': ConnectorReads._tool_read_room}
