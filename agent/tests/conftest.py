import json
from urllib.parse import parse_qs, unquote, urlsplit
import pytest


class FakeStation:
    """Just enough of the station API for ship-side tests. The real station is exercised
    end to end in peer/tests/test_ship_agent.py."""
    def __init__(self):
        self.users, self.rooms, self.mention_rows, self.keys = {}, {}, [], {}
        self.clock, self.counter, self.down = 1000.0, 0, False
        self.tickets, self.sources, self.ticket_override, self.label_refusals = {}, {}, {}, set()
        self.blocks, self.instruction_state, self.drafts = {}, {}, []

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
            if target:
                self.mention_rows.append({'seq': len(self.mention_rows) + 1, 'message_id': message['id'], 'room_id': room_id, 'user_id': target['id']})
        return message

    def view(self, room):
        last = max([m['created'] for m in room['messages']], default=0.0)
        return {'id': room['id'], 'title': room['title'], 'owner_id': room.get('owner_id'), 'linked_room_id': room.get('linked_room_id'),
                'member_ids': room['member_ids'], 'last_activity': last,
                'members': [self.users[i] for i in room['member_ids'] if i in self.users], 'messages': [dict(m, source=self.source_of(m)) for m in room['messages']]}

    def source_of(self, message):
        author = self.users.get(message['author_id'], {})
        if author.get('kind') != 'ship':
            return None
        ticket = self.tickets.get(self.sources.get(message['id']))
        if ticket is None:
            return {'kind': 'post'}
        return {'kind': 'run', 'mode': ticket['mode'], 'basis': ticket['basis'], 'root_name': ticket['root_name'], 'answering': ticket['message_id']}

    def __call__(self, method, url, headers, data):
        if self.down:
            raise OSError('station unreachable')
        parts = urlsplit(url)
        path, query = parts.path, parse_qs(parts.query)
        key = headers.get('authorization', '').removeprefix('Bearer ')
        me = self.keys.get(key)
        if me is None:
            return 401, b'{"error": "Invalid ship key"}'

        def ok(value, status=200):
            return status, json.dumps(value).encode()
        segments = [unquote(s) for s in path.strip('/').split('/')]
        if method == 'GET' and path == '/api/me':
            return ok(self.users[me])
        if method == 'GET' and path == '/api/chats':
            return ok([{k: v for k, v in self.view(r).items() if k != 'messages'} for r in self.rooms.values() if me in r['member_ids']])
        if segments[:2] == ['api', 'chats'] and len(segments) >= 3:
            room = self.rooms.get(segments[2])
            if room is None or me not in room['member_ids']:
                return 404, b'{"error": "Not found"}'
            if method == 'GET' and len(segments) == 3:
                return ok(self.view(room))
            if method == 'POST' and segments[3:] == ['messages']:
                payload = json.loads(data)
                ticket_id = payload.get('ticket_id')
                existing = next((m for m in room['messages'] if m['author_id'] == me and m['client_message_id'] == payload['client_message_id']), None)
                if existing is not None:
                    return ok(existing, 201) if existing['body'] == payload['body'] else (409, b'{"error": "Message ID already used with different text"}')
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
                return ok(message, 201)
        if method == 'GET' and path == '/api/mentions':
            after, rows = int(query.get('after', ['0'])[0]), []  # one page holds at most 50, as on the station
            for row in self.mention_rows:
                if row['user_id'] == me and row['seq'] > after and me in self.rooms[row['room_id']]['member_ids']:
                    message = next(m for m in self.rooms[row['room_id']]['messages'] if m['id'] == row['message_id'])
                    rows.append({'seq': row['seq'], 'message_id': message['id'], 'room_id': row['room_id'], 'body': message['body'],
                                 'created': message['created'], 'author': self.users[message['author_id']]})
            return ok(rows[:50])
        if method == 'DELETE' and path == '/api/ships/me/key':
            self.keys.pop(key)
            return ok({'ok': True})
        if method == 'POST' and path == '/api/ships/me/tickets':
            message_id = json.loads(data)['message_id']
            if message_id in self.ticket_override:
                status, payload = self.ticket_override[message_id]
                return status, json.dumps(payload).encode()
            message = next((m for r in self.rooms.values() if me in r['member_ids'] for m in r['messages'] if m['id'] == message_id), None)
            if message is None:
                return 404, b'{"error": "Not found"}'
            existing = next((t for t in self.tickets.values() if t['ship_id'] == me and t['message_id'] == message_id), None)
            if existing:
                return (409, b'{"error": "This message has already been answered"}') if existing['status'] == 'finished' else ok(existing)
            ship, author = self.users[me], self.users[message['author_id']]
            mentioned = any(r['message_id'] == message_id and r['user_id'] == me for r in self.mention_rows)
            build = bool(ship['owner_id'] and mentioned and author['kind'] == 'person' and author['id'] == ship['owner_id'])
            ticket = {'id': f't{len(self.tickets) + 1}', 'ship_id': me, 'message_id': message_id, 'mode': 'build' if build else 'read',
                      'basis': 'owner' if build else 'none', 'root_id': ship['owner_id'] if build else None,
                      'root_name': self.users[ship['owner_id']]['name'] if build else None, 'chain': [], 'hops': 0,
                      'instructions': [], 'blocks': self.blocks.get(me, ''), 'footer': f'Builder for {self.users[ship["owner_id"]]["name"]} (owner)' if build else '',
                      'status': 'running'}
            self.tickets[ticket['id']] = ticket
            return ok(ticket)
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
