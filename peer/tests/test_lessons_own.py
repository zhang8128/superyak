"""Own lessons, once a context window (docs/superpowers/specs/2026-11-09-own-lessons-on-the-rail-design.md), the peer's
side: the request's `own`, `window_seen` and `reask`, the answer's `own`, a receipt for a first reach only, and the
`reask` column. An old hook's request (no `window_seen`) gets main's answer byte for byte, and main's read_request drops
the new keys: both are checked against main's own lessons.py, read from git at MAIN."""
import itertools
import json
import math
import re
import sqlite3
import subprocess
import types
from contextlib import closing
from pathlib import Path
import pytest
from superyak_peer import lessons
from superyak_peer.common import Problem, uid
from conftest import LESSON_TIME, lesson_body

REPO = Path(__file__).resolve().parents[2]
MAIN = '7d80c067aed8fab886d19388e0020be99b46fed0'   # main when this branch began: the lessons.py an old peer runs
DUMMY = 'a' * 64 + ':' + 'b' * 64   # a full id for an entry built outside any store
FAILURE = {'command': 'grep --include=*.py x', 'error': 'zsh: no matches found'}
GLOB = lesson_body(claim='Quote a glob in zsh.', command=('--include=*',))   # tardis's
LATER = lesson_body(claim='A later word on the glob.', command=('--include=*',), why='Laid between two windows.')
MINE = lesson_body(ship='rio-grande', claim='Run make check before a push.', command=('make check',), why='A push failed CI.')


def lay(store, ids, room, *bodies, socket=None):
    for body in bodies:
        store.send_message(ids[lessons.parse_post(body).ship], room, f'c{uid()}', body)
    store.lessons_index(socket)


def full_id(store, body):
    return lessons.lesson_id(store._own_peer_id(), lessons.parse_post(body))


def short_id(store, body):
    return lessons.short_lesson_id(full_id(store, body))


def ask(store, clock, socket=None, ship='rio-grande', **fields):
    """The query as the hook runs it, at a failure or a session start; with `prompt`, the prompt path (index age 0)."""
    request = lessons.read_request(json.dumps({'ship': ship, **fields}))
    return lessons.query(request, store.data_dir, socket, clock=lambda: clock[0], monotonic=lambda: 0.0)[0]


def receipted(store):
    """The lesson ids receipted, in the order written."""
    with store.transaction() as db:
        return [r[0] for r in db.execute('SELECT lesson_id FROM lesson_receipts ORDER BY rowid')]


def query_rows(store):
    with store.transaction() as db:
        return [tuple(r) for r in db.execute('SELECT shown, reask FROM lesson_queries ORDER BY id')]


def size(answer):
    return len(lessons.dumps(answer).encode('utf-8'))


def entry(store, body, command, receipt=None):
    """The answer's entry for a laid lesson, built from the index as the query builds it."""
    index = lessons.read_index(store.data_dir / lessons.INDEX_FILE)
    item = next(i for i in index['lessons'] if i['id'] == full_id(store, body))
    return lessons.shown(item, 'words', command, receipt)


@pytest.fixture(scope='module')
def on_main():
    """main's lessons.py at MAIN, loaded beside this tree's as a module of its own package, so its relative imports
    resolve here. Skipped where the clone has no such commit (CI checks out one commit)."""
    try:
        source = subprocess.run(['git', '-C', str(REPO), 'show', f'{MAIN}:peer/superyak_peer/lessons.py'],
                                capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip(f"main's lessons.py at {MAIN[:8]} isn't in this clone")
    module = types.ModuleType('superyak_peer.lessons_on_main')
    module.__package__ = 'superyak_peer'
    exec(compile(source, f'{MAIN[:8]}:peer/superyak_peer/lessons.py', 'exec'), module.__dict__)
    return module


def test_a_reminder_writes_no_receipt(lessons_station):
    """A lesson in the session's `seen` but not in this window's is answered again, as a reminder: no `receipt` key, no
    receipt row, and the query row's `shown` counts first reaches only. One in `window_seen` isn't answered."""
    store, clock, ids, room = lessons_station
    lay(store, ids, room, GLOB)
    first = ask(store, clock, **FAILURE)['lessons']
    assert [list(e) for e in first] == [['id', 'ship', 'claim', 'why', 'match', 'command', 'receipt']]
    lesson = first[0]['id']
    again = ask(store, clock, **FAILURE, seen=[lesson], window_seen=[])['lessons']
    assert again == [{k: v for k, v in first[0].items() if k != 'receipt'}]
    assert receipted(store) == [full_id(store, GLOB)] and query_rows(store) == [(1, 0), (0, 0)]
    assert ask(store, clock, **FAILURE, seen=[lesson], window_seen=[lesson]) == {'lessons': []}
    assert receipted(store) == [full_id(store, GLOB)]


def test_a_reask_answers_reminders_only(lessons_station, fake_embedder):
    """A re-asked failure (`reask`) answers only ids already in `seen`, own lessons too: no receipt, no first reach,
    and no Near (Near runs over first reaches only). Its row is marked reask=1 and every count leaves it out. A lesson
    laid between the windows reaches the ship at the next new failure or the next prompt that matches it."""
    store, clock, ids, room = lessons_station
    lay(store, ids, room, GLOB, MINE, socket=fake_embedder.path)
    glob, mine = short_id(store, GLOB), short_id(store, MINE)
    failure = {'command': 'grep --include=*.py x && make check', 'error': 'zsh: no matches found'}
    assert [e['id'] for e in ask(store, clock, fake_embedder.path, **failure)['lessons']] == [glob]
    lay(store, ids, room, LATER, socket=fake_embedder.path)   # another ship's lesson, laid after the first window
    counts, asked = store.lesson_outcomes()[1], len(fake_embedder.requests)
    got = ask(store, clock, fake_embedder.path, **failure, seen=[glob], window_seen=[], reask=True, own=True)
    assert got == {'lessons': [entry(store, GLOB, '--include=*')]}   # a reminder; LATER and MINE aren't in seen
    both = ask(store, clock, fake_embedder.path, **failure, seen=[glob, mine], window_seen=[], reask=True, own=True)
    assert [e['id'] for e in both['lessons']] == [glob] and [e['id'] for e in both['own']] == [mine]
    assert all('receipt' not in e for e in both['lessons'] + both['own'])
    assert ask(store, clock, fake_embedder.path, **failure, reask=True, own=True) == {'lessons': []}
    assert len(fake_embedder.requests) == asked   # no Near at a re-ask
    assert receipted(store) == [full_id(store, GLOB)] and query_rows(store) == [(1, 0), (0, 1), (0, 1), (0, 1)]
    assert store.lesson_outcomes()[1] == counts   # the queries count leaves reask rows out
    later = ask(store, clock, fake_embedder.path, **failure, seen=[glob], window_seen=[glob])['lessons']
    assert [e['claim'] for e in later] == ['A later word on the glob.'] and 'receipt' in later[0]
    assert store.lesson_outcomes()[1]['queries'] == counts['queries'] + 1
    prompt = ask(store, clock, prompt='why does grep --include=*.py say no matches', window_seen=[glob])
    assert [e['claim'] for e in prompt['lessons']] == ['A later word on the glob.']
    with pytest.raises(ValueError, match='reask'):   # a failure's key alone: never at a prompt
        lessons.read_request(json.dumps({'ship': 'rio-grande', 'prompt': 'why', 'reask': True}))


def test_first_reaches_come_first(lessons_station):
    """Three slots, two reminders and two first reaches matching: both first reaches, with receipts, then one reminder,
    though the reminders match on two values each and today's order would put them first. The same within the fit:
    a first reach of about 1,050 bytes stays, where reminders first would have pushed it out."""
    store, clock, ids, room = lessons_station
    two = {'command': ('--include=*',), 'error': ('no matches found',)}
    reminders = [lesson_body(claim=f'Reminder {n}.', **two) for n in (1, 2)]
    firsts = [lesson_body(claim=f'First {n}.', command=('--include=*',)) for n in (1, 2)]
    lay(store, ids, room, *reminders, *firsts)
    seen = [short_id(store, body) for body in reminders]
    got = ask(store, clock, **FAILURE, seen=seen, window_seen=[])['lessons']
    assert sorted(e['claim'] for e in got[:2]) == ['First 1.', 'First 2.'] and len(got) == 3
    assert got[2]['claim'] in ('Reminder 1.', 'Reminder 2.') and ['receipt' in e for e in got] == [True, True, False]
    assert sorted(receipted(store)) == sorted(full_id(store, b) for b in firsts) and query_rows(store) == [(2, 0)]
    old = ask(store, clock, **FAILURE, seen=seen)['lessons']   # no window_seen: every id in seen is skipped, as on main
    assert sorted(e['claim'] for e in old) == ['First 1.', 'First 2.']

    wide = {'command': ('--exclude=*',), 'error': ('no such file',)}
    big = lesson_body(claim='"' * 160, why='"' * 300, command=('--exclude=*',))
    smalls = [lesson_body(claim=f'Small {n}.', why='"' * 200, **wide) for n in (1, 2)]
    lay(store, ids, room, big, *smalls)
    seen = [short_id(store, body) for body in smalls]
    before = len(receipted(store))
    got = ask(store, clock, command='grep --exclude=*.py x', error='no such file', seen=seen, window_seen=[])
    assert [e['claim'] for e in got['lessons']][0] == '"' * 160 and 'receipt' in got['lessons'][0]
    assert len(got['lessons']) == 2 and 'receipt' not in got['lessons'][1] and size(got) <= lessons.ANSWER_BYTES
    assert receipted(store)[before:] == [full_id(store, big)]
    reminders_first = [entry(store, s, '--exclude=*') for s in smalls] + [entry(store, big, '--exclude=*', 'f' * 8)]
    assert lessons.fit(reminders_first)['lessons'] == reminders_first[:2]   # the order this rule replaces loses it


@pytest.fixture
def old_hook_world(lessons_station, fake_embedder):
    """Lessons for every path an old hook takes: words of each kind, Near at a failure and at a prompt, the asking
    ship's own lessons, one learned from it, two that hold or don't before a command, and three past 2,000 bytes."""
    store, clock, ids, room = lessons_station
    bodies = [GLOB, MINE,
              lesson_body(claim='No matches.', error=('no matches found',), command=('qqqq',)),
              lesson_body(claim='In the peer.', command=('pytest -x',), file=('superyak/peer',)),
              lesson_body(claim='Near.', command=('zzzz-never',)),
              lesson_body(claim='Taught.', command=('--include=*',), learned='rio-grande'),
              lesson_body(claim='Short values.', command=('git', 'push')),
              lesson_body(claim='Long value.', command=('push --force',)),
              lesson_body(ship='rio-grande', claim='My glob.', command=('--include=*',))]
    bodies += [lesson_body(claim=f'{n}' + '"' * 159, why='"' * 300, command=('--big=*',)) for n in range(3)]
    for body in bodies:
        fake_embedder.vectors[lessons.embedded_text(lessons.parse_post(body))] = [0.0, 1.0, 0.0, 0.0]
    fake_embedder.vectors[lessons.embedded_text(lessons.parse_post(bodies[4]))] = [1.0, 0.0, 0.0, 0.0]
    close = [0.9, math.sqrt(1 - 0.81), 0.0, 0.0]   # 25.8 degrees from Near, 64 from the rest
    fake_embedder.vectors['cargo build\nlinker not found'] = close
    fake_embedder.vectors['tell me about the never thing please'] = close
    lay(store, ids, room, *bodies, socket=fake_embedder.path)
    return store, clock, fake_embedder, short_id(store, GLOB)


def old_hook_requests(glob):
    where = {'cwd': '/home/andy/superyak/peer', 'branch': 'main'}
    return [{'ship': 'rio-grande', **FAILURE, **where, 'limit': 3, 'budget_ms': 2000},
            {'ship': 'rio-grande', **FAILURE, **where, 'limit': 3, 'seen': [glob]},
            {'ship': 'rio-grande', **FAILURE, 'limit': 1},
            {'ship': 'rio-grande', 'command': 'git push --force origin main', 'words_only': True, 'limit': 3},
            {'ship': 'rio-grande', **where},
            {'ship': 'rio-grande', 'command': 'cargo build', 'error': 'linker not found', 'limit': 3},
            {'ship': 'rio-grande', 'command': 'cat --big=*', 'limit': 3},
            {'ship': 'tardis', 'command': 'make check && grep --include=*.py x', 'error': 'Error 2'},
            {'ship': 'rio-grande', 'prompt': 'why does grep --include=* say no matches found', 'limit': 2},
            {'ship': 'rio-grande', 'prompt': 'why does grep --include=* say no matches found', 'seen': [glob]},
            {'ship': 'rio-grande', 'prompt': 'tell me about the never thing please', 'limit': 2},
            {'ship': 'tardis', 'prompt': 'should I run make check first'}]


def answered(module, store, clock, socket, raw, monkeypatch):
    """One request through `module`'s read_request and query, with receipt ids drawn 1, 2, 3...: (the answer's bytes,
    the note, the receipts and query rows written, each row's reask or None). The rows are removed after, so each run
    starts from the same store."""
    from superyak_peer.db import Store
    drawn = (f'{n:032x}' for n in itertools.count(1))
    with monkeypatch.context() as patch:
        patch.setattr(module, 'uid', lambda: next(drawn))
        if module is not lessons:   # main's step 4, in the store main's query opens
            patch.setattr(Store, '_lessons_answer', module.Lessons._lessons_answer)
        answer, note = module.query(module.read_request(raw), store.data_dir, socket, clock=lambda: clock[0],
                                    monotonic=lambda: 0.0)
    with store.transaction() as db:
        receipts = [tuple(r) for r in db.execute('SELECT * FROM lesson_receipts ORDER BY rowid')]
        rows = [tuple(r) for r in db.execute('SELECT created, ship_id, nearest, shown FROM lesson_queries ORDER BY id')]
        marks = [r[0] for r in db.execute('SELECT reask FROM lesson_queries ORDER BY id')]
        db.execute('DELETE FROM lesson_receipts')
        db.execute('DELETE FROM lesson_queries')
    return module.dumps(answer).encode('utf-8'), note, receipts, rows, marks


def test_no_window_seen_is_mains_answer(old_hook_world, on_main, monkeypatch):
    """Review focus 5, an old hook with this peer: each request an old hook sends, with no `window_seen`, `own` or
    `reask`, gets main's answer byte for byte, main's note, and main's receipts and query rows, each row unmarked."""
    store, clock, fake, glob = old_hook_world
    answers = []
    for request in old_hook_requests(glob):
        raw = json.dumps(request)
        mains = answered(on_main, store, clock, fake.path, raw, monkeypatch)
        ours = answered(lessons, store, clock, fake.path, raw, monkeypatch)
        assert ours[:4] == mains[:4], request
        assert ours[4] == [0] * len(ours[3]), request
        answers.append(json.loads(mains[0]))
    matches = [e['match'] for answer in answers for e in answer['lessons']]
    assert all(answer['lessons'] for answer in answers) and 'words' in matches   # no comparison was of empty answers
    assert any(isinstance(m, float) for m in matches)   # Near ran, at a failure and at a prompt


def test_own_by_author_id(lessons_peers):
    """An own lesson is decided by author id: answered under `own`, last, with no receipt, and the query row's `shown`
    counts the others' first reaches only. A remote member's lesson whose text says `ship: rio-grande` is another
    ship's to rio-grande here, at a failure and at a prompt, and never in its `own`."""
    pi, pi_fed, pids = lessons_peers['peers']['pi']
    tardis, tardis_fed, tids = lessons_peers['peers']['tardis']
    clock, room = lessons_peers['clock'], lessons_peers['room']
    trick = lesson_body(ship='rio-grande', claim='Not mine, whatever it says.', command=('make check',))
    pi.send_message(pids['rio-grande'], room, 'p1', MINE)
    with pi.transaction() as db:   # as the origin's reply door stores a remote member's post (peer_messages)
        who = db.execute('SELECT peer_id, user_id FROM remote_contacts WHERE id=?', (pids['contact'],)).fetchone()
        epoch = db.execute('SELECT epoch FROM rooms WHERE id=?', (room,)).fetchone()[0]
        db.execute('INSERT INTO peer_messages VALUES(?,?,?,?,?,?,?)', (uid(), room, f"{who['peer_id']}:{who['user_id']}",
                                                                        't1', trick, epoch, clock[0]))
    pi.lessons_index(None)
    index = lessons.read_index(pi.data_dir / lessons.INDEX_FILE)
    assert sorted(i['ship'] for i in index['lessons']) == ['rio-grande', 'rio-grande'] and len(index['ships']) == 1
    theirs = lessons.lesson_id(tardis_fed.identity.peer_id, lessons.parse_post(trick))
    got = ask(pi, clock, command='make check', error='Error 2', own=True)
    assert list(got) == ['lessons', 'own']
    assert [(e['claim'], 'receipt' in e) for e in got['lessons']] == [('Not mine, whatever it says.', True)]
    assert got['own'] == [entry(pi, MINE, 'make check')] and list(got['own'][0]) == ['id', 'ship', 'claim', 'why',
                                                                                     'match', 'command']
    assert receipted(pi) == [theirs] and query_rows(pi) == [(1, 0)]
    at_prompt = ask(pi, clock, prompt='why does make check fail here', own=True)
    assert [e['claim'] for e in at_prompt['lessons']] == ['Not mine, whatever it says.']
    assert [e['claim'] for e in at_prompt['own']] == ['Run make check before a push.']
    assert all('receipt' not in e for e in at_prompt['lessons'] + at_prompt['own']) and receipted(pi) == [theirs]
    assert list(ask(pi, clock, command='make check', error='Error 2')) == ['lessons']   # not asked for: no `own` key


def test_words_only_never_gets_own(lessons_station):
    """Before a command (`words_only`) the peer never answers own lessons, whatever the request says, and could_hold
    still never holds on one."""
    store, clock, ids, room = lessons_station
    push = lesson_body(ship='rio-grande', claim='Never force a push to main.', command=('push --force',))
    lay(store, ids, room, push)
    command = 'git push --force origin main'
    assert ask(store, clock, command=command, words_only=True, own=True) == {'lessons': []}
    assert lessons.could_hold(command, 'rio-grande', store.data_dir) is False
    assert [e['claim'] for e in ask(store, clock, command=command, own=True)['own']] == ['Never force a push to main.']
    assert receipted(store) == []


def test_fitting_edges(lessons_station):
    """The fit runs on the exact bytes of `dumps`, with the `own` key in them only when it isn't empty. Three receipted
    lessons whose answer is 1,990 bytes, with own lessons matching: no `own` key, all three shown, a receipt for each of
    them and for nothing else. One other lesson and own lessons past 2,000 bytes: the other stays, own entries go."""
    store, clock, ids, room = lessons_station
    two = {'command': ('--include=*',), 'error': ('no matches found',)}
    pads = [lesson_body(claim='"' * 40 + f' {n}', why='"' * 300, **two) for n in (1, 2)]
    synthetic = lambda claim, why, receipt='f' * 8: lessons.shown({'id': DUMMY, 'ship': 'tardis', 'claim': claim,
                                                                    'why': why}, 'words', '--include=*', receipt)
    parsed = [lessons.parse_post(p) for p in pads]
    width = 1990 - size({'lessons': [synthetic(p.claim, p.why) for p in parsed] + [synthetic('Third.', '')]})
    assert 1 <= width <= 300
    third = lesson_body(claim='Third.', why='w' * width, **two)
    mine = [lesson_body(ship='rio-grande', claim=f'Mine {n}.', command=('--include=*',)) for n in (1, 2)]
    lay(store, ids, room, *pads, third, *mine)
    got = ask(store, clock, **FAILURE, own=True)
    assert list(got) == ['lessons'] and size(got) == 1990 and all('receipt' in e for e in got['lessons'])
    assert sorted(e['claim'] for e in got['lessons']) == sorted(lessons.parse_post(b).claim for b in pads + [third])
    assert sorted(receipted(store)) == sorted(full_id(store, b) for b in pads + [third])
    small = entry(store, mine[0], '--include=*')
    assert lessons.fit(got['lessons'], [small]) == {'lessons': got['lessons']}   # the key's bytes count: no room
    assert lessons.fit([], []) == {'lessons': []} and lessons.fit(got['lessons']) == {'lessons': got['lessons']}
    one = got['lessons'][:1]
    padded = lambda n: lessons.shown({'id': DUMMY, 'ship': 'rio-grande', 'claim': 'Mine.', 'why': 'w' * n}, 'words', 'x')
    exact = 2000 - size({'lessons': one, 'own': [padded(0)]})
    assert lessons.fit(one, [padded(exact)]) == {'lessons': one, 'own': [padded(exact)]}   # 2,000 bytes exactly
    assert lessons.fit(one, [padded(exact + 1)]) == {'lessons': one}

    other = lesson_body(claim='"' * 100, why='"' * 300, command=('--exclude=*',))
    owns = [lesson_body(ship='rio-grande', claim=f'Own {n}.', why='"' * 300, command=('--exclude=*',)) for n in (1, 2)]
    lay(store, ids, room, other, *owns)
    everything = {'lessons': [entry(store, other, '--exclude=*', 'f' * 8)],
                  'own': [entry(store, body, '--exclude=*') for body in owns]}
    assert size(everything) > lessons.ANSWER_BYTES
    before = len(receipted(store))
    got = ask(store, clock, command='grep --exclude=*.py x', own=True)
    assert [(e['claim'], 'receipt' in e) for e in got['lessons']] == [('"' * 100, True)]
    assert len(got['own']) == 1 and got['own'][0]['claim'] in ('Own 1.', 'Own 2.') and size(got) <= lessons.ANSWER_BYTES
    assert receipted(store)[before:] == [full_id(store, other)]


def test_per_event_rules(lessons_station):
    """An own lesson matches by the rule its event uses for others': at a failure or a session start every value, so a
    4-byte `command` value matches; at a prompt only a value of at least 6 bytes."""
    store, clock, ids, room = lessons_station
    four = lesson_body(ship='rio-grande', claim='Four bytes.', command=('make',))
    lay(store, ids, room, four)
    failure = ask(store, clock, command='make check', error='Error 2', own=True)
    assert failure == {'lessons': [], 'own': [entry(store, four, 'make')]}
    question = 'why does make check fail on the Pi'
    assert ask(store, clock, prompt=question, own=True) == {'lessons': []}
    ten = lesson_body(ship='rio-grande', claim='Ten bytes.', command=('make check',))
    lay(store, ids, room, ten)
    assert ask(store, clock, prompt=question, own=True) == {'lessons': [], 'own': [entry(store, ten, 'make check')]}
    # A session start runs words() itself: `make` only in the cwd is no match, since a command value matches the command
    assert ask(store, clock, cwd='/home/andy/make', branch='main', own=True) == {'lessons': []}
    assert ask(store, clock, prompt=question, own=True, window_seen=[short_id(store, ten)]) == {'lessons': []}


def test_retracted_own_lesson_is_not_shown(lessons_station):
    """At a failure an own lesson goes through step 4's live check, as others' do: retracted since the index ran, it
    isn't shown."""
    store, clock, ids, room = lessons_station
    lay(store, ids, room, MINE)
    assert [e['claim'] for e in ask(store, clock, command='make check', own=True)['own']] == ['Run make check before a push.']
    store.send_message(ids['rio-grande'], room, 'r1', 'retract ' + full_id(store, MINE))
    index = lessons.read_index(store.data_dir / lessons.INDEX_FILE)
    assert [i['id'] for i in index['lessons']] == [full_id(store, MINE)]   # no index run since: the index still has it
    assert ask(store, clock, command='make check', own=True) == {'lessons': []}


MAIN_QUERIES = ('CREATE TABLE lesson_queries(id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL NOT NULL, '
                'ship_id TEXT NOT NULL REFERENCES users(id), nearest REAL, shown INTEGER NOT NULL)')   # main's, as it stood


def test_reask_column_added_to_an_old_store(tmp_path):
    """A store whose lesson_queries has main's columns gains `reask INTEGER NOT NULL DEFAULT 0` when it opens, its rows
    keep 0 and count as queries, and a store made new has the same columns in the same order."""
    from superyak_peer.db import Store
    store = Store(tmp_path / 'old', clock=lambda: LESSON_TIME)
    ship = store.create_user('andy', 'Andy Example', 'a-long-password', is_admin=True)['id']
    with closing(sqlite3.connect(store.db_path)) as db, db:
        db.execute('DROP TABLE lesson_queries')
        db.execute(MAIN_QUERIES)
        db.execute('INSERT INTO lesson_queries(created, ship_id, nearest, shown) VALUES(?,?,NULL,1)', (LESSON_TIME, ship))
    reopened = Store(tmp_path / 'old', clock=lambda: LESSON_TIME)
    with reopened.transaction() as db:
        columns = [dict(r) for r in db.execute('PRAGMA table_info(lesson_queries)')]
        assert [tuple(r) for r in db.execute('SELECT shown, reask FROM lesson_queries')] == [(1, 0)]
    assert {k: columns[-1][k] for k in ('name', 'type', 'notnull', 'dflt_value')} == {
        'name': 'reask', 'type': 'INTEGER', 'notnull': 1, 'dflt_value': '0'}
    assert reopened.lesson_outcomes()[1]['queries'] == 1
    with Store(tmp_path / 'new').transaction() as db:
        assert [dict(r) for r in db.execute('PRAGMA table_info(lesson_queries)')] == columns


def test_one_outcome_a_session_after_a_reshow(lessons_station):
    """A re-shown lesson carries no receipt, so the ship's one outcome for it, against its first receipt, stays one:
    a second is refused by the rule that already refuses it."""
    store, clock, ids, room = lessons_station
    lay(store, ids, room, GLOB)
    first = ask(store, clock, **FAILURE)['lessons'][0]
    store.lesson_outcome(first['receipt'], 'helped')
    again = ask(store, clock, **FAILURE, seen=[first['id']], window_seen=[])['lessons']
    assert [e['id'] for e in again] == [first['id']] and 'receipt' not in again[0] and len(receipted(store)) == 1
    with pytest.raises(Problem, match=re.escape(lessons.OUTCOME_TWICE)):
        store.lesson_outcome(first['receipt'], 'misled')
    assert store.lesson_outcomes()[1]['outcomes'] == 1


def test_old_peer_drops_new_keys(on_main):
    """The claim the spec rests on: main's read_request drops the keys it doesn't know, so an old peer given a new
    hook's request parses it as it parsed the request without them, and none of them reaches the query."""
    new = {'own': True, 'window_seen': [], 'reask': True}
    shown = 'aaaaaaaa-bbbbbbbb'
    for base in ({'ship': 'rio-grande', **FAILURE, 'seen': [shown]}, {'ship': 'rio-grande', 'cwd': '/home/andy'},
                 {'ship': 'rio-grande', 'command': 'git push', 'words_only': True, 'seen': [shown]},
                 {'ship': 'rio-grande', 'prompt': 'why does make check fail', 'seen': [shown]}):
        parsed = on_main.read_request(json.dumps({**base, **new}))
        assert parsed == on_main.read_request(json.dumps(base)) and not set(new) & set(parsed)


def test_the_new_keys_are_checked():
    """`window_seen` is checked as `seen` is (short ids, at most SEEN_MAX) and stands for `seen` when absent; `own` and
    `reask` are booleans, false by default; `reask` comes only without a prompt. Before a command there is no reminder
    and no own lesson, so `window_seen` is `seen` there whatever was sent (could_hold reads `seen` alone)."""
    read = lambda **fields: lessons.read_request(json.dumps({'ship': 'rio-grande', **fields}))
    shown, other = 'aaaaaaaa-bbbbbbbb', 'cccccccc-dddddddd'
    got = read(command='make', seen=[shown])
    assert (got['window_seen'], got['own'], got['reask']) == ({shown}, False, False)
    got = read(command='make', seen=[shown], window_seen=[other], own=True, reask=True)
    assert (got['seen'], got['window_seen'], got['own'], got['reask']) == ({shown}, {other}, True, True)
    got = read(prompt='why', window_seen=[other], own=True)
    assert (got['seen'], got['window_seen'], got['own'], got['reask']) == (set(), {other}, True, False)
    got = read(command='make', seen=[shown], window_seen=[other], own=True, words_only=True)
    assert (got['window_seen'], got['own']) == ({shown}, False)
    for fields, key in [({'window_seen': ['x']}, 'window_seen'), ({'window_seen': shown}, 'window_seen'),
                        ({'window_seen': [shown] * (lessons.SEEN_MAX + 1)}, 'window_seen'),
                        ({'own': 1}, 'own'), ({'own': 'true'}, 'own'), ({'reask': 1}, 'reask'),
                        ({'prompt': 'why', 'reask': True}, 'reask'), ({'prompt': 'why', 'own': None}, 'own')]:
        with pytest.raises(ValueError, match=key):
            read(**fields)
    assert read(prompt='why', reask=False)['reask'] is False
    assert lessons.new_keys({'seen': {shown}}) == ({shown}, False, False)   # a request built in process, as before
