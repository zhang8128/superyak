"""First rail, the room: its chain and snapshot (section 4 step 1), its record on the origin and on other peers
(section 3), every door's checks (sections 2, 3 and 6), the add gate and the backfill (section 3's chain)."""
import pytest
from superyak_peer import lessons
from superyak_peer.common import Problem, uid
from conftest import LESSON_TIME, lesson_body, lesson_ship, run_lessons


def post(store, room, author, body, created=None):
    """A message written straight into a room, past every door: for testing what the index's own checks skip."""
    with store.transaction() as db:
        key = uid()
        db.execute('INSERT INTO messages VALUES(?,?,?,?,?,1,?)', (key, room, author, key, body, created or store.clock()))
        return key


# Task 4: the chain and the snapshot
def test_the_chain_runs_oldest_first_and_follows_an_add_forward(lessons_station):
    store, clock, ids, room = lessons_station
    with store.transaction() as db:
        newer = store._create_room(db, ids['andy'], 'Lessons', [ids['rio-grande'], ids['tardis']], room)['id']
        assert store._lessons_chain(db) == [room, newer]
        snapshot = store._lessons_snapshot(db)
    assert snapshot.room == newer and snapshot.owner == f"{snapshot.peer}:{ids['andy']}"
    assert snapshot.members == {f"{snapshot.peer}:{ids[name]}" for name in ('andy', 'rio-grande', 'tardis')}
    assert snapshot.ships == {'rio-grande': f"{snapshot.peer}:{ids['rio-grande']}", 'tardis': f"{snapshot.peer}:{ids['tardis']}"}


def test_no_record_no_chain_and_no_identity_no_lessons(tmp_path, lessons_station):
    from superyak_peer.db import Store
    bare = Store(tmp_path / 'bare', clock=lambda: LESSON_TIME)
    with bare.transaction() as db:
        assert bare._lessons_chain(db) == [] and bare._lessons_snapshot(db) is None
    store, clock, ids, room = lessons_station
    (store.data_dir / 'identity.json').rename(store.data_dir / 'identity.aside')
    store._identity = None
    with pytest.raises(Problem) as refused, store.transaction() as db:
        store._lessons_snapshot(db)
    assert refused.value.message == lessons.NO_IDENTITY and not (store.data_dir / 'identity.json').exists()


def test_copies_collapse_to_the_earliest_and_each_author_keeps_32(lessons_station):
    store, clock, ids, room = lessons_station
    for n in range(33):
        post(store, room, ids['tardis'], lesson_body(claim=f'Claim {n}.'), LESSON_TIME + n)
    post(store, room, ids['tardis'], lesson_body(claim='Claim 0.', learned='owner'), LESSON_TIME + 100)  # same text: a copy
    with store.transaction() as db:
        live, retracted = lessons.chain_lessons(store._lessons_snapshot(db))
    assert len(live) == 32 and live[0].lesson.claim == 'Claim 0.' and live[0].lesson.learned_from == 'own'
    assert live[-1].lesson.claim == 'Claim 31.' and retracted == set()


def test_retractions_count_from_the_author_or_the_owner_in_any_order(lessons_station):
    store, clock, ids, room = lessons_station
    peer = store._own_peer_id()
    first, second = (lessons.lesson_id(peer, lessons.parse_post(lesson_body(claim=c))) for c in ('One.', 'Two.'))
    post(store, room, ids['andy'], 'retract ' + first, LESSON_TIME)          # before the lesson: still counts
    post(store, room, ids['tardis'], lesson_body(claim='One.'), LESSON_TIME + 1)
    post(store, room, ids['tardis'], lesson_body(claim='Two.'), LESSON_TIME + 2)
    post(store, room, ids['rio-grande'], 'retract ' + second, LESSON_TIME + 3)  # neither author nor owner: no
    with store.transaction() as db:
        live, retracted = lessons.chain_lessons(store._lessons_snapshot(db))
    assert [item.lesson.claim for item in live] == ['Two.'] and retracted == {first}


def test_the_index_door_skips_the_station_non_members_strangers_names_and_wrong_ship_lines(lessons_station):
    store, clock, ids, room = lessons_station
    with store.transaction() as db:
        system = store.system_author_id(db)
    outsider = lesson_ship(store, ids['andy'], 'serenity')['id']   # not in the room
    post(store, room, system, lesson_body(ship='tardis'))
    post(store, room, outsider, lesson_body(ship='serenity', claim='Outside.'))
    post(store, room, ids['tardis'], lesson_body(claim='Ask Andy Example.'))
    post(store, room, ids['tardis'], lesson_body(ship='rio-grande', claim='Wrong ship line.'))
    post(store, room, ids['andy'], lesson_body(ship='andy', claim='A person.'))
    post(store, room, ids['tardis'], 'hello')
    post(store, room, ids['tardis'], lesson_body(claim='Kept.'))
    with store.transaction() as db:
        assert [item.lesson.claim for item in lessons.chain_lessons(store._lessons_snapshot(db))[0]] == ['Kept.']


# Fix round 1: a retraction counts from the accepted copy's author, and a recorded room the peer no longer holds is none
def test_only_the_accepted_copys_author_retracts_never_a_refused_copys_poster(lessons_station):
    store, clock, ids, room = lessons_station
    peer = store._own_peer_id()
    key = lessons.lesson_id(peer, lessons.parse_post(lesson_body(claim='Shared.')))
    post(store, room, ids['rio-grande'], lesson_body(claim='Shared.'), LESSON_TIME)      # ship: tardis, by rio-grande: refused
    post(store, room, ids['tardis'], lesson_body(claim='Shared.'), LESSON_TIME + 1)      # tardis's own: the accepted copy
    post(store, room, ids['rio-grande'], 'retract ' + key, LESSON_TIME + 2)              # the refused copy's poster: no
    with store.transaction() as db:
        live, retracted = lessons.chain_lessons(store._lessons_snapshot(db))
    assert [item.author for item in live] == [f"{peer}:{ids['tardis']}"] and retracted == set()
    post(store, room, ids['tardis'], 'retract ' + key, LESSON_TIME + 3)                  # the accepted copy's author: yes
    with store.transaction() as db:
        live, retracted = lessons.chain_lessons(store._lessons_snapshot(db))
    assert live == [] and retracted == {key}


def test_a_recorded_room_this_peer_no_longer_holds_gives_no_snapshot(lessons_station):
    store, clock, ids, room = lessons_station
    with store.transaction() as db:
        db.execute('UPDATE lessons_room SET room_key=?', (uid(),))  # hand edits only: room_key has no foreign key
        assert store._lessons_snapshot(db) is None and store._lessons_chain(db) == []
        assert not store._in_lessons_chain(db, room)


# Fix round 2: the paired peer's branches of the chain and the snapshot, and a dangling link further back
def test_a_paired_peer_follows_the_origins_replaced_room_and_reads_only_what_it_was_sent(tmp_path):
    """Section 3's chain on a peer that isn't the origin: the record names the origin's older room; the peer follows
    linked_room_id forward to the room that replaced it, and back to the first room it holds (it never held r0). The
    owner and members come from the current room's payload, the posts from every room's stored messages, and a post
    the origin attributes to this peer's own ship, with no reply from here to prove it, counts for nothing."""
    import json
    from superyak_peer.db import Store
    from superyak_peer.identity import PeerIdentity
    store = Store(tmp_path / 'mac', clock=lambda: LESSON_TIME)
    PeerIdentity.load_or_create(store.data_dir)
    andy = store.create_user('andy', 'Andy Example', 'a-long-password', is_admin=True)['id']
    serenity = lesson_ship(store, andy, 'serenity')['id']
    mac, origin = store._own_peer_id(), 'b' * 64

    def o(key):
        return f'{origin}:{key}'

    def message(room, n, author, body):
        return {'id': f'{room}-m{n}', 'room_id': room, 'author_id': author, 'client_message_id': f'c{n}', 'body': body,
                'epoch': 1, 'created': LESSON_TIME + n}

    def payload(linked, members, messages):  # the keys federation._room_snapshot sends, and the stored messages
        return {'title': 'Lessons', 'owner_id': o('u-andy'), 'member_ids': members, 'linked_room_id': linked,
                'members': [dict(zip(('peer', 'id'), m.split(':'))) for m in members], 'created': LESSON_TIME,
                'last_activity': LESSON_TIME, 'messages': messages}
    first = [o('u-andy'), o('u-rio'), f'{mac}:{serenity}']
    rooms = {'r1': (3, payload(o('r0'), first, [message('r1', 1, o('u-rio'), lesson_body(ship='rio-grande', claim='Laid in r1.'))])),
             'r2': (1, payload(o('r1'), first + [o('u-tardis')], [
                 message('r2', 2, o('u-tardis'), lesson_body(claim='Laid in r2.')),
                 message('r2', 3, f'{mac}:{serenity}', lesson_body(ship='serenity', claim='Not sent from here.'))]))}
    with store.transaction() as db:
        db.execute('INSERT INTO peers VALUES(?,?,1)', (origin, '{}'))
        for rid, (revision, body) in rooms.items():
            db.execute('INSERT INTO inbox VALUES(?,?,?,?,?,?,?)', (origin, rid, 'room', serenity, revision, 'u-andy', json.dumps(body)))
        db.execute('INSERT INTO lessons_room VALUES(1,?,?,?)', (o('r1'), serenity, LESSON_TIME))
        assert store._lessons_chain(db) == [o('r1'), o('r2')] and store._in_lessons_chain(db, o('r2'))
        snapshot = store._lessons_snapshot(db)
    assert (snapshot.peer, snapshot.room, snapshot.owner) == (mac, o('r2'), o('u-andy'))
    assert snapshot.epochs == [[o('r1'), 3], [o('r2'), 1]] and snapshot.members == set(first + [o('u-tardis')])
    assert snapshot.ships == {'serenity': f'{mac}:{serenity}'}
    assert [(post.room, post.skip) for post in snapshot.posts] == [(o('r1'), False), (o('r2'), False), (o('r2'), True)]
    live, retracted = lessons.chain_lessons(snapshot)
    assert [(item.author, item.lesson.claim) for item in live] == [(o('u-rio'), 'Laid in r1.'), (o('u-tardis'), 'Laid in r2.')]
    assert all(item.id.startswith(origin + ':') for item in live) and retracted == set()


def test_a_dangling_link_further_back_ends_the_chain_at_the_break(lessons_station):
    """Only a hand edit with foreign keys off points linked_room_id at a room that isn't there. The chain then ends at
    the last room this peer holds, as a paired peer's ends at the first room it never held, and the snapshot reads
    every room up to the break."""
    import sqlite3
    from contextlib import closing
    store, clock, ids, room = lessons_station
    with store.transaction() as db:
        newer = store._create_room(db, ids['andy'], 'Lessons', [ids['rio-grande'], ids['tardis']], room)['id']
    post(store, room, ids['tardis'], lesson_body(claim='Laid in the first room.'))
    with closing(sqlite3.connect(store.db_path)) as raw:
        raw.execute('PRAGMA foreign_keys=OFF')
        raw.execute('UPDATE rooms SET linked_room_id=? WHERE id=?', (uid(), room))
        raw.commit()
    with store.transaction() as db:
        snapshot = store._lessons_snapshot(db)
        assert store._lessons_chain(db) == [room, newer]
    assert [key for key, _ in snapshot.epochs] == [room, newer]
    assert [item.lesson.claim for item in lessons.chain_lessons(snapshot)[0]] == ['Laid in the first room.']
