"""First rail, revision 4: the index's chain time (section 4 step 4), the segments flag (section 7, "Independent
means...") and repeats after a seen lesson (section 7.1), whose records hold no text (section 6)."""
import json
import sqlite3
from contextlib import closing
import pytest
from superyak_peer import lessons
from superyak_peer.common import Problem
from conftest import LESSON_TIME, lesson_body, run_lessons

COLUMNS = ['id', 'created', 'ship_id', 'lesson_id', 'how', 'receipt_id', 'hook']
NOTE = 'zq-a-note-of-free-text'   # a value no refusal may echo


def full_id(store, body):
    return lessons.lesson_id(store._own_peer_id(), lessons.parse_post(body))


def shown_to(store, clock, ship, command):
    """One words-only query by `ship` at the clock's time, so the receipt it writes is this peer's, dated then."""
    request = lessons.read_request(json.dumps({'ship': ship, 'command': command, 'words_only': True}))
    return lessons.query(request, store.data_dir, None, clock=lambda: clock[0], monotonic=lambda: 0.0)[0]


def repeats(store):
    with store.transaction() as db:
        return [tuple(r) for r in db.execute('SELECT * FROM lesson_repeats ORDER BY created, rowid')]


def receipts(store):
    with store.transaction() as db:
        return [r['id'] for r in db.execute('SELECT id FROM lesson_receipts ORDER BY created, rowid')]


def index_of(store):
    return lessons.read_index(store.data_dir / lessons.INDEX_FILE)


HASHES = lesson_body(claim='Copy a hash from the output; never type one.', command=('git show',))
GLOBS = lesson_body(claim='Quote a glob in zsh.', command=('--include=*',))


# 1. The index records chain time
def test_the_index_records_when_each_lessons_post_entered_the_chain_and_a_copy_keeps_the_first(lessons_station):
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim='First.'))
    clock[0] += 30
    store.send_message(ids['tardis'], room, 'c2', lesson_body(claim='Second.'))
    clock[0] += 30
    store.send_message(ids['tardis'], room, 'c3', lesson_body(claim='First.', learned='owner'))   # the same text: a copy
    store.lessons_index(None)
    assert [(item['claim'], item['chain_time']) for item in index_of(store)['lessons']] == [
        ('First.', LESSON_TIME), ('Second.', LESSON_TIME + 30)]


def test_on_another_peer_a_lesson_enters_the_chain_when_the_origin_takes_it(lessons_peers):
    pi, _, _ = lessons_peers['peers']['pi']
    tardis, _, tids = lessons_peers['peers']['tardis']
    clock = lessons_peers['clock']
    tardis.send_message(tids['tardis'], lessons_peers['key'], 't1', GLOBS)
    clock[0] += 5
    lessons_peers['deliver']('tardis', 'pi')
    lessons_peers['deliver']('pi', 'tardis')
    for store in (pi, tardis):
        store.lessons_index(None)
        assert [item['chain_time'] for item in index_of(store)['lessons']] == [LESSON_TIME + 5]


def test_an_index_of_the_old_format_is_rebuilt_and_never_misread(lessons_station):
    """The magic line names the format's version. A version 1 file, whose lessons carry no chain time, is unreadable to
    every reader, never read as version 2, and the next index run rebuilds it even though its watermark still
    matches the chain."""
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', GLOBS)
    store.lessons_index(None)
    path = store.data_dir / lessons.INDEX_FILE
    data = path.read_bytes()
    at = len(lessons.INDEX_MAGIC)
    size = int.from_bytes(data[at:at + 4], 'big')
    value = json.loads(data[at + 4:at + 4 + size])
    for item in value['lessons']:
        del item['chain_time']
    head = json.dumps(value).encode()
    path.write_bytes(b'superyak-lessons-index 1\n' + len(head).to_bytes(4, 'big') + head + data[at + 4 + size:])
    assert lessons.INDEX_MAGIC == b'superyak-lessons-index 2\n'
    with pytest.raises(lessons.IndexUnreadable, match='older format'):
        lessons.read_index(path)
    assert lessons.could_hold('grep --include=*.py x', 'rio-grande', store.data_dir) is False
    with pytest.raises(lessons.IndexUnreadable):
        shown_to(store, clock, 'rio-grande', 'grep --include=*.py x')
    assert store.lessons_index(None)['status'] == 'written'   # never 'unchanged', though the watermark is the chain's
    assert path.read_bytes().startswith(lessons.INDEX_MAGIC)
    assert [item['chain_time'] for item in index_of(store)['lessons']] == [LESSON_TIME]
    assert lessons.could_hold('grep --include=*.py x', 'rio-grande', store.data_dir) is True


# 2. The segments flag
def test_segments_flag_a_pair_only_where_this_peer_holds_the_earlier_receipt(lessons_peers, fake_embedder):
    """Two pairs of rio-grande's and tardis's own lessons. On the Pi, rio-grande was shown tardis's `a` before it laid
    `b`, so that pair is flagged; it was shown `c` only after laying `d`, and its earlier receipt is for another lesson,
    so that pair isn't. Both are still segments. Tardis's peer holds no such receipt, so it flags neither."""
    pi, pi_fed, pids = lessons_peers['peers']['pi']
    tardis, tardis_fed, tids = lessons_peers['peers']['tardis']
    clock, deliver = lessons_peers['clock'], lessons_peers['deliver']
    a = lesson_body(ship='tardis', claim='Read before you trust a count.', command=('grep -c',))
    b = lesson_body(ship='rio-grande', claim='Never trust a keyword count over reading.', command=('grep -c',))
    c = lesson_body(ship='tardis', claim='Quote a glob in zsh.', command=('setopt nonomatch',))
    d = lesson_body(ship='rio-grande', claim='zsh expands an unquoted glob first.', command=('setopt nonomatch',))
    for body, vector in ((a, [1.0, 0.0, 0.0, 0.0]), (b, [1.0, 0.0, 0.0, 0.0]), (c, [0.0, 1.0, 0.0, 0.0]), (d, [0.0, 1.0, 0.0, 0.0])):
        fake_embedder.vectors[lessons.embedded_text(lessons.parse_post(body))] = vector
    tardis.send_message(tids['tardis'], lessons_peers['key'], 't1', a)
    tardis.send_message(tids['tardis'], lessons_peers['key'], 't2', c)
    deliver('tardis', 'pi')
    pi.lessons_index(fake_embedder.path)
    clock[0] += 10
    assert [e['claim'] for e in shown_to(pi, clock, 'rio-grande', 'grep -c x')['lessons']] == ['Read before you trust a count.']
    clock[0] += 10
    pi.send_message(pids['rio-grande'], lessons_peers['room'], 'p1', b)
    pi.send_message(pids['rio-grande'], lessons_peers['room'], 'p2', d)
    clock[0] += 10
    assert [e['claim'] for e in shown_to(pi, clock, 'rio-grande', 'setopt nonomatch x')['lessons']] == ['Quote a glob in zsh.']
    pi.lessons_index(fake_embedder.path)
    deliver('pi', 'tardis')
    tardis.lessons_index(fake_embedder.path)
    short = lambda peer, body: lessons.short_lesson_id(lessons.lesson_id(peer, lessons.parse_post(body)))
    on_pi = (pi_fed.identity.peer_id, tardis_fed.identity.peer_id)
    first = f'  {short(on_pi[0], b)}  {short(on_pi[1], a)}  0.0000 rad'
    second = f'  {short(on_pi[0], d)}  {short(on_pi[1], c)}  0.0000 rad'

    listed = run_lessons('segments', '--data-dir', pi.data_dir)
    assert listed.returncode == 0, listed.stderr
    lines = listed.stdout.splitlines()
    assert lines[0] == 'rio-grande and tardis: 2 segments'   # the flag changes nothing in what counts
    assert f'{first}  flagged: rio-grande was shown the other lesson first' in lines
    assert second in lines   # shown after it laid its own: not flagged
    assert sum('flagged:' in line for line in lines) == 1 and lines[-1].startswith('Flagged:')
    found = lessons.segments(index_of(pi))
    assert [x[5] for x in found] == [(), ()]   # with no receipts given, nothing is flagged

    elsewhere = run_lessons('segments', '--data-dir', tardis.data_dir)
    assert elsewhere.returncode == 0, elsewhere.stderr
    assert elsewhere.stdout.splitlines()[0] == 'rio-grande and tardis: 2 segments' and 'flagged' not in elsewhere.stdout.lower()
    assert first in elsewhere.stdout.splitlines() and second in elsewhere.stdout.splitlines()


# 3. The table
def test_the_repeats_table_has_only_the_specs_columns_and_refuses_anything_else_even_by_raw_sql(lessons_station):
    store, clock, ids, room = lessons_station
    key = 'a' * 64 + ':' + 'b' * 64
    good = dict(zip(COLUMNS, ('r0', LESSON_TIME, ids['rio-grande'], key, 'read', None, 'off')))
    with closing(sqlite3.connect(store.db_path)) as raw:
        assert [r[1] for r in raw.execute('PRAGMA table_info(lesson_repeats)')] == COLUMNS
        insert = 'INSERT INTO lesson_repeats VALUES(' + ','.join('?' * len(COLUMNS)) + ')'
        raw.execute(insert, tuple(good.values()))
        for n, bad in enumerate([{'how': 'seen'}, {'how': 'READ'}, {'how': None}, {'hook': 'maybe'}, {'hook': None},
                                 {'how': 'receipt'},                         # a receipt row names its receipt
                                 {'receipt_id': 'x' * 32},                   # a read row names none
                                 {'lesson_id': NOTE}, {'lesson_id': key.upper()}, {'lesson_id': key + ' ' + NOTE},
                                 {'ship_id': None}, {'created': None}]):
            row = {**good, **bad, 'id': f'r{n + 1}'}
            with pytest.raises(sqlite3.IntegrityError):
                raw.execute(insert, tuple(row[c] for c in COLUMNS))
        raw.execute(insert, tuple({**good, 'id': 'r9', 'how': 'receipt', 'receipt_id': 'x' * 32, 'hook': 'on'}.values()))
        assert raw.execute('SELECT count(*) FROM lesson_repeats').fetchone()[0] == 2


# 4. The verb
def test_a_repeat_with_a_receipt_is_verified_and_records_the_newest_receipts_id(lessons_station):
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', HASHES)
    store.lessons_index(None)
    key = full_id(store, HASHES)
    shown_to(store, clock, 'rio-grande', 'git show 1a2b')
    clock[0] += 600
    shown_to(store, clock, 'rio-grande', 'git show 1a2b')
    older, newest = receipts(store)
    done = run_lessons('repeat', '--data-dir', store.data_dir, lessons.short_lesson_id(key), '--how', 'receipt', '--hook', 'on',
                       now=LESSON_TIME + 3600)
    assert done.returncode == 0, done.stderr
    (row,) = repeats(store)
    assert row[1:] == (LESSON_TIME + 3600, ids['rio-grande'], key, 'receipt', newest, 'on') and len(row[0]) == 32
    assert 'verified' in done.stdout and 'unverified' not in done.stdout and lessons.short_lesson_id(key) in done.stdout
    assert 'Copy a hash' not in done.stdout


def test_a_repeat_read_in_a_room_is_unverified_and_names_no_receipt(lessons_station):
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', HASHES)
    store.lessons_index(None)
    key = full_id(store, HASHES)
    shown_to(store, clock, 'rio-grande', 'git show 1a2b')   # a receipt exists, and `read` still names none
    done = run_lessons('repeat', '--data-dir', store.data_dir, key, '--how', 'read', '--hook', 'off')
    assert done.returncode == 0, done.stderr
    (row,) = repeats(store)
    assert row[1:] == (LESSON_TIME, ids['rio-grande'], key, 'read', None, 'off') and 'unverified' in done.stdout
    made = store.lesson_repeat(lessons.short_lesson_id(key), 'read', 'on')   # in process too, the ship never an argument
    assert made['verified'] is False and made['receipt_id'] is None and made['ship'] == 'rio-grande'


def test_each_refusal_names_its_rule_echoes_nothing_and_writes_nothing(lessons_station):
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', HASHES)
    store.send_message(ids['rio-grande'], room, 'c2', lesson_body(ship='rio-grande', claim='Mine.', command=('make check',)))
    store.lessons_index(None)
    key, own = full_id(store, HASHES), full_id(store, lesson_body(ship='rio-grande', claim='Mine.', command=('make check',)))
    short = lessons.short_lesson_id(key)
    cases = {
        'unknown short form': [lessons.short_lesson_id('d' * 64 + ':' + 'e' * 64), '--how', 'read', '--hook', 'on'],
        'unknown full id': ['f' * 64 + ':' + 'f' * 64, '--how', 'read', '--hook', 'on'],
        'not an id': [NOTE, '--how', 'read', '--hook', 'on'],
        'an id in capitals': [key.upper(), '--how', 'read', '--hook', 'on'],
        'its own, by full id': [own, '--how', 'read', '--hook', 'on'],
        'its own, by short form': [lessons.short_lesson_id(own), '--how', 'read', '--hook', 'off'],
        'no receipt': [short, '--how', 'receipt', '--hook', 'on'],
        'a bad --how': [short, '--how', NOTE, '--hook', 'on'],
        'a bad --hook': [short, '--how', 'read', '--hook', NOTE],
        'a ship as an argument': [short, '--how', 'read', '--hook', 'on', '--ship', NOTE],
        'a note': [short, NOTE, '--how', 'read', '--hook', 'on'],
        'a second id': [short, key, '--how', 'read', '--hook', 'on'],
    }
    for name, args in cases.items():
        done = run_lessons('repeat', '--data-dir', store.data_dir, *args)
        assert done.returncode != 0 and done.stdout == '', name
        assert NOTE not in done.stderr and args[0] not in done.stderr, (name, done.stderr)
        assert key not in done.stderr and own not in done.stderr and short not in done.stderr, (name, done.stderr)
        assert done.stderr.strip(), name
    for missing in (['--how', 'read'], ['--hook', 'on'], []):
        done = run_lessons('repeat', '--data-dir', store.data_dir, short, *missing)
        assert done.returncode == 2 and ('--hook' in done.stderr or '--how' in done.stderr), missing
    assert run_lessons('repeat', '--data-dir', store.data_dir, '--how', 'read', '--hook', 'on').returncode == 2   # no id
    assert repeats(store) == []
    with pytest.raises(Problem, match="own lesson"):
        store.lesson_repeat(own, 'read', 'on')
    with pytest.raises(Problem, match='receipt'):
        store.lesson_repeat(key, 'receipt', 'off')
    with pytest.raises(Problem, match='--how'):
        store.lesson_repeat(key, 'seen', 'off')
    with pytest.raises(Problem, match='--hook'):
        store.lesson_repeat(key, 'read', None)
    assert repeats(store) == []


def test_an_ambiguous_short_form_is_refused_and_the_full_id_still_works(lessons_station):
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', HASHES)
    store.lessons_index(None)
    key = full_id(store, HASHES)
    path = store.data_dir / lessons.INDEX_FILE
    index = lessons.read_index(path)
    index.pop('block')
    twin = key[:-1] + ('0' if key[-1] != '0' else '1')   # the same short form
    index['lessons'].append({**index['lessons'][0], 'id': twin})
    lessons.write_index(path, index, [], LESSON_TIME)
    done = run_lessons('repeat', '--data-dir', store.data_dir, lessons.short_lesson_id(key), '--how', 'read', '--hook', 'on')
    assert done.returncode == 1 and 'more than one' in done.stderr and key not in done.stderr and twin not in done.stderr
    assert repeats(store) == []
    assert run_lessons('repeat', '--data-dir', store.data_dir, key, '--how', 'read', '--hook', 'on').returncode == 0
    assert [row[3] for row in repeats(store)] == [key]


def test_a_retracted_lesson_is_named_by_its_full_id_only(lessons_station):
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', HASHES)
    store.lessons_index(None)
    key = full_id(store, HASHES)
    short = lessons.short_lesson_id(key)
    shown_to(store, clock, 'rio-grande', 'git show 1a2b')
    store.send_message(ids['andy'], room, 'r1', 'retract ' + key)
    with pytest.raises(Problem, match='full id'):   # retracted since the index ran: the index still lists it
        store.lesson_repeat(short, 'receipt', 'off')
    store.lessons_index(None)
    with pytest.raises(Problem, match='full id'):   # the index has dropped it
        store.lesson_repeat(short, 'read', 'off')
    assert repeats(store) == []
    made = store.lesson_repeat(key, 'receipt', 'off')   # a repeat of a withdrawn lesson is still a repeat
    assert made['verified'] is True and repeats(store)[0][3:6] == (key, 'receipt', receipts(store)[0])


def test_a_short_form_needs_this_peers_index_and_a_full_id_does_not(lessons_station):
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', HASHES)
    key = full_id(store, HASHES)
    with pytest.raises(Problem, match='index'):
        store.lesson_repeat(lessons.short_lesson_id(key), 'read', 'on')
    assert store.lesson_repeat(key, 'read', 'on')['verified'] is False


RIO = lesson_body(ship='rio-grande', claim='Copy a hash from the output; never type one.', command=('git show',))


def test_on_another_peer_the_ship_is_its_one_ship_account_in_the_room(lessons_peers):
    """7.1, "run by a ship on its own peer": where the record names no ship (every peer but the origin, C28), the ship is
    the one ship account on this peer that is a member of the current lessons room. It is derived, never an argument:
    a ship account outside the room changes nothing, and a second one in the room leaves the ship unknown."""
    pi, pi_fed, pids = lessons_peers['peers']['pi']
    tardis, tardis_fed, tids = lessons_peers['peers']['tardis']
    clock, deliver = lessons_peers['clock'], lessons_peers['deliver']
    pi.send_message(pids['rio-grande'], lessons_peers['room'], 'p1', RIO)
    tardis.send_message(tids['tardis'], lessons_peers['key'], 't1', GLOBS)
    deliver('tardis', 'pi')
    deliver('pi', 'tardis')
    tardis.lessons_index(None)
    key = lessons.lesson_id(pi_fed.identity.peer_id, lessons.parse_post(RIO))
    own = lessons.lesson_id(tardis_fed.identity.peer_id, lessons.parse_post(GLOBS))
    assert [e['ship'] for e in shown_to(tardis, clock, 'tardis', 'git show 1a2b')['lessons']] == ['rio-grande']
    made = tardis.lesson_repeat(lessons.short_lesson_id(key), 'receipt', 'on')
    assert made['ship'] == 'tardis' and made['verified'] is True
    assert repeats(tardis) == [(made['id'], LESSON_TIME, tids['tardis'], key, 'receipt', receipts(tardis)[0], 'on')]
    with pytest.raises(Problem, match='own lesson'):   # the derived ship's own lesson, as on the origin
        tardis.lesson_repeat(own, 'read', 'on')
    done = run_lessons('repeat', '--data-dir', tardis.data_dir, key, '--how', 'read', '--hook', 'off')
    assert done.returncode == 0 and 'tardis, lesson' in done.stdout, done.stderr

    second = tardis.lessons_ship('defiant', 'andy')['id']   # a ship account here, not in the room: no change
    assert tardis.lesson_repeat(key, 'read', 'off')['ship'] == 'tardis'
    contact = pi_fed.pair(pids['andy'], tardis_fed.card(second))['id']
    pi.add_participants(pids['andy'], lessons_peers['room'], [contact])
    deliver('pi', 'tardis')
    before = repeats(tardis)
    for args in ((key, 'read', 'on'), (key, 'receipt', 'on')):
        with pytest.raises(Problem, match='More than one ship account'):
            tardis.lesson_repeat(*args)
    refused = run_lessons('repeat', '--data-dir', tardis.data_dir, key, '--how', 'read', '--hook', 'off')
    assert refused.returncode == 1 and 'More than one ship account' in refused.stderr and key not in refused.stderr
    assert repeats(tardis) == before and len(before) == 3


def test_the_recorded_ship_must_be_a_member_of_the_current_room(lessons_station):
    """On the origin, C28's record names the ship; once it leaves the lessons room, it records no repeat there."""
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', HASHES)
    key = full_id(store, HASHES)
    assert store.lesson_repeat(key, 'read', 'on')['ship'] == 'rio-grande'
    store.remove_participant(ids['andy'], room, ids['rio-grande'])
    with pytest.raises(Problem, match='not a member'):
        store.lesson_repeat(key, 'read', 'on')
    assert len(repeats(store)) == 1


def test_a_derived_ship_must_be_a_member_of_the_current_room(lessons_peers):
    """On another peer, a ship removed from the lessons room leaves no ship account in it, so nothing is recorded."""
    pi, pi_fed, pids = lessons_peers['peers']['pi']
    tardis, _, tids = lessons_peers['peers']['tardis']
    pi.send_message(pids['rio-grande'], lessons_peers['room'], 'p1', RIO)
    lessons_peers['deliver']('pi', 'tardis')
    key = lessons.lesson_id(pi_fed.identity.peer_id, lessons.parse_post(RIO))
    assert tardis.lesson_repeat(key, 'read', 'on')['ship'] == 'tardis'
    pi.remove_participant(pids['andy'], lessons_peers['room'], pids['contact'])
    lessons_peers['deliver']('pi', 'tardis')
    with pytest.raises(Problem, match='No ship account on this peer is a member'):
        tardis.lesson_repeat(key, 'read', 'on')
    assert len(repeats(tardis)) == 1


# 5. The list
def test_repeats_list_newest_first_with_ids_ship_how_hook_and_verified_apart_and_no_text(lessons_station):
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', HASHES)
    store.send_message(ids['tardis'], room, 'c2', GLOBS)
    store.lessons_index(None)
    hashes, globs = full_id(store, HASHES), full_id(store, GLOBS)
    shown_to(store, clock, 'rio-grande', 'git show 1a2b')
    clock[0] += 60
    verified = store.lesson_repeat(hashes, 'receipt', 'on')
    clock[0] += 60
    unverified = store.lesson_repeat(globs, 'read', 'off')
    done = run_lessons('repeats', '--data-dir', store.data_dir)
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert lines[0] == '1 verified, 1 unverified: read apart, never added together'
    assert lines[1] == (f"2027-01-15 08:02:00Z  {unverified['id']}  rio-grande  {lessons.short_lesson_id(globs)}  how read  "
                        'unverified  hook off (declared)')
    assert lines[2] == (f"2027-01-15 08:01:00Z  {verified['id']}  rio-grande  {lessons.short_lesson_id(hashes)}  how receipt  "
                        f"verified by receipt {receipts(store)[0]}  hook on (declared)")
    assert len(lines) == 3 and 'Copy a hash' not in done.stdout and 'glob' not in done.stdout and '2 ' not in lines[0]
    empty = run_lessons('repeats', '--data-dir', store.data_dir.parent / 'other')
    assert empty.returncode == 0 and empty.stdout == 'No repeats recorded yet.\n'
