"""Room moderators (docs/superpowers/specs/2026-10-27-room-moderators-design.md): the moderate grant."""
import json
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from superyak_peer.common import uid
from superyak_peer.grants import MODERATE_ACTIONS, _utc
from test_instructions import docked, ship_client

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


APPOINTED = '{owner} made {name} a moderator of this room, to {what}, until {when}.'


def moderate(store, issuer, grantee, room_id, **fields):
    return store.make_moderate_grant(issuer['id'], grantee['id'], room_id, **fields)['id']


def notices(store, room_id, prefix=''):
    with store.transaction() as db:
        return [(r[0], r[1]) for r in db.execute(
            'SELECT client_message_id, body FROM messages WHERE room_id=? AND author_id=? AND client_message_id LIKE ? '
            'ORDER BY created, rowid', (room_id, store.system_author_id(db), prefix + '%'))]


def table_rows(store):
    with store.transaction() as db:
        return {t: db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ('grants', 'grant_origins', 'messages')}


def test_the_owner_makes_a_moderate_grant_for_a_member_person_or_his_own_ship(city):
    c = city
    andy = login(c.app, 'andy')
    made = andy.post('/api/grants/moderate', json={'grantee': c.jenn['id'], 'room': c.room})
    assert made.status_code == 201, made.text
    view = made.json()
    assert (view['actions'], view['budget'], view['budget_left'], view['targets'], view['made_via'], view['valid']) == (
        ['add_member', 'remove_member'], 10, 10, [], 'browser', True)
    assert view['expires'] - view['created'] == 720 * 3600 and view['rooms'] == [{'id': c.room, 'title': 'Superyak: city of AI'}]
    adds = andy.post('/api/grants/moderate', json={'grantee': c.rio['id'], 'room': c.room, 'actions': ['add_member'],
                                                   'hours': 24, 'budget': 50}).json()
    removes = andy.post('/api/grants/moderate', json={'grantee': c.rio['id'], 'room': c.room,
                                                      'actions': ['remove_member']}).json()
    assert (adds['actions'], removes['actions']) == (['add_member'], ['remove_member'])
    assert notices(c.store, c.room, 'moderator-') == [
        (f'moderator-{view["id"]}', APPOINTED.format(owner='Andy', name='Jenn', what='add and remove members', when=_utc(view['expires']))),
        (f'moderator-{adds["id"]}', APPOINTED.format(owner='Andy', name='Rio Grande', what='add members', when=_utc(adds['expires']))),
        (f'moderator-{removes["id"]}', APPOINTED.format(owner='Andy', name='Rio Grande', what='remove members', when=_utc(removes['expires'])))]


@pytest.mark.parametrize('who, grantee, room, extra, status, error', [
    ('doctor', 'jenn', 'room', {}, 403, "Only the room's owner can let someone moderate it"),
    ('andy', 'jenn', 'unknown', {}, 404, 'The room must be a room you are in'),
    ('andy', 'jenn', 'remote', {}, 404, 'The room must be a room you are in'),
    ('andy', 'jenn', 'breakout', {}, 404, 'The room must be a room you are in'),
    ('andy', 'jenn', 'replaced', {}, 400, 'The room was replaced by a newer linked room; name the current one'),
    ('andy', 'jenn', 'federated', {}, 400, "A room with a member on another station can't have moderators"),
    ('andy', 'andy', 'room', {}, 400, 'You cannot grant to yourself'),
    *[('andy', g, 'room', {}, 400, 'A moderator is a person in this room or one of your own ships in it')
      for g in ('kestrel', 'odo', 'wormhole', 'system', 'pending', 'tardis', 'outsider')],
    *[('andy', 'jenn', 'room', {'hours': h}, 400, 'hours is a whole number from 1 to 720') for h in (0, 721, '24', True, 2.5)],
    *[('andy', 'jenn', 'room', {'budget': b}, 400, 'budget is a whole number from 1 to 50') for b in (0, 51, '10')],
    *[('andy', 'jenn', 'room', {'actions': a}, 400, 'actions is a list of add_member and remove_member, each at most once')
      for a in ([], ['direct'], ['add_member', 'add_member'], 'add_member', [None])],
])
def test_making_a_moderate_grant_refuses_each_case_and_writes_nothing(city, tmp_path, who, grantee, room, extra, status, error):
    c, store = city, city.store
    outsider = store.create_user('outsider', 'Outsider', 'long-password-outsider')
    rooms = {'room': c.room, 'unknown': 'nope', 'remote': 'ab' * 32 + ':room-1'}
    rooms['replaced'] = store.create_room(c.andy['id'], 'Old', [c.jenn['id']])['id']
    store.add_participants(c.andy['id'], rooms['replaced'], [c.doctor['id']])
    rooms['federated'] = store.create_room(c.andy['id'], 'Wide', [c.jenn['id'], remote_contact(store)])['id']
    store.create_room(c.andy['id'], 'Ops', [c.rio['id'], c.tardis['id']])
    rooms['breakout'] = store.open_breakout(c.rio['id'], 'Side', ['tardis'])['id']
    with store.transaction() as db:
        db.execute('INSERT INTO room_members VALUES(?,?)', (rooms['breakout'], c.andy['id']))  # by hand: never a person's
        for member in (c.kestrel, c.wormhole, c.pending):  # in the room, so kind alone refuses them
            db.execute('INSERT INTO room_members VALUES(?,?)', (c.room, member['id']))
        system = store.system_author_id(db)
    ids = {'jenn': c.jenn['id'], 'andy': c.andy['id'], 'kestrel': c.kestrel['id'], 'odo': c.odo['id'],
           'wormhole': c.wormhole['id'], 'system': system, 'pending': c.pending['id'], 'tardis': c.tardis['id'],
           'outsider': outsider['id']}
    before = table_rows(store)
    refused = login(c.app, who).post('/api/grants/moderate', json={'grantee': ids[grantee], 'room': rooms[room], **extra})
    assert (refused.status_code, refused.json()['error']) == (status, error)
    assert table_rows(store) == before


def test_checks_run_in_the_spec_order(city):
    """§6: the room, the grantee, hours, budget, actions; the first failure answers."""
    c = city
    andy = login(c.app, 'andy')
    def error(**body):
        return andy.post('/api/grants/moderate', json={'grantee': c.jenn['id'], 'room': c.room, **body}).json()['error']
    assert error(room='nope', grantee=c.odo['id'], hours=0) == 'The room must be a room you are in'
    assert error(grantee=c.odo['id'], hours=0) == 'A moderator is a person in this room or one of your own ships in it'
    assert error(hours=0, budget=0) == 'hours is a whole number from 1 to 720'
    assert error(budget=0, actions=[]) == 'budget is a whole number from 1 to 50'


def test_a_ship_key_gets_403_and_depth_is_never_read(city):
    c = city
    refused = ship_client(c.app, c.rio_key).post('/api/grants/moderate', json={'grantee': c.jenn['id'], 'room': c.room})
    assert (refused.status_code, refused.json()['error']) == (403, 'Ship keys cannot use this route')
    made = login(c.app, 'andy').post('/api/grants/moderate', json={'grantee': c.jenn['id'], 'room': c.room, 'depth': 2})
    assert made.status_code == 201 and grant_row(c.store, made.json()['id'])['depth'] == 0  # M13


def test_a_direct_grant_records_made_via_and_an_older_one_shows_null(city):
    c = city
    andy = login(c.app, 'andy')
    direct = andy.post('/api/grants', json={'grantee': c.jenn['id'], 'targets': [c.rio['id']], 'rooms': [c.room],
                                            'hours': 24, 'budget': 5}).json()
    assert (direct['actions'], direct['made_via']) == (['direct'], 'browser')
    with c.store.transaction() as db:
        older = c.store._insert_grant(db, c.andy['id'], c.jenn['id'], [c.rio['id']], [c.room], 24, 5)
    assert next(g for g in andy.get('/api/grants').json() if g['id'] == older)['made_via'] is None


def test_revoking_posts_the_end_notice_in_the_room_the_grant_covers_now(city):
    """M19, Review Focus 4: an add moved the room on; the end notice goes to the room the grant covers now."""
    c = city
    grant = moderate(c.store, c.andy, c.jenn, c.room)
    newer = c.store.add_participants(c.andy['id'], c.room, [c.tardis['id']])['id']
    revoked = login(c.app, 'andy').post(f'/api/grants/{grant}/revoke', json={})
    assert revoked.status_code == 200 and revoked.json()['valid'] is False
    assert notices(c.store, newer, 'moderator-') == [(f'moderator-{grant}-revoked', "Andy ended Jenn's moderation of this room.")]
    assert [cid for cid, _ in notices(c.store, c.room, 'moderator-')] == [f'moderator-{grant}']


def test_appointment_and_end_notices_pass_names_through_safe_line(city):
    """M19 with R1, T10's station half: a display name with an @ and a newline is one safe line; nothing is mentioned."""
    c = city
    c.store.rename_user(c.jenn['id'], '@venus\nhello')
    grant = moderate(c.store, c.andy, c.jenn, c.room, actions=['add_member'])
    c.store.revoke_grant(c.andy['id'], grant)
    bodies = [body for _, body in notices(c.store, c.room, 'moderator-')]
    assert bodies[0].startswith('Andy made (at)venus hello a moderator of this room, to add members, until ')
    assert bodies[1] == "Andy ended (at)venus hello's moderation of this room." and not any('@' in b for b in bodies)
    with c.store.transaction() as db:
        assert db.execute('SELECT count(*) FROM mentions').fetchone()[0] == 0


import shutil
import sqlite3
from contextlib import closing
from test_restore import reconcile as run_reconcile, staged


def logged(path):
    with closing(sqlite3.connect(path)) as db:
        return db.execute('SELECT grant_id, change, member_id FROM member_changes ORDER BY created, rowid').fetchall()


def test_a_restore_copies_the_act_log_so_a_moderators_day_does_not_reset(city, tmp_path, capsys):
    from test_moderator_acts import add, drop
    c = city
    grant = moderate(c.store, c.andy, c.jenn, c.room, budget=5)
    copy = staged(tmp_path, c.store)                                   # A: the grant, no changes yet
    jenn = login(c.app, 'jenn')
    for member in (c.doctor, c.rio):                                    # B: two changes in a room the copy has
        assert drop(jenn, c.room, member['id']).status_code == 200
    c.store.remove_participant(c.andy['id'], c.room, c.odo['id'])       # the owner's own (ruling 15)
    assert add(jenn, c.room, c.tardis['id']).status_code == 201         # its new room isn't in the copy
    code, out, err = run_reconcile(capsys, '--db', copy, '--replaced', c.store.db_path)
    assert code == 0, err
    assert 'member changes added (3)' in out
    assert logged(copy) == [(grant, 'remove', c.doctor['id']), (grant, 'remove', c.rio['id']), (None, 'remove', c.odo['id'])]
    code, out, err = run_reconcile(capsys, '--db', copy, '--replaced', c.store.db_path)
    assert code == 0 and 'member changes added (0)' in out and len(logged(copy)) == 3


def test_a_replaced_file_without_the_act_log_is_treated_as_absent(city, tmp_path, capsys):
    c = city
    moderate(c.store, c.andy, c.jenn, c.room)
    copy = staged(tmp_path, c.store)
    replaced = copy.parent / 'peer.sqlite3'
    shutil.copyfile(c.store.db_path, replaced)
    with closing(sqlite3.connect(replaced)) as db:
        db.execute('DROP TABLE member_changes')
        db.commit()
    code, out, err = run_reconcile(capsys, '--db', copy, '--replaced', replaced)
    assert code == 0 and 'The replaced file was treated as absent (it lacks tables or columns the copy has: ' in out
