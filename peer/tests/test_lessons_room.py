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


# Task 5: the record on the origin
@pytest.fixture
def origin(tmp_path):
    from superyak_peer.db import Store
    from superyak_peer.identity import PeerIdentity
    store = Store(tmp_path / 'pi', clock=lambda: LESSON_TIME)
    PeerIdentity.load_or_create(store.data_dir)
    andy = store.create_user('andy', 'Andy', 'a-long-password', is_admin=True)['id']
    rio = lesson_ship(store, andy, 'rio-grande')['id']
    return store, andy, rio, store.create_room(andy, 'Lessons', [rio])['id']


def test_station_lessons_room_shows_first_and_records_only_on_its_code(origin):
    store, andy, rio, room = origin
    view = store.station_lessons_room('andy', room[:6], 'rio-grande')
    assert view['recorded'] is False and len(view['confirm']) == 8 and view['peers'] == []
    assert sorted((m['username'], m['kind'], m['owner']) for m in view['members']) == [('andy', 'person', None), ('rio-grande', 'ship', 'andy')]
    with store.transaction() as db:
        assert store._lessons_record(db) is None
    with pytest.raises(Problem) as refused:
        store.station_lessons_room('andy', room[:6], 'rio-grande', confirm='00000000')
    assert 'changed since they were shown' in refused.value.message
    done = store.station_lessons_room('andy', room[:6], 'rio-grande', confirm=view['confirm'].upper())
    assert done['recorded'] and done['full_id'] == f'{store._own_peer_id()}:{room}'
    assert store.lessons_room_full_id() == done['full_id']


def test_station_lessons_room_refuses_what_isnt_only_andys(origin):
    store, andy, rio, room = origin
    odo = lesson_ship(store, None, 'odo')['id']
    crowded = store.create_room(andy, 'Lessons two', [rio, odo])['id']
    with pytest.raises(Problem, match='other than andy and rio-grande: odo'):
        store.station_lessons_room('andy', crowded[:6], 'rio-grande')
    with pytest.raises(Problem, match='not one of'):
        store.station_lessons_room('andy', room[:6], 'odo')
    empty = store.create_room(andy, 'No ship', [])['id']
    with pytest.raises(Problem, match='Add rio-grande'):
        store.station_lessons_room('andy', empty[:6], 'rio-grande')
    with pytest.raises(Problem, match='not paired'):
        store.station_lessons_room('andy', room[:6], 'rio-grande', ['f' * 64])
    view = store.station_lessons_room('andy', room[:6], 'rio-grande')
    store.station_lessons_room('andy', room[:6], 'rio-grande', confirm=view['confirm'])
    other = store.create_room(andy, 'Another', [rio])['id']
    with pytest.raises(Problem, match='already records another'):
        store.station_lessons_room('andy', other[:6], 'rio-grande')


def test_station_lessons_room_refuses_a_room_with_a_brief_or_a_moderator(origin):
    store, andy, rio, room = origin
    store.save_brief(andy, room, 'Our lessons.', 0)
    with pytest.raises(Problem, match='has a brief'):
        store.station_lessons_room('andy', room[:6], 'rio-grande')
    store.save_brief(andy, room, '', 1)   # Andy removes it
    store.station_moderate('andy', room[:6], 'rio-grande', actions=['add_member', 'remove_member'])   # as the CLI passes them
    with pytest.raises(Problem, match='has a moderator'):
        store.station_lessons_room('andy', room[:6], 'rio-grande')


def test_station_lessons_room_refuses_a_room_with_an_open_board_item_or_an_active_claim(origin):
    """Final review S1 (section 2: no board item and no claim), as C15 and C46 refuse a brief and a moderator: Andy
    closes the room's open items, and its claims end, before it can be recorded."""
    store, andy, rio, room = origin
    store.post_item(andy, room, 'spec:d7', 'A title', 'spec')
    with pytest.raises(Problem, match='has open board items'):
        store.station_lessons_room('andy', room[:6], 'rio-grande')
    store.drop_item(andy, room, 'spec:d7')
    store.claim(rio, room, 'spec:d8')
    with pytest.raises(Problem, match='has an active claim'):
        store.station_lessons_room('andy', room[:6], 'rio-grande')
    store.release(andy, room, 'spec:d8')   # the room's owner may release it
    view = store.station_lessons_room('andy', room[:6], 'rio-grande')
    assert store.station_lessons_room('andy', room[:6], 'rio-grande', confirm=view['confirm'])['recorded']


def test_nothing_puts_a_claim_kind_post_into_the_chain_and_no_add_carries_the_board_into_it(lessons_station):
    """Final review S1, from its probe: an open item and a claim written into the chain past every door (an older
    station, a hand edit) still can't post there. Link, done, drop and release are refused, and an add carries neither
    into the chain's new room: they stay with the room they were in."""
    store, clock, ids, room = lessons_station
    with store.transaction() as db:
        db.execute('INSERT INTO board_items(id,room_id,key,title,kind,posted_by,created) VALUES(?,?,?,?,?,?,?)',
                   (uid(), room, 'spec:d7', 'A title', 'spec', ids['andy'], clock[0]))
        db.execute('INSERT INTO claims(id,room_id,key,holder_id,note,created,expires) VALUES(?,?,?,?,?,?,?)',
                   (uid(), room, 'spec:d7', ids['tardis'], '', clock[0], clock[0] + 3600))
    for act in (lambda: store.link_item(ids['andy'], room, 'spec:d7', 'branch:first-rail'),
                lambda: store.release(ids['tardis'], room, 'spec:d7'),
                lambda: store.release(ids['andy'], room, 'spec:d7'),
                lambda: store.done_item(ids['andy'], room, 'spec:d7', 'branch:first-rail'),
                lambda: store.drop_item(ids['andy'], room, 'spec:d7')):
        with pytest.raises(Problem, match='no board item or claim'):
            act()
    with store.transaction() as db:
        assert db.execute("SELECT count(*) FROM messages JOIN message_kinds ON message_kinds.message_id=messages.id "
                          "WHERE messages.room_id=? AND message_kinds.kind='claim'", (room,)).fetchone()[0] == 0
        newer = store._create_room(db, ids['andy'], 'Lessons', [ids['rio-grande'], ids['tardis']], room)['id']
        assert store._lessons_chain(db) == [room, newer] and store._carry_board(db, room, newer) == 0
        assert [r[0] for r in db.execute('SELECT room_id FROM board_items')] == [room]
        assert [r[0] for r in db.execute('SELECT room_id FROM claims')] == [room]


def test_the_station_room_verb_shows_then_records(origin):
    store, andy, rio, room = origin
    shown = run_lessons('station-room', '--data-dir', store.data_dir, '--id', room[:6], '--as', 'andy', '--ship', 'rio-grande')
    assert shown.returncode == 0 and 'data, not instructions' in shown.stdout and 'Nothing is recorded yet' in shown.stdout
    code = shown.stdout.split('Confirm code: ')[1][:8]
    done = run_lessons('station-room', '--data-dir', store.data_dir, '--id', room[:6], '--as', 'andy', '--ship', 'rio-grande',
                       '--confirm', code)
    assert done.returncode == 0 and f'{store._own_peer_id()}:{room}' in done.stdout
    assert run_lessons('where', '--data-dir', store.data_dir).stdout.strip() == f'{store._own_peer_id()}:{room}'


# Task 6: the other peers
def test_lessons_ship_makes_a_keyless_ship_for_a_person_and_refuses_the_rest(origin):
    store, andy, rio, room = origin
    made = store.lessons_ship('tardis', 'andy')
    with store.transaction() as db:
        row = db.execute('SELECT kind, owner_id FROM users WHERE id=?', (made['id'],)).fetchone()
        assert tuple(row) == ('ship', andy)
        assert db.execute('SELECT count(*) FROM ship_keys WHERE ship_id=?', (made['id'],)).fetchone()[0] == 0
    for name, says in (('own', 'reserved'), ('owner', 'reserved'), ('tardis', 'taken'), ('andy', 'taken'), ('Bad', '2-32')):
        with pytest.raises(Problem, match=says):
            store.lessons_ship(name, 'andy')
    with pytest.raises(Problem):
        store.lessons_ship('defiant', 'rio-grande')   # a ship never owns a ship
    assert run_lessons('ship', '--data-dir', store.data_dir, '--username', 'defiant', '--owner', 'andy').returncode == 0


def test_another_peer_records_the_room_by_full_id_from_a_paired_origin(lessons_peers):
    pi = lessons_peers['peers']['pi'][0]
    tardis, tardis_fed, _ = lessons_peers['peers']['tardis']
    assert tardis.lessons_room_full_id() == lessons_peers['key']
    for wrong, says in ((lessons_peers['room'], 'full id'), (f'{"e" * 64}:{lessons_peers["room"]}', 'paired peer'),
                        (f'{tardis_fed.identity.peer_id}:x', 'origin')):
        with pytest.raises(Problem, match=says):
            tardis.record_lessons_room(wrong)
    with pytest.raises(Problem):
        pi.record_lessons_room(lessons_peers['key'])  # on the origin it is station-lessons-room


# Task 7: the doors
def test_the_origin_post_door_checks_every_lesson(lessons_station):
    store, clock, ids, room = lessons_station
    sent = store.send_message(ids['tardis'], room, 'c1', lesson_body())
    assert sent['replayed'] is False and store.send_message(ids['tardis'], room, 'c1', lesson_body())['replayed']
    for author, body, status, message in (
            ('tardis', 'hello', 422, lessons.NOT_A_LESSON),
            ('tardis', lesson_body(ship='rio-grande'), 422, lessons.SHIP_IS_AUTHOR),
            ('andy', lesson_body(ship='andy', claim='A person laid it.'), 403, lessons.SHIPS_ONLY),
            ('tardis', lesson_body(claim='Ask Andy Example first.'), 422, lessons.PERSON),
            ('tardis', lesson_body(claim='Mail git@github.com.'), 422, lessons.PERSON),
            ('tardis', lesson_body(claim='Ping @serenity about it.'), 422, lessons.NO_MENTIONS)):
        with pytest.raises(Problem) as refused:
            store.send_message(ids[author], room, uid(), body)
        assert (refused.value.status, refused.value.message) == (status, message)
    with pytest.raises(Problem, match='no reply label'):
        store.send_message(ids['tardis'], room, 'c2', lesson_body(claim='Two.'), reply_to=sent['id'])
    other = store.create_room(ids['andy'], 'Talk', [ids['tardis']])['id']
    assert store.send_message(ids['tardis'], other, 'c3', 'hello, @rio-grande')['replayed'] is False


def test_the_cap_retraction_for_good_and_a_repost(lessons_station):
    store, clock, ids, room = lessons_station
    for n in range(32):
        clock[0] += 3   # under 30 posts a minute
        store.send_message(ids['tardis'], room, f'c{n}', lesson_body(claim=f'Claim {n}.'))
    with pytest.raises(Problem) as refused:
        store.send_message(ids['tardis'], room, 'c32', lesson_body(claim='Claim 32.'))
    assert refused.value.message == lessons.CAP
    store.send_message(ids['tardis'], room, 'again', lesson_body(claim='Claim 0.'))   # a re-post adds no lesson
    first = store.check_lesson(ids['tardis'], lesson_body(claim='Claim 0.'))['lesson_id']
    with pytest.raises(Problem) as refused:
        store.send_message(ids['rio-grande'], room, 'r1', 'retract ' + first)
    assert refused.value.message == lessons.WHO_RETRACTS
    store.send_message(ids['andy'], room, 'r2', 'retract ' + first)
    with pytest.raises(Problem, match='No live lesson'):
        store.send_message(ids['andy'], room, 'r3', 'retract ' + first)
    with pytest.raises(Problem) as refused:
        store.send_message(ids['tardis'], room, 'c0b', lesson_body(claim='Claim 0.'))
    assert refused.value.message == lessons.RETRACTED
    store.send_message(ids['tardis'], room, 'c32b', lesson_body(claim='Claim 32.'))   # the retraction freed a place


def test_no_board_item_no_claim_and_no_brief_in_the_lessons_room(lessons_station):
    store, clock, ids, room = lessons_station
    with pytest.raises(Problem, match='no board item'):
        store.post_item(ids['andy'], room, 'spec:d7', 'A title', 'spec')
    with pytest.raises(Problem, match='no claim'):
        store.claim(ids['tardis'], room, 'spec:d7')
    with pytest.raises(Problem, match='no brief'):
        store.save_brief(ids['andy'], room, 'A brief.', 0)
    with pytest.raises(Problem, match='no brief'):
        store.save_ship_brief(ids['rio-grande'], room, 'A brief.', 0)


def test_the_laying_peers_door_and_the_origins_reply_door(lessons_peers):
    pi, pi_fed, pids = lessons_peers['peers']['pi']
    tardis, tardis_fed, tids = lessons_peers['peers']['tardis']
    with pytest.raises(Problem):
        tardis.send_message(tids['tardis'], lessons_peers['key'], 't0', 'hello')
    with pytest.raises(Problem) as refused:
        tardis.send_message(tids['andy'], lessons_peers['key'], 'a1', lesson_body(ship='andy'))
    assert refused.value.status == 403
    tardis.send_message(tids['tardis'], lessons_peers['key'], 't1', lesson_body())
    assert lessons_peers['deliver']('tardis', 'pi')['delivered'] == 1
    forged = tardis_fed.identity.envelope(destination=pi_fed.identity.peer_id, actor=tids['tardis'], resource_id=lessons_peers['room'],
                                          revision=1, action='room.reply', recipients=[pids['andy']],
                                          payload={'body': lesson_body(claim='Ask Andy Example.'), 'client_message_id': 'x'})
    with pytest.raises(Problem) as refused:
        pi_fed.receive(forged)   # skipped Tardis's door: the origin's refuses it, a 4xx to the sender
    assert refused.value.message == lessons.PERSON
    with pi.transaction() as db:
        assert db.execute('SELECT count(*) FROM peer_messages').fetchone()[0] == 1


def test_lessons_check_runs_the_doors_checks_without_posting(lessons_station):
    store, clock, ids, room = lessons_station
    ok = run_lessons('check', '--data-dir', store.data_dir, '--ship', 'tardis', stdin=lesson_body())
    assert ok.returncode == 0 and ok.stdout.startswith('ok: a lesson, lesson ')
    crlf = run_lessons('check', '--data-dir', store.data_dir, '--ship', 'tardis', stdin=lesson_body().replace('\n', '\r\n'))
    assert crlf.returncode == 1 and '\\r' in crlf.stderr
    with store.transaction() as db:
        assert db.execute('SELECT count(*) FROM messages WHERE room_id=?', (room,)).fetchone()[0] == 0


# Task 9: the add gate and the backfill
def test_no_new_local_member_and_no_bridge(lessons_station):
    store, clock, ids, room = lessons_station
    serenity = lesson_ship(store, ids['andy'], 'serenity')['id']
    for add in (lambda: store.add_participants(ids['andy'], room, [serenity]),
                lambda: store.station_add_ship('andy', room[:6], 'serenity')):
        with pytest.raises(Problem) as refused:
            add()
        assert refused.value.message == lessons.NEW_LOCAL
    lesson_ship(store, None, 'wormhole')
    with pytest.raises(Problem, match='no new member'):
        store.station_bridge('andy', room[:6], True)


def test_a_ship_removed_from_the_lessons_room_cant_be_added_back(lessons_station):
    """Final review N3, spec-literal and said in CLAUDE.md: once recorded, the chain takes no new local member, and a
    ship Andy removes, the recorded Rio Grande included, is a new member when added back."""
    store, clock, ids, room = lessons_station
    newer = store.remove_participant(ids['andy'], room, ids['rio-grande'])['id']
    with pytest.raises(Problem) as refused:
        store.add_participants(ids['andy'], newer, [ids['rio-grande']])
    assert refused.value.message == lessons.NEW_LOCAL


def test_no_moderator_in_the_lessons_room(lessons_station):
    store, clock, ids, room = lessons_station
    with pytest.raises(Problem, match='no moderator'):
        store.station_moderate('andy', room[:6], 'rio-grande', actions=['add_member', 'remove_member'])


def test_the_backfill_carries_live_lessons_once_to_a_new_peer(tmp_path, lessons_peers):
    from superyak_peer.db import Store
    from superyak_peer.federation import Federation
    pi, pi_fed, pids = lessons_peers['peers']['pi']
    tardis, tardis_fed, tids = lessons_peers['peers']['tardis']
    room, deliver, clock = lessons_peers['room'], lessons_peers['deliver'], lessons_peers['clock']
    tardis.send_message(tids['tardis'], lessons_peers['key'], 't1', lesson_body())
    deliver('tardis', 'pi')
    pi.send_message(pids['rio-grande'], room, 'p1', lesson_body(ship='rio-grande', claim='Kept.', command=('make check',)))
    pi.send_message(pids['rio-grande'], room, 'p2', lesson_body(ship='rio-grande', claim='Gone.', command=('make check',)))
    gone = pi.check_lesson(pids['rio-grande'], lesson_body(ship='rio-grande', claim='Gone.', command=('make check',)))
    pi.send_message(pids['andy'], room, 'p3', 'retract ' + gone['lesson_id'])
    mac = Store(tmp_path / 'mac', clock=lambda: clock[0])
    mac_fed = Federation(mac, endpoint='https://mac:7437')
    andy_m = mac.create_user('andy', 'Andy Example', 'a-long-password', is_admin=True)['id']
    contact = pi_fed.pair(pids['andy'], mac_fed.card(mac.lessons_ship('serenity', 'andy')['id']))['id']
    mac_fed.pair(andy_m, pi_fed.card(pids['andy']))
    with pytest.raises(Problem, match='not listed'):
        pi.add_participants(pids['andy'], room, [contact])
    both = [tardis_fed.identity.peer_id, mac_fed.identity.peer_id]
    pi.station_lessons_room('andy', room[:6], 'rio-grande', both, pi.station_lessons_room('andy', room[:6], 'rio-grande', both)['confirm'])
    new = pi.add_participants(pids['andy'], room, [contact])
    assert new['lessons_carried'] == 2   # not the retracted one
    later = pi_fed.pair(pids['andy'], mac_fed.card(andy_m))['id']
    assert pi.add_participants(pids['andy'], new['id'], [later])['lessons_carried'] == 0   # the Mac already had them
    pi_fed.sync_once(send=lambda card, prepare: (mac_fed if card['peer_id'] == mac_fed.identity.peer_id else tardis_fed).receive(prepare()))
    mac.record_lessons_room(pi.lessons_room_full_id())
    assert mac.lessons_index(None)['lessons'] == 2
    tardis.lessons_index(None)   # its own copy came back unverified and is skipped; the original stands
    assert len(lessons.read_index(tardis.data_dir / lessons.INDEX_FILE)['lessons']) == 2


def test_no_door_takes_the_carry_client_id_so_only_the_backfill_writes_it(lessons_station):
    """Final re-check, N4: a carried copy is marked by its client id, so a ship that chose one could hide its own lesson
    from the unread count. Every door refuses it; only _carry_lessons writes it. Today's message inserts (grep 'INSERT
    INTO messages\\|INSERT INTO peer_messages' in peer/superyak_peer): chats.py send (a door), federation.py receive (a
    door), peer_store.py remote_send (a door, via the laying peer), lessons.py's backfill (the one writer),
    room_claims.py (claim-, refused in the chain) and system_author.py (a server-chosen id)."""
    store, clock, ids, room = lessons_station
    with pytest.raises(Problem) as refused:
        store.send_message(ids['tardis'], room, f'{lessons.CARRIED}mine', lesson_body())
    assert (refused.value.status, refused.value.message) == (400, lessons.CARRY_ID)


def test_neither_peer_door_takes_the_carry_client_id(lessons_peers):
    pi, pi_fed, pids = lessons_peers['peers']['pi']
    tardis, tardis_fed, tids = lessons_peers['peers']['tardis']
    with pytest.raises(Problem) as refused:
        tardis.send_message(tids['tardis'], lessons_peers['key'], f'{lessons.CARRIED}laid', lesson_body())
    assert refused.value.message == lessons.CARRY_ID
    forged = tardis_fed.identity.envelope(destination=pi_fed.identity.peer_id, actor=tids['tardis'], resource_id=lessons_peers['room'],
                                          revision=1, action='room.reply', recipients=[pids['andy']],
                                          payload={'body': lesson_body(), 'client_message_id': f'{lessons.CARRIED}forged'})
    with pytest.raises(Problem) as refused:
        pi_fed.receive(forged)
    assert refused.value.message == lessons.CARRY_ID
