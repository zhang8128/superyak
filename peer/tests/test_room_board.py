"""The work board (docs/superpowers/specs/2026-10-14-work-board-design.md), station side: items on a local room's
board, taken by claiming their keys, closed with an outcome, refused in 5.1's order, and carried with their claims to
the room that replaces theirs."""
import pytest
from fastapi.testclient import TestClient
from superyak_peer.common import uid
from superyak_peer.db import Store
from superyak_peer.__main__ import main as cli
from test_federation import deliver, two_peers  # noqa: F401 - two_peers is a fixture
from test_presence import HEADERS, docked, say, ship_client

DAY = 86400
ITEM_FIELDS = {'id', 'room_id', 'key', 'title', 'kind', 'state', 'posted_by', 'poster_name', 'created', 'closed',
               'closed_by', 'closer_name', 'outcome', 'links', 'claim'}
CLAIM_FIELDS = {'id', 'room_id', 'key', 'holder_id', 'holder_name', 'note', 'created', 'expires'}
# The spec's words, written out here so a constant in the module can't drift from them.
KEY_SHAPE = 'A claim key is 1-100 characters from a-z 0-9 . _ : / ! -, starting with a letter or digit, like spec:d7'
LINK_SHAPE = 'A link is message:<id>, branch:<name>, commit:<sha>, path:<path> or claim:<key>'
AT_NAME = "A board item can't name anyone with @; write the name without it"
WRITER = "Only this room's owner and the owner's own ships can post on its board"
DONE_BY = "Only the room's owner, the item's poster, or a holder who can post on this board can mark it done"
DROP_BY = "Only the item's poster or the room's owner can drop it"
REPLACED = 'This room was replaced by a newer linked room; use its board there'
NOT_HERE = 'message:<id> must name a message in this room'


class Station:
    """Patient stands in for Andy and owns the room "Superyak: all hands". In it: his ships serenity and rio-grande
    (board writers); Doctor, a person, and Doctor's ship defiant (members who aren't); and the ownerless odo and
    wormhole. Organizer is in no room."""
    SHIPS = ('serenity', 'rio-grande', 'defiant', 'odo', 'wormhole')

    def __init__(self, env):
        self.app, self.clients, self.users, self.clock = env
        self.store = self.app.state.store
        self.andy, self.doctor, self.outsider = self.clients[0], self.clients[1], self.clients[2]
        self.ships, self.keys = {}, {}
        for name, owner in (('serenity', 0), ('rio-grande', 0), ('defiant', 1)):
            self.ships[name], self.keys[name] = docked(self.store, self.users[owner]['id'], name)
        for name in ('odo', 'wormhole'):
            self.ships[name] = self.store.create_station_ship(name, name.title())
            self.keys[name] = self.store.issue_ship_key(self.ships[name]['id'])
        self.room = self.make_room('Superyak: all hands')

    def make_room(self, title):
        member_ids = [self.ships[n]['id'] for n in self.SHIPS] + [self.users[1]['id']]
        response = self.andy.post('/api/chats', json={'title': title, 'member_ids': member_ids})
        assert response.status_code == 201, response.text
        return response.json()['id']

    def id(self, name):
        return {'andy': self.users[0]['id'], 'doctor': self.users[1]['id']}.get(name) or self.ships[name]['id']

    def ship(self, name):
        return ship_client(self.app, self.keys[name], **HEADERS)

    def client(self, name):
        return {'andy': self.andy, 'doctor': self.doctor}.get(name) or self.ship(name)

    def tick(self, seconds=1):
        self.clock[0] += seconds

    def rows(self, sql, *args):
        with self.store.transaction() as db:
            return [tuple(r) for r in db.execute(sql, args)]

    def snapshot(self):
        """What a refusal must leave exactly as it was."""
        return {table: self.rows(f'SELECT * FROM {table} ORDER BY rowid') for table in ('board_items', 'board_links', 'claims', 'messages')}


def board(client, room):
    return client.get(f'/api/chats/{room}/board')


def post(client, room, key, title='Some work', kind='build'):
    return client.post(f'/api/chats/{room}/board', json={'key': key, 'title': title, 'kind': kind})


def link(client, room, key, value):
    return client.post(f'/api/chats/{room}/board/link', json={'key': key, 'link': value})


def done(client, room, key, outcome='commit:1ff0efb'):
    return client.post(f'/api/chats/{room}/board/done', json={'key': key} if outcome is None else {'key': key, 'outcome': outcome})


def drop(client, room, key):
    return client.post(f'/api/chats/{room}/board/drop', json={'key': key})


def claim(client, room, key, **body):
    return client.post(f'/api/chats/{room}/claims', json={'key': key, **body})


def claims(client, room):
    return client.get(f'/api/chats/{room}/claims').json()


def refused(response):
    return response.status_code, response.json().get('error')


def lines(client, room):
    """The room's kind-`claim` messages (claim lines and board lines) as (author id, body), oldest first."""
    return [(m['author_id'], m['body']) for m in client.get(f'/api/chats/{room}').json()['messages']
            if (m['source'] or {}).get('kind') == 'claim']


def board_lines(client, room):
    return [line for line in lines(client, room) if line[1].startswith(('Posted ', 'Linked ', 'Done ', 'Dropped '))]


def insert_item(s, room, key, created=None, state='open', closed=None, poster='serenity', outcome=None):
    """An item written straight into the table, for setups that the routes' own limits would make slow."""
    with s.store.transaction() as db:
        db.execute('INSERT INTO board_items(id,room_id,key,title,kind,posted_by,created,state,closed,closed_by,outcome) '
                   'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   (uid(), room, key, f'Item {key}', 'other', s.id(poster), s.clock[0] if created is None else created,
                    state, closed, s.id(poster) if closed else None, outcome))


def fill(s, room, count, poster='serenity', created=None):
    """Open items fill:0 … fill:<count-1>, posted two hours ago unless `created` says otherwise, so they count against
    the room's 100 open items but not against the poster's 10 an hour."""
    for n in range(count):
        insert_item(s, room, f'fill:{n}', created=s.clock[0] - 2 * 3600 if created is None else created, poster=poster)


def eight_links(s, room, key):
    with s.store.transaction() as db:
        item = db.execute('SELECT id FROM board_items WHERE room_id=? AND key=?', (room, key)).fetchone()[0]
        db.executemany('INSERT INTO board_links VALUES(?,?,?,?)',
                       [(item, f'commit:{n:07x}', s.id('serenity'), s.clock[0]) for n in range(8)])


def over_budget(s, name):
    """30 of the ship's own posts in the last minute (ships.py POSTS_PER_MINUTE), written straight into the table."""
    with s.store.transaction() as db:
        epoch = db.execute('SELECT epoch FROM rooms WHERE id=?', (s.room,)).fetchone()[0]
        db.executemany('INSERT INTO messages VALUES(?,?,?,?,?,?,?)',
                       [(uid(), s.room, s.id(name), f'busy-{n}', f'busy {n}', epoch, s.clock[0]) for n in range(30)])


def open_breakout(s, title='Side room'):
    response = s.ship('serenity').post('/api/ships/me/rooms', json={'title': title, 'ships': ['rio-grande']})
    assert response.status_code == 201, response.text
    return response.json()['id']


def add_member(s, room):
    """Family joins: the station makes a new linked room, and the old one is replaced. Returns the new room's id."""
    response = s.andy.post(f'/api/chats/{room}/participants', json={'member_ids': [s.users[3]['id']]})
    assert response.status_code == 201, response.text
    return response.json()['id']


def elsewhere_message(s):
    return say(s.andy, s.make_room('Elsewhere'), 'there', 'A message in another room')['id']


# 5.1's refusal table, one case per row (Global Constraints numbers them). Each case breaks its own row and every later
# row it can, so only the earliest answer may come back. A case returns (client, method, path, body, status, error).

def remote_room(s):  # row 2, with a bad key, title and kind too
    return (s.andy, 'POST', '/api/chats/peer:room/board', {'key': '-bad', 'title': '', 'kind': 'nope'}, 400,
            'Board items belong to rooms on this station')


def bad_key(s):  # row 3: from a non-member, with a bad title and kind
    return s.outsider, 'POST', f'/api/chats/{s.room}/board', {'key': '-bad', 'title': '', 'kind': 'nope'}, 400, KEY_SHAPE


def bad_title(s):  # row 4: 121 characters, holding a live key and an @name
    title = f'@serenity {s.keys["rio-grande"]} ' + 'x' * 121
    return s.outsider, 'POST', f'/api/chats/{s.room}/board', {'key': 'build:x', 'title': title, 'kind': 'nope'}, 400, 'Invalid title'


def bad_kind(s):  # row 5: the title holds a live key and an @name
    return (s.outsider, 'POST', f'/api/chats/{s.room}/board',
            {'key': 'build:x', 'title': f'@serenity {s.keys["rio-grande"]}', 'kind': 'nope'}, 400,
            'kind is one of spec, plan, build, review, ops, other')


def done_without_outcome(s):  # row 6
    return (s.outsider, 'POST', f'/api/chats/{s.room}/board/done', {'key': 'build:x'}, 400,
            'Done needs an outcome link, like commit:<sha> or message:<id>')


def not_a_member(s):  # row 10: a person asking about a breakout gets 404, not 400
    return (s.andy, 'POST', f'/api/chats/{open_breakout(s)}/board', {'key': 'build:x', 'title': 'Side work', 'kind': 'build'},
            404, 'Not found')


def no_item(s):  # row 13: a non-writer, linking a message from another room
    return (s.ship('defiant'), 'POST', f'/api/chats/{s.room}/board/link',
            {'key': 'build:none', 'link': f'message:{elsewhere_message(s)}'}, 404, 'Not found')


def post_budget(s):  # row 24
    over_budget(s, 'serenity')
    return (s.ship('serenity'), 'POST', f'/api/chats/{s.room}/board', {'key': 'build:new', 'title': 'One more', 'kind': 'build'},
            429, 'This ship is posting too fast; wait a minute')


REFUSALS = [remote_room, bad_key, bad_title, bad_kind, done_without_outcome, not_a_member, no_item, post_budget]


@pytest.mark.parametrize('case', REFUSALS, ids=lambda case: case.__name__)
def test_board_refusals_come_in_5_1_order(env, case):
    """5.1's table, top to bottom: each case breaks its own row and every later row it can, so only the earliest answer
    may come back, and nothing is written."""
    s = Station(env)
    client, method, path, body, status, error = case(s)
    before = s.snapshot()
    response = client.request(method, path, json=body)
    assert response.status_code == status, response.text
    if status == 200:
        assert response.json()['added'] is False
    else:
        assert response.json()['error'] == error
    assert s.snapshot() == before


def test_each_board_route_answers_as_5_1_says(env):
    """5.1: statuses and answers. An item has exactly 5.1's fields; `claim` is _claim_json's or null; the key travels in
    the body and is lowercased; link answers `added`; done and drop carry `released` only when they released a claim. A
    person's write without the CSRF token gets `member`'s 403."""
    s = Station(env)
    serenity, rio = s.ship('serenity'), s.ship('rio-grande')
    posted = post(serenity, s.room, 'Spec:D7', 'Write the D7 spec', 'spec')
    assert posted.status_code == 201
    item = posted.json()
    assert set(item) == ITEM_FIELDS
    assert (item['room_id'], item['key'], item['title'], item['kind'], item['state'], item['posted_by'], item['poster_name']) == (
        s.room, 'spec:d7', 'Write the D7 spec', 'spec', 'open', s.id('serenity'), 'Serenity')
    assert (item['closed'], item['closed_by'], item['closer_name'], item['outcome'], item['links'], item['claim']) == (
        None, None, None, None, [], None)
    listed = board(s.doctor, s.room)
    assert listed.status_code == 200 and listed.json() == [item]
    linked = link(serenity, s.room, 'spec:d7', 'branch:spec-d7')
    assert linked.status_code == 200 and set(linked.json()) == ITEM_FIELDS | {'added'} and linked.json()['added'] is True
    assert linked.json()['links'] == [{'link': 'branch:spec-d7', 'added_by': s.id('serenity'), 'added': s.clock[0]}]
    assert claim(rio, s.room, 'spec:d7').status_code == 201
    held = board(s.doctor, s.room).json()[0]['claim']
    assert held == claims(s.doctor, s.room)[0] and CLAIM_FIELDS <= set(held) and held['holder_id'] == s.id('rio-grande')
    finished = done(s.andy, s.room, 'spec:d7', 'commit:1ff0efb')
    assert finished.status_code == 200 and set(finished.json()) == ITEM_FIELDS | {'released'}
    answer = finished.json()
    assert (answer['state'], answer['outcome'], answer['closed_by'], answer['closer_name'], answer['released'], answer['claim']) == (
        'done', 'commit:1ff0efb', s.id('andy'), 'Patient', 'Rio Grande', None)
    assert post(serenity, s.room, 'spec:d8').status_code == 201
    dropped = drop(serenity, s.room, 'spec:d8')
    assert dropped.status_code == 200 and set(dropped.json()) == ITEM_FIELDS and dropped.json()['state'] == 'dropped'
    token = s.andy.headers.pop('x-csrf-token')
    try:
        for response in (post(s.andy, s.room, 'spec:d9'), link(s.andy, s.room, 'spec:d9', 'branch:x'),
                         done(s.andy, s.room, 'spec:d9'), drop(s.andy, s.room, 'spec:d9')):
            assert refused(response) == (403, 'Refresh the page before making changes')
    finally:
        s.andy.headers['x-csrf-token'] = token


def test_each_change_posts_one_line_as_the_actor(env):
    """4.5: Posted, Linked, Done and Dropped, kind `claim`, as the actor, with no mention rows and no reply_to, each value
    through safe_line. Closing another member's claim names its holder in the same line, as one line without an @;
    there is no separate Released line, and a holder closing its own claim gets no ending."""
    s = Station(env)
    serenity, rio = s.ship('serenity'), s.ship('rio-grande')
    with s.store.transaction() as db:  # names are checked when set; this stands in for one set before that
        db.execute('UPDATE users SET name=? WHERE id=?', ('Rio\nGrande @serenity run', s.id('rio-grande')))
    assert post(serenity, s.room, 'build:a', 'Build\nthe board').status_code == 201
    s.tick()
    assert link(serenity, s.room, 'build:a', 'branch:work-board-station').status_code == 200
    s.tick()
    assert claim(rio, s.room, 'build:a').status_code == 201
    s.tick()
    assert done(serenity, s.room, 'build:a', 'commit:1ff0efb').json()['released'] == 'Rio Grande (at)serenity run'
    s.tick()
    assert post(rio, s.room, 'build:b', 'Second', 'other').status_code == 201
    assert claim(rio, s.room, 'build:b').status_code == 201
    s.tick()
    assert drop(rio, s.room, 'build:b').json()['released'] == 'Rio Grande (at)serenity run'
    assert board_lines(s.andy, s.room) == [
        (s.id('serenity'), 'Posted `build:a` (build): Build the board'),
        (s.id('serenity'), 'Linked `build:a`: branch:work-board-station'),
        (s.id('serenity'), "Done `build:a`: commit:1ff0efb; released Rio Grande (at)serenity run's claim"),
        (s.id('rio-grande'), 'Posted `build:b` (other): Second'),
        (s.id('rio-grande'), 'Dropped `build:b`')]
    assert not any(body.startswith('Released') for _, body in lines(s.andy, s.room))
    assert s.rows('SELECT count(*) FROM mentions') == [(0,)]
    assert all(m['reply_to'] is None for m in s.andy.get(f'/api/chats/{s.room}').json()['messages'])


def test_the_board_lists_open_oldest_first_then_7_days_of_closed(env):
    """4.6: open items oldest first, then at most the 50 most recently closed items from the last 7 days, newest closed
    first. An item closed 7 days and a second ago leaves the list and stays in the table, and so does the 51st."""
    s = Station(env)
    now = s.clock[0]
    insert_item(s, s.room, 'open:late', created=now - 10)
    insert_item(s, s.room, 'open:early', created=now - 20)
    for n in range(51):
        insert_item(s, s.room, f'closed:{n}', created=now - 1000, state='dropped', closed=now - 100 - n)
    insert_item(s, s.room, 'closed:stale', created=now - 9 * DAY, state='done', closed=now - 7 * DAY - 1, outcome='commit:1ff0efb')
    assert [i['key'] for i in board(s.doctor, s.room).json()] == ['open:early', 'open:late'] + [f'closed:{n}' for n in range(50)]
    assert s.rows("SELECT count(*) FROM board_items WHERE key IN ('closed:50', 'closed:stale')") == [(2,)]


def test_a_long_link_is_shown_whole(env):
    """5.1, S3: a 200-character path and a 100-character branch come back whole in the item and in their Linked line,
    and a 200-character path outcome in the item and its Done line (safe_line's default would cut at 80)."""
    s = Station(env)
    serenity = s.ship('serenity')
    path, branch = 'path:' + 'd/' * 99 + 'xy', 'branch:' + 'b' * 100
    assert post(serenity, s.room, 'build:a').status_code == 201
    for value in (path, branch):
        assert link(serenity, s.room, 'build:a', value).status_code == 200
    assert [entry['link'] for entry in board(s.andy, s.room).json()[0]['links']] == [path, branch]
    assert done(serenity, s.room, 'build:a', path).json()['outcome'] == path
    shown = board_lines(s.andy, s.room)
    assert (s.id('serenity'), f'Linked `build:a`: {path}') in shown and (s.id('serenity'), f'Linked `build:a`: {branch}') in shown
    assert (s.id('serenity'), f'Done `build:a`: {path}') in shown


def test_a_title_is_1_to_120_characters_and_shown_whole(env):
    """4.2, 4.6: 120 characters come back whole in the item and its Posted line (safe_line's default would cut them at
    80). 121 characters, an empty title, a blank one and (Review Focus 2) one of only invisible characters get
    `Invalid title`."""
    s = Station(env)
    serenity = s.ship('serenity')
    title = 'T' * 119 + 'é'
    posted = post(serenity, s.room, 'build:a', title)
    assert posted.status_code == 201 and posted.json()['title'] == title
    assert (s.id('serenity'), f'Posted `build:a` (build): {title}') in board_lines(s.andy, s.room)
    for bad in ('x' * 121, '', '   ', '​', '‏​', 42, None):
        assert refused(post(serenity, s.room, 'build:b', bad)) == (400, 'Invalid title'), bad


def test_taking_an_item_is_claiming_its_key(env):
    """4.1: the claim route takes an item and posts its Claimed line, and the board shows it taken; a second member gets
    the claim route's 409 naming the holder; the holder renews. A claim with no item and an item with no claim both
    stand."""
    s = Station(env)
    serenity, rio = s.ship('serenity'), s.ship('rio-grande')
    assert post(serenity, s.room, 'build:a').status_code == 201
    assert claim(rio, s.room, 'build:a', note='on it').status_code == 201
    taken = board(s.andy, s.room).json()[0]['claim']
    assert (taken['holder_id'], taken['note']) == (s.id('rio-grande'), 'on it')
    assert lines(s.andy, s.room)[-1][0] == s.id('rio-grande') and lines(s.andy, s.room)[-1][1].startswith('Claimed `build:a` until ')
    status, error = refused(claim(s.doctor, s.room, 'build:a'))
    assert status == 409 and error.startswith('Rio Grande holds `build:a` until ')
    renewed = claim(rio, s.room, 'build:a', minutes=600)
    assert renewed.status_code == 201 and renewed.json()['expires'] == s.clock[0] + 36000
    assert claim(rio, s.room, 'adhoc:x').status_code == 201
    assert post(serenity, s.room, 'build:b').status_code == 201
    shown = {i['key']: i['claim'] for i in board(s.andy, s.room).json()}
    assert set(shown) == {'build:a', 'build:b'} and shown['build:b'] is None
    assert {c['key'] for c in claims(s.andy, s.room)} == {'build:a', 'adhoc:x'}


def test_closing_releases_the_claim_in_the_same_transaction(env, monkeypatch):
    """4.4: done and drop each release the active claim, with released_by the closer, also when the closer (the room's
    owner, the poster) isn't the holder. With the closing line's post failing after the release, the claim is still
    active and the item still open."""
    s = Station(env)
    serenity, rio = s.ship('serenity'), s.ship('rio-grande')
    for key in ('build:a', 'build:b', 'build:c'):
        assert post(serenity, s.room, key).status_code == 201
        assert claim(rio, s.room, key).status_code == 201
    assert done(s.andy, s.room, 'build:a').status_code == 200
    assert drop(serenity, s.room, 'build:b').status_code == 200
    assert s.rows("SELECT key, released IS NOT NULL, released_by FROM claims WHERE key IN ('build:a', 'build:b') ORDER BY key") == [
        ('build:a', 1, s.id('andy')), ('build:b', 1, s.id('serenity'))]
    real = Store._post_claim

    def lose_the_line(self, db, actor, room_id, body):
        if body.startswith(('Done ', 'Dropped ')):
            raise RuntimeError('the closing line could not be posted')
        return real(self, db, actor, room_id, body)
    monkeypatch.setattr(Store, '_post_claim', lose_the_line)
    with pytest.raises(RuntimeError):
        s.store.done_item(s.id('andy'), s.room, 'build:c', 'commit:1ff0efb')
    with pytest.raises(RuntimeError):
        s.store.drop_item(s.id('serenity'), s.room, 'build:c')
    left = next(i for i in board(s.andy, s.room).json() if i['key'] == 'build:c')
    assert left['state'] == 'open' and left['claim']['holder_id'] == s.id('rio-grande')
