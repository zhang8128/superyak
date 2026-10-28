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
