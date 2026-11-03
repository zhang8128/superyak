"""Lessons room adds, Task 1 (docs/superpowers/specs/2026-11-03-lessons-room-adds-design.md): who typed each pairing
code, whether `pair` showed the lessons line, a reason on a member change, the lessons_addable table, and the restore
lists that carry them. Pairing codes are typed only the way conftest's paired() does; no test prints or asserts one."""
from contextlib import closing
import sqlite3
from types import SimpleNamespace

import pytest
from conftest import lesson_ship, paired, confirm_lessons_room  # noqa: F401
from superyak_peer import backups
from superyak_peer.db import Store
from superyak_peer.federation import Federation
from superyak_peer.identity import pairing_code
from test_restore import go_live, staged


@pytest.fixture
def adds(lessons_peers, tmp_path):
    """lessons_peers (the Pi, Tardis listed and paired both ways), plus pair_new: a ship account made on a peer and its
    card paired on the Pi by Andy's typed code. on='other' is a second peer paired with the Pi both ways but never
    listed for the lessons room."""
    lp = lessons_peers
    pi, pi_fed, pi_ids = lp['peers']['pi']
    tardis, tardis_fed, tardis_ids = lp['peers']['tardis']
    clock = lp['clock']
    other = Store(tmp_path / 'other', clock=lambda: clock[0])
    other_fed = Federation(other, endpoint='https://other:7437')
    andy_o = other.create_user('andy', 'Andy Example', 'a-long-password', is_admin=True)['id']
    paired(pi_fed, pi_ids['andy'], other_fed.card(andy_o))
    paired(other_fed, andy_o, pi_fed.card(pi_ids['andy']))
    machines = {'tardis': (tardis, tardis_fed), 'other': (other, other_fed)}

    def pair_new(username, *, on='tardis', lessons_line_shown=False):
        store, fed = machines[on]
        ship = store.lessons_ship(username, 'andy')['id']
        card = fed.card(ship)
        return pi_fed.pair(pi_ids['andy'], card, code=pairing_code(card), lessons_line_shown=lessons_line_shown)['id']

    def card_of(username, *, on='tardis'):
        store, fed = machines[on]
        return fed.card(store.lessons_ship(username, 'andy')['id'])

    ids = {**pi_ids, 'tardis-andy': tardis_ids['andy']}
    return SimpleNamespace(pi=pi, pi_fed=pi_fed, tardis=tardis, tardis_fed=tardis_fed, ids=ids, room=lp['room'], key=lp['key'],
                           clock=clock, deliver=lp['deliver'], pair_new=pair_new, card_of=card_of)


def confirmation(store, contact):
    with store.transaction() as db:
        return dict(db.execute('SELECT * FROM pairing_confirmations WHERE contact_id=?', (contact,)).fetchone())


def test_pair_records_who_typed_and_whether_the_line_was_shown(adds):
    contact = adds.pair_new('defiant', lessons_line_shown=True)      # Tardis is listed
    row = confirmation(adds.pi, contact)
    assert row['typed_by'] == adds.ids['andy'] and row['lessons_line'] == 1


def test_the_line_flag_needs_the_peer_listed_in_pairs_own_transaction(adds):
    contact = adds.pair_new('defiant', on='other', lessons_line_shown=True)   # paired, never listed
    row = confirmation(adds.pi, contact)
    assert row['lessons_line'] == 0 and row['typed_by'] == adds.ids['andy']


def test_a_line_not_shown_is_not_recorded(adds):
    assert confirmation(adds.pi, adds.pair_new('defiant'))['lessons_line'] == 0


def test_owner_removed_skips_held_rows(adds):
    pi, andy = adds.pi, adds.ids['andy']
    member = adds.pair_new('defiant')
    chain_room = adds.room

    def log(change, reason, at, grant=None, actor=andy):
        with pi.transaction() as db:
            db.execute('INSERT INTO member_changes(id,grant_id,actor_id,member_id,change,room_id,created,reason) VALUES(?,?,?,?,?,?,?,?)',
                       (f'chg{at}', grant, actor, member, change, chain_room, at, reason))

    def owner_removed():
        with pi.transaction() as db:
            return pi._owner_removed(db, chain_room, member, andy)

    log('add', None, 10.0)
    assert not owner_removed()
    log('remove', 'held', 11.0)                  # a hold's removal is not Andy's
    assert not owner_removed()
    log('remove', None, 12.0)                    # the owner's own removal after it is
    assert owner_removed()


def test_record_change_takes_a_reason(adds):
    with adds.pi.transaction() as db:
        key = adds.pi._record_change(db, 'remove', adds.room, 'someone', None, None, reason='held')
        assert db.execute('SELECT reason FROM member_changes WHERE id=?', (key,)).fetchone()[0] == 'held'
        key = adds.pi._record_change(db, 'remove', adds.room, 'someone', None, None)
        assert db.execute('SELECT reason FROM member_changes WHERE id=?', (key,)).fetchone()[0] is None


def new_state(path):
    with closing(sqlite3.connect(path)) as db:
        return ([tuple(r) for r in db.execute('SELECT contact_id, typed_by, lessons_line FROM pairing_confirmations ORDER BY contact_id')],
                [tuple(r) for r in db.execute('SELECT id, reason FROM member_changes ORDER BY id')],
                [tuple(r) for r in db.execute('SELECT * FROM lessons_addable ORDER BY contact_id')])


def seed(adds):
    contact = adds.pair_new('defiant', lessons_line_shown=True)
    with adds.pi.transaction() as db:
        db.execute("INSERT INTO member_changes(id,actor_id,member_id,change,room_id,created,reason) VALUES('chgheld',NULL,'m','remove',?,5.0,'held')",
                   (adds.room,))
        db.execute("INSERT INTO lessons_addable(contact_id,code_digest,typed_by,listed) VALUES(?,?,?,?)",
                   (contact, 'd' * 64, adds.ids['andy'], 7.0))
    return contact


def test_restore_keeps_the_new_columns_and_table(adds, tmp_path):
    seed(adds)
    copy = staged(tmp_path, adds.pi)
    live = go_live(copy, tmp_path / 'live')
    assert new_state(live.db_path) == new_state(adds.pi.db_path)
    typed, changes, addable = new_state(live.db_path)
    assert any(t[1] == adds.ids['andy'] and t[2] == 1 for t in typed) and ('chgheld', 'held') in changes and len(addable) == 1


def drop_new(path):
    """A copy from before the build: the three columns and the table gone (the tables rebuilt in their old shape)."""
    with closing(sqlite3.connect(path)) as db:
        db.execute('DROP TABLE lessons_addable')
        db.execute('ALTER TABLE pairing_confirmations RENAME TO pc_new')
        db.execute('CREATE TABLE pairing_confirmations(contact_id TEXT PRIMARY KEY, code TEXT NOT NULL, confirmed REAL NOT NULL)')
        db.execute('INSERT INTO pairing_confirmations SELECT contact_id, code, confirmed FROM pc_new')
        db.execute('DROP TABLE pc_new')
        db.execute('ALTER TABLE member_changes DROP COLUMN reason')
        db.commit()


def test_restore_of_a_backup_from_before_the_build(adds, tmp_path):
    seed(adds)
    copy = staged(tmp_path, adds.pi)
    drop_new(copy)
    live = go_live(copy, tmp_path / 'live')
    typed, changes, addable = new_state(live.db_path)
    assert typed and all(t[1] is None and t[2] == 0 for t in typed)
    assert changes and all(c[1] is None for c in changes) and addable == []


# ---- Task 2: pair says what it makes addable, before the code --------------------------------------------------------

def line_for(adds, card):
    from superyak_peer.lessons import lessons_line_for
    with adds.pi.transaction() as db:
        return lessons_line_for(db, card)


def test_the_line_for_a_listed_peer_is_the_exact_text(adds):
    card = adds.card_of('defiant')
    assert line_for(adds, card) == (f"Defiant on {card['peer_id'][:12]} can be added to the lessons room by Rio-Grande "
                                    "once you type its code; its lessons would reach every ship.")


def test_the_ship_is_the_recorded_ships_account_name(adds):
    with adds.pi.transaction() as db:
        db.execute("UPDATE users SET name='Odo' WHERE username='rio-grande'")
    assert ' by Odo once you' in line_for(adds, adds.card_of('defiant'))


def test_no_line_for_an_unlisted_peer(adds):
    assert line_for(adds, adds.card_of('defiant', on='other')) is None


def test_no_line_without_a_recorded_room(adds):
    card = adds.card_of('defiant')
    with adds.pi.transaction() as db:
        db.execute('DELETE FROM lessons_room')
    assert line_for(adds, card) is None


def test_no_line_off_the_origin(adds):
    card = adds.card_of('defiant')
    with adds.pi.transaction() as db:
        db.execute("UPDATE lessons_room SET room_key='someone:room'")
    assert line_for(adds, card) is None


def test_no_line_without_a_recorded_ship(adds):
    card = adds.card_of('defiant')
    with adds.pi.transaction() as db:
        db.execute('UPDATE lessons_room SET ship_id=NULL')
    assert line_for(adds, card) is None


def test_the_line_names_a_bidi_name_plainly(adds):
    card = adds.card_of('defiant')
    card = {**card, 'participant': {**card['participant'], 'name': 'Def\u202eiant'}}
    assert line_for(adds, card).startswith('Defiant on ')


# Task 3: the listing names the addable accounts.
import json
from superyak_peer.lessons import describe_station_room, listable


def list_view(adds, confirm=None):
    return adds.pi.station_lessons_room('andy', adds.room[:6], 'rio-grande', [adds.tardis_fed.identity.peer_id], confirm)


def addable_rows(adds):
    with adds.pi.transaction() as db:
        return [dict(r) for r in db.execute('SELECT * FROM lessons_addable ORDER BY contact_id')]


def test_the_listing_names_each_addable_account(adds):
    contact = adds.pair_new('defiant')
    view = list_view(adds)
    assert [a['id'] for a in view['addable']] == [contact]
    assert 'addable by' in describe_station_room(view) and 'code' not in json.dumps(view['addable'])
    assert set(view['addable'][0]) == {'id', 'label', 'user_short', 'peer_id', 'typed_by'}


def test_members_trust_made_held_and_removed_contacts_are_not_addable(adds):
    pi, andy = adds.pi, adds.ids['andy']
    held, trusted, removed, plain = (adds.pair_new(n) for n in ('held', 'trusted', 'removed', 'plain'))
    with pi.transaction() as db:
        db.execute('INSERT INTO contact_holds VALUES(?,?)', (held, 1.0))
        db.execute("INSERT INTO trust_confirmations VALUES('t1',?,'g','a','s',1.0,'d',1)", (trusted,))
        db.execute("INSERT INTO member_changes(id,actor_id,member_id,change,room_id,created) VALUES('c1',?,?,'remove',?,5.0)",
                   (andy, removed, adds.room))
    ids = [a['id'] for a in list_view(adds)['addable']]
    assert ids == [plain]            # the members (Tardis's ship and Andy there) are not offered either
    with pi.transaction() as db:
        assert listable(pi, db, {'id': adds.room, 'member_ids': [], 'owner_id': andy}, plain, [adds.tardis_fed.identity.peer_id])
        assert not listable(pi, db, {'id': adds.room, 'member_ids': [plain], 'owner_id': andy}, plain, [adds.tardis_fed.identity.peer_id])
        assert not listable(pi, db, {'id': adds.room, 'member_ids': [], 'owner_id': andy}, plain, [])


def test_an_unlisted_peers_account_is_not_addable(adds):
    adds.pair_new('elsewhere', on='other')
    assert list_view(adds)['addable'] == []


def test_the_confirm_code_changes_when_one_is_added_or_goes_stale(adds):
    before = list_view(adds)['confirm']
    contact = adds.pair_new('defiant')
    after_add = list_view(adds)['confirm']
    with adds.pi.transaction() as db:
        db.execute("UPDATE remote_contacts SET name='Renamed' WHERE id=?", (contact,))
    assert list_view(adds)['addable'] == []                      # stale: the code no longer fits the name
    with adds.pi.transaction() as db:                            # typed again under the new name
        row = db.execute('SELECT c.user_id, c.name, p.card FROM remote_contacts c JOIN peers p USING(peer_id) WHERE c.id=?', (contact,)).fetchone()
        db.execute('UPDATE pairing_confirmations SET code=? WHERE contact_id=?',
                   (pairing_code({**json.loads(row['card']), 'participant': {'id': row['user_id'], 'name': row['name']}}), contact))
    after_retyped = list_view(adds)
    assert [a['id'] for a in after_retyped['addable']] == [contact]
    assert len({before, after_add, after_retyped['confirm']}) == 3


def test_confirm_records_exactly_what_was_shown_and_a_rerun_replaces_it(adds):
    first = adds.pair_new('defiant')
    view = list_view(adds)
    assert addable_rows(adds) == []                      # a view writes nothing
    list_view(adds, view['confirm'])
    rows = addable_rows(adds)
    assert [r['contact_id'] for r in rows] == [first] and rows[0]['typed_by'] == adds.ids['andy']
    assert rows[0]['listed'] == adds.clock[0] and len(rows[0]['code_digest']) == 64
    with adds.pi.transaction() as db:
        code = db.execute('SELECT code FROM pairing_confirmations WHERE contact_id=?', (first,)).fetchone()['code']
    import hashlib
    assert rows[0]['code_digest'] == hashlib.sha256(code.encode()).hexdigest()
    assert code not in json.dumps(view) and code not in describe_station_room(view) and rows[0]['code_digest'] not in json.dumps(view)
    with adds.pi.transaction() as db:
        db.execute("UPDATE remote_contacts SET name='Renamed' WHERE id=?", (first,))
    second = adds.pair_new('voyager')
    again = list_view(adds)
    list_view(adds, again['confirm'])
    assert [r['contact_id'] for r in addable_rows(adds)] == [second]


def test_a_stale_confirm_writes_nothing(adds):
    adds.pair_new('defiant')
    view = list_view(adds)
    adds.pair_new('voyager')
    with pytest.raises(Exception):
        list_view(adds, view['confirm'])
    assert addable_rows(adds) == []


def test_the_listing_shows_a_bidi_name_plainly(adds):
    contact = adds.pair_new('defiant')
    view = {'room': adds.room, 'title': 'T', 'members': [], 'peers': ['p' * 64], 'recorded': False, 'confirm': 'c',
            'addable': [{'id': contact, 'label': 'Def‮iant', 'user_short': 'abcd1234', 'peer_id': 'p' * 64, 'typed_by': 'u'}],
            'ship': 'rio\u202e-grande'}
    text = describe_station_room(view)
    assert '‮' not in text and 'Defiant (abcd1234) addable by rio-grande' in text
