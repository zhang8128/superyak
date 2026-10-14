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


def bad_link(s):  # row 7: the shape fails first, though the link holds an @ and a live key
    return (s.outsider, 'POST', f'/api/chats/{s.room}/board/link', {'key': 'build:x', 'link': f'path:@odo/{s.keys["rio-grande"]}'},
            400, LINK_SHAPE)


def live_key(s):  # row 8: a title holding both a live key and an @name, from a non-member
    return (s.outsider, 'POST', f'/api/chats/{s.room}/board', {'key': 'build:x', 'title': f'@serenity {s.keys["rio-grande"]}', 'kind': 'build'},
            422, 'This title contains a live ship key, so it was not posted. Treat that key as exposed: its ship should revoke it and dock again.')


def at_name(s):  # row 9, from a non-member
    return s.outsider, 'POST', f'/api/chats/{s.room}/board', {'key': 'build:x', 'title': 'Ask @serenity', 'kind': 'build'}, 400, AT_NAME


def not_a_member(s):  # row 10: a person asking about a breakout gets 404, not 400
    return (s.andy, 'POST', f'/api/chats/{open_breakout(s)}/board', {'key': 'build:x', 'title': 'Side work', 'kind': 'build'},
            404, 'Not found')


def breakout(s):  # row 11: a member ship, who isn't a board writer there either
    return (s.ship('rio-grande'), 'POST', f'/api/chats/{open_breakout(s)}/board', {'key': 'build:x', 'title': 'Side work', 'kind': 'build'},
            400, 'Breakouts hold no board')


def no_item(s):  # row 13: a non-writer, linking a message from another room
    return (s.ship('defiant'), 'POST', f'/api/chats/{s.room}/board/link',
            {'key': 'build:none', 'link': f'message:{elsewhere_message(s)}'}, 404, 'Not found')


def message_elsewhere(s):  # row 14: on a closed item, from a non-writer
    insert_item(s, s.room, 'build:x', state='done', closed=s.clock[0], outcome='commit:1ff0efb')
    return (s.ship('defiant'), 'POST', f'/api/chats/{s.room}/board/link', {'key': 'build:x', 'link': f'message:{elsewhere_message(s)}'},
            400, NOT_HERE)


def key_used(s):  # row 15: a non-writer, on a full board
    insert_item(s, s.room, 'build:x', state='done', closed=s.clock[0], outcome='commit:1ff0efb')
    fill(s, s.room, 100)
    return (s.ship('defiant'), 'POST', f'/api/chats/{s.room}/board', {'key': 'build:x', 'title': 'Again', 'kind': 'build'}, 409,
            '`build:x` is already on this board or a room it replaced (done); new work needs a new key')


def closed(s):  # row 16: a holder's retried done gets 409, not 403
    rio = s.ship('rio-grande')
    insert_item(s, s.room, 'build:x')
    assert claim(rio, s.room, 'build:x').status_code == 201 and done(rio, s.room, 'build:x').status_code == 200
    return rio, 'POST', f'/api/chats/{s.room}/board/done', {'key': 'build:x', 'outcome': 'commit:1ff0efb'}, 409, '`build:x` is already done'


def not_a_writer(s):  # row 17: another owner's ship, on a full board, over its post budget
    fill(s, s.room, 100)
    over_budget(s, 'defiant')
    return s.ship('defiant'), 'POST', f'/api/chats/{s.room}/board', {'key': 'build:new', 'title': 'Mine', 'kind': 'build'}, 403, WRITER


def done_by_a_non_writer(s):  # row 18: the holder isn't a board writer, and is over its post budget
    insert_item(s, s.room, 'build:x')
    assert claim(s.ship('defiant'), s.room, 'build:x').status_code == 201
    over_budget(s, 'defiant')
    return s.ship('defiant'), 'POST', f'/api/chats/{s.room}/board/done', {'key': 'build:x', 'outcome': 'commit:1ff0efb'}, 403, DONE_BY


def drop_by_a_non_poster(s):  # row 19: a board writer who neither posted it nor owns the room, over its post budget
    insert_item(s, s.room, 'build:x')
    over_budget(s, 'rio-grande')
    return s.ship('rio-grande'), 'POST', f'/api/chats/{s.room}/board/drop', {'key': 'build:x'}, 403, DROP_BY


def link_it_has(s):  # row 20: on a full item, from a ship over its post budget
    insert_item(s, s.room, 'build:x')
    eight_links(s, s.room, 'build:x')
    over_budget(s, 'serenity')
    return s.ship('serenity'), 'POST', f'/api/chats/{s.room}/board/link', {'key': 'build:x', 'link': 'commit:0000000'}, 200, None


def board_full(s):  # row 21: the owner, who also posted 10 in the last hour
    fill(s, s.room, 100, poster='andy', created=s.clock[0])
    return (s.andy, 'POST', f'/api/chats/{s.room}/board', {'key': 'build:new', 'title': 'One more', 'kind': 'build'}, 429,
            'This board already has 100 open items')


def ten_an_hour(s):  # row 22: a ship over its post budget too
    fill(s, s.room, 10, created=s.clock[0])
    over_budget(s, 'serenity')
    return (s.ship('serenity'), 'POST', f'/api/chats/{s.room}/board', {'key': 'build:new', 'title': 'One more', 'kind': 'build'}, 429,
            'You posted 10 items in the last hour; wait before posting another')


def eight_links_full(s):  # row 23: a ship over its post budget too
    insert_item(s, s.room, 'build:x')
    eight_links(s, s.room, 'build:x')
    over_budget(s, 'serenity')
    return s.ship('serenity'), 'POST', f'/api/chats/{s.room}/board/link', {'key': 'build:x', 'link': 'branch:ninth'}, 429, '`build:x` already has 8 links'


def post_budget(s):  # row 24
    over_budget(s, 'serenity')
    return (s.ship('serenity'), 'POST', f'/api/chats/{s.room}/board', {'key': 'build:new', 'title': 'One more', 'kind': 'build'},
            429, 'This ship is posting too fast; wait a minute')


REFUSALS = [remote_room, bad_key, bad_title, bad_kind, done_without_outcome, bad_link, live_key, at_name, not_a_member, breakout,
            no_item, message_elsewhere, key_used, closed, not_a_writer, done_by_a_non_writer, drop_by_a_non_poster, link_it_has,
            board_full, ten_an_hour, eight_links_full, post_budget]


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


ACCEPTED = ['branch:work-board-spec', 'branch:a/b.c_d', 'path:a+b/c.md', 'commit:1ff0efb', 'commit:' + 'a' * 40, 'claim:spec:d7']
SHELL = [' ', ';', '|', '&', '$', '`', '(', '<', '>', '\\', "'", '"', '*', '?', '~', '\n']
REFUSED = ([f'{form}:a{c}b' for form in ('branch', 'path') for c in SHELL]
           + ['path:docs/a@b.md', 'path:@odo', 'branch:-x', 'path:-rf', 'path:/etc/passwd',
              'branch:a..b', 'path:..', 'path:../x', 'path:a/../b', 'branch:a//b', 'branch:x/', 'branch:x.lock',
              'branch:' + 'b' * 101, 'path:' + 'p' * 201, 'commit:' + 'a' * 6, 'commit:' + 'a' * 41, 'commit:1FF0EFB',
              'message:' + 'a' * 31, 'message:' + 'A' * 32, 'https://example.com', 'file:/etc/passwd', 'word'])


@pytest.mark.parametrize('as_', ['link', 'outcome'])
def test_links_have_only_the_five_shapes(env, as_):
    """4.3, 7.3: five forms, checked by shape, as a link and as done's outcome. Shell metacharacters, a leading - or /,
    `..`, `//`, a trailing / or .lock, @ in a path, over-long names, wrong hex and URLs are refused with the link
    message; a message id must be in this room."""
    s = Station(env)
    serenity = s.ship('serenity')
    here, elsewhere = say(s.andy, s.room, 'here', 'A verdict in this room')['id'], elsewhere_message(s)

    def write(key, value):
        return link(serenity, s.room, key, value) if as_ == 'link' else done(serenity, s.room, key, value)
    insert_item(s, s.room, 'build:shared')
    for n, value in enumerate(ACCEPTED + [f'message:{here}']):
        key = 'build:shared'
        if as_ == 'outcome':
            key = f'build:ok{n}'
            insert_item(s, s.room, key)
        assert write(key, value).status_code == 200, value
    for value in REFUSED:
        assert refused(write('build:shared', value)) == (400, LINK_SHAPE), value
    for value in (f'message:{elsewhere}', 'message:' + 'a' * 32):
        assert refused(write('build:shared', value)) == (400, NOT_HERE), value


def test_board_text_cannot_name_anyone_with_at(env):
    """7.2: an @name in a title is refused on the raw text, also inside backticks, quotes or a quoted line (label()
    strips backticks in tool output, so a quoted name wouldn't stay quoted). An email address passes. (@ in a link gets
    the link-shape 400 first: test_links_have_only_the_five_shapes.) No board line writes a mention row."""
    s = Station(env)
    serenity = s.ship('serenity')
    for title in ('Ask @serenity', 'Ask `@serenity`', 'Ask "@serenity"', "Ask '@serenity'", '> @serenity'):
        assert refused(post(serenity, s.room, 'build:a', title)) == (400, AT_NAME), title
    assert post(serenity, s.room, 'build:a', 'Mail andy@example.com').status_code == 201
    assert s.rows('SELECT count(*) FROM mentions') == [(0,)]


def test_a_live_ship_key_is_refused_in_titles_links_and_outcomes(env):
    """7.6, S10: 422 naming the key, title, link or outcome, never repeating the live key, with nothing written. Checked
    on the raw value as received: a mixed-case key used as an item's key or in a claim: link would pass a check on the
    lowercased value. A revoked key's text passes."""
    s = Station(env)
    serenity, live = s.ship('serenity'), s.keys['rio-grande']
    assert live != live.lower()  # a key with no capitals couldn't tell the raw check from a lowercased one (odds ~1e-7)
    insert_item(s, s.room, 'build:a')
    before = s.snapshot()
    for response, what in ((post(serenity, s.room, f'k:{live}', 'Fine title'), 'key'),
                           (post(serenity, s.room, 'build:b', f'See {live}'), 'title'),
                           (link(serenity, s.room, 'build:a', f'claim:k:{live}'), 'link'),
                           (done(serenity, s.room, 'build:a', f'claim:k:{live}'), 'outcome')):
        status, error = refused(response)
        assert status == 422 and error.startswith(f'This {what} contains a live ship key, so it was not posted.'), what
        assert live not in error and live.lower() not in error
    assert s.snapshot() == before
    assert s.ship('rio-grande').delete('/api/ships/me/key').status_code == 200
    assert post(serenity, s.room, f'k:{live}', f'See {live}').status_code == 201
    assert link(serenity, s.room, 'build:a', f'claim:k:{live}').status_code == 200


def test_a_revoked_ship_key_gets_401_on_a_board_route(env):
    """The board routes authenticate through member(): a revoked ship key is 401 on a read and a write."""
    s = Station(env)
    rio = s.ship('rio-grande')
    assert rio.delete('/api/ships/me/key').status_code == 200
    assert board(rio, s.room).status_code == 401
    assert post(rio, s.room, 'build:a').status_code == 401


def test_a_remote_room_id_is_a_400_on_a_board_read(env):
    """5.1 row 2 on the read route too: a room id with a colon is 400, not a lookup."""
    s = Station(env)
    assert refused(board(s.andy, 'peer:room')) == (400, 'Board items belong to rooms on this station')


def test_a_non_member_cannot_read_a_board(env):
    """5.1 row 10 on the read route: a non-member gets 404 and learns nothing about the room."""
    s = Station(env)
    assert post(s.ship('serenity'), s.room, 'build:a').status_code == 201
    assert refused(board(s.outsider, s.room)) == (404, 'Not found')


@pytest.mark.parametrize('who, writes', [('andy', True), ('serenity', True), ('doctor', False), ('defiant', False),
                                         ('odo', False), ('wormhole', False)])
def test_only_the_owner_and_the_owners_ships_post_and_link(env, who, writes):
    """6.1: the room's owner and a ship he owns are board writers; another person in the room, another owner's ship and
    the ownerless Odo and wormhole get 403, for post and for link."""
    s = Station(env)
    client = s.client(who)
    insert_item(s, s.room, 'build:a', poster='andy')
    posted, linked = post(client, s.room, 'build:new'), link(client, s.room, 'build:a', 'branch:x')
    if writes:
        assert (posted.status_code, linked.status_code) == (201, 200)
    else:
        assert refused(posted) == refused(linked) == (403, WRITER)


def test_done_needs_an_outcome_link_and_a_writer(env):
    """4.4, 6.1: without an outcome, 400. The room's owner, the poster, and a holder who is a board writer may mark it
    done; a holder who isn't one (another owner's ship) and a writer who is neither poster nor holder get 403."""
    s = Station(env)
    serenity, rio, defiant = s.ship('serenity'), s.ship('rio-grande'), s.ship('defiant')
    insert_item(s, s.room, 'build:x')
    assert refused(done(serenity, s.room, 'build:x', None)) == (400, 'Done needs an outcome link, like commit:<sha> or message:<id>')
    for closer, client in (('owner', s.andy), ('poster', serenity), ('holder', rio)):
        insert_item(s, s.room, f'build:{closer}')
        if closer == 'holder':
            assert claim(rio, s.room, 'build:holder').status_code == 201
        assert done(client, s.room, f'build:{closer}').status_code == 200, closer
    insert_item(s, s.room, 'build:held')
    assert claim(defiant, s.room, 'build:held').status_code == 201
    insert_item(s, s.room, 'build:other')
    assert refused(done(defiant, s.room, 'build:held')) == (403, DONE_BY)
    assert refused(done(rio, s.room, 'build:other')) == (403, DONE_BY)


def test_drop_is_for_the_poster_and_the_owner(env):
    """4.4: the poster or the room's owner drops an item; its holder, another owner's ship and another person get 403."""
    s = Station(env)
    serenity, rio = s.ship('serenity'), s.ship('rio-grande')
    for key in ('build:a', 'build:b', 'build:c'):
        insert_item(s, s.room, key)
    assert claim(rio, s.room, 'build:c').status_code == 201
    for client, key in ((rio, 'build:c'), (s.ship('defiant'), 'build:a'), (s.doctor, 'build:a')):
        assert refused(drop(client, s.room, key)) == (403, DROP_BY)
    assert drop(serenity, s.room, 'build:a').status_code == 200
    assert drop(s.andy, s.room, 'build:b').status_code == 200


def test_any_member_reads_and_takes(env):
    """6.1: members who aren't board writers read the board and claim a key. (It passes before Step 3 too: it pins that
    the writer rules leave reading and taking open.)"""
    s = Station(env)
    insert_item(s, s.room, 'build:a', poster='andy')
    for client in (s.doctor, s.ship('defiant'), s.ship('odo')):
        response = board(client, s.room)
        assert response.status_code == 200 and [i['key'] for i in response.json()] == ['build:a']
    assert claim(s.ship('defiant'), s.room, 'build:a').status_code == 201
    assert board(s.doctor, s.room).json()[0]['claim']['holder_id'] == s.id('defiant')


def test_done_and_dropped_are_final(env):
    """4.4: link, done and drop on a closed item get 409 naming its state, from the room's owner too. Claiming its key
    afterwards works and reopens nothing."""
    s = Station(env)
    serenity = s.ship('serenity')
    insert_item(s, s.room, 'build:done')
    insert_item(s, s.room, 'build:dropped')
    assert done(serenity, s.room, 'build:done').status_code == 200 and drop(serenity, s.room, 'build:dropped').status_code == 200
    for key, state in (('build:done', 'done'), ('build:dropped', 'dropped')):
        for response in (link(s.andy, s.room, key, 'branch:x'), done(s.andy, s.room, key), drop(s.andy, s.room, key)):
            assert refused(response) == (409, f'`{key}` is already {state}')
    assert claim(s.ship('rio-grande'), s.room, 'build:done').status_code == 201
    assert {i['key']: i['state'] for i in board(s.andy, s.room).json()} == {'build:done': 'done', 'build:dropped': 'dropped'}


def test_breakouts_hold_no_board(env):
    """6: every board route on an open and on a closed breakout gets 400, and a non-member gets 404; nothing is written,
    except that a breakout closed by quiet and seen first by a board route keeps the closure _room saved (keep=True).
    Claims in a breakout work as before."""
    s = Station(env)
    serenity, rio = s.ship('serenity'), s.ship('rio-grande')
    side = open_breakout(s)

    def every_route(client, room):
        return [board(client, room), post(client, room, 'build:a'), link(client, room, 'build:a', 'branch:x'),
                done(client, room, 'build:a'), drop(client, room, 'build:a')]
    before = s.snapshot()
    assert all(refused(r) == (400, 'Breakouts hold no board') for r in every_route(rio, side))
    assert all(refused(r) == (404, 'Not found') for r in every_route(s.andy, side))
    assert serenity.post(f'/api/ships/me/rooms/{side}/close').status_code == 200
    assert all(refused(r) == (400, 'Breakouts hold no board') for r in every_route(rio, side))
    assert s.snapshot() == before
    quiet = open_breakout(s, 'Quiet side')
    s.tick(8 * DAY)
    assert s.rows('SELECT closed FROM breakouts WHERE room_id=?', quiet) == [(None,)]
    assert refused(board(rio, quiet)) == (400, 'Breakouts hold no board')
    assert s.rows('SELECT closed FROM breakouts WHERE room_id=?', quiet) != [(None,)]
    assert claim(rio, open_breakout(s, 'Claims side'), 'build:a').status_code == 201


def test_claims_mark_board_items(env):
    """5.6, station half: _claim_json carries `board`, the item's state, only when the room has an item with that key, in
    the claim route's answer, the claims list and the room view. A plain claim has exactly today's keys. (The tools
    half is agent/tests/test_board_tools.py, step 2.)"""
    s = Station(env)
    rio = s.ship('rio-grande')
    for key in ('build:open', 'build:done', 'build:dropped'):
        insert_item(s, s.room, key, poster='andy')
    assert done(s.andy, s.room, 'build:done').status_code == 200 and drop(s.andy, s.room, 'build:dropped').status_code == 200
    answers = {key: claim(rio, s.room, key).json() for key in ('build:open', 'build:done', 'build:dropped', 'adhoc:x')}
    expected = {'build:open': 'open', 'build:done': 'done', 'build:dropped': 'dropped', 'adhoc:x': None}
    assert {key: answer.get('board') for key, answer in answers.items()} == expected
    assert set(answers['adhoc:x']) == CLAIM_FIELDS
    assert {c['key']: c.get('board') for c in claims(rio, s.room)} == expected
    assert {c['key']: c.get('board') for c in s.andy.get(f'/api/chats/{s.room}').json()['claims']} == expected


def test_adding_members_carries_open_items_and_leaves_the_record(env):
    """5.x: the new room holds the open items with their ids, keys, posters, created times and links; add_participants
    answers board_carried and the carry posts nothing. A taken item stays taken there by the same holder until the same
    expiry, through the same claim row; the old room holds no active claim on its key, and the holder's count is
    unchanged. Done and dropped items stay as the record. A claim whose holder isn't in the new room stays behind."""
    s = Station(env)
    serenity, rio, defiant = s.ship('serenity'), s.ship('rio-grande'), s.ship('defiant')
    for key in ('build:waiting', 'build:taken', 'build:done', 'build:dropped', 'build:left'):
        assert post(serenity, s.room, key).status_code == 201
        s.tick()
    assert link(serenity, s.room, 'build:taken', 'branch:work-board-station').status_code == 200
    assert claim(rio, s.room, 'build:taken', note='on it', minutes=60).status_code == 201
    assert done(serenity, s.room, 'build:done').status_code == 200 and drop(serenity, s.room, 'build:dropped').status_code == 200
    assert claim(defiant, s.room, 'build:left').status_code == 201
    assert s.andy.delete(f'/api/chats/{s.room}/participants/{s.id("defiant")}').status_code == 200
    was = {i['key']: i for i in board(s.andy, s.room).json()}
    rio_holds = s.rows('SELECT count(*) FROM claims WHERE holder_id=? AND released IS NULL', s.id('rio-grande'))
    messages = s.rows('SELECT count(*) FROM messages')
    added = s.andy.post(f'/api/chats/{s.room}/participants', json={'member_ids': [s.users[3]['id']]})
    assert added.status_code == 201 and added.json()['board_carried'] == 3
    new = added.json()['id']
    assert s.rows('SELECT count(*) FROM messages') == messages
    moved = {i['key']: i for i in board(s.andy, new).json()}
    assert list(moved) == ['build:waiting', 'build:taken', 'build:left']
    same = ('id', 'key', 'title', 'kind', 'posted_by', 'created', 'links')
    for key, item in moved.items():
        assert {f: item[f] for f in same} == {f: was[key][f] for f in same} and item['room_id'] == new
    assert moved['build:waiting']['claim'] is None and moved['build:left']['claim'] is None
    taken, held = moved['build:taken']['claim'], was['build:taken']['claim']
    assert (taken['id'], taken['room_id'], taken['holder_id'], taken['note'], taken['expires']) == (
        held['id'], new, s.id('rio-grande'), 'on it', held['expires'])
    assert s.rows('SELECT count(*) FROM claims WHERE holder_id=? AND released IS NULL', s.id('rio-grande')) == rio_holds
    assert [c['key'] for c in claims(s.andy, s.room)] == ['build:left']
    assert {i['key']: i['state'] for i in board(s.andy, s.room).json()} == {'build:done': 'done', 'build:dropped': 'dropped'}


def test_a_key_is_used_once_per_room_for_all_time(env):
    """4.2: posting a key again gets 409 naming its state, open, done or dropped; `Fix:X` is `fix:x`; another room may use
    the same key. After an add, a key done in the replaced room, and the carried open one, get the 409 in the new
    room."""
    s = Station(env)
    serenity = s.ship('serenity')
    for key, close in (('fix:open', None), ('fix:done', done), ('fix:dropped', drop)):
        assert post(serenity, s.room, key).status_code == 201
        if close:
            assert close(serenity, s.room, key).status_code == 200
    for key, state in (('Fix:Open', 'open'), ('fix:done', 'done'), ('FIX:DROPPED', 'dropped')):
        assert refused(post(serenity, s.room, key)) == (
            409, f'`{key.lower()}` is already on this board or a room it replaced ({state}); new work needs a new key')
    assert post(serenity, s.make_room('Other room'), 'fix:done').status_code == 201
    new = add_member(s, s.room)
    for key, state in (('fix:done', 'done'), ('fix:open', 'open')):
        assert refused(post(serenity, new, key)) == (
            409, f'`{key}` is already on this board or a room it replaced ({state}); new work needs a new key')


def test_a_board_holds_100_open_items(env):
    """4.6: the 101st open item gets 429; dropping one frees a place, and closed items don't count."""
    s = Station(env)
    fill(s, s.room, 99, poster='andy')
    insert_item(s, s.room, 'closed:1', poster='andy', state='done', closed=s.clock[0], outcome='commit:1ff0efb')
    assert post(s.andy, s.room, 'build:100').status_code == 201
    assert refused(post(s.andy, s.room, 'build:101')) == (429, 'This board already has 100 open items')
    assert drop(s.andy, s.room, 'fill:0').status_code == 200
    assert post(s.andy, s.room, 'build:101').status_code == 201


def test_a_poster_posts_10_items_an_hour(env):
    """4.6, 7.4: the 11th item within the hour gets 429, in the same room or another; another poster isn't held back,
    and an hour later it works."""
    s = Station(env)
    serenity, other = s.ship('serenity'), s.make_room('Other room')
    for n in range(10):
        assert post(serenity, s.room if n % 2 else other, f'build:{n}').status_code == 201
    for room in (s.room, other):
        assert refused(post(serenity, room, 'build:10')) == (429, 'You posted 10 items in the last hour; wait before posting another')
    assert post(s.ship('rio-grande'), s.room, 'build:rio').status_code == 201
    s.tick(3601)
    assert post(serenity, s.room, 'build:10').status_code == 201


def test_an_item_holds_8_links(env):
    """4.3, 4.6: the 9th link gets 429."""
    s = Station(env)
    serenity = s.ship('serenity')
    insert_item(s, s.room, 'build:a')
    for n in range(8):
        assert link(serenity, s.room, 'build:a', f'commit:{n:07x}').status_code == 200
    assert refused(link(serenity, s.room, 'build:a', 'branch:ninth')) == (429, '`build:a` already has 8 links')


def test_a_link_the_item_has_writes_and_posts_nothing(env):
    """5.1, ruling 8: a link the item already has answers 200 with added: false, writing and posting nothing, also on an
    item with 8 links and from a ship over its post budget. A non-writer re-adding it still gets 403, and a retry on a
    closed item gets 409. A carried message: link re-added in the new room gets the message: 400."""
    s = Station(env)
    serenity = s.ship('serenity')
    insert_item(s, s.room, 'build:a')
    assert link(serenity, s.room, 'build:a', 'branch:x').json()['added'] is True
    before = s.snapshot()
    again = link(serenity, s.room, 'build:a', 'branch:x')
    assert again.status_code == 200 and again.json()['added'] is False and s.snapshot() == before
    for n in range(7):
        assert link(serenity, s.room, 'build:a', f'commit:{n:07x}').status_code == 200
    over_budget(s, 'serenity')
    before = s.snapshot()
    again = link(serenity, s.room, 'build:a', 'branch:x')
    assert again.status_code == 200 and again.json()['added'] is False and s.snapshot() == before
    assert refused(link(s.ship('defiant'), s.room, 'build:a', 'branch:x')) == (403, WRITER)
    insert_item(s, s.room, 'build:closed', poster='andy')
    assert link(s.andy, s.room, 'build:closed', 'branch:x').status_code == 200
    assert done(s.andy, s.room, 'build:closed').status_code == 200
    assert refused(link(s.andy, s.room, 'build:closed', 'branch:x')) == (409, '`build:closed` is already done')
    verdict = say(s.andy, s.room, 'verdict', 'Approved.')['id']
    insert_item(s, s.room, 'build:m', poster='andy')
    assert link(s.andy, s.room, 'build:m', f'message:{verdict}').status_code == 200
    new = add_member(s, s.room)
    assert refused(link(s.andy, new, 'build:m', f'message:{verdict}')) == (400, NOT_HERE)


def test_the_carry_leaves_claims_that_are_not_on_open_items(env):
    """Task 4 review pin: an ad hoc claim and a claim on a closed item's key are not board work, so the carry leaves
    both in the old room even though their holders are members of the new one. Fails if _carry_board moves every
    active claim whose holder is a member."""
    s = Station(env)
    serenity, rio = s.ship('serenity'), s.ship('rio-grande')
    insert_item(s, s.room, 'build:done', state='done', closed=s.clock[0], outcome='commit:1ff0efb')
    assert claim(rio, s.room, 'adhoc:x').status_code == 201
    assert claim(serenity, s.room, 'build:done').status_code == 201
    new = add_member(s, s.room)
    assert sorted(c['key'] for c in claims(s.andy, s.room)) == ['adhoc:x', 'build:done']
    assert claims(s.andy, new) == []


def test_bridging_carries_open_items_and_unbridging_moves_none(tmp_path, capsys):
    """5.x: station-bridge carries them through add_participants, and describe_bridge says the replaced room keeps its
    messages and closed board items, then how many open items came along, or that there were none. Unbridging keeps
    the room and its board."""
    store = Store(tmp_path / 'station')  # the CLI opens its own Store with the real clock, so the state is made with it too
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    store.create_station_ship('wormhole', 'Wormhole')

    def run(*args):
        cli([args[0], '--data-dir', str(store.data_dir), *args[1:]])
        return capsys.readouterr().out
    gamma = store.create_room(andy['id'], 'Gamma Quadrant', [])['id']
    for key in ('spec:a', 'spec:b', 'spec:c'):
        store.post_item(andy['id'], gamma, key, 'Gamma work', 'spec')
    store.drop_item(andy['id'], gamma, 'spec:c')
    out = run('station-bridge', '--id', gamma[:6], '--as', 'andy')
    assert 'keeps its messages and closed board items but is no longer the current room' in out
    assert out.rstrip().endswith('2 open board items came along.')
    new = next(r['id'] for r in store.list_rooms(andy['id']) if r['linked_room_id'] == gamma)
    assert [i['key'] for i in store.room_board(andy['id'], new)] == ['spec:a', 'spec:b']
    assert [i['key'] for i in store.room_board(andy['id'], gamma)] == ['spec:c']
    assert 'Unbridged' in run('station-unbridge', '--id', new[:6], '--as', 'andy')
    assert [i['key'] for i in store.room_board(andy['id'], new)] == ['spec:a', 'spec:b']
    one = store.create_room(andy['id'], 'One item', [])['id']
    store.post_item(andy['id'], one, 'spec:one', 'Just one', 'spec')
    assert run('station-bridge', '--id', one[:6], '--as', 'andy').rstrip().endswith('1 open board item came along.')
    quiet = store.create_room(andy['id'], 'Quiet', [])['id']
    assert run('station-bridge', '--id', quiet[:6], '--as', 'andy').rstrip().endswith('The room had no open board items.')


def test_a_failed_carry_rolls_the_whole_add_back(env, monkeypatch):
    """5.x: the brief's carry and the board's carry run in add_participants' own transaction. If the board carry fails
    after moving the items (the brief is already written by then), nothing is added: no new room, no carried brief, and
    the open items, their claims and the old room's brief stay where they were."""
    s = Station(env)
    assert post(s.ship('serenity'), s.room, 'build:a').status_code == 201
    assert claim(s.ship('rio-grande'), s.room, 'build:a').status_code == 201
    assert s.andy.put(f'/api/chats/{s.room}/brief', json={'body': 'Keep the lights on.', 'revision': 0}).status_code == 200
    briefs = 'SELECT * FROM room_briefs ORDER BY room_id'
    history = 'SELECT * FROM room_brief_revisions ORDER BY room_id, revision'
    before = s.snapshot(), s.rows('SELECT id FROM rooms ORDER BY id'), s.rows(briefs), s.rows(history)
    assert len(before[2]) == 1
    real = Store._carry_board

    def carry_then_fail(self, db, old, new):
        real(self, db, old, new)
        raise RuntimeError('the carry failed after moving the items')
    monkeypatch.setattr(Store, '_carry_board', carry_then_fail)
    with pytest.raises(RuntimeError):
        s.store.add_participants(s.id('andy'), s.room, [s.users[3]['id']], 1)
    assert (s.snapshot(), s.rows('SELECT id FROM rooms ORDER BY id'), s.rows(briefs), s.rows(history)) == before


def test_a_non_writer_linking_a_done_item_gets_the_409_before_the_403(env):
    """Link's refusals run in 5.1's order: row 16 (already done) comes before row 17 (a board writer), so a member who
    couldn't link an open item is told the item is closed, not that they may not."""
    s = Station(env)
    assert post(s.ship('serenity'), s.room, 'build:a').status_code == 201
    assert done(s.andy, s.room, 'build:a').status_code == 200
    assert refused(link(s.ship('defiant'), s.room, 'build:a', 'branch:x')) == (409, '`build:a` is already done')


def test_the_board_mark_on_a_claim_is_scoped_to_its_room(env):
    """5.6: `board` comes from an item in the claim's own room. An item with the same key in another room doesn't mark
    a claim here, where the key is not an item."""
    s = Station(env)
    insert_item(s, s.make_room('Another room'), 'adhoc:x', poster='andy')
    answer = claim(s.ship('rio-grande'), s.room, 'adhoc:x')
    assert answer.status_code == 201 and 'board' not in answer.json()
    assert all('board' not in c for c in claims(s.andy, s.room))
