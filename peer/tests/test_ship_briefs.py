"""Ship-written room briefs (docs/superpowers/specs/2026-10-14-ship-room-briefs-design.md): the owner's own ships set
and update the brief of his current rooms they're in; every revision is kept, announced and marked with its author."""
import sqlite3
import pytest
from superyak_peer.db import Store
from test_presence import docked, ship_client
from test_room_brief import add_members, brief_of, brief_row, new_room, put_brief


def wrote(store, author_id, room, body):
    """A revision by author_id, written the way both routes write one after their checks: through _write_brief. Tasks
    1-3 use it for a ship's revision, before Task 4's route exists. Returns the new revision."""
    with store.transaction() as db:
        revision = store._room_brief(db, room)[1] + 1
        store._write_brief(db, room, body, revision, author_id)
    return revision


def history(app, room):
    """The room's history as stored, oldest first: (revision, body, author_id, carried_from)."""
    with app.state.store.transaction() as db:
        return [tuple(r) for r in db.execute('SELECT revision, body, author_id, carried_from FROM room_brief_revisions '
                                             'WHERE room_id=? ORDER BY revision', (room,))]


def revisions(app, room):
    return [r[0] for r in history(app, room)]


def test_every_write_keeps_a_revision_and_startup_backfills(env):
    """R11: a save, a ship's save, a removal and a carry each write their revision into the history, in the same
    transaction as the room's brief; every start copies each room's current revision in once."""
    app, clients, users, clock = env
    store, patient = app.state.store, users[0]['id']
    ship, key = docked(store, patient, 'rio-grande')
    room = new_room(clients[0], users[1], ship)
    assert put_brief(clients[0], room, 'The owner wrote this.', 0).status_code == 200
    wrote(store, ship['id'], room, 'Rio Grande wrote this.')
    assert put_brief(clients[0], room, '', 2).status_code == 200
    assert history(app, room) == [(1, 'The owner wrote this.', patient, None), (2, 'Rio Grande wrote this.', ship['id'], None),
                                  (3, '', patient, None)]
    put_brief(clients[0], room, 'Back again.', 3)
    carried = add_members(clients[0], room, users[2], carry_brief=4).json()['id']
    assert history(app, carried) == [(1, 'Back again.', patient, room)]
    # One transaction: when the history row can't be written, the room's brief stays as it was.
    with store.transaction() as db:
        db.execute('INSERT INTO room_brief_revisions VALUES(?,?,?,?,?,?)', (room, 5, 'in the way', patient, clock[0], None))
    with pytest.raises(sqlite3.IntegrityError):
        store.save_brief(patient, room, 'Never saved.', 4)
    assert brief_row(app, room) == ('Back again.', 4)
    with store.transaction() as db:
        db.execute('DELETE FROM room_brief_revisions WHERE room_id=? AND revision=5', (room,))
    # The backfill: a brief that older code wrote, with no history row.
    old = new_room(clients[0], users[1], title='Before history')
    with store.transaction() as db:
        db.execute('INSERT INTO room_briefs VALUES(?,?,?,?,?,?)', (old, 'Written by older code.', 7, patient, 999.0, None))
    assert history(app, old) == []
    for _ in range(2):
        Store(store.data_dir)  # a restart
    assert history(app, old) == [(7, 'Written by older code.', patient, None)]
    assert revisions(app, room) == [1, 2, 3, 4]  # two restarts doubled nothing


def test_pruning_keeps_fifty_the_last_day_and_the_owners_last_act(env):
    """R11: after each write a room keeps its newest 50 revisions, everything from the last 24 hours, and the owner's
    newest revision, a removal included. Anything else goes, so text the owner removed ages out like any other."""
    app, clients, users, clock = env
    store, patient = app.state.store, users[0]['id']
    ship, key = docked(store, patient, 'rio-grande')
    room = new_room(clients[0], users[1], ship)
    put_brief(clients[0], room, 'The owner wrote this.', 0)    # r1, at 1,000,000
    put_brief(clients[0], room, '', 1)                         # r2: he removed it
    for n in range(3, 63):                                     # r3-r62: a ship save every 72 minutes, for three days
        clock[0] += 72 * 60
        assert wrote(store, ship['id'], room, f'Ship text {n}.') == n
    # The newest 50 are r13-r62 (the last day, r42-r62, is among them). r2 is the owner's last act; r1 aged out.
    assert revisions(app, room) == [2] + list(range(13, 63))
    assert history(app, room)[0] == (2, '', patient, None)
    for n in range(63, 118):                                   # r63-r117: 55 saves, 361 s apart, in 5.5 hours
        clock[0] += 361
        wrote(store, ship['id'], room, f'Ship text {n}.')
    # The newest 50 are r68-r117. The last day also keeps r47-r67, so 71 ship revisions stay, more than 50.
    assert revisions(app, room) == [2] + list(range(47, 118))


def test_the_brief_names_its_authors_kind_and_username(env):
    """R8: the brief carries author_kind and author_username from the account, so it names a ship that has since left
    the room, which the members list can't; author_name is still one safe line."""
    app, clients, users, clock = env
    store, patient = app.state.store, users[0]['id']
    ship, key = docked(store, patient, 'rio-grande')
    room = new_room(clients[0], users[1], ship)
    put_brief(clients[0], room, 'The owner wrote this.', 0)
    mine = brief_of(clients[1], room)
    assert (mine['author_kind'], mine['author_username'], mine['author_name']) == ('person', 'patient', 'Patient')
    wrote(store, ship['id'], room, 'Rio Grande wrote this.')
    assert clients[0].delete(f'/api/chats/{room}/participants/{ship["id"]}').status_code == 200
    view = clients[1].get(f'/api/chats/{room}').json()
    assert ship['id'] not in [m['id'] for m in view['members']]
    assert {k: view['brief'][k] for k in ('author_id', 'author_kind', 'author_username', 'author_name')} == {
        'author_id': ship['id'], 'author_kind': 'ship', 'author_username': 'rio-grande', 'author_name': 'Rio Grande'}
    with store.transaction() as db:
        db.execute('UPDATE users SET name=? WHERE id=?', ('Rio\n@serenity Grande', ship['id']))
    assert brief_of(clients[1], room)['author_name'] == 'Rio (at)serenity Grande'


def test_carrying_and_bridging_keep_the_carried_revisions_author(env):
    """R7: carrying is the owner's act, not his endorsement. Adding members with carry_brief and make station-bridge
    copy a ship's revision under the ship's name, into the brief and its history; the owner's own text stays his."""
    app, clients, users, clock = env
    store, patient = app.state.store, users[0]['id']
    ship, key = docked(store, patient, 'rio-grande')
    store.create_station_ship('wormhole', 'Wormhole')
    room = new_room(clients[0], users[1], ship)
    wrote(store, ship['id'], room, 'Rio Grande keeps this brief.')
    added = add_members(clients[0], room, users[2], carry_brief=1)
    assert added.status_code == 201, added.text
    carried_id = added.json()['id']
    carried = brief_of(clients[2], carried_id)
    assert (carried['author_id'], carried['author_kind'], carried['author_username'], carried['carried_from']) == (
        ship['id'], 'ship', 'rio-grande', room)
    bridged, changed = store.station_bridge('patient', carried_id[:6], True)
    assert changed and bridged['brief_carried']
    again = store.get_room(patient, bridged['id'])['brief']
    assert (again['author_id'], again['author_kind'], again['carried_from']) == (ship['id'], 'ship', carried_id)
    assert history(app, bridged['id']) == [(1, 'Rio Grande keeps this brief.', ship['id'], carried_id)]
    mine = new_room(clients[0], users[1], title='Mine')
    put_brief(clients[0], mine, 'The owner wrote this.', 0)
    kept = brief_of(clients[0], add_members(clients[0], mine, users[2], carry_brief=1).json()['id'])
    assert (kept['author_id'], kept['author_kind']) == (patient, 'person')
