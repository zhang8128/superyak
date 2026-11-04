"""Lesson outcomes spec (2026-11-03-lesson-outcomes-design), sections 3 and 5: an outcome per receipt (helped, misled or
unused, once, within 24 h), its verb and its list with section 5's counts. The records hold no text and echo nothing typed."""
import json
import sqlite3
from contextlib import closing, contextmanager
import pytest
from superyak_peer import lessons
from superyak_peer.common import Problem
from conftest import LESSON_TIME, lesson_body, paired, run_lessons

COLUMNS = ['id', 'created', 'receipt_id', 'outcome']
NOTE = 'zq-a-note-of-free-text'   # a value no refusal may echo
HASHES = lesson_body(claim='Copy a hash from the output; never type one.', command=('git show',))
GLOBS = lesson_body(claim='Quote a glob in zsh.', command=('--include=*',), why='zsh expands an unquoted glob first.')


def full_id(store, body):
    return lessons.lesson_id(store._own_peer_id(), lessons.parse_post(body))


def shown_to(store, clock, ship, command):
    request = lessons.read_request(json.dumps({'ship': ship, 'command': command, 'words_only': True}))
    return lessons.query(request, store.data_dir, None, clock=lambda: clock[0], monotonic=lambda: 0.0)[0]


def receipts(store):
    with store.transaction() as db:
        return [r['id'] for r in db.execute('SELECT id FROM lesson_receipts ORDER BY created, rowid')]


def outcomes(store):
    with store.transaction() as db:
        return [tuple(r) for r in db.execute('SELECT * FROM lesson_outcomes ORDER BY created, rowid')]


def add_receipt(store, key, ship_id, lesson_id, created=LESSON_TIME):
    """A receipt written straight to the table, for the ids and ages a query can't produce."""
    with store.transaction() as db:
        db.execute('INSERT INTO lesson_receipts VALUES(?,?,?,?,?,?)', (key, created, ship_id, lesson_id, 'x', None))


def laid(lessons_station, *bodies):
    store, clock, ids, room = lessons_station
    for n, body in enumerate(bodies):
        store.send_message(ids[lessons.parse_post(body).ship], room, f'c{n}', body)
    store.lessons_index(None)
    return store, clock, ids, room


def test_the_outcomes_table_has_only_the_specs_columns_and_refuses_anything_else_even_by_raw_sql(lessons_station):
    store, clock, ids, room = laid(lessons_station, HASHES)
    shown_to(store, clock, 'rio-grande', 'git show 1a2b')
    shown_to(store, clock, 'rio-grande', 'git show 1a2b')
    first, second = receipts(store)
    with closing(sqlite3.connect(store.db_path)) as raw:
        raw.execute('PRAGMA foreign_keys=ON')
        assert [r[1] for r in raw.execute('PRAGMA table_info(lesson_outcomes)')] == COLUMNS
        insert = 'INSERT INTO lesson_outcomes VALUES(?,?,?,?)'
        raw.execute(insert, ('o0', LESSON_TIME, first, 'helped'))
        for n, row in enumerate([('o1', LESSON_TIME, second, 'great'), ('o2', LESSON_TIME, second, None),
                                 ('o3', LESSON_TIME, first, 'misled'), ('o4', LESSON_TIME, 'f' * 32, 'unused'),
                                 ('o5', None, second, 'unused'), ('o6', LESSON_TIME, second, 'Helped')]):
            with pytest.raises(sqlite3.IntegrityError):
                raw.execute(insert, row)
        assert raw.execute('SELECT count(*) FROM lesson_outcomes').fetchone()[0] == 1


def test_an_outcome_against_this_ships_receipt_is_recorded_by_full_id_and_by_prefix(lessons_station):
    store, clock, ids, room = laid(lessons_station, HASHES)
    key = full_id(store, HASHES)
    for _ in range(3):
        shown_to(store, clock, 'rio-grande', 'git show 1a2b')
    one, two, three = receipts(store)
    made = store.lesson_outcome(one, 'helped')
    assert made['outcome'] == 'helped' and made['receipt_id'] == one and made['ship'] == 'rio-grande'
    assert made['short'] == lessons.short_lesson_id(key) and len(made['id']) == 32 and made['created'] == LESSON_TIME
    assert store.lesson_outcome(two[:6], 'misled')['receipt_id'] == two
    assert store.lesson_outcome(three[:8], 'unused')['receipt_id'] == three
    assert [(row[2], row[3]) for row in outcomes(store)] == [(one, 'helped'), (two, 'misled'), (three, 'unused')]


def test_each_refusal_names_its_rule_echoes_nothing_and_writes_nothing(lessons_station):
    store, clock, ids, room = laid(lessons_station, HASHES, lesson_body(ship='rio-grande', claim='Mine.', command=('make check',)))
    key = full_id(store, HASHES)
    shown_to(store, clock, 'rio-grande', 'git show 1a2b')
    (mine,) = receipts(store)
    shown_to(store, clock, 'tardis', 'make check')                  # tardis is shown rio-grande's lesson
    theirs = [r for r in receipts(store) if r != mine][0]
    add_receipt(store, 'ab12cd' + '0' * 26, ids['rio-grande'], key)
    add_receipt(store, 'ab12cd' + '1' * 26, ids['rio-grande'], key)
    old = 'e' * 32
    add_receipt(store, old, ids['rio-grande'], key, created=LESSON_TIME - 86401)
    store.lesson_outcome(mine, 'helped')
    cases = [
        ('the word, great', 'great', mine, lessons.OUTCOME_WORD, 400),
        ('the word, capitalized', 'Helped', mine, lessons.OUTCOME_WORD, 400),
        ('the word, empty', '', mine, lessons.OUTCOME_WORD, 400),
        ('a prefix of 5', 'helped', mine[:5], lessons.OUTCOME_ID, 400),
        ('uppercase hex', 'helped', mine.upper(), lessons.OUTCOME_ID, 400),
        ('33 hex', 'helped', mine + '0', lessons.OUTCOME_ID, 400),
        ('an unknown prefix', 'helped', '999999', lessons.OUTCOME_UNKNOWN, 404),
        ('another ships receipt', 'helped', theirs, lessons.OUTCOME_UNKNOWN, 404),
        ('a shared prefix', 'helped', 'ab12cd', lessons.OUTCOME_AMBIGUOUS, 409),
        ('a second outcome', 'misled', mine, lessons.OUTCOME_TWICE, 409),
        ('an age of 86,401 s', 'helped', old, lessons.OUTCOME_LATE, 409),
    ]
    before = outcomes(store)
    for name, word, typed, rule, status in cases:
        with pytest.raises(Problem) as caught:
            store.lesson_outcome(typed, word)
        assert str(caught.value) == rule and caught.value.status == status, name
        for value in (typed, word):
            assert not value or value not in str(caught.value), name
    assert outcomes(store) == before


def test_another_ships_receipt_is_refused(lessons_peers):
    pi, _, pids = lessons_peers['peers']['pi']
    tardis, _, tids = lessons_peers['peers']['tardis']
    # Written straight to the table: a receipt for the Pi's ship, held on the Tardis peer, whose one ship is tardis.
    other = tardis.lessons_ship('other', 'andy')['id']
    with tardis.transaction() as db:
        db.execute('INSERT INTO lesson_receipts VALUES(?,?,?,?,?,?)', ('c' * 32, LESSON_TIME, other, 'a' * 64 + ':' + 'b' * 64, 'x', None))
    with pytest.raises(Problem) as caught:
        tardis.lesson_outcome('c' * 32, 'helped')
    assert str(caught.value) == lessons.OUTCOME_UNKNOWN and caught.value.status == 404
    with tardis.transaction() as db:
        assert db.execute('SELECT count(*) FROM lesson_outcomes').fetchone()[0] == 0


def test_an_age_of_exactly_24_hours_is_accepted(lessons_station):
    store, clock, ids, room = laid(lessons_station, HASHES)
    shown_to(store, clock, 'rio-grande', 'git show 1a2b')
    (key,) = receipts(store)
    clock[0] += 86400
    assert store.lesson_outcome(key, 'helped')['outcome'] == 'helped'


def test_a_retracted_lessons_receipt_still_takes_its_outcome(lessons_station):
    store, clock, ids, room = laid(lessons_station, HASHES)
    shown_to(store, clock, 'rio-grande', 'git show 1a2b')
    (key,) = receipts(store)
    store.send_message(ids['tardis'], room, 'r1', 'retract ' + full_id(store, HASHES))
    assert store.lesson_outcome(key, 'misled')['outcome'] == 'misled'


def test_a_race_for_one_receipt_is_refused_as_a_second_outcome(lessons_station, monkeypatch):
    store, clock, ids, room = laid(lessons_station, HASHES)
    shown_to(store, clock, 'rio-grande', 'git show 1a2b')
    (key,) = receipts(store)
    real = store.transaction

    class Racing:
        def __init__(self, db):
            self.db = db

        def execute(self, sql, *args):
            if sql.startswith('INSERT INTO lesson_outcomes'):
                self.db.execute('INSERT INTO lesson_outcomes VALUES(?,?,?,?)', ('rival', LESSON_TIME, key, 'unused'))
            return self.db.execute(sql, *args)

    @contextmanager
    def racing():
        with real() as db:
            yield Racing(db)

    monkeypatch.setattr(store, 'transaction', racing)
    with pytest.raises(Problem) as caught:
        store.lesson_outcome(key, 'helped')
    assert str(caught.value) == lessons.OUTCOME_TWICE and caught.value.status == 409
    monkeypatch.undo()
    assert outcomes(store) == []


def refused_with(store, rule):
    with pytest.raises(Problem) as caught:
        store.lesson_outcome('a' * 32, 'helped')
    assert str(caught.value) == rule and caught.value.status == 409


def test_the_ship_is_derived_as_for_repeats_and_the_recorded_ship_must_be_a_member(lessons_peers):
    pi, _, pids = lessons_peers['peers']['pi']
    pi.remove_participant(pids['andy'], lessons_peers['room'], pids['rio-grande'])
    refused_with(pi, lessons.OUTCOME_NOT_MEMBER)


def test_with_no_ship_account_in_the_room_there_is_no_ship(lessons_peers):
    pi, _, pids = lessons_peers['peers']['pi']
    tardis, _, _ = lessons_peers['peers']['tardis']
    pi.remove_participant(pids['andy'], lessons_peers['room'], pids['contact'])
    lessons_peers['deliver']('pi', 'tardis')
    refused_with(tardis, lessons.OUTCOME_NO_SHIP)


def test_with_two_ship_accounts_in_the_room_the_ship_is_unknown(lessons_peers):
    pi, pi_fed, pids = lessons_peers['peers']['pi']
    tardis, tardis_fed, _ = lessons_peers['peers']['tardis']
    second = tardis.lessons_ship('defiant', 'andy')['id']
    contact = paired(pi_fed, pids['andy'], tardis_fed.card(second))['id']
    pi.add_participants(pids['andy'], lessons_peers['room'], [contact])
    lessons_peers['deliver']('pi', 'tardis')
    refused_with(tardis, lessons.OUTCOME_SHIPS)


def test_outcomes_list_newest_first_with_ids_ship_lesson_and_outcome_and_section_5s_counts_and_no_text(lessons_station):
    store, clock, ids, room = laid(lessons_station, HASHES, GLOBS)
    hashes, globs = full_id(store, HASHES), full_id(store, GLOBS)
    from superyak_peer.db import Store
    Store(store.data_dir.parent / 'other', signing=False)  # an empty peer, which the verb no longer makes for itself
    assert run_lessons('outcomes', '--data-dir', store.data_dir.parent / 'other').stdout == 'No outcomes on this peer yet.\n'
    shown_to(store, clock, 'rio-grande', 'git show 1a2b')
    shown_to(store, clock, 'rio-grande', 'grep --include=*')
    first, second = receipts(store)[0], receipts(store)[1]
    clock[0] += 60
    one = store.lesson_outcome(first, 'helped')
    clock[0] += 60
    two = store.lesson_outcome(second, 'unused')
    store.lesson_repeat(hashes, 'receipt', 'on')
    rows, counts = store.lesson_outcomes()
    assert counts == {'receipts': 2, 'outcomes': 2, 'helped': 1, 'misled': 0, 'unused': 1, 'queries': 2, 'verified_repeats': 1}
    assert [r['id'] for r in rows] == [two['id'], one['id']] and set(rows[0]) == {
        'id', 'created', 'ship', 'receipt_id', 'lesson_id', 'outcome'}
    done = run_lessons('outcomes', '--data-dir', store.data_dir)
    assert done.returncode == 0, done.stderr
    lessons_of = {first: rows[1]['lesson_id'], second: rows[0]['lesson_id']}
    assert done.stdout.splitlines() == [
        f"{two['id'][:8]}  rio-grande  lesson {lessons.short_lesson_id(lessons_of[second])}  receipt {second[:8]}  unused",
        f"{one['id'][:8]}  rio-grande  lesson {lessons.short_lesson_id(lessons_of[first])}  receipt {first[:8]}  helped",
        'Coverage: 2 outcomes on 2 receipts. Helped 1, misled 0, unused 1. Verified repeats: 1 in 2 queries (50.0 per 100).']
    for text in ('Copy a hash', 'Quote a glob', 'zsh expands'):
        assert text not in done.stdout
    limited = lessons.describe_outcomes(*store.lesson_outcomes(limit=1))
    assert len(limited.splitlines()) == 2 and 'Coverage: 2 outcomes on 2 receipts.' in limited
    assert lessons.describe_outcomes([], {**counts, 'queries': 0}) == 'No outcomes on this peer yet.'
    assert lessons.describe_outcomes(rows, {**counts, 'queries': 0}).endswith('Verified repeats: 1 in 0 queries (- per 100).')


def test_the_verbs_run_through_the_cli(lessons_station):
    store, clock, ids, room = laid(lessons_station, HASHES)
    shown_to(store, clock, 'rio-grande', 'git show 1a2b')
    (key,) = receipts(store)
    done = run_lessons('outcome', '--data-dir', store.data_dir, key, 'helped')
    assert done.returncode == 0, done.stderr
    (row,) = outcomes(store)
    assert done.stdout.startswith(f'Recorded outcome {row[0][:8]}: rio-grande, lesson ') and f'receipt {key[:8]}, helped.' in done.stdout
    extra = run_lessons('outcome', '--data-dir', store.data_dir, key, 'helped', NOTE)
    assert extra.returncode == 2 and extra.stdout == ''
    assert extra.stderr == 'lessons outcome takes one receipt id and one outcome, and nothing else\n'
    refused = run_lessons('outcome', '--data-dir', store.data_dir, key, 'helped')
    assert refused.returncode == 1 and key not in refused.stderr and len(outcomes(store)) == 1
    listed = run_lessons('outcomes', '--data-dir', store.data_dir)
    assert listed.returncode == 0 and 'Coverage: 1 outcomes on 1 receipts.' in listed.stdout
