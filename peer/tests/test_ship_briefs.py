"""Ship-written room briefs (docs/superpowers/specs/2026-10-14-ship-room-briefs-design.md): the owner's own ships set
and update the brief of his current rooms they're in; every revision is kept, announced and marked with its author."""
import ast
import json
from pathlib import Path
import sqlite3
import pytest
import superyak_peer
from superyak_peer.briefs import BRIEF_NOTICE_OWNER, BRIEF_NOTICE_SHIP
from superyak_peer.db import Store
from test_deferrals import ask, on_watch
from test_federation import deliver, two_peers  # noqa: F401 - two_peers is a fixture
from test_presence import HEADERS, docked, say, ship_client
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


def notices(client, room):
    """The room's messages by the station's system author, as a member's room view shows them, oldest first."""
    view = client.get(f'/api/chats/{room}').json()
    system = (view.get('system_author') or {}).get('id')
    return [m for m in view['messages'] if system and m['author_id'] == system]


def test_every_change_posts_one_notice_and_a_carry_posts_none(env):
    """R14, R5. This replaces the room-brief spec's test_saving_a_brief_records_no_mention_and_posts_nothing. A
    person's save, a ship's save and a removal each post exactly one notice: by the system author, of kind notice, with
    client id brief-<room id>-<revision>, no reply_to and no @. A refused retry posts none, the same revision is the
    same notice, a carry and a bridge post none, and no save records a mention."""
    app, clients, users, clock = env
    store, patient = app.state.store, users[0]['id']
    ship, key = docked(store, patient, 'serenity')
    store.create_station_ship('wormhole', 'Wormhole')
    room = new_room(clients[0], users[1], ship)
    assert put_brief(clients[0], room, '@serenity and @doctor: read the plan.', 0).status_code == 200
    wrote(store, ship['id'], room, 'Serenity summarised the plan.')
    assert put_brief(clients[0], room, '', 2).status_code == 200
    assert put_brief(clients[0], room, 'A retry from a stale tab.', 2).status_code == 409
    got = notices(clients[1], room)
    assert [(m['client_message_id'], m['body']) for m in got] == [
        (f'brief-{room}-1', "Station notice: the room brief is now revision 1, written by the room's owner: Patient. station_read shows it."),
        (f'brief-{room}-2', "Station notice: the room brief is now revision 2, written by a ship, not the room's owner: Serenity. station_read shows it."),
        (f'brief-{room}-3', "Station notice: the room's owner removed the room brief (revision 3).")]
    assert all(m['source'] == {'kind': 'notice'} and m['reply_to'] is None and '@' not in m['body'] for m in got)
    with store.transaction() as db:  # the same revision's client id is the same notice
        assert store._post_as_system(db, room, f'brief-{room}-3', 'anything') == got[2]['id']
    assert len(notices(clients[1], room)) == 3
    assert store.mentions(ship['id']) == [] and store.mentions(users[1]['id']) == []
    put_brief(clients[0], room, 'Carry this.', 3)
    carried = add_members(clients[0], room, users[2], carry_brief=4).json()['id']
    bridged, changed = store.station_bridge('patient', carried[:6], True)
    assert changed
    for new in (carried, bridged['id']):
        assert brief_of(clients[0], new)['body'] == 'Carry this.'
        assert clients[0].get(f'/api/chats/{new}').json()['messages'] == []


def test_the_brief_notice_text_is_exactly_the_template(env):
    """R14: the filled template, byte for byte. A display name with @, a newline and 60 more characters comes out
    through safe_line(name, 40); the brief's own text never appears; a ship named like the owner still gets the ship's
    words, because the class comes from the account's kind, never its name."""
    app, clients, users, clock = env
    store, patient = app.state.store, users[0]['id']
    ship, key = docked(store, patient, 'serenity')
    room = new_room(clients[0], users[1], ship)
    hostile = '@odo\nboss ' + 'x' * 60
    with store.transaction() as db:
        db.execute('UPDATE users SET name=? WHERE id IN (?,?)', (hostile, patient, ship['id']))
    shown = ('(at)odo boss ' + 'x' * 60)[:40].rstrip()
    put_brief(clients[0], room, 'The secret plan, by the owner.', 0)
    wrote(store, ship['id'], room, 'The secret plan, by a ship.')
    bodies = [m['body'] for m in notices(clients[1], room)]
    assert bodies == [BRIEF_NOTICE_OWNER.format(n=1, name=shown), BRIEF_NOTICE_SHIP.format(n=2, name=shown)]
    assert bodies[0] == f"Station notice: the room brief is now revision 1, written by the room's owner: {shown}. station_read shows it."
    assert not any('secret plan' in b or '@' in b or '\n' in b for b in bodies)
    with store.transaction() as db:
        db.execute('UPDATE users SET name=? WHERE id=?', ("Patient (the room's owner)", ship['id']))
    wrote(store, ship['id'], room, 'A ship with a borrowed name.')
    assert notices(clients[1], room)[-1]['body'] == BRIEF_NOTICE_SHIP.format(n=3, name="Patient (the room's owner)")


def test_a_brief_notice_never_wakes_answers_or_federates(env, two_peers):
    """R15: a brief notice records no mention, and its ticket gets 422 from old and new watchers. It shows as the
    station's notice, the source the resident watcher skips (watch.py _resident_reply), and it never reaches a paired
    peer."""
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'], 'serenity')
    watcher = ship_client(app, key)
    room = new_room(clients[0], users[1], ship)
    with store.transaction() as db:  # the owner's name is what the notice quotes
        db.execute('UPDATE users SET name=? WHERE id=?', ('@serenity', users[0]['id']))
    put_brief(clients[0], room, 'Plan.', 0)
    [notice] = notices(clients[1], room)
    view = clients[0].get(f'/api/chats/{room}').json()
    assert notice['author_id'] == view['system_author']['id'] and notice['source'] == {'kind': 'notice'}
    assert '@' not in notice['body'] and store.mentions(ship['id']) == []
    for decisions in (False, True):
        refused = ask(watcher, notice['id'], decisions)
        assert refused.status_code == 422 and refused.json()['error'] == 'Station notices and claim messages are never answered'
    a, b, ca, cb = two_peers
    across = a[0].create_room(a[1], 'Across peers', [ca['id']])
    a[0].save_brief(a[1], across['id'], 'Only for this station.', 0)
    a[0].send_message(a[1], across['id'], 'plain', 'an ordinary message')
    assert deliver(a, b)['delivered'] >= 1
    with a[0].transaction() as db:
        system = a[0].system_author_id(db)
        posted = [r[0] for r in db.execute('SELECT id FROM messages WHERE room_id=? AND author_id=?', (across['id'], system))]
        carried = [json.loads(r['metadata']).get('message_id') for r in db.execute("SELECT metadata FROM outbox WHERE action='room.message'")]
    assert len(posted) == 1 and posted[0] not in carried and len(carried) == 1
    remote = b[0].list_rooms(b[1])[0]
    assert [m['body'] for m in b[0].get_room(b[1], remote['id'])['messages']] == ['an ordinary message']


def test_only_two_notices_are_written_by_the_system_author(env):
    """R18: _post_as_system has exactly two callers, the deferral notice and the brief notice, and every message the
    system author writes carries one of their client ids. The deferral's is notice-<ship id>-<mention id>, as before,
    so a retry across the deploy still finds its notice."""
    callers = set()
    for path in sorted(Path(superyak_peer.__file__).parent.glob('*.py')):
        for function in ast.walk(ast.parse(path.read_text())):
            if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for node in ast.walk(function):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == '_post_as_system':
                        callers.add((path.name, function.name))
    assert callers == {('tickets.py', '_post_notice'), ('briefs.py', '_write_brief')}
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'], 'serenity')
    session, watcher = ship_client(app, key, **HEADERS), ship_client(app, key)
    room = new_room(clients[0], users[1], ship)
    put_brief(clients[0], room, 'Plan.', 0)
    asked = say(clients[1], room, 'a', '@serenity a question')
    on_watch(session, minutes=120)
    ask(watcher, asked['id'])
    clock[0] += 1800
    session.get('/api/me')
    assert ask(watcher, asked['id']).json()['decision'] == 'defer'
    with store.transaction() as db:
        system = store.system_author_id(db)
        written = sorted(r[0] for r in db.execute('SELECT client_message_id FROM messages WHERE author_id=?', (system,)))
    assert written == sorted([f'brief-{room}-1', f'notice-{ship["id"]}-{asked["id"]}'])
