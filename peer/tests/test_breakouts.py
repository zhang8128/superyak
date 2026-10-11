"""Breakout rooms (docs/superpowers/specs/2026-10-11-breakout-rooms-design.md): a ship opens a room of its own with
sibling ships its owner already put together in a room. Ships only (D12): no person and never `_station` is a
member. Membership is fixed at creation; a member may leave, the owner leaving closes it, and one check decides
whether a breakout is closed."""
import pytest
from fastapi.testclient import TestClient
from test_presence import HEADERS, docked, say, ship_client

DAY = 86400
REFUSED = "Every invited ship must be one of your owner's ships that already shares a room with you"


class Fleet:
    """Patient stands in for Andy: three of his ships in one room he owns, as in "Superyak: all hands"."""
    def __init__(self, env, names=('serenity', 'rio-grande', 'tardis')):
        self.app, self.clients, self.users, self.clock = env
        self.store = self.app.state.store
        self.andy = self.clients[0]
        self.ships, self.keys = {}, {}
        for name in names:
            self.dock(name)
        self.hands = self.room(self.andy, 'Superyak: all hands', names)

    def dock(self, name, owner=0):
        ship, key = docked(self.store, self.users[owner]['id'], name)
        self.ships[name], self.keys[name] = ship, key
        return ship

    def id(self, name):
        return self.ships[name]['id']

    def ship(self, name, **headers):
        return ship_client(self.app, self.keys[name], **headers)

    def room(self, person, title, names, *people):
        response = person.post('/api/chats', json={'title': title, 'member_ids': [self.id(n) for n in names] + list(people)})
        assert response.status_code == 201, response.text
        return response.json()['id']

    def open(self, name, title, ships):
        return self.ship(name).post('/api/ships/me/rooms', json={'title': title, 'ships': list(ships)})

    def opened(self, name, title, ships):
        response = self.open(name, title, ships)
        assert response.status_code == 201, response.text
        return response.json()['id']

    def rows(self, sql, *args):
        with self.store.transaction() as db:
            return [tuple(r) for r in db.execute(sql, args)]


def counts(fleet):
    return fleet.rows('SELECT (SELECT count(*) FROM rooms), (SELECT count(*) FROM breakouts), (SELECT count(*) FROM room_members)')


# R1 ---------------------------------------------------------------------------------------------------------------

def test_only_an_owned_ships_key_opens_a_breakout(env):
    """R1: a signed-in person, a request with no key and an ownerless ship get 403 and nothing is made; a ship with
    an owner opens an ordinary local room that it owns and is in, with the named ships, marked as a breakout."""
    fleet = Fleet(env)
    odo = fleet.store.create_station_ship('odo', 'Odo')
    fleet.room(fleet.andy, 'Ops', ['serenity', 'rio-grande'], odo['id'])
    odo_client = ship_client(fleet.app, fleet.store.issue_ship_key(odo['id']))
    nobody = TestClient(fleet.app, base_url='http://testserver', headers={'origin': 'http://testserver'})
    before, body = counts(fleet), {'title': 'Sync', 'ships': ['rio-grande']}
    for client in (fleet.andy, nobody, odo_client):
        refused = client.post('/api/ships/me/rooms', json=body)
        assert refused.status_code == 403, refused.text
    assert counts(fleet) == before
    room = fleet.open('serenity', 'Sync', ['rio-grande'])
    assert room.status_code == 201, room.text
    room = room.json()
    assert (room['owner_id'], room['title'], room['linked_room_id']) == (fleet.id('serenity'), 'Sync', None)
    assert room['member_ids'] == sorted([fleet.id('serenity'), fleet.id('rio-grande')])
    assert room['breakout'] == {'creator': fleet.id('serenity'), 'closed': None}
    shown = fleet.ship('rio-grande').get(f'/api/chats/{room["id"]}').json()
    assert shown['breakout'] == room['breakout'] and shown['brief'] is None
    assert [m['username'] for m in shown['members']] == sorted(['serenity', 'rio-grande'], key=lambda n: fleet.id(n))
    listed = {r['id']: r for r in fleet.ship('rio-grande').get('/api/chats').json()}
    assert listed[room['id']]['breakout'] == room['breakout'] and 'breakout' not in listed[fleet.hands]


# R2 ---------------------------------------------------------------------------------------------------------------

def a_person(fleet):
    fleet.room(fleet.andy, 'Ward', ['serenity'], fleet.users[1]['id'])
    return ['doctor']


def the_owner(fleet):
    return ['patient']


def an_ownerless_ship(fleet):
    odo = fleet.store.create_station_ship('odo', 'Odo')
    fleet.room(fleet.andy, 'Ops', ['serenity'], odo['id'])
    return ['odo']


def the_system_author(fleet):
    return ['_station']


def another_owners_ship(fleet):
    worf = fleet.dock('worf', owner=1)
    fleet.room(fleet.andy, 'Ops', ['serenity'], worf['id'])
    return ['worf']


def a_sibling_met_only_in_a_breakout(fleet):
    fleet.dock('defiant')
    lab = fleet.room(fleet.andy, 'Lab', ['serenity', 'defiant'])
    fleet.opened('serenity', 'Pair', ['defiant'])
    assert fleet.andy.delete(f'/api/chats/{lab}/participants/{fleet.id("defiant")}').status_code == 200
    return ['defiant']


def a_sibling_only_in_a_superseded_room(fleet):
    fleet.dock('defiant')
    lab = fleet.room(fleet.andy, 'Lab', ['serenity', 'defiant'])
    newer = fleet.andy.post(f'/api/chats/{lab}/participants', json={'member_ids': [fleet.users[1]['id']]}).json()['id']
    assert fleet.andy.delete(f'/api/chats/{newer}/participants/{fleet.id("defiant")}').status_code == 200
    return ['defiant']


def an_unknown_name(fleet):
    return ['nobody']


def two_invitees_who_share_no_room(fleet):
    fleet.dock('defiant')
    fleet.room(fleet.andy, 'Lab', ['serenity', 'defiant'])
    return ['rio-grande', 'defiant']


@pytest.mark.parametrize('invite', [a_person, the_owner, an_ownerless_ship, the_system_author, another_owners_ship,
                                    a_sibling_met_only_in_a_breakout, a_sibling_only_in_a_superseded_room,
                                    an_unknown_name, two_invitees_who_share_no_room])
def test_invitees_are_the_same_owners_ships_already_put_together(env, invite):
    """R2: each refusal has the same 400 message, so it never tells a person from an unknown name or another owner's
    ship, and nothing is created; a refused invitee beside a good one refuses the whole request."""
    fleet = Fleet(env)
    ships = invite(fleet)
    before = counts(fleet)
    for asked in (ships, ['rio-grande', *ships]):
        refused = fleet.open('serenity', 'Sync', asked)
        assert (refused.status_code, refused.json()) == (400, {'error': REFUSED}), asked
    assert counts(fleet) == before
    assert fleet.open('serenity', 'Sync', ['rio-grande', 'tardis']).status_code == 201   # siblings put together


# R3 ---------------------------------------------------------------------------------------------------------------

def test_no_person_is_ever_a_breakout_member(env):
    """R3: not at creation, and not later through the person-only membership routes, by a person (who is never a
    member, so the room is not found) or by the owning ship (a ship key can't use them)."""
    fleet = Fleet(env)
    fleet.room(fleet.andy, 'Ward', ['serenity'], fleet.users[1]['id'])
    for person in ('patient', 'doctor', '_station'):
        assert fleet.open('serenity', 'Sync', ['rio-grande', person]).status_code == 400
    room = fleet.opened('serenity', 'Sync', ['rio-grande'])
    andy, doctor = fleet.users[0]['id'], fleet.users[1]['id']
    assert fleet.andy.post(f'/api/chats/{room}/participants', json={'member_ids': [andy]}).status_code == 404
    assert fleet.andy.delete(f'/api/chats/{room}/participants/{fleet.id("rio-grande")}').status_code == 404
    assert fleet.andy.get(f'/api/chats/{room}').status_code == 404
    owner = fleet.ship('serenity')
    assert owner.post(f'/api/chats/{room}/participants', json={'member_ids': [doctor]}).status_code == 403
    assert owner.delete(f'/api/chats/{room}/participants/{fleet.id("rio-grande")}').status_code == 403
    assert owner.post('/api/chats', json={'title': 'Mine', 'member_ids': [andy]}).status_code == 403
    assert fleet.rows('''SELECT users.kind FROM room_members JOIN users ON users.id=room_members.user_id
                         WHERE room_members.room_id IN (SELECT room_id FROM breakouts)''') == [('ship',), ('ship',)]
    assert room not in {r['id'] for r in fleet.andy.get('/api/chats').json()}


# R9 ---------------------------------------------------------------------------------------------------------------

def test_breakout_titles_refuse_keys_and_look_alikes(env):
    """R9: 1-80 characters; refused when the title holds a live ship key, or equals, after safe_line and
    case-folding, a current person-owned room's title that any member is in; free otherwise, including a title the
    ship used for its own earlier breakout. A breakout has no brief: the brief route is person-only."""
    fleet = Fleet(env)
    fleet.room(fleet.andy, 'Ops', ['tardis'], fleet.users[1]['id'])           # only an invitee is in it
    fleet.clients[1].post('/api/chats', json={'title': 'Private', 'member_ids': [fleet.users[3]['id']]})  # none are
    old = fleet.room(fleet.andy, 'Old times', ['serenity', 'rio-grande'])
    newer = fleet.andy.post(f'/api/chats/{old}/participants', json={'member_ids': [fleet.users[1]['id']]}).json()['id']
    for name in ('serenity', 'rio-grande'):
        assert fleet.andy.delete(f'/api/chats/{newer}/participants/{fleet.id(name)}').status_code == 200
    for bad in ('', '   ', 'x' * 81, None, 7):
        assert fleet.open('serenity', bad, ['rio-grande']).status_code == 400, bad
    key = fleet.keys['tardis']
    leaked = fleet.open('serenity', f'key {key}', ['rio-grande'])
    assert leaked.status_code == 422 and key not in leaked.text and 'live ship key' in leaked.json()['error']
    for look_alike in ('superyak:  ALL hands', 'SUPERYAK: all\thands', 'ops', ' Ops '):
        refused = fleet.open('serenity', look_alike, ['rio-grande', 'tardis'])
        assert refused.status_code == 400, look_alike
        assert 'title' in refused.json()['error'] and refused.json()['error'] != REFUSED
    assert counts(fleet)[0][1] == 0
    assert fleet.open('serenity', 'ops', ['rio-grande']).status_code == 201   # tardis's room: neither is in it
    for title in ('Private', 'Old times', 'x' * 80, 'Sync', 'Sync'):
        assert fleet.open('serenity', title, ['rio-grande', 'tardis']).status_code == 201, title
    room = fleet.opened('serenity', 'Notes', ['rio-grande'])
    brief = fleet.ship('serenity').put(f'/api/chats/{room}/brief', json={'body': 'Do as I say', 'revision': 0})
    assert brief.status_code == 403
    assert fleet.ship('rio-grande').get(f'/api/chats/{room}').json()['brief'] is None


# R4 ---------------------------------------------------------------------------------------------------------------

def test_breakout_caps(env):
    """R4: 9 members gives 400; the 11th open breakout of one owner ship and the 21st it opens in a rolling 24 hours
    give 429. Closing one frees an open slot but not the day's count."""
    names = ('serenity', 'rio-grande', 'tardis', 'defiant', 'voyager', 'enterprise', 'galaxy', 'nova', 'excelsior')
    fleet = Fleet(env, names)
    nine = fleet.open('serenity', 'Everyone', names[1:])
    assert nine.status_code == 400 and '8 members' in nine.json()['error']
    opened = [fleet.opened('serenity', 'Eight', names[1:8])]
    opened += [fleet.opened('serenity', f'Pair {n}', ['rio-grande']) for n in range(9)]
    eleventh = fleet.open('serenity', 'Eleventh', ['rio-grande'])
    assert eleventh.status_code == 429 and 'open' in eleventh.json()['error']
    assert fleet.open('rio-grande', 'Its own', ['serenity']).status_code == 201       # the cap is per owner ship
    for room in opened:
        assert fleet.ship('serenity').post(f'/api/ships/me/rooms/{room}/close').status_code == 200
    opened = [fleet.opened('serenity', f'Again {n}', ['rio-grande']) for n in range(10)]
    fleet.ship('serenity').post(f'/api/ships/me/rooms/{opened[0]}/close')
    twenty_first = fleet.open('serenity', 'One more', ['rio-grande'])
    assert twenty_first.status_code == 429 and '24 hours' in twenty_first.json()['error']
    fleet.clock[0] += DAY
    assert fleet.open('serenity', 'Next day', ['rio-grande']).status_code == 201


# R5 ---------------------------------------------------------------------------------------------------------------

def ticket(client, message_id, decisions=True):
    return client.post('/api/ships/me/tickets', json={'message_id': message_id, **({'decisions': ['defer', 'answered']} if decisions else {})})


def watch(fleet, *names):
    for name in names:
        assert fleet.ship(name, **HEADERS).post('/api/ships/me/watch', json={'minutes': 120, 'writable': True}).status_code == 200


def deferrals(fleet, room):
    return sorted(fleet.rows('SELECT deferrals.ship_id FROM deferrals JOIN messages ON messages.id=deferrals.message_id WHERE messages.room_id=?', room))


def test_membership_is_fixed_and_leaving_works(env):
    """R5: any member may leave, which drops its own deferrals there and no one else's; the room is then not found
    for it, so a ticket for the room's mention gets 404 (the watcher's half, a 404 treated as done, is build step 2);
    the owner leaving closes the room. Only a member leaves, and only a breakout."""
    fleet = Fleet(env)
    room = fleet.opened('serenity', 'Sync', ['rio-grande', 'tardis'])
    watch(fleet, 'rio-grande', 'tardis')
    asked = say(fleet.ship('serenity'), room, 'a', '@rio-grande @tardis can you check?')
    for name in ('rio-grande', 'tardis'):
        assert ticket(fleet.ship(name), asked['id']).json()['decision'] == 'defer'
    assert fleet.andy.post(f'/api/ships/me/rooms/{room}/leave').status_code == 403
    assert fleet.ship('serenity').post(f'/api/ships/me/rooms/{fleet.hands}/leave').status_code == 400
    rio = fleet.ship('rio-grande')
    left = rio.post(f'/api/ships/me/rooms/{room}/leave')
    assert (left.status_code, left.json()) == (200, {'room_id': room, 'left': True, 'closed': None})
    assert deferrals(fleet, room) == [(fleet.id('tardis'),)]
    for refused in (rio.get(f'/api/chats/{room}'), ticket(rio, asked['id']), ticket(rio, asked['id'], decisions=False),
                    rio.post(f'/api/chats/{room}/messages', json={'client_message_id': 'b', 'body': 'back'}),
                    rio.post(f'/api/ships/me/rooms/{room}/leave'), rio.post(f'/api/ships/me/rooms/{room}/close')):
        assert refused.status_code == 404, refused.text
    assert room not in {r['id'] for r in rio.get('/api/chats').json()}
    assert fleet.ship('tardis').get(f'/api/chats/{room}').json()['member_ids'] == sorted([fleet.id('serenity'), fleet.id('tardis')])
    fleet.clock[0] += 60
    owner = fleet.ship('serenity').post(f'/api/ships/me/rooms/{room}/leave')
    assert (owner.status_code, owner.json()) == (200, {'room_id': room, 'left': True, 'closed': fleet.clock[0]})
    shown = fleet.ship('tardis').get(f'/api/chats/{room}').json()
    assert shown['breakout']['closed'] == fleet.clock[0] and shown['member_ids'] == [fleet.id('tardis')]
    assert deferrals(fleet, room) == []
    assert say_refused(fleet.ship('tardis'), room).status_code == 409


# R6 ---------------------------------------------------------------------------------------------------------------

CLOSED = {'error': 'This breakout is closed'}


def say_refused(client, room, body='more'):
    return client.post(f'/api/chats/{room}/messages', json={'client_message_id': f'late-{body}', 'body': body})


def quiet_breakout(fleet):
    """A breakout whose last ordinary message is a mention that both invitees' watches deferred, followed by a station
    notice and a claim (neither is activity). Returns the room, the mention and when its seven quiet days end."""
    room = fleet.opened('serenity', 'Sync', ['rio-grande', 'tardis'])
    fleet.clock[0] += DAY
    watch(fleet, 'rio-grande', 'tardis')
    asked = say(fleet.ship('serenity'), room, 'a', '@rio-grande @tardis can you check?')
    last = fleet.clock[0]
    for name in ('rio-grande', 'tardis'):
        assert ticket(fleet.ship(name), asked['id']).json()['decision'] == 'defer'
    fleet.clock[0] += 31 * 60
    assert ticket(fleet.ship('rio-grande'), asked['id']).json()['decision'] == 'defer'   # posts the station notice
    fleet.clock[0] = last + 5 * DAY
    assert fleet.ship('tardis').post(f'/api/chats/{room}/claims', json={'key': 'spec:d7', 'minutes': 60}).status_code == 201
    kinds = fleet.rows('SELECT message_kinds.kind FROM message_kinds JOIN messages ON messages.id=message_kinds.message_id WHERE room_id=?', room)
    assert sorted(kinds) == [('claim',), ('notice',)]
    return room, asked, last + 7 * DAY


def first_look_list(fleet, room, asked, ends):
    assert {r['id']: r for r in fleet.ship('tardis').get('/api/chats').json()}[room]['breakout']['closed'] == ends


def first_look_get(fleet, room, asked, ends):
    shown = fleet.ship('tardis').get(f'/api/chats/{room}').json()
    assert shown['breakout']['closed'] == ends and asked['id'] in [m['id'] for m in shown['messages']]   # still readable


def first_look_post(fleet, room, asked, ends):
    assert say_refused(fleet.ship('tardis'), room).json() == CLOSED


def first_look_claim(fleet, room, asked, ends):
    refused = fleet.ship('tardis').post(f'/api/chats/{room}/claims', json={'key': 'spec:d8'})
    assert (refused.status_code, refused.json()) == (409, CLOSED)


def first_look_release(fleet, room, asked, ends):
    refused = fleet.ship('serenity').post(f'/api/chats/{room}/claims/release', json={'key': 'spec:d7'})
    assert (refused.status_code, refused.json()) == (409, CLOSED)


def first_look_ticket(fleet, room, asked, ends):
    refused = ticket(fleet.ship('rio-grande'), asked['id'])
    assert (refused.status_code, refused.json()) == (422, CLOSED)


def first_look_unread(fleet, room, asked, ends):
    got = fleet.ship('rio-grande').post('/api/ships/me/unread', json={'cursor': 'first-look'}).json()['messages']
    item = {m['message_id']: m for m in got}[asked['id']]
    assert item['mentions_me'] and 'deferred' not in item


def first_look_mentions(fleet, room, asked, ends):
    assert asked['id'] in [m['message_id'] for m in fleet.ship('rio-grande').get('/api/mentions').json()]


def first_look_open_count(fleet, room, asked, ends):
    assert fleet.open('serenity', 'Eleventh', ['rio-grande']).status_code == 201


@pytest.mark.parametrize('first_look', [first_look_list, first_look_get, first_look_post, first_look_claim,
                                        first_look_release, first_look_ticket, first_look_unread, first_look_mentions,
                                        first_look_open_count])
def test_one_closed_check_on_every_path(env, first_look):
    """R6: seven days without an ordinary message close a breakout; claim and notice messages don't count. Whichever
    path sees it first saves the closure, as of when the seven days ended, and drops every member's deferrals there.
    Then posts, claims and releases get 409, tickets 422 with the breakout's own text, a claim at day 8 doesn't
    reopen it, it stays readable, and the open-rooms count skips it."""
    fleet = Fleet(env)
    room, asked, ends = quiet_breakout(fleet)
    fleet.clock[0] = ends - 2
    extra = [fleet.opened('serenity', f'Extra {n}', ['rio-grande']) for n in range(9)]   # ten open, with Sync
    fleet.clock[0] = ends - 1
    assert fleet.ship('tardis').get(f'/api/chats/{room}').json()['breakout']['closed'] is None
    assert len(deferrals(fleet, room)) == 2
    fleet.clock[0] = ends
    first_look(fleet, room, asked, ends)
    assert fleet.rows('SELECT closed FROM breakouts WHERE room_id=?', room) == [(ends,)]
    assert deferrals(fleet, room) == []
    fleet.clock[0] = ends + DAY                                               # day 8 and later: nothing reopens it
    assert say_refused(fleet.ship('serenity'), room).json() == CLOSED
    for name in ('serenity', 'tardis'):
        assert fleet.ship(name).post(f'/api/chats/{room}/claims', json={'key': 'spec:d9'}).json() == CLOSED
    assert fleet.ship('serenity').post(f'/api/chats/{room}/claims/release', json={'key': 'spec:d7'}).json() == CLOSED
    assert ticket(fleet.ship('tardis'), asked['id'], decisions=False).json() == CLOSED
    assert fleet.rows('SELECT closed FROM breakouts WHERE room_id=?', room) == [(ends,)]
    assert fleet.rows('SELECT count(*) FROM breakouts WHERE closed IS NULL') == [(len(extra) + (first_look is first_look_open_count),)]


def test_the_owner_closes_a_breakout_and_only_the_owner(env):
    """R6 by the owner's close route: any other member gets 403, a non-member 404, a person 403, and a room that
    isn't a breakout 400; closing again changes nothing; the deferrals there go at once."""
    fleet = Fleet(env)
    room = fleet.opened('serenity', 'Sync', ['rio-grande', 'tardis'])
    watch(fleet, 'rio-grande')
    asked = say(fleet.ship('serenity'), room, 'a', '@rio-grande can you check?')
    assert ticket(fleet.ship('rio-grande'), asked['id']).json()['decision'] == 'defer'
    fleet.dock('defiant')
    fleet.room(fleet.andy, 'Lab', ['defiant'])
    for client, status in ((fleet.ship('rio-grande'), 403), (fleet.ship('defiant'), 404), (fleet.andy, 403)):
        assert client.post(f'/api/ships/me/rooms/{room}/close').status_code == status
    assert fleet.ship('serenity').post(f'/api/ships/me/rooms/{fleet.hands}/close').status_code == 400
    assert deferrals(fleet, room) == [(fleet.id('rio-grande'),)]
    closed_at = fleet.clock[0]
    closed = fleet.ship('serenity').post(f'/api/ships/me/rooms/{room}/close')
    assert closed.status_code == 200 and closed.json()['breakout'] == {'creator': fleet.id('serenity'), 'closed': closed_at}
    assert deferrals(fleet, room) == []
    fleet.clock[0] += 60
    again = fleet.ship('serenity').post(f'/api/ships/me/rooms/{room}/close')
    assert again.status_code == 200 and again.json()['breakout']['closed'] == closed_at
    assert say_refused(fleet.ship('rio-grande'), room).json() == CLOSED
    assert ticket(fleet.ship('rio-grande'), asked['id']).json() == CLOSED
    assert fleet.ship('serenity').post(f'/api/ships/me/rooms/{room}/leave').json()['closed'] == closed_at
