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
    return SimpleNamespace(pi=pi, pi_fed=pi_fed, tardis=tardis, tardis_fed=tardis_fed, other_fed=other_fed, ids=ids,
                           room=lp['room'], key=lp['key'], clock=clock, deliver=lp['deliver'], pair_new=pair_new, card_of=card_of)


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


# ---- Task 4: make station-lessons-add CONTACT= -------------------------------------------------------------------------
from superyak_peer.common import Problem
from superyak_peer import lessons
from conftest import lesson_body, run_lessons
from test_owner_trust import b_ship, grant, pairs


def short(contact_id):
    """A contact's short id as Rio Grande types it: the start of its id after remote_."""
    return contact_id.removeprefix('remote_')[:8]


def snapshot(store):
    """Every table's rows, so a refusal can be shown to write nothing."""
    with closing(sqlite3.connect(store.db_path)) as db:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {t: sorted(repr(tuple(r)) for r in db.execute(f'SELECT * FROM "{t}"')) for t in tables}


def card_again(a, contact):
    """The card of an account pair_new already made on Tardis, for typing its code again."""
    with a.pi.transaction() as db:
        user = db.execute('SELECT user_id FROM remote_contacts WHERE id=?', (contact,)).fetchone()['user_id']
    return a.tardis_fed.card(user)


def relist(a, *peers):
    """make station-lessons-room's two runs, PEERS= these peers (Tardis's when none is given)."""
    peers = list(peers) or [a.tardis_fed.identity.peer_id]
    room = a.pi.lessons_room_key()
    shown = a.pi.station_lessons_room('andy', room[:6], 'rio-grande', peers)
    return a.pi.station_lessons_room('andy', room[:6], 'rio-grande', peers, shown['confirm'])


def members_of(store, room):
    with store.transaction() as db:
        return {r[0] for r in db.execute('SELECT contact_id FROM remote_room_members WHERE room_id=?', (room,))}


@pytest.fixture
def adds_trusted(adds):
    """adds, plus a live owner trust (expect 2) for Andy's contact on Tardis, a member of the lessons room, granted with
    Andy's password, and one ship of his there, voyager, that Rio Grande paired under it as make station-pair-trusted
    does (Federation.pair_trusted). trusted_ship(name, owner_user=None) pairs another (owner_user: a person on Tardis)."""
    with adds.pi.transaction() as db:
        owner = db.execute('SELECT id FROM remote_contacts WHERE peer_id=? AND user_id=?',
                           (adds.tardis_fed.identity.peer_id, adds.ids['tardis-andy'])).fetchone()['id']
    trust = grant((adds.pi, {'id': adds.ids['andy']}, {'id': owner}, None), password='a-long-password', expect=2)
    t = SimpleNamespace(machine=(adds.tardis, {'id': adds.ids['tardis-andy']}, None, adds.tardis_fed), clock=adds.clock,
                        fed=adds.pi_fed, ship=adds.ids['rio-grande'])

    def trusted_ship(name, owner_user=None):
        return pairs(t, *b_ship(t, name, now=int(adds.clock[0]), owner=owner_user))['id']
    return SimpleNamespace(**vars(adds), owner=owner, trust=trust, ship=trusted_ship('voyager'), trusted_ship=trusted_ship)


def refusal_case(a, case):
    """Sets up one refusal; returns what Rio Grande types for it."""
    pi, andy = a.pi, a.ids['andy']
    if case == 'unlisted':
        return short(a.pair_new('elsewhere', on='other', lessons_line_shown=True))
    if case == 'not_remote':
        return a.ids['rio-grande'][:8]
    if case == 'ambiguous':                      # a twin of Tardis's Andy, by participant id, on the other peer
        card = a.other_fed.identity.card(a.other_fed.endpoint, {'id': a.ids['tardis-andy'], 'name': 'Andy Twin'})
        a.pi_fed.pair(andy, card, code=pairing_code(card))
        return a.ids['tardis-andy'][:8]
    if case == 'ambiguous_id':
        return 'remote_'                         # the start of every contact's id
    if case.startswith('trust_') or case == 'owner_not_addable':
        if case == 'trust_revoked':
            pi.revoke_owner_trust(andy, a.trust['grant_id'])
        elif case == 'trust_expired':
            a.clock[0] += 91 * 86400
        elif case == 'trust_paused':
            a.trusted_ship('serenity')           # expect 2: the second pairing fills the window
        elif case == 'trust_held':
            with pi.transaction() as db:
                db.execute('INSERT INTO contact_holds VALUES(?,?)', (a.ship, 1.0))
        elif case == 'trust_member':
            pi.station_lessons_add(short(a.ship))
        elif case == 'owner_not_addable':
            pi.remove_participant(andy, a.room, a.owner)   # Andy took his Tardis account out: not a member, not addable
        return short(a.ship)
    if case in ('member', 'owner_removed'):
        contact = a.pair_new('defiant', lessons_line_shown=True)
        added = pi.station_lessons_add(short(contact))
        if case == 'owner_removed':
            pi.remove_participant(andy, added['new_room'], contact)
        return short(contact)
    if case == 'other_admin':                    # named by Andy's confirmed listing, then typed again by Bob, line shown
        bob = pi.create_user('bob', 'Bob', 'a-long-password', is_admin=True)['id']
        contact = a.pair_new('defiant')
        relist(a)
        card = card_again(a, contact)
        a.pi_fed.pair(bob, card, code=pairing_code(card), lessons_line_shown=True)
        return short(contact)
    contact = a.pair_new('defiant', lessons_line_shown=case != 'no_typed_by_not_listed')
    with pi.transaction() as db:
        if case == 'no_code':
            db.execute('DELETE FROM pairing_confirmations WHERE contact_id=?', (contact,))
        elif case == 'stale':
            db.execute("UPDATE remote_contacts SET name='Renamed' WHERE id=?", (contact,))
        elif case == 'held':
            db.execute('INSERT INTO contact_holds VALUES(?,?)', (contact, 1.0))
        elif case == 'no_typed_by_not_listed':   # as a restore from before the build leaves it
            db.execute('UPDATE pairing_confirmations SET typed_by=NULL, lessons_line=0 WHERE contact_id=?', (contact,))
    return short(contact)


NO_CODE = (403, "Defiant has no current typed code here, or it's held.")
NOT_VOUCHED = (403, "Defiant's code wasn't typed by Andy Example with the lessons line shown, and the listing Andy Example "
                    "confirmed didn't name it.")
VOYAGER = 'ship of Andy Example: voyager'
REASON = {
    'unlisted': (403, "Elsewhere is on {other12}, which isn't listed for the lessons room."),
    'no_code': NO_CODE, 'stale': (403, "Renamed has no current typed code here, or it's held."), 'held': NO_CODE,
    'member': (409, 'Defiant is already in the lessons room.'),
    'owner_removed': (403, 'Andy Example removed Defiant from the lessons room; adding it back is his act.'),
    'other_admin': NOT_VOUCHED, 'no_typed_by_not_listed': NOT_VOUCHED,
    'not_remote': (404, "{typed} isn't a remote contact here."),
    'ambiguous': (400, '{typed} matches more than one contact; give more of its id.'),
    'ambiguous_id': (400, 'remote_ matches more than one contact; give more of its id.'),
    'trust_revoked': (403, f'{VOYAGER} was paired by owner trust, and that trust is revoked.'),
    'trust_expired': (403, f'{VOYAGER} was paired by owner trust, and that trust is expired.'),
    'trust_paused': (403, f'{VOYAGER} was paired by owner trust, and that trust is paused.'),
    'trust_held': (403, f"{VOYAGER} has no current typed code here, or it's held."),
    'trust_member': (409, f'{VOYAGER} is already in the lessons room.'),
    'owner_not_addable': (403, f"{VOYAGER}'s owner, Andy Example, isn't in the lessons room or addable to it."),
}


@pytest.mark.parametrize('case', list(REASON))
def test_each_refusal_writes_nothing(adds_trusted, case):
    a = adds_trusted
    typed = refusal_case(a, case)
    before = snapshot(a.pi)
    with pytest.raises(Problem) as refused:
        a.pi.station_lessons_add(typed)
    status, text = REASON[case]
    assert (refused.value.status, refused.value.message) == (status, text.format(typed=typed, other12=a.other_fed.identity.peer_id[:12]))
    assert snapshot(a.pi) == before


def test_the_refusal_names_match_their_texts(adds_trusted):
    """Ruling 3: addable_now gives the refusal's name with its text, so a caller (Task 7's pause count) needn't read text."""
    a = adds_trusted
    a.trusted_ship('serenity')
    with a.pi.transaction() as db:
        room = a.pi._room(db, a.ids['andy'], a.pi._lessons_chain(db)[-1])
        name, text = lessons.addable_now(a.pi, db, room, a.ship, a.clock[0])
        assert name == 'ADD_TRUST' and text.endswith('that trust is paused.')
        assert lessons.addable_now(a.pi, db, room, a.owner, a.clock[0])[0] == 'ADD_MEMBER'


def test_a_code_typed_with_the_line_shown_is_added(adds):
    contact = adds.pair_new('defiant', lessons_line_shown=True)
    done = adds.pi.station_lessons_add(short(contact))
    assert done['old_room'] == adds.room and adds.pi.lessons_room_key() == done['new_room']
    assert contact in members_of(adds.pi, done['new_room']) and contact not in members_of(adds.pi, adds.room)


def test_an_account_the_confirmed_listing_named_is_added(adds):
    contact = adds.pair_new('defiant')                   # Andy typed it, but with no line shown
    with pytest.raises(Problem) as refused:
        adds.pi.station_lessons_add(short(contact))
    assert refused.value.message == NOT_VOUCHED[1]
    shown = relist(adds)['addable']
    assert [a['id'] for a in shown] == [contact]
    done = adds.pi.station_lessons_add(shown[0]['user_short'])   # typed as the listing shows it
    assert contact in members_of(adds.pi, done['new_room'])


def test_a_listing_row_counts_only_while_the_code_and_typist_are_the_ones_shown(adds):
    contact = adds.pair_new('defiant')
    relist(adds)
    with adds.pi.transaction() as db:                    # the digest no longer fits (as a re-pair under a new name)
        db.execute("UPDATE lessons_addable SET code_digest=? WHERE contact_id=?", ('0' * 64, contact))
    with pytest.raises(Problem, match="wasn't typed by"):
        adds.pi.station_lessons_add(short(contact))


def test_the_add_goes_to_the_chains_newest_room(adds):
    pi, andy = adds.pi, adds.ids['andy']
    first, second, third = (adds.pair_new(n, lessons_line_shown=True) for n in ('defiant', 'voyager', 'enterprise'))
    by_andy = pi.add_participants(andy, adds.room, [first])['id']     # Andy's own add moved the chain
    done = pi.station_lessons_add(short(second))
    assert done['old_room'] == by_andy
    again = pi.station_lessons_add(short(third))
    assert again['old_room'] == done['new_room']
    with pi.transaction() as db:
        assert pi._lessons_chain(db) == [adds.room, by_andy, done['new_room'], again['new_room']]
    assert {first, second, third} <= members_of(pi, again['new_room'])


def test_success_makes_the_next_room_carries_once_and_names_the_ship(adds):
    pi, ids = adds.pi, adds.ids
    relist(adds, adds.tardis_fed.identity.peer_id, adds.other_fed.identity.peer_id)
    pi.send_message(ids['rio-grande'], adds.room, 'p1', lesson_body(ship='rio-grande', claim='Kept.', command=('make check',)))
    contact = adds.pair_new('serenity', on='other', lessons_line_shown=True)
    done = pi.station_lessons_add(short(contact))
    assert done['lessons_carried'] == 1
    with pi.transaction() as db:
        user = db.execute('SELECT user_id FROM remote_contacts WHERE id=?', (contact,)).fetchone()['user_id']
        rows = [dict(r) for r in db.execute('SELECT * FROM member_changes WHERE member_id=?', (contact,))]
        assert [(r['change'], r['actor_id'], r['grant_id'], r['room_id'], r['new_room_id'], r['reason']) for r in rows] == \
            [('add', ids['rio-grande'], None, adds.room, done['new_room'], None)]
        said = [r[0] for r in db.execute('SELECT body FROM messages WHERE room_id=? AND author_id=?',
                                         (done['new_room'], pi.system_author_id(db)))]
        carried = db.execute("SELECT COUNT(*) FROM messages WHERE room_id=? AND client_message_id LIKE 'lesson-carry-%'",
                             (done['new_room'],)).fetchone()[0]
    assert said == [f'Rio-Grande added Serenity to this room. It continues room {adds.room[:6]}.'] and carried == 1
    assert done == {'label': 'Serenity', 'user_short': user[:8], 'peer12': adds.other_fed.identity.peer_id[:12],
                    'old_room': adds.room, 'new_room': done['new_room'], 'lessons_carried': 1}
    assert lessons.describe_lessons_add(done) == (
        f"Added Serenity ({user[:8]}) on {adds.other_fed.identity.peer_id[:12]} to the lessons room: room {adds.room[:6]} "
        f"became {done['new_room'][:6]}; 1 lessons carried.")
    later = adds.pair_new('defiant', on='other', lessons_line_shown=True)
    assert pi.station_lessons_add(short(later))['lessons_carried'] == 0   # the other peer has them already: carried once


def test_a_trust_made_ship_is_added_under_a_live_trust_with_its_owner_addable(adds_trusted):
    a = adds_trusted
    done = a.pi.station_lessons_add(short(a.ship))       # its owner, Andy's Tardis account, is a member
    assert done['label'] == VOYAGER and a.ship in members_of(a.pi, done['new_room'])
    # An owner who isn't a member but is addable: Bea on Tardis, her code typed by Andy with the line shown.
    bea = a.tardis.create_user('bea', 'Bea', 'a-long-password')['id']
    card = a.tardis_fed.card(bea)
    owner = a.pi_fed.pair(a.ids['andy'], card, code=pairing_code(card), lessons_line_shown=True)['id']
    grant((a.pi, {'id': a.ids['andy']}, {'id': owner}, None), password='a-long-password', expect=2)
    ship = a.trusted_ship('defiant', owner_user=bea)
    again = a.pi.station_lessons_add(short(ship))
    assert ship in members_of(a.pi, again['new_room']) and owner not in members_of(a.pi, again['new_room'])


def test_a_ship_whose_own_code_was_typed_stays_off_the_code_path_while_trust_made(adds_trusted):
    """The trust path is for a trust-made contact with no current code of its own; with one, it takes the code path,
    where listable never names a trust-made contact (Ruling 2), so it is refused, writing nothing."""
    a = adds_trusted
    card = b_ship(SimpleNamespace(machine=(a.tardis, {'id': a.ids['tardis-andy']}, None, a.tardis_fed), clock=a.clock),
                  'voyager', now=int(a.clock[0]))[0]
    a.pi_fed.pair(a.ids['andy'], card, code=pairing_code(card), lessons_line_shown=True)
    before = snapshot(a.pi)
    with pytest.raises(Problem) as refused:
        a.pi.station_lessons_add(short(a.ship))
    assert refused.value.message == f'{VOYAGER} was paired by owner trust, and that trust is live.'
    assert snapshot(a.pi) == before


def test_a_contact_key_with_a_colon_or_an_empty_chain_is_refused(adds):
    contact = adds.pair_new('defiant', lessons_line_shown=True)
    with pytest.raises(Problem) as elsewhere:            # Tardis records the room by its full id: not the origin
        adds.tardis.station_lessons_add(short(contact))
    with adds.pi.transaction() as db:
        db.execute('DELETE FROM lessons_peers')
        db.execute('DELETE FROM lessons_room')
    with pytest.raises(Problem) as empty:
        adds.pi.station_lessons_add(short(contact))
    for refused in (elsewhere, empty):
        assert (refused.value.status, refused.value.message) == (409, 'No lessons room is recorded at this origin.')


def test_a_typed_value_shaped_like_a_pairing_code_is_refused_and_not_echoed(adds):
    """32 hex, as a code is shown or typed: refused before the database is read, and never echoed. No real code is read
    here: the shape is enough."""
    shaped = 'c0de' * 8
    before = snapshot(adds.pi)
    for typed in (shaped, ' '.join(shaped[i:i + 4] for i in range(0, 32, 4)), shaped.upper().replace('C0', 'C-0')):
        with pytest.raises(Problem) as refused:
            adds.pi.station_lessons_add(typed)
        assert refused.value.status == 400 and 'c0de' not in refused.value.message.lower()
    assert snapshot(adds.pi) == before


def test_a_confirm_rerun_that_drops_a_contact_before_the_add_makes_the_add_refuse(adds):
    contact = adds.pair_new('defiant')
    relist(adds)                                         # the listing named it
    with adds.pi.transaction() as db:
        db.execute("UPDATE remote_contacts SET name='Renamed' WHERE id=?", (contact,))
    assert contact not in [a['id'] for a in relist(adds)['addable']]   # stale: the rerun no longer names it
    with adds.pi.transaction() as db:
        db.execute("UPDATE remote_contacts SET name='Defiant' WHERE id=?", (contact,))   # its code is current again
    with pytest.raises(Problem) as refused:
        adds.pi.station_lessons_add(short(contact))
    assert refused.value.message == NOT_VOUCHED[1]


def test_the_adds_output_shows_a_bidi_label_plainly(adds):
    ship = adds.tardis.lessons_ship('defiant', 'andy')['id']
    with adds.tardis.transaction() as db:
        db.execute("UPDATE users SET name=? WHERE id=?", ('Def‮iant', ship))
    card = adds.tardis_fed.card(ship)
    contact = adds.pi_fed.pair(adds.ids['andy'], card, code=pairing_code(card))['id']
    with pytest.raises(Problem) as refused:
        adds.pi.station_lessons_add(short(contact))
    assert refused.value.message.startswith("Defiant's code wasn't typed")
    relist(adds)
    said = lessons.describe_lessons_add(adds.pi.station_lessons_add(short(contact)))
    assert '‮' not in said and said.startswith('Added Defiant (')
    assert lessons.describe_lessons_add({'label': 'A⁦b', 'user_short': 'c‮d', 'peer12': 'p' * 12, 'old_room': 'o' * 32,
                                         'new_room': 'n' * 32, 'lessons_carried': 0}).startswith('Added Ab (cd) on ')


def test_the_station_add_verb_adds_and_a_refusal_exits_1(adds):
    contact = adds.pair_new('defiant', lessons_line_shown=True)
    done = run_lessons('station-add', '--data-dir', adds.pi.data_dir, '--contact', short(contact))
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith('Added Defiant (') and done.stdout.endswith('; 0 lessons carried.\n')
    again = run_lessons('station-add', '--data-dir', adds.pi.data_dir, '--contact', short(contact))
    assert again.returncode == 1 and 'Defiant is already in the lessons room.' in again.stderr
