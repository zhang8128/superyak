"""Room claims (spec S8): advisory, exclusive per (room, key), announced in the room as the claimant with kind
`claim`, and never a reason for anything else to change."""
import pytest
from superyak_peer.common import Problem
from test_federation import deliver, two_peers  # noqa: F401 - two_peers is a fixture
from test_presence import HEADERS, docked, say, ship_client


def setup(env):
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'])
    room = clients[0].post('/api/chats', json={'title': 'Ops', 'member_ids': [ship['id'], users[1]['id']]}).json()['id']
    return app, clients, users, clock, store, ship, ship_client(app, key, **HEADERS), room


def claim(client, room, key, **body):
    return client.post(f'/api/chats/{room}/claims', json={'key': key, **body})


def release(client, room, key):
    return client.post(f'/api/chats/{room}/claims/release', json={'key': key})


def claims(client, room):
    return client.get(f'/api/chats/{room}/claims').json()


def claim_messages(client, room):
    return [(m['author_id'], m['body']) for m in client.get(f'/api/chats/{room}').json()['messages'] if (m['source'] or {}).get('kind') == 'claim']


def test_claim_keys_outside_the_syntax_are_refused(env):
    """R14: lowercased first, then refused with 400 before anything is written; the other arguments are checked too."""
    app, clients, users, clock, store, ship, serenity, room = setup(env)
    for bad in ('', '-lead', 'a b', 'x' * 101, 'ä', 'spec:d7\n', '@serenity', 42, None):
        assert claim(serenity, room, bad).status_code == 400, bad
    for body in ({'minutes': 9}, {'minutes': 1441}, {'minutes': 30.5}, {'note': 'x' * 201}, {'note': 5}):
        assert claim(serenity, room, 'spec:d8', **body).status_code == 400, body
    assert claims(serenity, room) == [] and claim_messages(clients[0], room) == []
    assert claim(serenity, room, 'Spec:D7').status_code == 201
    assert [c['key'] for c in claims(serenity, room)] == ['spec:d7'] and claims(serenity, room) == clients[0].get(f'/api/chats/{room}').json()['claims']
    assert claim(clients[1], room, 'spec:d7').status_code == 409


def test_a_held_key_is_refused_to_another_and_renewed_for_its_holder(env):
    """R15: one active claim per (room, key); a second claimant gets 409 naming the holder, the note and the expiry;
    the holder re-claiming renews; another room's claim on the same key is separate; an expired claim frees the key."""
    app, clients, users, clock, store, ship, serenity, room = setup(env)
    assert claim(serenity, room, 'branch:lane-mac', note='the two Mac failures', minutes=60).status_code == 201
    refused = claim(clients[1], room, 'Branch:Lane-Mac')
    assert refused.status_code == 409
    assert refused.json()['error'] == f"{ship['name']} holds `branch:lane-mac` until 14:46 UTC: the two Mac failures"
    renewed = claim(serenity, room, 'branch:lane-mac', minutes=120).json()
    assert renewed['expires'] == clock[0] + 7200 and renewed['note'] == 'the two Mac failures'
    other = clients[0].post('/api/chats', json={'title': 'Other', 'member_ids': [users[1]['id']]}).json()['id']
    assert claim(clients[1], other, 'branch:lane-mac').status_code == 201
    clock[0] += 7200
    assert claim(clients[1], room, 'branch:lane-mac').status_code == 201


def test_release_is_for_the_holder_its_owner_and_the_room_owner(env):
    """R16: 403 for anyone else, 404 when nothing is held; a released claim is not active."""
    app, clients, users, clock, store, ship, serenity, room = setup(env)
    lab = clients[1].post('/api/chats', json={'title': 'Lab', 'member_ids': [ship['id'], users[0]['id'], users[3]['id']]}).json()['id']
    for releaser in (serenity, clients[0], clients[1]):        # the holder, its owner, the room's owner
        assert claim(serenity, lab, 'spec:d7').status_code == 201
        assert release(clients[3], lab, 'spec:d7').status_code == 403
        assert release(releaser, lab, 'spec:d7').status_code == 200
        assert claims(serenity, lab) == []
    assert release(serenity, lab, 'spec:d7').status_code == 404
    assert claim(clients[3], lab, 'spec:d7').status_code == 201 and release(serenity, lab, 'spec:d7').status_code == 403


def test_claim_messages_post_on_claim_and_release_and_on_a_changed_note_only(env):
    """R17: one message on claiming, one on releasing, one on a renewal only when its note changes, none on expiry;
    each posted as the claimant with kind `claim`; a 200-character note intact; a note with a live ship key refused
    before anything is written."""
    app, clients, users, clock, store, ship, serenity, room = setup(env)
    assert claim(serenity, room, 'spec:d7', note='n' * 200, minutes=60).status_code == 201
    clock[0] += 1
    claim(serenity, room, 'spec:d7', minutes=90)                 # the same note: silent
    clock[0] += 1
    claim(serenity, room, 'spec:d7', note='now the tests')       # a new note: one message
    clock[0] += 1
    release(serenity, room, 'spec:d7')
    clock[0] += 1
    claim(clients[1], room, 'spec:d8', minutes=10)
    clock[0] += 601                                              # the expiry posts nothing
    live_key = serenity.headers['authorization'].removeprefix('Bearer ')
    assert claim(serenity, room, 'spec:d9', note=f'key {live_key}').status_code == 422
    assert claim_messages(clients[0], room) == [
        (ship['id'], f'Claimed `spec:d7` until 14:46 UTC: {"n" * 200}'),
        (ship['id'], 'Renewed `spec:d7` until 17:46 UTC: now the tests'),
        (ship['id'], 'Released `spec:d7`'),
        (users[1]['id'], 'Claimed `spec:d8` until 13:56 UTC')]
    assert claims(serenity, room) == []


def test_claims_never_change_posting_ticketing_or_runs(env):
    """R18: with a key claimed by someone else, the ship still posts about it, and its tickets are decided exactly as
    without the claim."""
    app, clients, users, clock, store, ship, serenity, room = setup(env)
    claim(clients[1], room, 'branch:main', note='mine')
    asked = say(clients[1], room, 'q', '@serenity please look at branch:main')
    assert serenity.post('/api/ships/me/tickets', json={'message_id': asked['id']}).json()['mode'] == 'read'
    owner = say(clients[0], room, 'o', '@serenity build on branch:main')
    assert serenity.post('/api/ships/me/tickets', json={'message_id': owner['id']}).json()['mode'] == 'build'
    assert say(serenity, room, 'p', 'working on branch:main anyway')['body'] == 'working on branch:main anyway'


def test_claims_and_presence_stay_local(two_peers):
    """R19: claims belong to local rooms only, and their messages never reach a paired peer."""
    a, b, ca, cb = two_peers
    store = a[0]
    room = store.create_room(a[1], 'Across peers', [ca['id']])
    store.claim(a[1], room['id'], 'spec:d7', 'local only', 60)
    deliver(a, b)
    remote = b[0].list_rooms(b[1])[0]
    with pytest.raises(Problem) as refused:
        b[0].claim(b[1], remote['id'], 'spec:d7', None, 60)
    assert refused.value.status == 400
    shown = b[0].get_room(b[1], remote['id'])
    assert shown['messages'] == [] and 'claims' not in shown


def test_claim_and_notice_messages_never_wake_a_ship(env):
    """R20, station side, and Review Focus 3: an @name quoted in a note shows as (at)name, records no mention, and its
    ticket is refused with 422. The resident watcher's half (a person's claim in a DM with Odo) is Task 10's
    test_a_system_message_never_starts_a_run_or_counts_as_answered."""
    app, clients, users, clock, store, ship, serenity, room = setup(env)
    claim(clients[1], room, 'spec:d7', note='ask @serenity to build it')
    message = [m for m in clients[0].get(f'/api/chats/{room}').json()['messages'] if (m['source'] or {}).get('kind') == 'claim'][0]
    assert '(at)serenity' in message['body'] and '@' not in message['body']
    assert serenity.get('/api/mentions?after=0').json() == []
    assert serenity.post('/api/ships/me/tickets', json={'message_id': message['id']}).status_code == 422


def test_a_claimant_holds_at_most_20_claims(env):
    """S8 budgets: 20 active claims per claimant; a release frees one."""
    app, clients, users, clock, store, ship, serenity, room = setup(env)
    for n in range(20):
        assert claim(clients[1], room, f'task:{n}').status_code == 201
    assert claim(clients[1], room, 'task:20').status_code == 429
    release(clients[1], room, 'task:0')
    assert claim(clients[1], room, 'task:20').status_code == 201


def test_claims_made_in_one_instant_list_in_the_order_they_were_made(env):
    """Claim ids are random, so a frozen clock must not let them reorder the room's claim list (the same tie as room
    messages): one instant, insertion order."""
    app, clients, users, clock, store, ship, serenity, room = setup(env)
    keys = [f'task:{n}' for n in range(15)]
    for key in keys:
        assert claim(clients[1], room, key).status_code == 201
    assert [c['key'] for c in claims(clients[1], room)] == keys
