"""The receipt-place spec (docs/superpowers/specs/2026-11-18-lesson-receipt-place.md, draft 4): a receipt keeps where its
lesson was shown, `superyak`, `other` or NULL, and the outcomes report splits by it. The peer's half: the column and its
migration, the request's check, the receipt's write and the split. Each test fails on the code before the change."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from superyak_peer import lessons
from superyak_peer.db import Store
from conftest import LESSON_TIME, lesson_body, run_lessons

HASHES = lesson_body(claim='Copy a hash from the output; never type one.', command=('git show',))
GLOBS = lesson_body(claim='Quote a glob in zsh.', command=('--include=*',), why='zsh expands an unquoted glob first.')
SECRET = '/home/someone/private-project'      # a value no refusal may echo


def laid(lessons_station, *bodies):
    store, clock, ids, room = lessons_station
    for n, body in enumerate(bodies):
        store.send_message(ids[lessons.parse_post(body).ship], room, f'c{n}', body)
    store.lessons_index(None)
    return store, clock, ids, room


def shown(store, clock, command, **extra):
    request = lessons.read_request(json.dumps({'ship': 'rio-grande', 'command': command, 'words_only': True, **extra}))
    return lessons.query(request, store.data_dir, None, clock=lambda: clock[0], monotonic=lambda: 0.0)[0]


def places(store):
    with store.transaction() as db:
        return [r['place'] for r in db.execute('SELECT place FROM lesson_receipts ORDER BY created, rowid')]


# ---- the request ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('place', ['superyak', 'other'])
def test_a_request_takes_superyak_or_other(place):
    assert lessons.read_request(json.dumps({'ship': 'tardis', 'command': 'ls', 'place': place}))['place'] == place


def test_a_request_with_no_place_reads_as_none():
    assert lessons.read_request(json.dumps({'ship': 'tardis', 'command': 'ls'}))['place'] is None


@pytest.mark.parametrize('place', ['Superyak', 'x', 5, None, SECRET, ['superyak'], ''])
def test_any_other_place_is_refused_without_echoing_it(place):
    for extra in ({'command': 'ls'}, {'prompt': 'hello'}):      # checked before the prompt's early return
        with pytest.raises(ValueError) as e:
            lessons.read_request(json.dumps({'ship': 'tardis', 'place': place, **extra}))
        assert str(e.value) == 'place' and SECRET not in str(e.value)


# ---- the receipt ---------------------------------------------------------------------------------------------------

def test_a_place_reaches_its_receipt_and_none_stays_null(lessons_station):
    store, clock, ids, room = laid(lessons_station, HASHES, GLOBS)
    shown(store, clock, 'git show 1a2b', place='superyak')
    shown(store, clock, 'grep --include=*', place='other')
    assert places(store) == ['superyak', 'other']


def test_an_old_hooks_request_writes_a_null_place(lessons_station):
    store, clock, ids, room = laid(lessons_station, HASHES)
    shown(store, clock, 'git show 1a2b')
    assert places(store) == [None]


def test_the_column_refuses_any_other_value_even_by_raw_sql(lessons_station):
    store, *_ = lessons_station
    with pytest.raises(sqlite3.IntegrityError), store.transaction() as db:
        db.execute("INSERT INTO lesson_receipts(id, created, ship_id, lesson_id, author_id, angle, place) "
                   "VALUES('k', 1, 'u', 'l', 'a', NULL, 'home')")


def test_every_insert_names_its_columns():
    source = Path(lessons.__file__).read_text()
    assert 'INSERT INTO lesson_receipts VALUES' not in source and 'INSERT INTO lesson_receipts(' in source


# ---- the migration ---------------------------------------------------------------------------------------------------

def _as_before(path):
    """The store as a peer before this change left it: lesson_receipts with six columns, one receipt and its outcome."""
    with closing(sqlite3.connect(path)) as db:
        db.executescript('''
            CREATE TABLE old(id TEXT PRIMARY KEY, created REAL NOT NULL, ship_id TEXT NOT NULL REFERENCES users(id),
                             lesson_id TEXT NOT NULL, author_id TEXT NOT NULL, angle REAL);
            DROP INDEX lesson_receipts_by_created;
            DROP TABLE lesson_receipts;
            ALTER TABLE old RENAME TO lesson_receipts;
            CREATE INDEX lesson_receipts_by_created ON lesson_receipts(created);
            INSERT INTO lesson_receipts VALUES('r1', 1800000000.0, 'u', 'l', 'a', 0.5);
            INSERT INTO lesson_outcomes VALUES('o1', 1800000060.0, 'r1', 'helped');''')


def test_a_populated_store_gains_the_column_once_and_keeps_its_rows(tmp_path):
    data = tmp_path / 'peer'
    Store(data, signing=False)
    _as_before(data / 'peer.sqlite3')
    for _ in range(2):                                   # opened twice: the column is added once
        Store(data, signing=False)
    with closing(sqlite3.connect(data / 'peer.sqlite3')) as db:
        columns = [r[1] for r in db.execute('PRAGMA table_info(lesson_receipts)')]
        rows = db.execute('SELECT id, angle, place FROM lesson_receipts').fetchall()
        linked = db.execute('SELECT o.id FROM lesson_outcomes o JOIN lesson_receipts r ON r.id = o.receipt_id').fetchall()
    assert columns.count('place') == 1 and rows == [('r1', 0.5, None)] and linked == [('o1',)]


def test_a_fresh_store_has_the_column(tmp_path):
    Store(tmp_path / 'peer', signing=False)
    with closing(sqlite3.connect(tmp_path / 'peer' / 'peer.sqlite3')) as db:
        assert 'place' in [r[1] for r in db.execute('PRAGMA table_info(lesson_receipts)')]


# ---- the split -------------------------------------------------------------------------------------------------------

def test_the_report_splits_receipts_and_outcomes_by_place_and_keeps_its_line(lessons_station):
    store, clock, ids, room = laid(lessons_station, HASHES, GLOBS)
    shown(store, clock, 'git show 1a2b', place='superyak')
    shown(store, clock, 'grep --include=*', place='other')
    with store.transaction() as db:
        first, second = [r['id'] for r in db.execute('SELECT id FROM lesson_receipts ORDER BY created, rowid')]
        db.execute("INSERT INTO lesson_receipts(id, created, ship_id, lesson_id, author_id, angle, place) "
                   "SELECT '0123456789abcdef0123456789abcdef', created, ship_id, lesson_id, author_id, angle, NULL FROM lesson_receipts WHERE id = ?",
                   (first,))
    clock[0] += 60
    store.lesson_outcome(first, 'helped')
    store.lesson_outcome(second, 'unused')
    store.lesson_outcome('0123456789abcdef0123456789abcdef', 'misled')
    rows, counts = store.lesson_outcomes(limit=1)        # the groups count the whole store, past the listing's limit
    by = counts['by_place']
    assert by == {'superyak': {'receipts': 1, 'outcomes': 1, 'helped': 1, 'misled': 0, 'unused': 0},
                  'other': {'receipts': 1, 'outcomes': 1, 'helped': 0, 'misled': 0, 'unused': 1},
                  'unknown': {'receipts': 1, 'outcomes': 1, 'helped': 0, 'misled': 1, 'unused': 0}}
    for key in ('receipts', 'outcomes', 'helped', 'misled', 'unused'):
        assert sum(group[key] for group in by.values()) == counts[key]
    done = run_lessons('outcomes', '--data-dir', store.data_dir)
    assert done.returncode == 0, done.stderr
    out = done.stdout.splitlines()
    assert out[-5].startswith('Coverage: 3 outcomes on 3 receipts. Helped 1, misled 1, unused 1. Verified repeats: 0 in ')
    assert out[-4:] == [
        'In Superyak sessions: 1 outcome on 1 receipt. Helped 1, misled 0, unused 0.',
        'In other sessions: 1 outcome on 1 receipt. Helped 0, misled 0, unused 1.',
        'Unknown place, including receipts from before this change: 1 outcome on 1 receipt. Helped 0, misled 1, unused 0.',
        'Verified repeats are counted over all places: a query keeps no place.']


# ---- the round trip through the command the hook runs ------------------------------------------------------------

TOOL = lesson_body(claim='Read the room before posting.', command=('mcp__station__station_post',))
PEER = lesson_body(claim='In the peer.', command=('zzzz-never',), file=('superyak/peer',))
SHAPES = {'start': {'cwd': '/home/x/superyak/peer', 'branch': 'main'},
          'failure': {'command': 'git show 1a2b', 'error': 'fatal: bad object 1a2b', 'cwd': '/home/x/p'},
          'hold': {'command': 'git show 1a2b', 'words_only': True},
          'held tool': {'command': 'mcp__station__station_post', 'words_only': True}}


@pytest.mark.parametrize('place', ['superyak', 'other', None])
@pytest.mark.parametrize('shape', list(SHAPES))
def test_a_place_goes_through_the_query_command_to_its_receipt(lessons_station, tmp_path, shape, place):
    """The table's "A place reaches its receipt": each request shape the hook and the hold send, through `lessons
    query` in a child as the hook runs it, read back from lesson_receipts."""
    store, clock, ids, room = laid(lessons_station, HASHES, TOOL, PEER)
    config = tmp_path / 'runtime.json'
    config.write_text(json.dumps({'embedder_socket': str(tmp_path / 'none.sock')}))
    request = {'ship': 'rio-grande', 'budget_ms': 3000, **SHAPES[shape], **({} if place is None else {'place': place})}
    done = run_lessons('query', '--data-dir', store.data_dir, '--runtime-config', config, stdin=json.dumps(request))
    assert done.returncode == 0 and json.loads(done.stdout)['lessons'], (done.stdout, done.stderr)
    assert places(store) == [place]


def test_a_bad_place_through_the_query_command_writes_no_receipt_and_echoes_nothing(lessons_station, tmp_path):
    store, clock, ids, room = laid(lessons_station, HASHES)
    config = tmp_path / 'runtime.json'
    config.write_text(json.dumps({'embedder_socket': str(tmp_path / 'none.sock')}))
    request = {'ship': 'rio-grande', 'command': 'git show 1a2b', 'words_only': True, 'place': SECRET}
    done = run_lessons('query', '--data-dir', store.data_dir, '--runtime-config', config, stdin=json.dumps(request))
    assert places(store) == [] and SECRET not in done.stdout + done.stderr
