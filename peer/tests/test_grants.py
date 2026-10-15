"""Grants (spec A step 3, merge 3b: G7-G14 of docs/superpowers/specs/2026-10-15-grants-step3-design.md)."""
import base64
from contextlib import closing
import shutil
import sqlite3
import pytest
from superyak_peer import grants as G
from superyak_peer.common import uid
from superyak_peer.grants import short_id
from superyak_peer.identity import PeerIdentity, RECORD_KEYS, verify_record
from test_instructions import docked, ship_client
from test_restore import reconcile as run_reconcile, staged
from test_signatures import card_of, raw_sign

DAY = 86400


def make(store, issuer, grantee, targets, rooms='*', hours=24, budget=5):
    """A grant stored through the store method POST /api/grants uses once its checks pass (G8): its id."""
    with store.transaction() as db:
        return store._insert_grant(db, issuer['id'], grantee['id'], [ship['id'] for ship in targets], rooms, hours, budget)


def validity(store, grant_id):
    with store.transaction() as db:
        return store._grant_validity(db, db.execute('SELECT * FROM grants WHERE id=?', (grant_id,)).fetchone())


def charge(store, grant_id, *ages):
    """One budget use per age, that many seconds before now, each under its own ticket id."""
    with store.transaction() as db:
        for age in ages:
            db.execute('INSERT INTO budget_uses(grant_id, ticket_id, created) VALUES(?,?,?)', (grant_id, uid(), store.clock() - age))


def narrowed(store, monkeypatch, **changes):
    """Test 6: the policy narrowed after the grant was made, by replacing _grant_policy (G7's one function)."""
    defaults = type(store)._grant_policy
    monkeypatch.setattr(store, '_grant_policy', lambda db: {**defaults(store, db), **changes})


def revoke_by_hand(store, grant_id, by, reason='revoked'):
    with store.transaction() as db:
        db.execute('UPDATE grants SET revoked=?, revoked_by=?, revoke_reason=? WHERE id=?',
                   (store.clock(), by and by['id'], reason, grant_id))


def test_a_new_grant_is_valid_and_its_short_id_is_four_characters(env):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    grant = make(store, users[0], users[1], [ship])
    assert validity(store, grant) == (True, None)
    assert short_id(grant) == '#' + grant[:4] and len(short_id(grant)) == 5


def test_a_revoked_grant_names_who_revoked_it_even_once_expired(env):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    store.rename_user(users[0]['id'], 'Andy\n@serenity')  # a name is a person's text: one safe line in a reason
    grant = make(store, users[0], users[1], [ship], hours=1)
    revoke_by_hand(store, grant, users[0])
    assert validity(store, grant) == (False, f'Grant #{grant[:4]} was revoked by Andy (at)serenity')
    clock[0] += 3600  # expired too: the revoked reason comes first (test 6)
    assert validity(store, grant) == (False, f'Grant #{grant[:4]} was revoked by Andy (at)serenity')
    restored = make(store, users[0], users[1], [ship])
    revoke_by_hand(store, restored, None, 'restored')  # the restore reconcile records no person (G13)
    assert validity(store, restored) == (False, f'Grant #{restored[:4]} was revoked')


def test_a_grant_expires_at_its_expiry_time(env):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    grant = make(store, users[0], users[1], [ship], hours=1)  # made at 1000000.0, so it expires at 1003600.0
    clock[0] += 3599
    assert validity(store, grant) == (True, None)
    clock[0] += 1
    assert validity(store, grant) == (False, f'Grant #{grant[:4]} expired 1970-01-12 14:46 UTC')


def test_a_narrowed_policy_takes_effect_at_the_next_check(env, monkeypatch):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    grant = make(store, users[0], users[1], [ship], hours=24)
    policy = f"Grant #{grant[:4]} is no longer allowed by the station's policy"
    for changes, expected in (({'max_expiry_hours': 24}, (True, None)),  # exactly its lifetime still fits
                              ({'max_expiry_hours': 23}, (False, f'Grant #{grant[:4]} lasts longer than the station now allows')),
                              ({'max_depth': 1}, (True, None)),  # a root is a chain of one link
                              ({'max_depth': 0}, (False, policy)),
                              ({'grantees': {users[1]['id']}}, (True, None)),
                              ({'grantees': {users[3]['id']}}, (False, policy))):
        narrowed(store, monkeypatch, **changes)
        assert validity(store, grant) == expected, changes


def test_the_budget_counts_builds_in_the_last_24_hours_only(env):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    grant = make(store, users[0], users[1], [ship], budget=2)
    charge(store, grant, DAY, DAY - 1)  # exactly 24 hours old no longer counts; a second younger does
    assert validity(store, grant) == (True, None)
    charge(store, grant, 0)
    assert validity(store, grant) == (False, f'Grant #{grant[:4]} has used its 2 builds for the last 24 hours')
    single = make(store, users[0], users[1], [ship], budget=1)
    charge(store, single, 10)
    assert validity(store, single) == (False, f'Grant #{single[:4]} has used its 1 build for the last 24 hours')


def test_an_issuer_who_no_longer_owns_every_target_holds_no_valid_grant(env):
    app, clients, users, clock = env
    store = app.state.store
    serenity, _ = docked(store, users[0]['id'], 'serenity')
    rio, _ = docked(store, users[0]['id'], 'rio-grande')
    grant = make(store, users[0], users[1], [serenity, rio])
    with store.transaction() as db:  # by hand: ownership never changes today, but a restored or edited database could
        db.execute('UPDATE users SET owner_id=? WHERE id=?', (users[3]['id'], rio['id']))
    assert validity(store, grant) == (False, 'Patient no longer owns Rio Grande')


def test_the_first_check_that_fails_is_the_reason(env, monkeypatch):
    """G9's order, one pair of neighbours at a time: each grant fails two checks, and the earlier one is the reason."""
    app, clients, users, clock = env
    store = app.state.store
    serenity, _ = docked(store, users[0]['id'], 'serenity')
    rio, _ = docked(store, users[0]['id'], 'rio-grande')
    spent_and_lost = make(store, users[0], users[1], [rio], budget=1)  # 4 (budget) before 5 (ownership)
    charge(store, spent_and_lost, 10)
    with store.transaction() as db:
        db.execute('UPDATE users SET owner_id=? WHERE id=?', (users[3]['id'], rio['id']))
    assert validity(store, spent_and_lost) == (False, f'Grant #{spent_and_lost[:4]} has used its 1 build for the last 24 hours')
    spent = make(store, users[0], users[1], [serenity], budget=1)  # 3 (policy) before 4 (budget)
    charge(store, spent, 10)
    narrowed(store, monkeypatch, max_depth=0)
    assert validity(store, spent) == (False, f"Grant #{spent[:4]} is no longer allowed by the station's policy")
    long = make(store, users[0], users[1], [serenity], hours=24)  # 2 (expired) before 3 (lifetime)
    narrowed(store, monkeypatch, max_expiry_hours=1)
    clock[0] += DAY
    assert validity(store, long) == (False, f'Grant #{long[:4]} expired 1970-01-13 13:46 UTC')


def grant_row(store, grant_id):
    with store.transaction() as db:
        return dict(db.execute('SELECT * FROM grants WHERE id=?', (grant_id,)).fetchone())


def stored_grant_record(store, grant_id):
    with store.transaction() as db:
        return store._grant_record(db, grant_id)


def test_a_grants_signature_verifies_and_its_record_has_exactly_g12s_keys(env, tmp_path):
    app, clients, users, clock = env
    store = app.state.store
    serenity, _ = docked(store, users[0]['id'], 'serenity')
    rio, _ = docked(store, users[0]['id'], 'rio-grande')
    room = store.create_room(users[0]['id'], 'Ops', [users[1]['id']])
    grant = make(store, users[0], users[1], [serenity, rio], rooms=[room['id']], hours=48, budget=3)
    identity, record, signature = store._station_identity(), stored_grant_record(store, grant), grant_row(store, grant)['signature']
    card = card_of(identity)
    assert set(record) == RECORD_KEYS['grant']
    assert record == {'kind': 'grant', 'station': identity.peer_id, 'id': grant, 'issuer_id': users[0]['id'],
                      'grantee_id': users[1]['id'], 'actions': ['direct'], 'targets': [serenity['id'], rio['id']],
                      'rooms': [room['id']], 'expires': 1000000.0 + 48 * 3600, 'budget': 3, 'depth': 0, 'confirm': 'none',
                      'parent_id': None, 'charter_layer_id': None, 'charter_revision': None, 'follow': 0,
                      'created': 1000000.0}
    assert verify_record(card, record, signature)
    assert not verify_record(card, {**record, 'budget': 4}, signature)  # one changed value
    flipped = bytearray(base64.b64decode(signature))
    flipped[0] ^= 1
    assert not verify_record(card, record, base64.b64encode(bytes(flipped)).decode())
    other = PeerIdentity.load_or_create(tmp_path / 'other')
    named_other = {**record, 'station': other.peer_id}
    assert not verify_record(card, named_other, raw_sign(identity, named_other))  # names another station
    added = {**record, 'session': 'x'}
    assert not verify_record(card, added, raw_sign(identity, added))  # a key a later step might add
    missing = {key: value for key, value in record.items() if key != 'follow'}
    assert not verify_record(card, missing, raw_sign(identity, missing))
    forged = {**record, 'station': '0' * 64}
    assert not verify_record({**card, 'peer_id': '0' * 64}, forged, raw_sign(identity, forged))  # peer id isn't the key's hash
    anywhere = make(store, users[0], users[1], [serenity])
    assert stored_grant_record(store, anywhere)['rooms'] == '*'  # '"*"' parsed, not the stored text
    assert verify_record(card, stored_grant_record(store, anywhere), grant_row(store, anywhere)['signature'])


def test_a_grant_whose_signing_fails_is_not_stored(env, monkeypatch):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')

    def refuse(self, record):
        raise ValueError('no key')

    monkeypatch.setattr(PeerIdentity, 'sign_record', refuse)
    with pytest.raises(ValueError):
        make(store, users[0], users[1], [ship])
    with store.transaction() as db:
        assert db.execute('SELECT count(*) FROM grants').fetchone()[0] == 0  # signed in the insert's transaction, or not at all


def test_a_station_holding_grants_does_not_start_without_its_identity(tmp_path):
    """G4b, from merge 3b: a grant is a signed record, so a station holding one refuses to start without identity.json;
    and a new station's first grant still creates the identity (the row being signed doesn't count itself)."""
    from superyak_peer.db import Store
    store = Store(tmp_path / 'station')
    owner, other = store.create_user('owner', 'Owner', 'long-password'), store.create_user('other', 'Other', 'long-password')
    ship, _ = docked(store, owner['id'], 'serenity')
    assert not (store.data_dir / 'identity.json').exists()
    grant = make(store, owner, other, [ship])  # the station's first signature
    assert verify_record(card_of(PeerIdentity.load_or_create(store.data_dir)), stored_grant_record(store, grant),
                         grant_row(store, grant)['signature'])
    with store.transaction() as db:
        assert db.execute('SELECT count(*) FROM revision_signatures').fetchone()[0] == 0  # the grant is the only record
    (store.data_dir / 'identity.json').unlink()
    with pytest.raises(ValueError, match='identity.json'):
        Store(store.data_dir)


def listed(client):
    response = client.get('/api/grants')
    assert response.status_code == 200, response.text
    return response.json()


def ids(client):
    return [grant['id'] for grant in listed(client)]


def test_each_person_sees_the_grants_they_issued_hold_or_that_cover_their_ships(env):
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    serenity, _ = docked(store, patient['id'], 'serenity')
    rio, _ = docked(store, patient['id'], 'rio-grande')
    held = make(store, patient, doctor, [serenity])
    clock[0] += 1
    covering = make(store, patient, doctor, [rio])
    with store.transaction() as db:  # by hand: in step 3 a ship's owner is its grants' issuer
        db.execute('UPDATE users SET owner_id=? WHERE id=?', (family['id'], rio['id']))
    assert ids(clients[0]) == [covering, held]  # the issuer, newest first
    assert ids(clients[1]) == [covering, held]  # the grantee
    assert ids(clients[3]) == [covering]  # rio-grande's owner now
    assert ids(clients[2]) == []  # an admin with no tie sees nothing
    card = card_of(store._station_identity())
    for client, grant in ((clients[0], held), (clients[1], held), (clients[3], covering)):
        signed = client.get(f'/api/grants/{grant}/signed')
        assert signed.status_code == 200, signed.text
        assert set(signed.json()) == {'station', 'record', 'signature'} and signed.json()['record']['id'] == grant
        assert signed.json()['station'] == store._station_identity().peer_id
        assert verify_record(card, signed.json()['record'], signed.json()['signature'])
    for client, grant in ((clients[3], held), (clients[2], held), (clients[2], covering), (clients[0], 'no-such-grant')):
        assert client.get(f'/api/grants/{grant}/signed').status_code == 404, grant


def test_a_grant_shows_its_people_ships_rooms_budget_and_validity(env):
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    serenity, _ = docked(store, patient['id'], 'serenity')
    rio, _ = docked(store, patient['id'], 'rio-grande')
    ops = store.create_room(patient['id'], 'Ops', [doctor['id'], serenity['id']])
    grant = make(store, patient, doctor, [serenity, rio], rooms=[ops['id']], hours=24, budget=5)
    other = make(store, patient, family, [serenity])
    charge(store, grant, 10, 20, DAY)  # two in the last 24 hours; one exactly 24 hours old, which no longer counts
    sent = [store.send_message(patient['id'], ops['id'], f'm{n}', f'@serenity {n}')['id'] for n in range(5)]
    with store.transaction() as db:  # serenity's tickets, as merge 3c will write them: two grant builds count
        for message, mode, basis, age in ((sent[0], 'build', 'grant', 10), (sent[1], 'build', 'grant', DAY - 1),
                                          (sent[2], 'build', 'grant', DAY), (sent[3], 'build', 'owner', 10),
                                          (sent[4], 'read', 'none', 10)):
            db.execute("INSERT INTO tickets(id,ship_id,message_id,mode,basis,status,created) VALUES(?,?,?,?,?,'finished',?)",
                       (uid(), serenity['id'], message, mode, basis, clock[0] - age))
    views = {view['id']: view for view in listed(clients[0])}
    assert views[grant] == {
        'id': grant, 'short': '#' + grant[:4], 'issuer': {'id': patient['id'], 'name': 'Patient'},
        'grantee': {'id': doctor['id'], 'name': 'Doctor'},
        'targets': [{'id': serenity['id'], 'name': 'Serenity', 'ship_builds_left': 18},
                    {'id': rio['id'], 'name': 'Rio Grande', 'ship_builds_left': 20}],
        'rooms': [{'id': ops['id'], 'title': 'Ops'}], 'expires': 1000000.0 + DAY, 'budget': 5, 'budget_left': 3,
        'created': 1000000.0, 'revoked': None, 'revoked_by': None, 'revoke_reason': None, 'valid': True}
    assert views[other]['targets'] == [{'id': serenity['id'], 'name': 'Serenity', 'ship_builds_left': 18}]  # every grant's
    assert views[other]['rooms'] == '*' and views[other]['budget_left'] == 5
    charge(store, other, *range(1, 8))  # more uses than its budget (only by hand): none left, never fewer
    revoke_by_hand(store, grant, patient, 'Done for now')
    views = {view['id']: view for view in listed(clients[1])}
    assert views[grant]['valid'] is False and views[grant]['reason'] == f'Grant #{grant[:4]} was revoked by Patient'
    assert (views[grant]['revoked'], views[grant]['revoked_by'], views[grant]['revoke_reason']) == \
        (1000000.0, {'id': patient['id'], 'name': 'Patient'}, 'Done for now')
    views = {view['id']: view for view in listed(clients[0])}
    assert views[other]['budget_left'] == 0 and views[other]['reason'].endswith('has used its 5 builds for the last 24 hours')


def test_room_titles_show_only_to_members_and_a_replaced_room_shows_the_current_one(env):
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    serenity, _ = docked(store, patient['id'], 'serenity')
    ops = store.create_room(patient['id'], 'Ops', [doctor['id']])
    plans = store.create_room(patient['id'], 'Plans', [doctor['id']])
    grant = make(store, patient, doctor, [serenity], rooms=[ops['id'], plans['id']])
    removed = clients[0].delete(f'/api/chats/{ops["id"]}/participants/{doctor["id"]}')  # the room's owner removes the grantee
    assert removed.status_code == 200, removed.text
    second = clients[0].post(f'/api/chats/{plans["id"]}/participants', json={'member_ids': [family['id']]}).json()
    third = clients[0].post(f'/api/chats/{second["id"]}/participants', json={'member_ids': [organizer['id']]}).json()
    current = {'id': third['id'], 'title': 'Plans'}  # Plans was replaced twice: the grant covers the newest
    assert listed(clients[1])[0]['rooms'] == [
        {'id': ops['id'], 'title': 'a room you are not in'}, {'id': plans['id'], 'title': 'Plans', 'current': current}]
    assert listed(clients[0])[0]['rooms'] == [
        {'id': ops['id'], 'title': 'Ops'}, {'id': plans['id'], 'title': 'Plans', 'current': current}]
    gone = clients[0].delete(f'/api/chats/{third["id"]}/participants/{doctor["id"]}')  # M1: doctor leaves the newest room
    assert gone.status_code == 200, gone.text
    assert listed(clients[1])[0]['rooms'][1]['current'] == {'id': third['id'], 'title': 'a room you are not in'}
    with store.transaction() as db:  # by hand, so serenity's new owner sees the grant: added later, never in Plans itself
        db.execute('UPDATE users SET owner_id=? WHERE id=?', (family['id'], serenity['id']))
    assert listed(clients[3])[0]['rooms'] == [
        {'id': ops['id'], 'title': 'a room you are not in'},
        {'id': plans['id'], 'title': 'a room you are not in', 'current': current}]
    loop_a = store.create_room(patient['id'], 'Loop A', [doctor['id']])
    loop_b = store.create_room(patient['id'], 'Loop B', [doctor['id']])
    with store.transaction() as db:  # a linked_room_id cycle, made by hand, ends the walk: no current room
        db.execute('UPDATE rooms SET linked_room_id=? WHERE id=?', (loop_b['id'], loop_a['id']))
        db.execute('UPDATE rooms SET linked_room_id=? WHERE id=?', (loop_a['id'], loop_b['id']))
    looped = make(store, patient, doctor, [serenity], rooms=[loop_a['id']])
    shown = next(view for view in listed(clients[0]) if view['id'] == looped)
    assert shown['rooms'] == [{'id': loop_a['id'], 'title': 'Loop A'}]


def test_the_people_list_has_active_people_only(env, tmp_path):
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    docked(store, patient['id'], 'serenity')
    lower, zoe = store.create_user('lower', 'andy', 'long-password-low'), store.create_user('zoe', 'Zoe', 'long-password-zoe')
    store.create_station_ship('odo', 'Odo')  # a resident
    store.bootstrap_super_admin('root', 'Root', tmp_path / 'activation.json')  # awaiting activation
    with store.transaction() as db:
        db.execute("INSERT INTO peers(peer_id, card, paired) VALUES(?, '{}', 1)", ('ab' * 32,))
        db.execute("INSERT INTO remote_contacts(id, peer_id, user_id, name) VALUES('contact-1', ?, 'remote-user', 'Aaron')",
                   ('ab' * 32,))
    people = clients[0].get('/api/grants/people')
    assert people.status_code == 200, people.text
    assert people.json() == [{'id': lower['id'], 'name': 'andy'}, {'id': doctor['id'], 'name': 'Doctor'},
                             {'id': family['id'], 'name': 'Family'}, {'id': organizer['id'], 'name': 'Organizer'},
                             {'id': zoe['id'], 'name': 'Zoe'}]  # by name, ignoring case; no caller, ship, resident, system author


def test_a_ship_key_gets_403_on_every_grants_route(env):
    """G14: every /api/grants route takes a person session only (spec A Testing 3). The body is current_user's own
    refusal, so no store-level check can be what refused the ship."""
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'], 'serenity')
    grant = make(store, users[0], users[1], [ship])
    made = {'grantee': users[1]['id'], 'targets': [ship['id']], 'rooms': '*', 'hours': 24, 'budget': 5}
    routes = [('POST', '/api/grants', made), ('GET', '/api/grants', None), ('GET', '/api/grants/people', None),
              ('GET', f'/api/grants/{grant}/signed', None), ('POST', f'/api/grants/{grant}/revoke', {})]
    for method, path, body in routes:
        response = ship_client(app, key).request(method, path, json=body)
        assert (response.status_code, response.json()) == (403, {'error': 'Ship keys cannot use this route'}), (method, path)


def fleet(store, owner_id, count):
    """count ships owned by owner_id, written directly (docking allows 20 an hour, and scrypt is slow): their ids."""
    with store.transaction() as db:
        ships = [uid() for _ in range(count)]
        db.executemany("INSERT INTO users(id,username,name,salt,password_hash,is_admin,created,kind,owner_id) "
                       "VALUES(?,?,?,?,?,0,?,'ship',?)",
                       [(ship, f'fleet-{n}', f'Fleet {n}', b'\0' * 16, b'\0' * 32, store.clock(), owner_id)
                        for n, ship in enumerate(ships)])
    return ships


@pytest.fixture
def station(env, tmp_path):
    """Test 5's station: patient makes grants to doctor. Every refused room is one the caller (and, where it matters,
    the grantee) is in by hand, so the check named is the only one that can refuse it."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    serenity, _ = docked(store, patient['id'], 'serenity')
    rio, _ = docked(store, patient['id'], 'rio-grande')
    theirs, _ = docked(store, doctor['id'], 'jenn-ship')
    odo = store.create_station_ship('odo', 'Odo')
    pending = store.bootstrap_super_admin('root', 'Root', tmp_path / 'activation.json')
    shared = store.create_room(patient['id'], 'Ops', [doctor['id'], serenity['id'], rio['id']])
    alone = store.create_room(patient['id'], 'Alone', [])
    elsewhere = store.create_room(family['id'], 'Elsewhere', [doctor['id']])
    old = store.create_room(patient['id'], 'Old', [doctor['id']])
    store.add_participants(patient['id'], old['id'], [family['id']])  # Old is replaced now
    side = store.open_breakout(serenity['id'], 'Side', ['rio-grande'])
    remote = 'ab' * 32 + ':room-1'
    with store.transaction() as db:
        db.executemany('INSERT INTO room_members(room_id, user_id) VALUES(?,?)', [(side['id'], patient['id']), (side['id'], doctor['id'])])
        db.execute('INSERT INTO rooms(id, owner_id, title, epoch, linked_room_id) VALUES(?,?,?,1,NULL)', (remote, patient['id'], 'Remote'))
        db.executemany('INSERT INTO room_members(room_id, user_id) VALUES(?,?)', [(remote, patient['id']), (remote, doctor['id'])])
        system = store.system_author_id(db)
    good = {'grantee': doctor['id'], 'targets': [serenity['id']], 'rooms': [shared['id']], 'hours': 24, 'budget': 5}
    return dict(app=app, clients=clients, users=users, clock=clock, store=store, serenity=serenity, rio=rio,
                theirs=theirs, odo=odo, pending=pending, shared=shared, alone=alone, elsewhere=elsewhere, old=old,
                side=side, remote=remote, system=system, good=good)


def answer(station, client=None, **changes):
    response = (client or station['clients'][0]).post('/api/grants', json={**station['good'], **changes})
    return response.status_code, response.json().get('error')


def test_making_a_grant_refuses_each_bad_field_with_its_status(station):
    s = station
    patient, doctor, organizer, family = s['users']
    for rooms in (['no-such-room'], [s['remote']], [s['side']['id']], [s['elsewhere']['id']]):
        assert answer(s, rooms=rooms) == (404, G.ROOM_NOT_YOURS), rooms  # the same body for each (G8 step 1)
    hours = 'hours is a whole number from 1 to 720'
    for changes, error in (
            ({'rooms': [s['old']['id']]}, G.ROOM_REPLACED), ({'rooms': [s['alone']['id']]}, G.ROOM_WITHOUT_GRANTEE),
            ({'rooms': [s['shared']['id'], s['shared']['id']]}, G.ROOMS_SHAPE), ({'rooms': []}, G.ROOMS_SHAPE),
            ({'rooms': 'everywhere'}, G.ROOMS_SHAPE), ({'rooms': [5]}, G.ROOMS_SHAPE),
            ({'rooms': '*', 'grantee': patient['id']}, G.GRANTEE_IS_YOU),
            ({'rooms': '*', 'grantee': s['serenity']['id']}, G.GRANTEE_NOT_PERSON),
            ({'rooms': '*', 'grantee': s['system']}, G.GRANTEE_NOT_PERSON),
            ({'rooms': '*', 'grantee': s['pending']['id']}, G.GRANTEE_NOT_PERSON),
            ({'rooms': '*', 'grantee': 'no-such-person'}, G.GRANTEE_NOT_PERSON),
            ({'rooms': '*', 'grantee': ['x']}, G.GRANTEE_NOT_PERSON),
            ({'targets': [s['theirs']['id']]}, G.TARGET_NOT_YOURS), ({'targets': [s['odo']['id']]}, G.TARGET_NOT_YOURS),
            ({'targets': ['no-such-ship']}, G.TARGET_NOT_YOURS), ({'targets': [doctor['id']]}, G.TARGET_NOT_YOURS),
            ({'targets': [s['serenity']['id'], s['serenity']['id']]}, G.TARGETS_SHAPE), ({'targets': []}, G.TARGETS_SHAPE),
            ({'targets': s['serenity']['id']}, G.TARGETS_SHAPE),
            ({'hours': 0}, hours), ({'hours': 721}, hours), ({'hours': 1.5}, hours), ({'hours': True}, hours),
            ({'hours': '24'}, hours), ({'hours': None}, hours),
            ({'budget': 0}, G.BUDGET_RANGE), ({'budget': 501}, G.BUDGET_RANGE), ({'budget': 2.0}, G.BUDGET_RANGE),
            ({'budget': True}, G.BUDGET_RANGE), ({'budget': '5'}, G.BUDGET_RANGE)):
        assert answer(s, **changes) == (400, error), changes
    admin = {'rooms': '*', 'targets': [s['serenity']['id']]}  # an admin's power never reaches another person's ships
    assert answer(s, s['clients'][2], **admin) == (400, G.TARGET_NOT_YOURS)
    with s['store'].transaction() as db:
        assert db.execute('SELECT count(*) FROM grants').fetchone()[0] == 0


def test_making_a_grant_checks_in_the_spec_order(station):
    """G8's order, rooms first: each request fails two steps, and the earlier one answers."""
    s = station
    patient, doctor, organizer, family = s['users']
    assert answer(s, rooms=['no-such-room'], grantee=patient['id'], targets=[s['theirs']['id']], hours=0,
                  budget=0) == (404, G.ROOM_NOT_YOURS)  # 1 before everything
    assert answer(s, rooms=[s['alone']['id'], 'no-such-room']) == (404, G.ROOM_NOT_YOURS)  # every room's 1 before any 2
    assert answer(s, rooms=[s['old']['id']], grantee=patient['id']) == (400, G.ROOM_REPLACED)  # 2 before 3
    assert answer(s, rooms=[s['alone']['id']], grantee=s['serenity']['id']) == (400, G.ROOM_WITHOUT_GRANTEE)  # 2 before 3
    assert answer(s, rooms='*', grantee=patient['id'], targets=[s['theirs']['id']]) == (400, G.GRANTEE_IS_YOU)  # 3 before 4
    assert answer(s, targets=[s['theirs']['id']], hours=0) == (400, G.TARGET_NOT_YOURS)  # 4 before 5
    assert answer(s, hours=721, budget=0) == (400, 'hours is a whole number from 1 to 720')  # 5 before 6


def test_making_a_grant_takes_the_edges_and_refuses_one_past_them(station):
    s = station
    patient, doctor, organizer, family = s['users']
    ships = fleet(s['store'], patient['id'], 21)
    rooms = [s['store'].create_room(patient['id'], f'Room {n}', [doctor['id']])['id'] for n in range(21)]
    assert answer(s, targets=ships) == (400, G.TARGETS_SHAPE)
    assert answer(s, rooms=rooms) == (400, G.ROOMS_SHAPE)
    assert answer(s, targets=ships[:20], rooms=rooms[:20], hours=1, budget=1) == (201, None)
    assert answer(s, hours=720, budget=500) == (201, None)


def test_making_a_grant_reads_the_policy_in_force(station, monkeypatch):
    s = station
    narrowed(s['store'], monkeypatch, max_expiry_hours=24)
    assert answer(s, hours=25) == (400, 'hours is a whole number from 1 to 24')
    assert answer(s, hours=24) == (201, None)


def test_a_grant_made_in_the_browser_is_stored_signed_and_shown(station):
    s = station
    patient, doctor, organizer, family = s['users']
    client = s['clients'][0]
    assert client.post('/api/grants', json=s['good'], headers={'x-csrf-token': 'stale'}).status_code == 403  # CSRF
    made = client.post('/api/grants', json=s['good'])
    assert made.status_code == 201, made.text
    view = made.json()
    assert view == {'id': view['id'], 'short': '#' + view['id'][:4], 'issuer': {'id': patient['id'], 'name': 'Patient'},
                    'grantee': {'id': doctor['id'], 'name': 'Doctor'},
                    'targets': [{'id': s['serenity']['id'], 'name': 'Serenity', 'ship_builds_left': 20}],
                    'rooms': [{'id': s['shared']['id'], 'title': 'Ops'}], 'expires': 1000000.0 + 24 * 3600, 'budget': 5,
                    'budget_left': 5, 'created': 1000000.0, 'revoked': None, 'revoked_by': None, 'revoke_reason': None,
                    'valid': True}
    assert listed(client) == [view]  # the grant as G11 shows it
    row = grant_row(s['store'], view['id'])
    assert (row['actions'], row['depth'], row['confirm'], row['parent_id'], row['charter_layer_id'],
            row['charter_revision'], row['follow']) == ('["direct"]', 0, 'none', None, None, None, 0)
    assert verify_record(card_of(s['store']._station_identity()), stored_grant_record(s['store'], view['id']), row['signature'])
    anywhere = client.post('/api/grants', json={**s['good'], 'rooms': '*'})
    assert anywhere.status_code == 201 and anywhere.json()['rooms'] == '*'


def revoke(client, grant_id, **body):
    return client.post(f'/api/grants/{grant_id}/revoke', json=body)


def test_the_issuer_or_a_targets_owner_revokes_and_no_one_else(env):
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    rio, _ = docked(store, patient['id'], 'rio-grande')
    first = make(store, patient, doctor, [rio])
    second = make(store, patient, doctor, [rio])
    with store.transaction() as db:  # by hand: in step 3 the target's owner is the issuer, so this splits the two rules
        db.execute('UPDATE users SET owner_id=? WHERE id=?', (family['id'], rio['id']))
    assert revoke(clients[1], first).status_code == 403  # the grantee sees it but may not revoke it
    assert revoke(clients[2], first).status_code == 404  # an admin with no other tie doesn't see it
    assert revoke(clients[0], 'no-such-grant').status_code == 404
    done = revoke(clients[0], first)  # the issuer, who no longer owns rio-grande
    assert done.status_code == 200, done.text
    assert (done.json()['revoked'], done.json()['revoked_by'], done.json()['revoke_reason'], done.json()['valid'],
            done.json()['reason']) == (1000000.0, {'id': patient['id'], 'name': 'Patient'}, 'revoked', False,
                                       f'Grant #{first[:4]} was revoked by Patient')
    assert revoke(clients[0], first).status_code == 409  # a second revoke
    assert revoke(clients[1], first).status_code == 403  # 403 before 409
    assert revoke(clients[2], first).status_code == 404  # 404 before both
    by_owner = revoke(clients[3], second, reason='Not this week')  # rio-grande's owner, who didn't issue it
    assert by_owner.status_code == 200, by_owner.text
    assert (by_owner.json()['revoked_by']['id'], by_owner.json()['revoke_reason']) == (family['id'], 'Not this week')


def test_the_issuer_of_a_grant_above_may_revoke_it(env):
    """G10's walk, which step 3 never reaches: a child row made by hand, as step 5's delegation will make them."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    serenity, _ = docked(store, patient['id'], 'serenity')
    root = make(store, patient, doctor, [serenity])
    child = make(store, doctor, family, [serenity])
    with store.transaction() as db:  # patient now neither issued the child nor owns its ship: only the walk reaches it
        db.execute('UPDATE grants SET parent_id=? WHERE id=?', (root, child))
        db.execute('UPDATE users SET owner_id=? WHERE id=?', (organizer['id'], serenity['id']))
    revoked = revoke(clients[0], child)
    assert revoked.status_code == 200, revoked.text


def test_a_revoke_reason_is_one_line_of_at_most_200_characters(env):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    grant = make(store, users[0], users[1], [ship])
    for reason in ('x' * 201, 'two\nlines', 'two lines', 'nul\x00', 5, ['x']):
        assert revoke(clients[0], grant, reason=reason).status_code == 400, reason
    assert revoke(clients[0], grant, reason='   ').json()['revoke_reason'] == 'revoked'  # blank is no reason
    longest = make(store, users[0], users[1], [ship])
    assert revoke(clients[0], longest, reason='x' * 200).json()['revoke_reason'] == 'x' * 200


def test_a_revocations_signature_verifies_and_the_signed_route_carries_it(env, tmp_path):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    grant = make(store, users[0], users[1], [ship])
    assert 'revocation' not in clients[1].get(f'/api/grants/{grant}/signed').json()
    clock[0] += 60
    assert revoke(clients[0], grant, reason='Done').status_code == 200
    signed = clients[1].get(f'/api/grants/{grant}/signed').json()  # the grantee reads it too
    identity = store._station_identity()
    card = card_of(identity)
    record, signature = signed['revocation']['record'], signed['revocation']['signature']
    assert set(signed) == {'station', 'record', 'signature', 'revocation'} and set(signed['revocation']) == {'record', 'signature'}
    assert set(record) == RECORD_KEYS['grant-revocation']
    assert record == {'kind': 'grant-revocation', 'station': identity.peer_id, 'grant': grant, 'revoked': 1000060.0,
                      'revoked_by': users[0]['id'], 'reason': 'Done'}
    assert verify_record(card, record, signature)
    assert verify_record(card, signed['record'], signed['signature'])  # the grant's own signature still verifies
    assert not verify_record(card, {**record, 'reason': 'revoked'}, signature)  # one changed value
    assert not verify_record(card, signed['record'], signature)  # a revocation's signature never passes for its grant's
    other = PeerIdentity.load_or_create(tmp_path / 'other')
    named_other = {**record, 'station': other.peer_id}
    assert not verify_record(card, named_other, raw_sign(identity, named_other))
    added = {**record, 'note': 'x'}
    assert not verify_record(card, added, raw_sign(identity, added))
    missing = {key: value for key, value in record.items() if key != 'reason'}
    assert not verify_record(card, missing, raw_sign(identity, missing))
    forged = {**record, 'station': '0' * 64}
    assert not verify_record({**card, 'peer_id': '0' * 64}, forged, raw_sign(identity, forged))


def test_startup_signs_each_unsigned_revocation_once(env, monkeypatch):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    revoked, kept = make(store, users[0], users[1], [ship]), make(store, users[0], users[1], [ship])
    assert revoke(clients[0], revoked).status_code == 200
    with store.transaction() as db:  # as the restore reconcile leaves a revocation (G13)
        db.execute('UPDATE grants SET revocation_signature=NULL WHERE id=?', (revoked,))
    from superyak_peer.db import Store
    assert grant_row(Store(store.data_dir, signing=False), revoked)['revocation_signature'] is None  # G4a: no backfill there
    restarted = Store(store.data_dir)
    rows = {grant: grant_row(restarted, grant)['revocation_signature'] for grant in (revoked, kept)}
    assert rows[kept] is None  # nothing to sign on a grant still in force
    with restarted.transaction() as db:
        assert verify_record(card_of(restarted._station_identity()), restarted._revocation_record(db, revoked), rows[revoked])
    signed, real = [], PeerIdentity.sign_record
    monkeypatch.setattr(PeerIdentity, 'sign_record', lambda self, record: signed.append(record) or real(self, record))
    Store(store.data_dir)
    assert signed == [] and grant_row(restarted, revoked)['revocation_signature'] == rows[revoked]  # a second start signs nothing


def lighthouse(tmp_path):
    """A station on a clock the test moves, with andy granting jenn: (store, clock, andy, jenn, serenity)."""
    from superyak_peer.db import Store
    clock = [1000000.0]
    store = Store(tmp_path / 'lighthouse', clock=lambda: clock[0])
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    jenn = store.create_user('jenn', 'Jenn', 'long-password-jenn')
    serenity, _ = docked(store, andy['id'], 'serenity')
    return store, clock, andy, jenn, serenity


def revocations(path):
    with closing(sqlite3.connect(path)) as db:
        return {row[0]: row[1:] for row in db.execute('SELECT id, revoked, revoked_by, revoke_reason, revocation_signature FROM grants')}


def uses(path):
    with closing(sqlite3.connect(path)) as db:
        return db.execute('SELECT grant_id, ticket_id, created FROM budget_uses ORDER BY grant_id, created').fetchall()


def report_line(out, start):
    return next((line for line in out.splitlines() if line.startswith(start)), None)


def test_the_reconcile_takes_back_revoked_grants_and_spent_budgets(tmp_path, capsys):
    """Test 10, with a replaced file: a grant revoked there is revoked here as it was there, a grant missing there is
    revoked, the budget uses there are added once, and the station's next start signs those revocations."""
    store, clock, andy, jenn, serenity = lighthouse(tmp_path)
    kept = make(store, andy, jenn, [serenity])  # in force in both files
    clock[0] += 1
    later = make(store, andy, jenn, [serenity])  # revoked after the copy
    clock[0] += 1
    lost = make(store, andy, jenn, [serenity])  # missing from the replaced file
    clock[0] += 1
    early = make(store, andy, jenn, [serenity])  # revoked before the copy: left as it is
    store.revoke_grant(andy['id'], early, 'before the copy')
    charge(store, kept, 100)
    copy = staged(tmp_path, store)  # A
    early_row = revocations(copy)[early]
    clock[0] += 60  # B moves on
    store.revoke_grant(andy['id'], later, 'Not this week')
    charge(store, kept, 50, 10)  # two builds after the copy
    newer = make(store, andy, jenn, [serenity])  # made after the copy: gone after the restore, with its use
    charge(store, newer, 5)
    with store.transaction() as db:  # by hand: grants are never deleted, so a missing one means damage
        db.execute('DELETE FROM grants WHERE id=?', (lost,))
    there = revocations(store.db_path)
    code, out, err = run_reconcile(capsys, '--db', copy, '--replaced', store.db_path)
    assert code == 0, err
    here = revocations(copy)
    assert here[later] == there[later][:3] + (None,)  # the same time, person and reason; signed at the next start
    assert here[lost][0] is not None and here[lost][1:] == (None, 'restored', None)  # now, with no person
    assert here[kept] == (None, None, None, None) and here[early] == early_row
    assert [(grant, created) for grant, _, created in uses(copy)] == [(kept, clock[0] - 60 - 100), (kept, clock[0] - 50), (kept, clock[0] - 10)]
    assert report_line(out, 'Grants revoked: ') == (f'Grants revoked: #{later[:4]} (andy to jenn, as in the replaced file); '
                                                   f'#{lost[:4]} (andy to jenn, missing from the replaced file).')
    assert 'budget uses added (2)' in report_line(out, 'Taken back: ')
    code, out, err = run_reconcile(capsys, '--db', copy, '--replaced', store.db_path)  # a second run adds none
    assert code == 0, err
    assert report_line(out, 'Grants revoked: ') is None and 'budget uses added (0)' in report_line(out, 'Taken back: ')
    assert len(uses(copy)) == 3
    live = tmp_path / 'live'
    live.mkdir(mode=0o700)
    shutil.copyfile(store.data_dir / 'identity.json', live / 'identity.json')  # the identity stays put (runbook step 6)
    shutil.copyfile(copy, live / 'peer.sqlite3')
    from superyak_peer.db import Store
    started = Store(live)
    card = card_of(started._station_identity())
    with started.transaction() as db:
        for grant in (later, lost, early):
            row = db.execute('SELECT signature, revocation_signature FROM grants WHERE id=?', (grant,)).fetchone()
            assert verify_record(card, started._revocation_record(db, grant), row['revocation_signature']), grant
            assert verify_record(card, started._grant_record(db, grant), row['signature']), grant


def test_without_a_replaced_file_the_reconcile_revokes_every_grant(tmp_path, capsys):
    store, clock, andy, jenn, serenity = lighthouse(tmp_path)
    first = make(store, andy, jenn, [serenity])
    clock[0] += 1
    second = make(store, andy, jenn, [serenity])
    clock[0] += 1
    done = make(store, andy, jenn, [serenity])
    store.revoke_grant(andy['id'], done, 'before the copy')
    copy = staged(tmp_path, store)
    done_row = revocations(copy)[done]
    code, out, err = run_reconcile(capsys, '--db', copy)
    assert code == 0, err
    here = revocations(copy)
    for grant in (first, second):
        assert here[grant][1:] == (None, 'restored', None), grant
    assert here[done] == done_row  # already revoked: kept as it was, with its signature
    assert report_line(out, 'Grants revoked: ') == (f'Grants revoked: #{first[:4]} (andy to jenn, no usable replaced file); '
                                                   f'#{second[:4]} (andy to jenn, no usable replaced file).')
    assert 'grants revoked (2)' in report_line(out, 'Taken back: ')


def test_a_replaced_file_without_the_grants_tables_is_treated_as_absent(tmp_path, capsys):
    """G13: the grants columns join COMPARED, so a replaced file lacking them (the wrong file, or a damaged one) is
    treated as absent and the reconcile fails closed: every grant is revoked, rather than none compared."""
    store, clock, andy, jenn, serenity = lighthouse(tmp_path)
    grant = make(store, andy, jenn, [serenity])
    copy = staged(tmp_path, store)
    replaced = copy.parent / 'peer.sqlite3'
    shutil.copyfile(store.db_path, replaced)
    with closing(sqlite3.connect(replaced)) as db:
        db.execute('DROP TABLE budget_uses')
        db.execute('DROP TABLE grants')
        db.commit()
    code, out, err = run_reconcile(capsys, '--db', copy, '--replaced', replaced)
    assert code == 0, err
    assert 'The replaced file was treated as absent (it lacks tables or columns the copy has: ' in out
    assert revocations(copy)[grant][2] == 'restored'
