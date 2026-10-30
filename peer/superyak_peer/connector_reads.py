"""Remote connector, Task 8: the four read-only tools and their receipts (spec "The tools", D11; "Receipts and
revoking", D4). Each tool builds its own result from the fields the spec lists and never passes a room object through.
It reads only rooms on this home that are in the grant's set, that the person is still a member of and that aren't
marked, checked at every read. Every call writes one receipt: room ids, never text and never an argument."""
import json
import math
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
# {room, why}, a room recorded only when the person is in it; `outcome` is ok, refused or failed. It names its person
# and app (the redirect host) itself and has no foreign key to connector_grants, so a receipt whose grant a restore
# removed can still be shown on its own (Rio Grande and Tardis, on the restore design).

REFUSALS = {
    'marked': 'A member of this room keeps it away from cloud models.',
    'not_shared': "This room isn't shared with Claude. You can add it in Connected apps on your home.",
    'remote': 'This room is on another home. This connector reads rooms on this home only.',
    'no_such': 'No such room.',
}
TOO_LONG = 'This read took too long. Ask for less, such as a smaller limit.'
BAD_LIMIT = '`limit` must be a whole number from 1 to 100.'
BAD_CURSOR = 'Give at most one of `before` and `since`, each a whole number from an earlier result.'
SEARCH_RESULTS = 20
DOT = ' \u00b7 '  # a search result's title: room title, author, date
# search (spec "search is one bounded query"): one statement over local and paired homes' messages, with the membership,
# room-set and mark filters inside it, never a post-filter and never a loop over rooms. LIKE folds ASCII case only.
SEARCH_SQL = '''
SELECT * FROM (
  SELECT m.id, m.room_id, m.created, r.title, coalesce(u.name, 'Someone') AS author FROM messages m
    JOIN room_members rm ON rm.room_id=m.room_id AND rm.user_id=:person JOIN rooms r ON r.id=m.room_id
    LEFT JOIN users u ON u.id=m.author_id
    WHERE m.body LIKE :pattern ESCAPE '\\' AND NOT EXISTS (SELECT 1 FROM room_cloud WHERE room_cloud.room_id=m.room_id)
      AND (:every OR m.room_id IN (SELECT value FROM json_each(:rooms)))
  UNION ALL
  SELECT p.id, p.room_id, p.created, r.title, coalesce(c.name, 'Someone on another home') FROM peer_messages p
    JOIN room_members rm ON rm.room_id=p.room_id AND rm.user_id=:person JOIN rooms r ON r.id=p.room_id
    LEFT JOIN remote_contacts c ON c.peer_id || ':' || c.user_id=p.author_id
    WHERE p.body LIKE :pattern ESCAPE '\\' AND NOT EXISTS (SELECT 1 FROM room_cloud WHERE room_cloud.room_id=p.room_id)
      AND (:every OR p.room_id IN (SELECT value FROM json_each(:rooms)))
) ORDER BY created DESC, id LIMIT 20'''
BAD_QUERY = '`query` must be text of 1 to 200 characters.'
TEXT_CAP = 100_000  # characters of a result's JSON (Claude takes about 150,000); cut at a message or room boundary
QUERY_SECONDS = 5  # SQLite's progress handler ends a connector query past this: it holds the store's lock while it runs
DEFAULT_LIMIT, MAX_LIMIT = 30, 100
CURSOR_MAX = 10 ** 15 - 1  # app.py's paging takes at most 15 digits; a larger one overflowed SQLite's integer (a 500)
CALLS_PER_MINUTE, CALLS_PER_DAY = 60, 2000  # tools/call per grant (spec "Limits"); the other methods don't count


def iso(when):
    """A time as ISO 8601 in UTC, to the second."""
    return datetime.fromtimestamp(when, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def size(value):
    """The characters a value takes as the result's JSON: what /mcp sends."""
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')))


def fitted(message, fits):
    """The message whole when `fits` takes it; else with its text cut to the longest start that fits, and `text_cut`,
    the number of characters left out, so Claude knows it holds part (Rio Grande). A message alone past the cap is kept
    this way, so a read's cursor always moves past it (the reader's must-fix 3: one hostile message stalled read_room
    both ways)."""
    if fits(message):
        return message
    text, low, high = message['text'], 0, len(message['text'])
    while low < high:
        middle = (low + high + 1) // 2
        if fits(message | {'text': text[:middle], 'text_cut': len(text) - middle}):
            low = middle
        else:
            high = middle - 1
    return message | {'text': text[:low], 'text_cut': len(text) - low}


def day(when):
    return datetime.fromtimestamp(when, timezone.utc).strftime('%Y-%m-%d')


def room_url(grant, room_id):
    """The web app's route to a room (app.js's #chats/<id>) on this home's public origin, from the token's audience. It
    never carries text or the query."""
    return grant['resource'].removesuffix('/mcp') + '/#chats/' + room_id


def whole(value, low, high=None):
    """A whole number in range, never a bool or a float."""
    return type(value) is int and value >= low and (high is None or value <= high)


class CallLimited(Exception):
    """A tools/call over its grant's minute or day: /mcp answers 429 with Retry-After `seconds`. Nothing is written."""

    def __init__(self, seconds):
        super().__init__(seconds)
        self.seconds = seconds


class GrantGone(Exception):
    """The token or its connection ended after bearer checked it and before the read: /mcp answers the challenge (401),
    as the next call would. Nothing is read or written."""


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
                grant = self._still_live(db, grant, self.clock())  # bearer's check was another transaction
                wait = self._limited(db, grant['grant_id'], self.clock())  # in the call's own transaction: no race
                if wait is not None:
                    raise CallLimited(wait)
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
        except (CallLimited, GrantGone):
            raise
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

    def _still_live(self, db, grant, now):
        """The grant as it stands in this transaction (the reader's should-fix: a revoke, or a room set narrowed, between
        bearer and the read let text out): its access token still unexpired and its connection still live and active,
        with the rooms and person read from the row now, else GrantGone."""
        token = db.execute("SELECT expires FROM connector_tokens WHERE hash=? AND kind='access' AND grant_id=?",
                           (grant.get('token'), grant['grant_id'])).fetchone()  # bound to its grant (Task 8's re-check)
        live = self._live_grant(db, grant['grant_id'], now) if token is not None and now < token['expires'] else None
        if live is None:
            raise GrantGone()
        return grant | {'person_id': live['person_id'], 'rooms': live['rooms']}

    def connector_limited(self, grant_id):
        """None, or the whole seconds until the grant may make one more tools/call."""
        with self.transaction() as db:
            return self._limited(db, grant_id, self.clock())

    def _limited(self, db, grant_id, now):
        """Counted from the receipts, so a restart doesn't empty it. A call the limit refuses writes no receipt, so a 429
        spends nothing; a tool's own refusal writes one, and counts. Each window is read by its oldest receipt, so a clock set back only makes it stricter, and every wait
        is above 0, since every receipt counted is inside its window."""
        for window, most in ((86400, CALLS_PER_DAY), (60, CALLS_PER_MINUTE)):
            count, oldest = db.execute('SELECT count(*), min(at) FROM connector_reads WHERE grant_id=? AND at>?',
                                       (grant_id, now - window)).fetchone()
            if count >= most:
                return math.ceil(oldest + window - now)
        return None

    def _receipt(self, db, grant, tool, seen, outcome, length):
        row = db.execute('SELECT redirect_host FROM connector_grants WHERE id=?', (grant['grant_id'],)).fetchone()
        db.execute('UPDATE connector_grants SET last_used=? WHERE id=?', (self.clock(), grant['grant_id']))  # Task 9a
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
        if (before is not None and since is not None) or not all(v is None or whole(v, 0, CURSOR_MAX) for v in (before, since)):
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
                if size(message) + 1 > budget:
                    if not kept:  # one message alone past the cap: kept cut, so `before` moves past it
                        kept.insert(0, (position, fitted(message, lambda m: size(m) + 1 <= budget)))
                    break
                budget -= size(message) + 1
                kept.insert(0, (position, message))
            result.update(messages=[m for _, m in kept], first_position=kept[0][0] if kept else end,
                          more=bool(kept) and kept[0][0] > 0)
            if len(kept) < len(positions) or any(m.get('text_cut') for _, m in kept):
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
                if size(shaped[at]) + 1 > budget:
                    if not kept:  # one message alone past the cap: kept cut, so `seq` moves past it
                        shaped[at] = fitted(shaped[at], lambda m: size(m) + 1 <= budget)
                        kept.append((event_id, at))
                    cut = True
                    break
                budget -= size(shaped[at]) + 1
                kept.append((event_id, at))
            positions = sorted(at for _, at in kept)
            result.update(messages=[shaped[at] for at in positions], first_position=positions[0] if positions else total,
                          more=more or cut, seq=kept[-1][0] if (more or cut) and kept else (since if cut else room_seq))
            if cut:
                result['truncated'] = True
        seen.reading(room_id)
        return result

    def _tool_search(self, db, grant, args, seen):
        """Messages whose text contains `query`, newest first, at most SEARCH_RESULTS, in ChatGPT's deep-research shape.
        Its receipt lists the rooms in its results. It never says how many matches were hidden."""
        query = args.get('query')
        if not isinstance(query, str) or not 1 <= len(query) <= 200:
            raise ToolRefused(BAD_QUERY)
        pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        every = grant['rooms'] == '*'
        rows = db.execute(SEARCH_SQL, {'person': grant['person_id'], 'pattern': pattern, 'every': int(every),
                                       'rooms': '[]' if every else grant['rooms']}).fetchall()
        for row in rows:
            seen.reading(row['room_id'])
        return {'results': [{'id': row['id'], 'title': DOT.join([row['title'], row['author'], day(row['created'])]),
                             'url': room_url(grant, row['room_id'])} for row in rows]}

    def _tool_fetch(self, db, grant, args, seen):
        """One message from `search`, with the 2 before and the 2 after it in its room, as JSON lines shaped as in
        read_room; cut at a message boundary at TEXT_CAP, the message itself always kept."""
        message_id = args.get('id')
        if not isinstance(message_id, str) or not message_id or len(message_id) > 200:
            raise ToolRefused(REFUSALS['no_such'])
        row = db.execute('SELECT room_id FROM messages WHERE id=? UNION ALL SELECT room_id FROM peer_messages WHERE id=?',
                         (message_id, message_id)).fetchone()
        if row is None:
            raise ToolRefused(REFUSALS['no_such'])
        room_id = self._readable(db, grant, row['room_id'], seen)
        order = self._message_order(db, room_id)
        at = next(i for i, (mid, _) in enumerate(order) if mid == message_id)
        begin = max(0, at - 2)
        shaped = self._shaped(db, room_id, order[begin:at + 3])
        target = shaped[at - begin]
        title = db.execute('SELECT title FROM rooms WHERE id=?', (room_id,)).fetchone()[0]
        result = {'id': message_id, 'title': DOT.join([title, target['author'], target['time'][:10]]), 'text': '',
                  'url': room_url(grant, room_id)}
        def line(message):
            return json.dumps(message, ensure_ascii=False, separators=(',', ':'))

        def whole(text):  # measured on the result's whole JSON: the lines are escaped again inside it (the reader's 2x)
            return size(result | {'text': text, 'truncated': True})
        lines, kept, here = [line(message) for message in shaped], list(range(len(shaped))), at - begin
        while len(kept) > 1 and whole('\n'.join(lines[i] for i in kept)) > TEXT_CAP:
            kept.remove(max(kept, key=lambda i: (abs(i - here), i)))  # the farthest goes first, later before earlier
        target = shaped[here]
        if whole('\n'.join(lines[i] for i in kept)) > TEXT_CAP:  # the message alone past the cap: its text is cut
            target = fitted(target, lambda m: whole(line(m)) <= TEXT_CAP)
            lines[here] = line(target)
        result['text'] = '\n'.join(lines[i] for i in kept)
        if len(kept) < len(lines) or 'text_cut' in target:  # fitted's own mark, not a search of the line (Tardis)
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
        contacts = {r['author']: r['name'] for r in db.execute(  # a paired home's author is <peer>:<user> (federation.py)
            "SELECT peer_id || ':' || user_id AS author, name FROM remote_contacts WHERE peer_id || ':' || user_id IN "
            f'({",".join("?" * len(remote))})', tuple(remote))} if remote else {}
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


TOOLS = {'rooms': ConnectorReads._tool_rooms, 'read_room': ConnectorReads._tool_read_room,
         'search': ConnectorReads._tool_search, 'fetch': ConnectorReads._tool_fetch}
