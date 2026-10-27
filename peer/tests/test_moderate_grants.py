"""Room moderators (docs/superpowers/specs/2026-10-27-room-moderators-design.md): the moderate grant."""
import json
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from superyak_peer.common import uid
from superyak_peer.grants import MODERATE_ACTIONS
from test_instructions import docked

DAY = 86400


@pytest.fixture
def city(tmp_path):
    """Andy's room "Superyak: city of AI" with Jenn, the doctor, his ship Rio Grande and the resident Odo; his ship Tardis
    docked but not in it; Jenn's ship Kestrel; the station ship Wormhole; Root, awaiting activation."""
    from superyak_peer.app import create_app
    clock = [1000000.0]
    app = create_app(tmp_path / 'peer', clock=lambda: clock[0], allowed_origins=['http://testserver'])
    store = app.state.store
    people = {name: store.create_user(name, name.title(), f'long-password-{name}', is_admin=name == 'andy')
              for name in ('andy', 'jenn', 'doctor')}
    rio, rio_key = docked(store, people['andy']['id'], 'rio-grande')
    tardis, tardis_key = docked(store, people['andy']['id'], 'tardis')
    kestrel, _ = docked(store, people['jenn']['id'], 'kestrel')
    odo, wormhole = store.create_station_ship('odo', 'Odo'), store.create_station_ship('wormhole', 'Wormhole')
    pending = store.bootstrap_super_admin('root', 'Root', tmp_path / 'activation.json')
    room = store.create_room(people['andy']['id'], 'Superyak: city of AI',
                             [people['jenn']['id'], people['doctor']['id'], rio['id'], odo['id']])
    return SimpleNamespace(app=app, store=store, clock=clock, **people, rio=rio, rio_key=rio_key, tardis=tardis,
                           tardis_key=tardis_key, kestrel=kestrel, odo=odo, wormhole=wormhole, pending=pending,
                           room=room['id'])


def login(app, username):
    client = TestClient(app, base_url='http://testserver')
    client.headers['origin'] = 'http://testserver'
    signed = client.post('/api/login', json={'username': username, 'password': f'long-password-{username}'})
    assert signed.status_code == 200
    client.headers['x-csrf-token'] = signed.json()['csrf_token']
    return client


def insert_moderate(store, issuer, grantee, room_id, hours=720, budget=10, actions=MODERATE_ACTIONS):
    with store.transaction() as db:
        return store._insert_grant(db, issuer['id'], grantee['id'], [], [room_id], hours, budget, actions=list(actions))


def grant_row(store, grant_id):
    with store.transaction() as db:
        return db.execute('SELECT * FROM grants WHERE id=?', (grant_id,)).fetchone()


def validity(store, grant_id):
    with store.transaction() as db:
        return store._grant_validity(db, db.execute('SELECT * FROM grants WHERE id=?', (grant_id,)).fetchone())


def covered(store, grant_id):
    with store.transaction() as db:
        return store._covered_room(db, db.execute('SELECT * FROM grants WHERE id=?', (grant_id,)).fetchone())


def charge(store, grant_id, room_id, *ages):
    """One member_changes row per age, that many seconds before now, as the act log records a moderator's change."""
    with store.transaction() as db:
        for age in ages:
            db.execute("INSERT INTO member_changes(id, grant_id, member_id, change, room_id, created) VALUES(?,?,?,'add',?,?)",
                       (uid(), grant_id, 'someone', room_id, store.clock() - age))


def remote_contact(store, name='Willa'):
    """A paired peer's contact, as federation stores one: its id."""
    with store.transaction() as db:
        db.execute("INSERT OR IGNORE INTO peers(peer_id, card, paired) VALUES(?, '{}', 1)", ('a' * 64,))
        db.execute('INSERT INTO remote_contacts VALUES(?,?,?,?)', (f'remote_{name.lower()}', 'a' * 64, name.lower(), name))
    return f'remote_{name.lower()}'


def test_a_moderate_grant_is_a_depth_0_root_that_never_builds(city):
    c = city
    grant = insert_moderate(c.store, c.andy, c.jenn, c.room)
    row = grant_row(c.store, grant)
    assert (json.loads(row['actions']), json.loads(row['targets']), json.loads(row['rooms']), row['depth'], row['budget'],
            row['expires'] - row['created']) == (['add_member', 'remove_member'], [], [c.room], 0, 10, 720 * 3600)
    assert row['signature'] and validity(c.store, grant) == (True, None)
    with c.store.transaction() as db:
        assert c.store._grant_policy(db)['delegable'] == ['direct']
    asked = c.store.send_message(c.jenn['id'], c.room, 'ask', '@rio-grande build the notes')
    assert c.store.issue_ticket(c.rio['id'], asked['id'])['mode'] == 'read'  # M1: _spendable_grant needs `direct`


def test_the_grant_follows_the_room_and_a_fork_covers_nothing(city):
    c = city
    grant = insert_moderate(c.store, c.andy, c.jenn, c.room)
    assert covered(c.store, grant) == c.room
    newer = c.store.add_participants(c.andy['id'], c.room, [c.tardis['id']])['id']
    assert covered(c.store, grant) == newer and validity(c.store, grant) == (True, None)
    with c.store.transaction() as db:  # a fork, by hand: add_participants never makes one
        for fork in ('fork-a', 'fork-b'):
            db.execute('INSERT INTO rooms VALUES(?,?,?,1,?)', (fork, c.andy['id'], 'Fork', newer))
    assert covered(c.store, grant) is None
    assert validity(c.store, grant) == (False, f'Grant #{grant[:4]} covers no current room')


def test_check_4_counts_the_grants_changes_in_the_last_24_hours(city):
    c = city
    grant = insert_moderate(c.store, c.andy, c.jenn, c.room, budget=2)
    charge(c.store, grant, c.room, DAY, 100)  # one exactly a day old no longer counts (Review Focus 5)
    assert validity(c.store, grant) == (True, None)
    charge(c.store, grant, c.room, 10)
    assert validity(c.store, grant) == (False, f'Grant #{grant[:4]} has used its 2 changes for the last 24 hours')
    one = insert_moderate(c.store, c.andy, c.rio, c.room, budget=1)
    charge(c.store, one, c.room, 5)
    assert validity(c.store, one) == (False, f'Grant #{one[:4]} has used its 1 change for the last 24 hours')


def test_check_5_pauses_the_grant_for_ownership_membership_and_remote_members(city):
    c = city
    grant = insert_moderate(c.store, c.andy, c.jenn, c.room)
    with c.store.transaction() as db:
        db.execute('DELETE FROM room_members WHERE room_id=? AND user_id=?', (c.room, c.jenn['id']))
    assert validity(c.store, grant) == (False, 'Jenn is no longer in this room')
    with c.store.transaction() as db:
        db.execute('INSERT INTO room_members VALUES(?,?)', (c.room, c.jenn['id']))
        db.execute('UPDATE rooms SET owner_id=? WHERE id=?', (c.doctor['id'], c.room))
    assert validity(c.store, grant) == (False, 'Andy no longer owns this room')
    with c.store.transaction() as db:
        db.execute('UPDATE rooms SET owner_id=? WHERE id=?', (c.andy['id'], c.room))
    c.store.add_participants(c.andy['id'], c.room, [remote_contact(c.store)])  # M11: the room gains a remote member
    assert validity(c.store, grant) == (False, 'This room now has a member on another station')
