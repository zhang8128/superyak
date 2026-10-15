import json
from urllib.parse import parse_qs, unquote, urlsplit
import pytest

INVITEE_REFUSED = "Every invited ship must be one of your owner's ships that already shares a room with you"
BREAKOUT_CLOSED = 'This breakout is closed'
DAY = 86400


def board_item(key, title='Some work', kind='build', state='open', poster=None, created=1000.0, links=(), claim=None,
               room_id='r1', closed=None, closer=None, outcome=None):
    """A board item as the station's routes give it (work board 5.1)."""
    poster = poster or {'id': 'u-andy', 'name': 'Andy'}
    return {'id': f'i-{key}', 'room_id': room_id, 'key': key, 'title': title, 'kind': kind, 'state': state,
            'posted_by': poster['id'], 'poster_name': poster['name'], 'created': created, 'closed': closed,
            'closed_by': closer['id'] if closer else None, 'closer_name': closer['name'] if closer else None,
            'outcome': outcome, 'links': [{'link': l, 'added_by': poster['id'], 'added': created} for l in links],
            'claim': claim}


def held_by(member, key, expires=4600.0):
    """The active claim on a key, as _claim_json gives it."""
    return {'id': f'c-{key}', 'room_id': 'r1', 'key': key, 'holder_id': member['id'], 'holder_name': member['name'],
            'note': '', 'created': 1000.0, 'expires': expires}


@pytest.fixture(autouse=True)
def private_home(monkeypatch, tmp_path_factory):
    """Every test gets its own HOME and no Claude Code project directory, so no test can read or write the machine's
    ~/.superyak (its claims registry included), ~/.claude or ~/.codex, and a test run from a Claude session started in
    a claimed project behaves like any other (D7)."""
    home = tmp_path_factory.mktemp('home')
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)
    return home


class FakeStation:
    """Just enough of the station API for ship-side tests. The real station is exercised
    end to end in peer/tests/test_ship_agent.py."""
    def __init__(self):
        self.users, self.rooms, self.mention_rows, self.keys = {}, {}, [], {}
        self.clock, self.counter, self.down = 1000.0, 0, False
        self.tickets, self.sources, self.ticket_override, self.label_refusals = {}, {}, {}, set()
        self.blocks, self.instruction_state, self.drafts = {}, {}, []
        self.briefs = {}  # room id -> the brief as GET /api/chats/{id} shows it, or None
        self.brief_revisions = {}  # room id -> brief_revision, as GET /api/chats/{id} shows it
        self.brief_puts, self.brief_refusals = [], []  # every ship brief PUT's JSON; (status, error) to answer first
        self.cursors, self.replies, self.unread_calls = {}, {}, []  # (ship, name) -> position; message id -> reply_to
        self.requests = []  # every call: method, path, JSON body and its x-superyak-* headers (spec S1)
        self.watches = {}  # (ship, session) -> {minutes, writable, label}
        # ship status: deferred mention ids; room id -> deferred ids; message id -> 'claim' or 'notice'; GET /api/ships/directory
        self.deferred_marks, self.deferred_here, self.kinds, self.directory_rows = set(), {}, {}, []
        self.claims = {}  # room id -> active claims, as GET /api/chats/{id}/claims shows them
        self.ticket_bodies, self.decide = [], {}  # every ticket request's JSON; message id -> its answer when decisions are asked
        self.breakouts = {}  # breakouts: room id -> {creator, created, closed}, as step 1's station keeps them
        self.board = {}  # work board: room id -> its items, as GET /api/chats/{id}/board gives them
        self.board_missing = None  # a status (404 or 405): every board route answers {"detail": "Not Found"}, as a station without the board does
        self.board_refusal = None  # (status, error): what the count route answers instead, as an older or failing station

    def user(self, username, name, kind='person', owner_id=None, key=None):
        user = {'id': f'u-{username}', 'username': username, 'name': name, 'kind': kind, 'owner_id': owner_id}
        self.users[user['id']] = user
        if key:
            self.keys[key] = user['id']
        return user

    def room(self, title, *members, linked_room_id=None):
        """A room owned by its first member; `linked_room_id` names the room it replaces, as when the station
        makes a new room for added members."""
        room_id = f'r{len(self.rooms) + 1}'
        self.rooms[room_id] = {'id': room_id, 'title': title, 'owner_id': members[0]['id'], 'linked_room_id': linked_room_id,
                               'member_ids': [m['id'] for m in members], 'messages': []}
        return room_id

    def breakout(self, title, *members):
        """A breakout opened by its first member (a ship), as POST /api/ships/me/rooms makes one."""
        room_id = self.room(title, *members)
        self.breakouts[room_id] = {'creator': members[0]['id'], 'created': self.clock, 'closed': None}
        return room_id

    def closed(self, room_id):
        return (self.breakouts.get(room_id) or {}).get('closed')

    def current_person_room(self, room):
        """Breakouts S2: a person-owned room no later linked room replaced; breakouts never count."""
        owner = self.users.get(room.get('owner_id'), {})
        return (owner.get('kind') == 'person' and room['id'] not in self.breakouts
                and not any(r.get('linked_room_id') == room['id'] for r in self.rooms.values()))

    def say(self, room_id, author, body, client_message_id=None):
        room = self.rooms[room_id]
        cid = client_message_id or f'c{self.counter + 1}'
        for message in room['messages']:
            if message['author_id'] == author['id'] and message['client_message_id'] == cid:
                return message if message['body'] == body else None
        self.counter += 1
        self.clock += 1
        message = {'id': f'm{self.counter}', 'room_id': room_id, 'author_id': author['id'], 'client_message_id': cid, 'body': body, 'created': self.clock}
        room['messages'].append(message)
        for word in body.replace(',', ' ').split():
            name = word[1:].rstrip('.!?:;)').lower() if word.startswith('@') else None
            target = next((u for u in self.users.values() if u['username'] == name and u['id'] in room['member_ids']), None)
            if target and self.closed(room_id) is None:  # breakouts S4: a closed breakout records no mention
                self.mention_rows.append({'seq': len(self.mention_rows) + 1, 'message_id': message['id'], 'room_id': room_id, 'user_id': target['id']})
        return message

    def brief(self, room_id, author, body, revision=1, carried_from=None, old_station=False):
        """A room's brief as the station shows it. A blank body removes it: GET then says null, with the removed
        revision as brief_revision. A station with ship briefs names the author's kind and username; old_station leaves
        them out, as an older station does."""
        self.clock += 1
        self.brief_revisions[room_id] = revision
        shown = {'body': body, 'revision': revision, 'author_id': author['id'], 'author_name': author['name'],
                 'updated': self.clock, 'carried_from': carried_from}
        if not old_station:
            shown.update(author_kind=author['kind'], author_username=author['username'])
        self.briefs[room_id] = shown if body.strip() else None

    def view(self, room):
        last = max([m['created'] for m in room['messages']], default=0.0)
        system = next((self.users[m['author_id']] for m in room['messages'] if self.users.get(m['author_id'], {}).get('kind') == 'system'), None)
        return {'id': room['id'], 'title': room['title'], 'owner_id': room.get('owner_id'), 'linked_room_id': room.get('linked_room_id'),
                'member_ids': room['member_ids'], 'last_activity': last,
                'members': [self.users[i] for i in room['member_ids'] if i in self.users], 'brief': self.briefs.get(room['id']),
                'brief_revision': self.brief_revisions.get(room['id'], 0),
                'claims': self.claims.get(room['id'], []),
                'messages': [dict(m, source=self.source_of(m), reply_to=self.replies.get(m['id'])) for m in room['messages']],
                **({'system_author': system} if system else {}),
                **({'breakout': {'creator': self.breakouts[room['id']]['creator'], 'closed': self.closed(room['id'])}}
                   if room['id'] in self.breakouts else {})}  # breakouts S6: only a breakout carries the key

    def listed(self, room):
        return {k: v for k, v in self.view(room).items() if k not in ('messages', 'brief', 'brief_revision')}

    def open_breakout(self, me, payload):
        """POST /api/ships/me/rooms, with step 1's checks in its order."""
        def refuse(status, error):
            return status, json.dumps({'error': error}).encode()
        creator, title, ships = self.users[me], payload.get('title'), payload.get('ships')
        if creator['kind'] != 'ship' or not creator['owner_id']:
            return refuse(403, 'Only a ship with an owner can open a breakout')
        if not isinstance(title, str) or not title.strip() or len(title) > 80:
            return refuse(400, 'A breakout title is 1-80 characters')
        if not isinstance(ships, list) or any(not isinstance(s, str) or not 0 < len(s) <= 100 for s in ships):
            return refuse(400, 'ships is a list of ship usernames')
        names = [s for s in dict.fromkeys(ships) if s != creator['username']]
        if not names:
            return refuse(400, 'Name at least one ship to invite')
        if len(names) + 1 > 8:
            return refuse(400, 'A breakout has at most 8 members, its opener included')
        if any(key in title for key in self.keys):
            return refuse(422, 'This title contains a live ship key, so the breakout was not opened.')
        invited = [next((u for u in self.users.values() if u['username'] == n), None) for n in names]
        if any(u is None or u['kind'] != 'ship' or u['owner_id'] != creator['owner_id'] for u in invited):
            return refuse(400, INVITEE_REFUSED)
        members, current = [creator, *invited], [r for r in self.rooms.values() if self.current_person_room(r)]
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                if not any(a['id'] in r['member_ids'] and b['id'] in r['member_ids'] for r in current):
                    return refuse(400, INVITEE_REFUSED)
        if title.casefold() in {r['title'].casefold() for r in current if any(m['id'] in r['member_ids'] for m in members)}:
            return refuse(400, 'That title is already a room title for one of these ships; choose another')
        if sum(self.rooms[r]['owner_id'] == me and self.closed(r) is None for r in self.breakouts) >= 10:
            return refuse(429, 'This ship already has 10 open breakouts; close one first')
        if sum(b['creator'] == me and b['created'] > self.clock - DAY for b in self.breakouts.values()) >= 20:
            return refuse(429, 'This ship opened 20 breakouts in the last 24 hours; wait before opening another')
        return 201, json.dumps(self.listed(self.rooms[self.breakout(title, *members)])).encode()

    def end_breakout(self, me, room_id, how):
        """POST /api/ships/me/rooms/{id}/leave or /close."""
        room = self.rooms.get(room_id)
        if room is None or me not in room['member_ids']:
            return 404, b'{"error": "Not found"}'
        if room_id not in self.breakouts:
            return 400, b'{"error": "This room isn\'t a breakout; a person manages its members"}'
        if how == 'close':
            if room['owner_id'] != me:
                return 403, b'{"error": "Only the ship that opened this breakout can close it"}'
            self.breakouts[room_id]['closed'] = self.closed(room_id) or self.clock
            return 200, json.dumps(self.listed(room)).encode()
        room['member_ids'] = [i for i in room['member_ids'] if i != me]
        if room['owner_id'] == me and self.closed(room_id) is None:
            self.breakouts[room_id]['closed'] = self.clock
        return 200, json.dumps({'room_id': room_id, 'left': True, 'closed': self.closed(room_id)}).encode()

    def ship_brief(self, me, room_id, payload):
        """PUT /api/ships/me/rooms/{id}/brief (ship briefs S3): just the checks the tool's tests need, in the station's
        words. A refusal queued in brief_refusals answers first, as the station would."""
        self.brief_puts.append(dict(payload))
        if self.brief_refusals:
            status, error = self.brief_refusals.pop(0)
            return status, json.dumps({'error': error}).encode()
        room = self.rooms.get(room_id)
        if room is None or me not in room['member_ids']:
            return 404, b'{"error": "Not found"}'
        body, revision = payload.get('body'), payload.get('revision')
        if not isinstance(body, str) or not body.strip():
            return 403, json.dumps({'error': "Only the room's owner can remove its brief"}).encode()
        if type(revision) is not int or revision != self.brief_revisions.get(room_id, 0):
            return 409, json.dumps({'error': 'The brief changed since you read it. Read it again with station_read and merge before saving.'}).encode()
        if self.briefs.get(room_id) and self.briefs[room_id]['body'] == body:  # unchanged text: the station writes nothing
            return 200, json.dumps(self.briefs[room_id]).encode()
        self.brief(room_id, self.users[me], body, revision + 1)
        return 200, json.dumps(self.briefs[room_id]).encode()

    def unread_page(self, me, name, limit, breakouts):
        """POST /api/ships/me/unread. With breakouts=mentions, breakout messages that don't mention the reader are left
        out, counted up to the page's last message (all of them when it is empty), and those before the page's first
        message passed at once, as step 1's station does."""
        position = self.cursors.setdefault((me, name), max([p for (s, _), p in self.cursors.items() if s == me], default=0))
        rows = [(int(m['id'][1:]), r, m) for r in self.rooms.values() if me in r['member_ids'] for m in r['messages']
                if m['author_id'] != me and int(m['id'][1:]) > position]
        rows.sort(key=lambda row: row[0])
        noise = [row for row in rows if row[1]['id'] in self.breakouts
                 and not any(x['message_id'] == row[2]['id'] and x['user_id'] == me for x in self.mention_rows)] if breakouts else []
        rows = [row for row in rows if row not in noise]
        page = rows[:limit]
        counted = [row for row in noise if not page or row[0] <= page[-1][0]]
        passed = [row[0] for row in noise if not page or row[0] < page[0][0]]
        if passed:
            position = self.cursors[(me, name)] = passed[-1]
        got = {'cursor': name, 'position': position, 'more': len(rows) > limit,
               **({'on_watch': True} if self.watches.get((me, name), {}).get('writable') else {}), 'messages': [  # R26, R35
            {'event_id': n, 'message_id': m['id'], 'room_id': r['id'], 'room_title': r['title'], 'body': m['body'], 'created': m['created'],
             'author': self.users[m['author_id']], 'mentions_me': any(x['message_id'] == m['id'] and x['user_id'] == me for x in self.mention_rows),
             'reply_to': self.replies.get(m['id']), 'source': self.source_of(m),
             **({'deferred': {'author_verified': self.users[m['author_id']], 'would_be': 'read'}} if m['id'] in self.deferred_marks else {}),
             **({'breakout': True} if r['id'] in self.breakouts else {})}
            for n, r, m in page]}
        if breakouts:
            got['breakout_counts'], got['breakout_titles'] = {}, {}
            for _, r, _ in counted:
                got['breakout_counts'][r['id']] = got['breakout_counts'].get(r['id'], 0) + 1
                got['breakout_titles'][r['id']] = r['title']
        return got

    def source_of(self, message):
        if message['id'] in self.kinds:
            return {'kind': self.kinds[message['id']]}
        author = self.users.get(message['author_id'], {})
        if author.get('kind') != 'ship':
            return None
        ticket = self.tickets.get(self.sources.get(message['id']))
        if ticket is None:
            return {'kind': 'post'}
        return {'kind': 'run', 'mode': ticket['mode'], 'basis': ticket['basis'], 'root_name': ticket['root_name'], 'answering': ticket['message_id']}

    def board_route(self, me, room, method, rest, payload):
        """The room routes of work board 5.1, as step 1's station answers them, with the refusals the tool tests use.
        It does NOT refuse what the real station refuses: the writer, done-by and drop-by 403s (WRITER, DONE_BY,
        DROP_BY); the 400s for kind, title, link and outcome; the 429 limits (open items, posts per hour, links per
        item); and breakouts, replaced rooms and non-members. It only has the used-key 409, the closed-item 409 and the
        missing-key 404. The real behaviour is covered by the real-station test in peer/tests/test_ship_agent.py,
        test_a_ship_works_a_board_item_through_the_real_station."""
        items = self.board.setdefault(room['id'], [])

        def answer(value, status=200):
            return status, json.dumps(value).encode()

        def refuse(status, error):
            return status, json.dumps({'error': error}).encode()
        if method == 'GET' and not rest:
            return answer(items)
        key = str(payload.get('key', '')).lower()
        found = next((i for i in items if i['key'] == key), None)
        if not rest:
            if found is not None:
                return refuse(409, f'`{key}` is already on this board or a room it replaced ({found["state"]}); new work needs a new key')
            self.clock += 1
            made = board_item(key, payload['title'], payload['kind'], poster=self.users[me], created=self.clock, room_id=room['id'])
            items.append(made)
            return answer(made, 201)
        if found is None:
            return refuse(404, 'Not found')
        if found['state'] != 'open':
            return refuse(409, f'`{key}` is already {found["state"]}')
        if rest == ['link']:
            if any(entry['link'] in (payload['link'], payload['link'].lower()) for entry in found['links']):
                return answer({**found, 'added': False})
            stored = payload['link'].lower() if payload['link'].startswith('claim:') else payload['link']  # the station lowercases a claim: link
            found['links'].append({'link': stored, 'added_by': me, 'added': self.clock})
            return answer({**found, 'added': True})
        held = found['claim']
        found.update(state='done' if rest == ['done'] else 'dropped', closed=self.clock, closed_by=me,
                     closer_name=self.users[me]['name'], outcome=payload.get('outcome'), claim=None)
        return answer({**found, **({'released': held['holder_name']} if held else {})})

    def board_counts(self, me):
        """GET /api/ships/me/board: per current room with open items, waiting and taken; oldest waiting first."""
        rows = []
        for room in self.rooms.values():
            if me not in room['member_ids'] or any(r.get('linked_room_id') == room['id'] for r in self.rooms.values()):
                continue
            open_items = [i for i in self.board.get(room['id'], []) if i['state'] == 'open']
            waiting = [i for i in open_items if not i.get('claim')]
            if open_items:
                oldest = min((i['created'] for i in waiting), default=None)
                rows.append(((oldest is None, oldest or 0, room['id']),
                             {'room_id': room['id'], 'title': room['title'], 'waiting': len(waiting), 'taken': len(open_items) - len(waiting)}))
        return {'rooms': [row for _, row in sorted(rows, key=lambda pair: pair[0])]}

    def __call__(self, method, url, headers, data):
        if self.down:
            raise OSError('station unreachable')
        self.requests.append({'method': method, 'path': urlsplit(url).path, 'query': urlsplit(url).query, 'body': json.loads(data) if data else None,
                              'presence': {k: v for k, v in headers.items() if k.startswith('x-superyak-')}})
        parts = urlsplit(url)
        path, query = parts.path, parse_qs(parts.query)
        key = headers.get('authorization', '').removeprefix('Bearer ')
        me = self.keys.get(key)
        if me is None:
            return 401, b'{"error": "Invalid ship key"}'

        def ok(value, status=200):
            return status, json.dumps(value).encode()
        if self.board_missing and (path == '/api/ships/me/board' or '/board' in path.split('/api/chats/', 1)[-1]):
            return self.board_missing, b'{"detail": "Not Found"}'
        segments = [unquote(s) for s in path.strip('/').split('/')]
        if method == 'GET' and path == '/api/me':
            return ok(self.users[me])
        if method == 'GET' and path == '/api/chats':  # breakouts S12: one closed over 7 days ago leaves the list
            return ok([self.listed(r) for r in self.rooms.values() if me in r['member_ids']
                       and not (self.closed(r['id']) is not None and self.clock - self.closed(r['id']) > 7 * DAY)])
        if segments[:2] == ['api', 'chats'] and len(segments) >= 3:
            room = self.rooms.get(segments[2])
            if room is None or me not in room['member_ids']:
                return 404, b'{"error": "Not found"}'
            if method == 'GET' and len(segments) == 3:
                return ok(self.view(room))
            if segments[3:4] == ['board']:  # work board 5.1
                return self.board_route(me, room, method, segments[4:], json.loads(data) if data else {})
            if method == 'POST' and segments[3:] in (['claims'], ['claims', 'release']) and self.closed(room['id']) is not None:
                return 409, json.dumps({'error': BREAKOUT_CLOSED}).encode()  # breakouts S4
            if method == 'POST' and segments[3:] == ['messages']:
                payload = json.loads(data)
                ticket_id = payload.get('ticket_id')
                reply_to = payload.get('reply_to')
                existing = next((m for m in room['messages'] if m['author_id'] == me and m['client_message_id'] == payload['client_message_id']), None)
                if ':' in room['id'] and reply_to is not None:
                    return 400, b'{"error": "Replies are labelled in local rooms only"}'
                if existing is not None:
                    same = existing['body'] == payload['body'] and self.replies.get(existing['id']) == reply_to
                    return ok(dict(existing, replayed=True), 201) if same else (409, b'{"error": "Message ID already used with different text"}')
                if self.closed(room['id']) is not None:  # breakouts S4: a retry still replays, as on the station
                    return 409, json.dumps({'error': BREAKOUT_CLOSED}).encode()
                if reply_to is not None and not any(m['id'] == reply_to for m in room['messages']):
                    return 400, b'{"error": "reply_to is not a message in this room"}'
                if ticket_id is not None:
                    ticket = self.tickets.get(ticket_id)
                    ticket_room = next((r['id'] for r in self.rooms.values() for m in r['messages'] if ticket and m['id'] == ticket['message_id']), None)
                    if (ticket is None or ticket['ship_id'] != me or ticket['status'] != 'running' or ticket_room != room['id']
                            or ticket_id in self.sources.values() or ticket_id in self.label_refusals):
                        return 409, b'{"error": "This ticket cannot label a message here"}'
                message = self.say(room['id'], self.users[me], payload['body'], payload['client_message_id'])
                if message is None:
                    return 409, b'{"error": "Message ID already used with different text"}'
                if ticket_id is not None:
                    self.sources[message['id']] = ticket_id
                if reply_to is not None:
                    self.replies[message['id']] = reply_to
                waiting = self.deferred_here.get(room['id']) if reply_to is None else None
                return ok(dict(message, replayed=False, **({'deferred_here': waiting} if waiting else {})), 201)
            if segments[3:] == ['claims']:
                if method == 'GET':
                    return ok(self.claims.get(room['id'], []))
                payload = json.loads(data)
                key = payload['key'].lower()
                held = next((c for c in self.claims.get(room['id'], []) if c['key'] == key), None)
                if held and held['holder_id'] != me:
                    return 409, json.dumps({'error': f'{held["holder_name"]} holds `{key}` until 18:00 UTC'}).encode()
                made = {'id': f'c-{key}', 'room_id': room['id'], 'key': key, 'holder_id': me, 'holder_name': self.users[me]['name'],
                        'note': payload.get('note') or '', 'created': self.clock, 'expires': self.clock + 60 * payload.get('minutes', 240)}
                item = next((i for i in self.board.get(room['id'], []) if i['key'] == key), None)
                if item is not None:  # work board 5.6: _claim_json's `board`, only for an item's key
                    made['board'] = item['state']
                self.claims[room['id']] = [c for c in self.claims.get(room['id'], []) if c['key'] != key] + [made]
                return ok(made, 201)
            if method == 'POST' and segments[3:] == ['claims', 'release']:
                key = json.loads(data)['key'].lower()
                self.claims[room['id']] = [c for c in self.claims.get(room['id'], []) if c['key'] != key]
                return ok({'released': key})
        if method == 'GET' and path == '/api/mentions':
            after, rows = int(query.get('after', ['0'])[0]), []  # one page holds at most 50, as on the station
            for row in self.mention_rows:
                if row['user_id'] == me and row['seq'] > after and me in self.rooms[row['room_id']]['member_ids']:
                    message = next(m for m in self.rooms[row['room_id']]['messages'] if m['id'] == row['message_id'])
                    rows.append({'seq': row['seq'], 'message_id': message['id'], 'room_id': row['room_id'], 'body': message['body'],
                                 'created': message['created'], 'author': self.users[message['author_id']],
                                 **({'breakout': True} if row['room_id'] in self.breakouts else {})})
            return ok(rows[:50])
        if method == 'POST' and path == '/api/ships/me/unread':
            payload = json.loads(data)
            name, limit = payload.get('cursor') or 'default', payload.get('limit', 30)
            self.unread_calls.append(dict(payload))
            flag = parse_qs(parts.query, keep_blank_values=True).get('breakouts')
            if flag not in (None, ['mentions']):  # breakouts S6: the opt-in; any other value gets 400
                return 400, b'{"error": "breakouts is mentions, or left out"}'
            return ok(self.unread_page(me, name, limit, flag is not None))
        if method == 'POST' and path == '/api/ships/me/rooms':
            return self.open_breakout(me, json.loads(data))
        if method == 'POST' and segments[:4] == ['api', 'ships', 'me', 'rooms'] and len(segments) == 6 and segments[5] in ('leave', 'close'):
            return self.end_breakout(me, segments[4], segments[5])
        if method == 'PUT' and segments[:4] == ['api', 'ships', 'me', 'rooms'] and len(segments) == 6 and segments[5] == 'brief':
            return self.ship_brief(me, segments[4], json.loads(data))
        if method == 'POST' and path == '/api/ships/me/unread/advance':
            payload = json.loads(data)
            name = payload.get('cursor') or 'default'
            position = self.cursors.setdefault((me, name), max([p for (s, _), p in self.cursors.items() if s == me], default=0))
            self.cursors[(me, name)] = max(position, payload['to'])
            return ok({'cursor': name, 'position': self.cursors[(me, name)]})
        if method == 'DELETE' and path == '/api/ships/me/key':
            self.keys.pop(key)
            return ok({'ok': True})
        if method == 'POST' and path == '/api/ships/me/tickets':
            asked = json.loads(data)
            self.ticket_bodies.append(asked)
            message_id, decisions = asked['message_id'], asked.get('decisions') == ['defer', 'answered']
            if message_id in self.ticket_override:
                status, payload = self.ticket_override[message_id]
                return status, json.dumps(payload).encode()
            if decisions and message_id in self.decide:
                return ok(self.decide[message_id])
            message = next((m for r in self.rooms.values() if me in r['member_ids'] for m in r['messages'] if m['id'] == message_id), None)
            if message is None:
                return 404, b'{"error": "Not found"}'
            if self.closed(message['room_id']) is not None:  # breakouts S4: any of a closed breakout's messages
                return 422, json.dumps({'error': BREAKOUT_CLOSED}).encode()
            existing = next((t for t in self.tickets.values() if t['ship_id'] == me and t['message_id'] == message_id), None)
            if existing:
                return (409, b'{"error": "This message has already been answered"}') if existing['status'] == 'finished' else ok(dict(existing, decision='run') if decisions else existing)
            ship, author = self.users[me], self.users[message['author_id']]
            mentioned = any(r['message_id'] == message_id and r['user_id'] == me for r in self.mention_rows)
            build = bool(ship['owner_id'] and mentioned and author['kind'] == 'person' and author['id'] == ship['owner_id'])
            ticket = {'id': f't{len(self.tickets) + 1}', 'ship_id': me, 'message_id': message_id, 'mode': 'build' if build else 'read',
                      'basis': 'owner' if build else 'none', 'root_id': ship['owner_id'] if build else None,
                      'root_name': self.users[ship['owner_id']]['name'] if build else None, 'chain': [], 'hops': 0,
                      'instructions': [], 'blocks': self.blocks.get(me, ''), 'footer': f'Builder for {self.users[ship["owner_id"]]["name"]} (owner)' if build else '',
                      'status': 'running'}
            self.tickets[ticket['id']] = ticket
            return ok(dict(ticket, decision='run') if decisions else ticket)
        if method == 'GET' and path == '/api/ships/me/instructions':
            return ok(self.instruction_state.get(me) or {'instructions': [], 'layers': [], 'blocks': self.blocks.get(me, '')})
        if method == 'POST' and path == '/api/ships/me/drafts':
            payload = json.loads(data)
            self.drafts.append((payload['title'], payload['body']))
            return ok({'id': 'L9', 'title': payload['title'], 'version': 1, 'state': 'draft', 'drafted_by': me}, 201)
        if method == 'POST' and segments[:4] == ['api', 'ships', 'me', 'tickets'] and segments[5:] == ['finish']:
            ticket = self.tickets.get(segments[4])
            if ticket is None or ticket['ship_id'] != me:
                return 404, b'{"error": "Not found"}'
            ticket['status'] = 'finished'
            return ok(ticket)
        if method == 'GET' and path == '/api/ships/directory':
            return ok(self.directory_rows)
        if method == 'POST' and path == '/api/ships/me/watch':
            name, payload = headers.get('x-superyak-session'), json.loads(data)
            if not name:
                return 400, b'{"error": "Watching needs this session\'s name in the x-superyak-session header"}'
            minutes = payload.get('minutes', 20)
            if minutes:
                self.watches[(me, name)] = {'minutes': minutes, 'writable': payload.get('writable', False), 'label': payload.get('label')}
            else:
                self.watches.pop((me, name), None)
            held = self.watches.get((me, name))
            return ok({'name': name, 'on_watch': held is not None, 'watch_until': self.clock + minutes * 60 if held else None,
                       'writable': bool(held and held['writable']), 'label': held['label'] if held else None})
        if method == 'GET' and path == '/api/ships/me/board':
            if self.board_refusal is not None:
                return self.board_refusal[0], json.dumps({'error': self.board_refusal[1]}).encode()
            return ok(self.board_counts(me))
        return 403, b'{"error": "Ship keys cannot use this route"}'


@pytest.fixture
def station():
    fake = FakeStation()
    andy = fake.user('andy', 'Andy')
    jenn = fake.user('jenn', 'Jenn')
    serenity = fake.user('serenity', 'Serenity', 'ship', andy['id'], key='serenity-key')
    return fake, andy, jenn, serenity


@pytest.fixture
def ship_config(station, tmp_path):
    fake, andy, jenn, serenity = station
    return {'station': 'http://station.test', 'origin': None, 'ship': 'serenity', 'ship_id': serenity['id'], 'ship_name': 'Serenity',
            'owner_id': andy['id'], 'key': 'serenity-key', 'workspace': str(tmp_path / 'repo'), 'machine': 'andy-mac', 'created': 1.0}
