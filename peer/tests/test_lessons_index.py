"""First rail, the reading side: the index (section 4), the query and its agreed output (section 5), the prompt path,
receipts and segments (sections 5 and 7), and unread leaving the lessons room out (section 3)."""
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import pytest
from superyak_peer import lessons
from conftest import LESSON_TIME, lesson_body, run_lessons


def embedded(**fields):
    return lessons.embedded_text(lessons.parse_post(lesson_body(**fields)))


def watch_transactions(store, fake):
    """Every station transaction sets the fake embedder's flag while it is open, so a request inside one shows."""
    opened = store.transaction

    @contextmanager
    def flagged():
        with opened() as db:
            fake.in_transaction.set()
            try:
                yield db
            finally:
                fake.in_transaction.clear()
    store.transaction = flagged


def ask(store, clock, socket=None, **fields):
    request = lessons.read_request(json.dumps({'ship': 'rio-grande', **fields}))
    return lessons.query(request, store.data_dir, socket, clock=lambda: clock[0], monotonic=lambda: 0.0)


# Task 8: the index
def test_the_index_run_keeps_its_watermark_mtime_and_adds_vectors_later(lessons_station, fake_embedder):
    store, clock, ids, room = lessons_station
    watch_transactions(store, fake_embedder)
    store.send_message(ids['tardis'], room, 'c1', lesson_body())
    path = store.data_dir / lessons.INDEX_FILE
    assert store.lessons_index(None) == {'status': 'written', 'lessons': 1, 'vectors': 0}
    assert os.stat(path).st_mtime == LESSON_TIME and (os.stat(path).st_mode & 0o777) == 0o600
    index = lessons.read_index(path)
    assert index['lessons'][0]['vector'] is None and index['complete'] is False and index['dimension'] is None
    clock[0] += 60
    assert store.lessons_index(None)['status'] == 'unchanged' and os.stat(path).st_mtime == LESSON_TIME + 60
    clock[0] += 60
    assert store.lessons_index(fake_embedder.path) == {'status': 'written', 'lessons': 1, 'vectors': 1}
    assert lessons.read_index(path)['complete'] is True
    clock[0] += 60
    assert store.lessons_index(fake_embedder.path)['status'] == 'unchanged'
    embeds = [r for r in fake_embedder.requests if r['op'] == 'embed']
    assert len(embeds) == 1 and embeds[0]['prefix'] == 'search_document'
    assert embeds[0]['texts'] == [embedded()]
    assert not any(r['in_transaction'] for r in fake_embedder.requests)


def test_the_index_embeds_8_at_a_time_and_a_new_model_rebuilds_every_vector(lessons_station, fake_embedder):
    store, clock, ids, room = lessons_station
    for n in range(20):
        clock[0] += 3
        store.send_message(ids['tardis'], room, f'c{n}', lesson_body(claim=f'Claim {n}.'))
    store.lessons_index(fake_embedder.path)
    assert [len(r['texts']) for r in fake_embedder.requests if r['op'] == 'embed'] == [8, 8, 4]
    fake_embedder.model, fake_embedder.requests[:] = 'another-model', []
    clock[0] += 60
    assert store.lessons_index(fake_embedder.path)['vectors'] == 20
    assert lessons.read_index(store.data_dir / lessons.INDEX_FILE)['model'] == 'another-model'


def test_a_damaged_index_is_rebuilt_and_only_member_ships_are_listed(lessons_station):
    store, clock, ids, room = lessons_station
    path = store.data_dir / lessons.INDEX_FILE
    path.write_bytes(lessons.INDEX_MAGIC + b'\x00\x00\x00\x09{"lessons"')
    with pytest.raises(lessons.IndexUnreadable):
        lessons.read_index(path)
    assert store.lessons_index(None)['status'] == 'written'
    assert sorted(lessons.read_index(path)['ships']) == ['rio-grande', 'tardis']   # andy is a member, not a ship


def test_the_index_verb_without_a_room(tmp_path):
    from superyak_peer.db import Store
    Store(tmp_path / 'p', clock=lambda: LESSON_TIME)
    done = run_lessons('index', '--data-dir', tmp_path / 'p', '--runtime-config', tmp_path / 'none.json')
    assert done.returncode == 0 and json.loads(done.stdout) == {'status': 'no lessons room'}


# Group B fix round: the index file's time and a stale temporary file
def test_the_live_index_never_shows_a_time_fresher_than_step_1s_read(lessons_station, monkeypatch):
    """The temporary file gets step 1's read time before it is renamed over the live one, so the moment the rename lands,
    the live file already shows that time: no reader sees the write time, which would make the index look fresher than
    the chain it was built from. The clock is pinned at LESSON_TIME, years from the real time the write happens at."""
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body())
    path, renamed, seen = store.data_dir / lessons.INDEX_FILE, os.replace, []

    def replace(source, target):
        seen.append(('before', os.stat(source).st_mtime))
        renamed(source, target)
        seen.append(('after', os.stat(target).st_mtime))   # the first moment a reader can open the new file
    monkeypatch.setattr(lessons.os, 'replace', replace)
    assert store.lessons_index(None)['status'] == 'written'
    assert seen == [('before', LESSON_TIME), ('after', LESSON_TIME)]
    assert os.stat(path).st_mtime == LESSON_TIME


def test_a_stale_temporary_file_with_this_pids_name_doesnt_stop_the_run(lessons_station):
    """A run killed between its open and its rename leaves `.lessons-index.bin.<pid>.tmp`. A later run that gets the same
    pid removes it (the name is that pid's own) instead of failing on the exclusive open."""
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body())
    stale = store.data_dir / f'.{lessons.INDEX_FILE}.{os.getpid()}.tmp'
    stale.write_bytes(b'half an index')
    assert store.lessons_index(None) == {'status': 'written', 'lessons': 1, 'vectors': 0}
    assert not stale.exists() and len(lessons.read_index(store.data_dir / lessons.INDEX_FILE)['lessons']) == 1


# Task 10: the prompt path
def prompt(store, clock, text, socket=None, ship='rio-grande', seen=(), age=10, limit=3, budget=None):
    fields = {'ship': ship, 'prompt': text, 'seen': list(seen), 'limit': limit, **({} if budget is None else {'budget_ms': budget})}
    return lessons.answer_prompt(lessons.read_request(json.dumps(fields)), store.data_dir, socket, clock=lambda: clock[0] + age,
                                 monotonic=lambda: 0.0)


def test_at_a_prompt_6_byte_values_by_words_and_near_within_r_prompt(lessons_station, fake_embedder):
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim='Words.', error=('no matches found',), command=('ls',)))
    store.send_message(ids['tardis'], room, 'c2', lesson_body(claim='Near.', command=('zzzz-never',)))
    store.send_message(ids['tardis'], room, 'c3', lesson_body(claim='Far.', command=('yyyy-never',)))
    fake_embedder.vectors[embedded(claim='Near.', command=('zzzz-never',))] = [1.0, 0.0, 0.0, 0.0]
    fake_embedder.vectors[embedded(claim='Far.', command=('yyyy-never',))] = [0.0, 1.0, 0.0, 0.0]
    question = 'why does ls say no matches found'
    fake_embedder.vectors[question] = [0.8, 0.6, 0.0, 0.0]   # cos 0.8 to Near (inside r_prompt), 0.6 to Far (outside)
    store.lessons_index(fake_embedder.path)
    got = prompt(store, clock, question, fake_embedder.path)
    assert [(e['claim'], e['match']) for e in got['lessons']] == [('Words.', 'words'), ('Near.', round(math.acos(0.8), 4))]
    assert prompt(store, clock, 'ls', fake_embedder.path) == {'lessons': []}   # 'ls' is under 6 bytes
    assert prompt(store, clock, 'zzzz', fake_embedder.path) == {'lessons': []}   # under 4 words: no Near
    asked = len(fake_embedder.requests)
    assert prompt(store, clock, question, fake_embedder.path, budget=0) == {'lessons': []}   # the hook has no time left
    assert len(fake_embedder.requests) == asked
    with store.transaction() as db:
        assert db.execute('SELECT count(*) FROM lesson_receipts').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM lesson_queries').fetchone()[0] == 0


def test_at_a_prompt_a_budget_spent_during_near_leaves_words_and_the_socket_waits_no_longer(lessons_station, fake_embedder, monkeypatch):
    """Tardis's condition for the in-process path: the embedder's socket timeout is what the budget leaves, since a
    blocked socket can't be interrupted in process; a budget spent during Near answers words only."""
    import socket
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim='Words.', error=('no matches found',)))
    store.lessons_index(fake_embedder.path)
    timeouts, settimeout = [], socket.socket.settimeout
    monkeypatch.setattr(socket.socket, 'settimeout', lambda sock, value: (timeouts.append(value), settimeout(sock, value))[1])
    fake_embedder.delay = 0.5   # it answers long after the 50 ms the hook has left
    got = prompt(store, clock, 'why does it say no matches found', fake_embedder.path, budget=50)
    assert [e['match'] for e in got['lessons']] == ['words'] and timeouts and max(timeouts) <= 0.05


def test_where_the_switch_is_off_near_never_runs_at_a_prompt(lessons_station, fake_embedder):
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim='Near.', command=('zzzz-never',)))
    fake_embedder.vectors[embedded(claim='Near.', command=('zzzz-never',))] = [1.0, 0.0, 0.0, 0.0]
    fake_embedder.vectors['tell me about the never thing'] = [1.0, 0.0, 0.0, 0.0]
    store.lessons_index(fake_embedder.path)
    assert [e['claim'] for e in prompt(store, clock, 'tell me about the never thing', fake_embedder.path)['lessons']] == ['Near.']
    (store.data_dir / lessons.PROMPT_NEAR_OFF).touch()
    asked = len(fake_embedder.requests)
    assert prompt(store, clock, 'tell me about the never thing', fake_embedder.path) == {'lessons': []}
    assert len(fake_embedder.requests) == asked


def test_at_a_prompt_at_most_2_and_nothing_from_a_stale_or_missing_index(lessons_station):
    store, clock, ids, room = lessons_station
    assert prompt(store, clock, 'no matches found at all') == {'lessons': []}   # no index yet
    for n in range(3):
        store.send_message(ids['tardis'], room, f'c{n}', lesson_body(claim=f'Claim {n}.', error=('no matches found',)))
    store.lessons_index(None)
    assert len(prompt(store, clock, 'no matches found at all')['lessons']) == 2   # limit 3 can't raise the prompt's 2
    assert len(prompt(store, clock, 'no matches found at all', limit=1)['lessons']) == 1
    assert prompt(store, clock, 'no matches found at all', limit=0) == {'lessons': []}
    assert prompt(store, clock, 'no matches found at all', age=181) == {'lessons': []}
    assert prompt(store, clock, 'no matches found at all', ship='odo') == {'lessons': []}
    shown = [e['id'] for e in prompt(store, clock, 'no matches found at all')['lessons']]
    assert len(prompt(store, clock, 'no matches found at all', seen=shown)['lessons']) == 1


# Task 11: the query
def two_lessons(store, ids, room, fake):
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim='Words.', command=('--include=*',)))
    store.send_message(ids['tardis'], room, 'c2', lesson_body(claim='Near.', command=('zzzz-never',)))
    fake.vectors[embedded(claim='Near.', command=('zzzz-never',))] = [1.0, 0.0, 0.0, 0.0]
    fake.vectors['grep --include=*.py x'] = [0.9, math.sqrt(1 - 0.81), 0.0, 0.0]
    store.lessons_index(fake.path)


def test_words_first_then_near_with_a_receipt_each_and_one_query_row(lessons_station, fake_embedder):
    store, clock, ids, room = lessons_station
    two_lessons(store, ids, room, fake_embedder)
    answer, note = ask(store, clock, fake_embedder.path, command='grep --include=*.py x')
    assert [(e['claim'], e['match']) for e in answer['lessons']] == [('Words.', 'words'), ('Near.', round(math.acos(0.9), 4))]
    assert note is None and fake_embedder.requests[-1]['prefix'] == 'search_query'
    with store.transaction() as db:
        receipts = db.execute('SELECT ship_id, lesson_id, author_id, angle FROM lesson_receipts ORDER BY angle').fetchall()
        row = db.execute('SELECT ship_id, nearest, shown FROM lesson_queries').fetchone()
    assert [r['angle'] for r in receipts] == [None, round(math.acos(0.9), 4)] and {r['author_id'] for r in receipts} == {f"{store._own_peer_id()}:{ids['tardis']}"}
    assert tuple(row) == (ids['rio-grande'], pytest.approx(math.acos(0.9)), 2)
    assert 'grep' not in json.dumps([dict(r) for r in receipts] + [dict(row)])   # no context in any record


def test_seen_the_asking_ships_own_and_its_learned_from_are_skipped(lessons_station, fake_embedder):
    store, clock, ids, room = lessons_station
    two_lessons(store, ids, room, fake_embedder)
    first = ask(store, clock, fake_embedder.path, command='grep --include=*.py x')[0]['lessons'][0]['id']
    assert [e['claim'] for e in ask(store, clock, fake_embedder.path, command='grep --include=*.py x', seen=[first])[0]['lessons']] == ['Near.']
    store.send_message(ids['tardis'], room, 'c3', lesson_body(claim='Taught.', command=('grep',), learned='rio-grande'))
    store.lessons_index(fake_embedder.path)
    assert 'Taught.' not in [e['claim'] for e in ask(store, clock, fake_embedder.path, command='grep --include=*.py x')[0]['lessons']]
    assert ask(store, clock, fake_embedder.path, command='grep --include=*.py x', ship='tardis')[0] == {'lessons': []}   # all its own


def test_before_a_command_only_command_values_match_and_each_lesson_says_which(lessons_station):
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim='Short.', command=('make', 'zz')))
    store.send_message(ids['tardis'], room, 'c2', lesson_body(claim='Long.', command=('--include=*',), error=('make',)))
    store.send_message(ids['tardis'], room, 'c3', lesson_body(claim='Error.', command=('qqqq',), error=('no matches found',)))
    store.lessons_index(None)
    held, _ = ask(store, clock, command='make --include=*.py', error='zsh: no matches found', words_only=True)
    assert sorted((e['claim'], e['command']) for e in held['lessons']) == [('Long.', '--include=*'), ('Short.', 'make')]
    after, _ = ask(store, clock, command='make --include=*.py', error='make; zsh: no matches found')
    got = [(e['claim'], e.get('command')) for e in after['lessons']]
    assert got[0] == ('Long.', '--include=*') and sorted(got[1:]) == [('Error.', None), ('Short.', 'make')]   # 2 values, then 1 each by id


def test_embedder_unavailable_is_noted_only_when_nothing_is_found(lessons_station, fake_embedder):
    store, clock, ids, room = lessons_station
    two_lessons(store, ids, room, fake_embedder)
    assert ask(store, clock, None, command='nothing here') == ({'lessons': []}, 'embedder unavailable')
    assert ask(store, clock, None, command='grep --include=*.py x')[1] is None
    assert ask(store, clock, fake_embedder.path, command='zzz', words_only=True) == ({'lessons': []}, None)
    asked = len(fake_embedder.requests)
    assert ask(store, clock, fake_embedder.path, command='nothing here', budget_ms=0) == ({'lessons': []}, None)   # out of time: said nowhere
    fake_embedder.delay = 0.3   # later than a 100 ms budget: words only, never an error
    assert ask(store, clock, fake_embedder.path, command='grep --include=*.py x', budget_ms=100)[0]['lessons'][0]['match'] == 'words'
    assert len(fake_embedder.requests) == asked + 1


def test_step_4_never_names_a_lesson_retracted_since_the_index_run(lessons_station):
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body())
    store.lessons_index(None)
    key = store.check_lesson(ids['tardis'], lesson_body())['lesson_id']
    store.send_message(ids['andy'], room, 'r1', 'retract ' + key)
    assert ask(store, clock, command='grep --include=*.py x')[0] == {'lessons': []}
    with store.transaction() as db:
        assert db.execute('SELECT count(*) FROM lesson_receipts').fetchone()[0] == 0


def test_a_ship_removed_from_the_room_stops_being_shown_and_comes_back_when_added(lessons_peers):
    pi, pi_fed, pids = lessons_peers['peers']['pi']
    tardis, tardis_fed, tids = lessons_peers['peers']['tardis']
    tardis.send_message(tids['tardis'], lessons_peers['key'], 't1', lesson_body())
    lessons_peers['deliver']('tardis', 'pi')
    pi.lessons_index(None)
    clock = lessons_peers['clock']
    assert len(ask(pi, clock, command='grep --include=*.py x')[0]['lessons']) == 1
    pi.remove_participant(pids['andy'], lessons_peers['room'], pids['contact'])
    assert ask(pi, clock, command='grep --include=*.py x')[0] == {'lessons': []}   # step 4, before any index run
    pi.add_participants(pids['andy'], lessons_peers['room'], [pids['contact']])
    pi.lessons_index(None)
    assert len(ask(pi, clock, command='grep --include=*.py x')[0]['lessons']) == 1   # never laid again


def test_a_lesson_that_would_pass_2000_bytes_is_dropped_whole(lessons_station):
    store, clock, ids, room = lessons_station
    for n in range(3):   # quotes double in JSON: each lesson is about 1,000 bytes of answer
        store.send_message(ids['tardis'], room, f'c{n}', lesson_body(claim=f'{n}' + '"' * 159, why='"' * 300, command=('--include=*',)))
    store.lessons_index(None)
    answer, _ = ask(store, clock, command='grep --include=*.py x')
    assert len(answer['lessons']) == 1 and len(lessons.dumps(answer).encode()) <= 2000
    with store.transaction() as db:
        assert db.execute('SELECT count(*) FROM lesson_receipts').fetchone()[0] == 1
        assert db.execute('SELECT shown FROM lesson_queries').fetchone()[0] == 1


def test_limit_keeps_at_most_that_many_and_writes_a_receipt_only_for_each(lessons_station, fake_embedder, monkeypatch):
    store, clock, ids, room = lessons_station
    two_lessons(store, ids, room, fake_embedder)
    one, _ = ask(store, clock, fake_embedder.path, command='grep --include=*.py x', limit=1)
    assert [e['claim'] for e in one['lessons']] == ['Words.']
    with store.transaction() as db:
        assert db.execute('SELECT count(*) FROM lesson_receipts').fetchone()[0] == 1
        assert db.execute('SELECT shown FROM lesson_queries').fetchone()[0] == 1
    from superyak_peer.db import Store
    def no_store(*args, **kwargs):
        raise AssertionError('limit 0 opened the store')
    monkeypatch.setattr(Store, '__init__', no_store)
    asked = len(fake_embedder.requests)
    assert ask(store, clock, fake_embedder.path, command='grep --include=*.py x', limit=0) == ({'lessons': []}, None)
    assert len(fake_embedder.requests) == asked
    monkeypatch.undo()
    with store.transaction() as db:
        assert db.execute('SELECT count(*) FROM lesson_receipts').fetchone()[0] == 1


def test_query_stdout_keeps_to_the_agreed_contract(lessons_station, fake_embedder, tmp_path):
    """The output Tardis's hook is built against (the plan's Interfaces): exactly {"lessons": [...]}, each lesson exactly
    id, ship, claim, why and match, in that order; match "words" or a Kahan angle rounded to 4 places; words first, then
    Near; at most 3 and 2,000 bytes; "answers nothing" is {"lessons": []} with exit 0; a real failure exits non-zero
    with nothing on stdout."""
    store, clock, ids, room = lessons_station
    two_lessons(store, ids, room, fake_embedder)
    store.send_message(ids['tardis'], room, 'c9', lesson_body(claim='Error only.', command=('qqqq',), error=('no matches found',)))
    store.lessons_index(fake_embedder.path)
    config = tmp_path / 'runtime.json'
    config.write_text(json.dumps({'embedder_socket': str(fake_embedder.path)}))
    fake_embedder.vectors['nothing'] = fake_embedder.vectors['zsh: no matches found'] = [0.0, 0.0, 1.0, 0.0]   # a right angle from every lesson

    def run(request, stdin=None):
        return run_lessons('query', '--data-dir', store.data_dir, '--runtime-config', config,
                           stdin=stdin if stdin is not None else json.dumps(request))
    done = run({'ship': 'rio-grande', 'command': 'grep --include=*.py x'})
    assert done.returncode == 0 and not done.stdout.endswith('\n')
    answer = json.loads(done.stdout)
    assert done.stdout == json.dumps(answer, ensure_ascii=False) and len(done.stdout.encode()) <= 2000
    assert list(answer) == ['lessons'] and 1 <= len(answer['lessons']) <= 3
    for entry in answer['lessons']:
        assert list(entry) in (['id', 'ship', 'claim', 'why', 'match'], ['id', 'ship', 'claim', 'why', 'match', 'command'])
        assert lessons.SHORT.fullmatch(entry['id']) and ('command' in entry) == (entry['claim'] == 'Words.')
        assert entry['match'] == 'words' or (type(entry['match']) is float and entry['match'] == round(entry['match'], 4)
                                             and 0 <= entry['match'] <= math.pi)
    matches = [entry['match'] for entry in answer['lessons']]
    assert matches == ['words', round(math.acos(0.9), 4)]   # an angle in radians, never the cosine 0.9
    assert answer['lessons'][0]['command'] == '--include=*'   # the value exactly as the lesson holds it; Near carries none
    by_error = json.loads(run({'ship': 'rio-grande', 'error': 'zsh: no matches found'}).stdout)
    assert [(e['claim'], 'command' in e) for e in by_error['lessons']] == [('Error only.', False)]   # an error-only words match
    spent = run({'ship': 'rio-grande', 'command': 'grep --include=*.py x', 'budget_ms': 0})
    assert spent.returncode == 0 and [e['match'] for e in json.loads(spent.stdout)['lessons']] == ['words']   # words only
    nothing = '{"lessons": []}'
    for request in ({'ship': 'odo', 'command': 'grep --include=*.py x'}, {'ship': 'rio-grande', 'command': 'nothing'},
                    {'ship': 'rio-grande', 'prompt': 'why does it say --include=* here', 'seen': []}):
        quiet = run(request) if 'prompt' not in request else run_lessons(
            'query', '--data-dir', store.data_dir, '--runtime-config', config, stdin=json.dumps(request), now=LESSON_TIME + 181)
        assert (quiet.returncode, quiet.stdout) == (0, nothing), request
    for bad in ('not json', json.dumps({'ship': 'rio-grande', 'cwd': 'd' * 201}), json.dumps({'ship': 'rio-grande', 'seen': ['x']}),
                json.dumps({'ship': 'rio-grande', 'prompt': 'p' * 2001}), json.dumps({'ship': 'rio-grande', 'limit': 4}),
                json.dumps({'ship': 'rio-grande', 'limit': True}), json.dumps({'ship': 'rio-grande', 'budget_ms': -1}),
                json.dumps({'ship': 'rio-grande', 'budget_ms': 0.5})):
        failed = run(None, bad)
        assert failed.returncode != 0 and failed.stdout == '', bad
    (store.data_dir / lessons.INDEX_FILE).write_bytes(b'damaged')
    failed = run({'ship': 'rio-grande', 'command': 'grep --include=*.py x'})
    assert failed.returncode != 0 and failed.stdout == ''


def test_a_words_match_shows_a_command_value_that_can_hold(lessons_station):
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim='Both.', command=('make', 'make check')))
    store.lessons_index(None)
    held, _ = ask(store, clock, command='make check -j4', words_only=True)
    assert [(e['claim'], e['command']) for e in held['lessons']] == [('Both.', 'make check')]   # not 'make': it can't hold


def test_the_deadline_counts_from_the_request(lessons_station, fake_embedder):
    store, clock, ids, room = lessons_station
    two_lessons(store, ids, room, fake_embedder)
    asked = len(fake_embedder.requests)
    request = lessons.read_request(json.dumps({'ship': 'rio-grande', 'command': 'grep --include=*.py x'}))
    late, _ = lessons.query(request, store.data_dir, fake_embedder.path, clock=lambda: clock[0], monotonic=lambda: 0.9, started=0.0)
    assert [e['match'] for e in late['lessons']] == ['words'] and len(fake_embedder.requests) == asked   # 800 ms are gone


def test_a_stranger_costs_no_embedding_and_the_nearest_angle_counts_only_what_could_be_shown(lessons_station, fake_embedder):
    store, clock, ids, room = lessons_station
    two_lessons(store, ids, room, fake_embedder)
    asked = len(fake_embedder.requests)
    assert ask(store, clock, fake_embedder.path, command='grep --include=*.py x', ship='odo') == ({'lessons': []}, None)
    assert len(fake_embedder.requests) == asked
    assert ask(store, clock, fake_embedder.path, command='grep --include=*.py x', ship='tardis')[0] == {'lessons': []}
    with store.transaction() as db:
        assert [tuple(r) for r in db.execute('SELECT ship_id, nearest FROM lesson_queries')] == [(ids['tardis'], None)]


def test_the_prompt_path_imports_no_store_and_writes_nothing(lessons_station, tmp_path):
    import subprocess, sys
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim='Words.', error=('no matches found',)))
    store.lessons_index(None)
    request = tmp_path / 'request.json'
    request.write_text(json.dumps({'ship': 'rio-grande', 'prompt': 'MARKER why does it say no matches found here', 'seen': []}))
    before = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in store.data_dir.rglob('*')}
    code = (f'import json, sys, time; time.time = lambda: {LESSON_TIME + 10!r}\n'
            'from superyak_peer import lessons\n'
            f'sys.stdin = open({str(request)!r})\n'
            f"lessons.main(['query', '--data-dir', {str(store.data_dir)!r}, '--runtime-config', '/nonexistent'])\n"
            "print(json.dumps(sorted(m for m in sys.modules if 'sqlite' in m or m.startswith('superyak_peer'))), file=sys.stderr)")
    done = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, text=True, cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)['lessons'][0]['claim'] == 'Words.'
    assert json.loads(done.stderr.strip().splitlines()[-1]) == ['superyak_peer', 'superyak_peer.common', 'superyak_peer.lessons']
    assert {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in store.data_dir.rglob('*')} == before
    assert not any(b'MARKER' in p.read_bytes() for p in store.data_dir.rglob('*') if p.is_file())


def test_the_prompt_path_runs_on_the_standard_library_alone_and_writes_no_bytecode(lessons_station, tmp_path):
    """Tardis's conditions for the hook's in-process path. Its interpreter is the system python3 without the peer's venv,
    so superyak_peer/__init__.py imports only the standard library, and __init__, common and lessons import with no
    site-packages at all (-S); importing them with bytecode off writes no __pycache__."""
    import ast, shutil, subprocess, sys
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim='Words.', error=('no matches found',)))
    store.lessons_index(None)
    package = Path(lessons.__file__).parent
    init = ast.parse((package / '__init__.py').read_text())
    roots = {a.name.split('.')[0] for n in ast.walk(init) if isinstance(n, ast.Import) for a in n.names}
    roots |= {n.module.split('.')[0] for n in ast.walk(init) if isinstance(n, ast.ImportFrom) and n.module}
    assert roots <= set(sys.stdlib_module_names) and not any(isinstance(n, ast.ImportFrom) and n.level for n in ast.walk(init))
    checkout = tmp_path / 'checkout'
    (checkout / 'superyak_peer').mkdir(parents=True)
    for name in ('__init__.py', 'common.py', 'lessons.py'):
        shutil.copy(package / name, checkout / 'superyak_peer' / name)
    code = (f'import json, sys, time; sys.dont_write_bytecode = True; sys.path.insert(0, {str(checkout)!r}); '
            f'time.time = lambda: {LESSON_TIME + 10!r}\n'
            'from superyak_peer import lessons\n'
            "request = lessons.read_request(json.dumps({'ship': 'rio-grande', 'prompt': 'why does it say no matches found', 'budget_ms': 90}))\n"
            f'print(lessons.dumps(lessons.answer_prompt(request, {str(store.data_dir)!r}, None)))')
    done = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', code], capture_output=True, text=True, cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)['lessons'][0]['claim'] == 'Words.'
    assert not list(checkout.rglob('__pycache__'))
