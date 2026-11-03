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

    ids = {**pi_ids, 'tardis-andy': tardis_ids['andy']}
    return SimpleNamespace(pi=pi, pi_fed=pi_fed, tardis=tardis, tardis_fed=tardis_fed, ids=ids, room=lp['room'], key=lp['key'],
                           clock=clock, deliver=lp['deliver'], pair_new=pair_new)


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
