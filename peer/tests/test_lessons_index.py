"""First rail, the reading side: the index (section 4), the query and its agreed output (section 5), the prompt path,
receipts and segments (sections 5 and 7), and unread leaving the lessons room out (section 3)."""
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import pytest
from superyak_peer import lessons
from conftest import LESSON_TIME, lesson_body, lesson_ship, paired, run_lessons


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
    """A run killed between its open and its rename leaves `.lessons-index.bin.<pid>.<thread>.tmp`. A later run that gets
    the same pid and thread id removes it (the name is that thread's own) instead of failing on the exclusive open."""
    import threading
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body())
    stale = store.data_dir / f'.{lessons.INDEX_FILE}.{os.getpid()}.{threading.get_ident()}.tmp'
    stale.write_bytes(b'half an index')
    assert store.lessons_index(None) == {'status': 'written', 'lessons': 1, 'vectors': 0}
    assert not stale.exists() and len(lessons.read_index(store.data_dir / lessons.INDEX_FILE)['lessons']) == 1


def test_two_threads_of_one_process_write_the_index_at_once(tmp_path, monkeypatch):
    """Final review concern 4: the temporary name holds the thread's id beside the pid, so one thread's unlink of a stale
    temp can never remove another's while it is being written. Both threads are held at their fsync until both have
    opened and written their temp; then each renames its own, and the file is one whole index."""
    import threading
    barrier, fsync, errors = threading.Barrier(2, timeout=5), os.fsync, []

    def together(fd):
        barrier.wait()
        fsync(fd)
    monkeypatch.setattr(lessons.os, 'fsync', together)
    path = tmp_path / lessons.INDEX_FILE

    def write(n):
        try:
            lessons.write_index(path, {'peer': 'p', 'room': 'r', 'watermark': f'w{n}', 'model': None, 'dimension': None,
                                       'complete': False, 'ships': {}, 'lessons': []}, [], LESSON_TIME)
        except Exception as error:   # noqa: BLE001 - the test reports it
            errors.append(error)
    threads = [threading.Thread(target=write, args=(n,)) for n in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert errors == [] and lessons.read_index(path)['watermark'] in ('w0', 'w1')
    assert [p.name for p in tmp_path.iterdir()] == [lessons.INDEX_FILE]   # no temp left behind


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


def test_a_vector_of_another_size_is_near_unavailable_never_a_crash(lessons_station, fake_embedder):
    """Final review N2: an embedder that answers with the index's model name but vectors of another size gives Near
    nothing to measure. At a failure the query answers words alone, and "embedder unavailable" when that leaves it empty
    (C24, as another model); at a prompt answer_prompt answers words alone, so the only error a hook calling it in
    process catches is IndexUnreadable. Before, math.dist raised ValueError in both."""
    store, clock, ids, room = lessons_station
    two_lessons(store, ids, room, fake_embedder)   # indexed at 4 dimensions
    fake_embedder.dimension, fake_embedder.default = 3, [0.0, 0.0, 1.0]
    fake_embedder.vectors.clear()
    answer, note = ask(store, clock, fake_embedder.path, command='grep --include=*.py x')
    assert [(e['claim'], e['match']) for e in answer['lessons']] == [('Words.', 'words')] and note is None
    assert ask(store, clock, fake_embedder.path, command='nothing here') == ({'lessons': []}, 'embedder unavailable')
    at_prompt = prompt(store, clock, 'why does grep --include=* skip it', fake_embedder.path)
    assert [(e['claim'], e['match']) for e in at_prompt['lessons']] == [('Words.', 'words')]
    assert fake_embedder.requests[-1]['texts'] == ['why does grep --include=* skip it']   # Near was asked, and its answer set aside


def test_an_index_with_a_model_and_no_vectors_is_embedder_unavailable_without_asking(lessons_station, fake_embedder):
    """Final review N5 (C24): an index that names a model but holds no vectors (its embeds failed after the model was
    known) gives Near nothing, so the query says "embedder unavailable" when its answer is empty, and neither path asks
    the embedder to embed the context."""
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim='Words.', command=('--include=*',)))
    fake_embedder.default = [0.0, 0.0, 0.0, 0.0]   # a zero vector: each embed fails, after info named the model
    assert store.lessons_index(fake_embedder.path) == {'status': 'written', 'lessons': 1, 'vectors': 0}
    index = lessons.read_index(store.data_dir / lessons.INDEX_FILE)
    assert index['model'] == 'fake-model' and index['dimension'] is None
    fake_embedder.default, asked = [0.0, 0.0, 0.0, 1.0], len(fake_embedder.requests)
    assert ask(store, clock, fake_embedder.path, command='nothing here') == ({'lessons': []}, 'embedder unavailable')
    answer, note = ask(store, clock, fake_embedder.path, command='grep --include=*.py x')
    assert [e['claim'] for e in answer['lessons']] == ['Words.'] and note is None   # words found it: nothing to say
    assert prompt(store, clock, 'why does this suite fail on the second run', fake_embedder.path) == {'lessons': []}
    assert len(fake_embedder.requests) == asked   # no embed was asked for


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
    assert [(e['claim'], e['command']) for e in held['lessons']] == [('Long.', '--include=*')]   # make can't hold (M2)
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


def test_the_query_and_the_list_write_utf8_whatever_the_locale(lessons_station):
    """Final review N1: stdout gets UTF-8 bytes, so a locale that isn't UTF-8 can't crash the query, at a failure or at a
    prompt, or make lessons-list, on a lesson that isn't ASCII. The C locale with Python's UTF-8 mode and its locale
    coercion turned off gives an ASCII stdout (alone, a C or POSIX locale would turn UTF-8 mode on)."""
    import subprocess
    import sys
    store, clock, ids, room = lessons_station
    claim = 'Quote a glob in zsh \u2014 always.'
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim=claim))
    store.lessons_index(None)
    env = {**{k: v for k, v in os.environ.items() if k not in ('PYTHONIOENCODING', 'LANGUAGE') and not k.startswith('LC_')},
           'LC_ALL': 'C', 'LANG': 'C', 'PYTHONUTF8': '0', 'PYTHONCOERCECLOCALE': '0', 'PYTHONDONTWRITEBYTECODE': '1'}
    code = f'import time; time.time = lambda: {LESSON_TIME + 10!r}\nimport sys\nfrom superyak_peer.lessons import main\nmain(sys.argv[1:])'

    def run(*args, request=None):
        return subprocess.run([sys.executable, '-c', code, *args, '--data-dir', str(store.data_dir)],
                              input=json.dumps(request or {}).encode(), capture_output=True, env=env, timeout=60)
    probe = subprocess.run([sys.executable, '-c', 'import sys; print(sys.stdout.encoding)'], capture_output=True, env=env, text=True)
    assert probe.stdout.strip().lower() in ('ascii', 'ansi_x3.4-1968')   # the locale this test needs
    for request in ({'ship': 'rio-grande', 'command': 'grep --include=*.py x'},
                    {'ship': 'rio-grande', 'prompt': 'why grep --include=* here', 'seen': []}):
        done = run('query', '--runtime-config', '/nonexistent', request=request)
        assert done.returncode == 0, done.stderr
        assert [e['claim'] for e in json.loads(done.stdout.decode('utf-8'))['lessons']] == [claim], request
    listed = run('list')
    assert listed.returncode == 0 and claim in listed.stdout.decode('utf-8'), listed.stderr


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
    nothing = '{"lessons": []}'
    spent = run({'ship': 'rio-grande', 'command': 'grep --include=*.py x', 'budget_ms': 0})
    assert (spent.returncode, spent.stdout) == (0, nothing)   # no time left: nobody sees it, so no receipt (review S1)
    assert json.loads(run({'ship': 'rio-grande', 'command': 'grep --include=*.py x', 'budget_ms': 30000}).stdout)['lessons']
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
    failed, _ = ask(store, clock, command='make check -j4', error='make: *** [check] Error 2')
    assert [(e['claim'], e['command']) for e in failed['lessons']] == [('Both.', 'make check')]   # C43 after a failure too


# The hold contract, the query's side (section 2 review of tardis/rail-lessons-hook, M2 and S1)
SHORT_VALUES = lesson_body(claim='Short values.', command=('git', 'push'))
LONG_VALUE = lesson_body(claim='Long value.', command=('push --force',))
PROBE = 'git push --force origin main'


def receipted(store):
    """The full lesson id of each of this peer's receipts, oldest first."""
    with store.transaction() as db:
        return [r['lesson_id'] for r in db.execute('SELECT lesson_id FROM lesson_receipts ORDER BY created, rowid')]


@pytest.mark.parametrize('limit', [1, 3])
def test_before_a_command_a_lesson_matches_only_on_a_command_value_that_can_hold(lessons_station, limit):
    """The reviewer's probe (M2). The hook holds only on a `command` value of at least HOLD_BYTES, and before a command
    the seam shows a lesson only in a hold. So a lesson whose matched values are all shorter would be shown nowhere: it
    is neither answered nor receipted, and it takes none of the `limit` slots. At limit 1, the limit when two checklists
    lead the deny, it took the only slot."""
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', SHORT_VALUES)
    store.send_message(ids['tardis'], room, 'c2', LONG_VALUE)
    store.lessons_index(None)
    held, note = ask(store, clock, command=PROBE, words_only=True, limit=limit)
    assert ([(e['claim'], e['command']) for e in held['lessons']], note) == ([('Long value.', 'push --force')], None)
    assert receipted(store) == [store.check_lesson(ids['tardis'], LONG_VALUE)['lesson_id']] and counts(store) == (1, 1)


def test_before_a_command_only_values_that_can_hold_count_toward_the_order(lessons_station):
    """A short value is no match before a command, so it doesn't count toward section 5's order there either; after a
    failure it still does. The lesson with fewer values that can hold has the lower id, so only the count puts the
    other first: a count of one per lesson would fall to the id and answer it (the review's mutant M3)."""
    store, clock, ids, room = lessons_station
    fewer = lesson_body(claim='Fewer hold.', command=('make', 'zz', 'make check'))
    two = lesson_body(claim='Two long.', command=('make check', 'check -j4'))
    store.send_message(ids['tardis'], room, 'c1', fewer)
    store.send_message(ids['tardis'], room, 'c2', two)
    store.lessons_index(None)
    assert store.check_lesson(ids['tardis'], fewer)['lesson_id'] < store.check_lesson(ids['tardis'], two)['lesson_id']
    held, _ = ask(store, clock, command='make check -j4 zz', words_only=True, limit=1)
    assert [e['claim'] for e in held['lessons']] == ['Two long.']   # 2 values that can hold, against 1
    failed, _ = ask(store, clock, command='make check -j4 zz', error='Error 2', limit=1)
    assert [e['claim'] for e in failed['lessons']] == ['Fewer hold.']   # 3 values, against 2


def test_the_hold_contract_leaves_a_failure_a_session_start_and_a_prompt_as_they_were(lessons_station):
    """Only `words_only` changed (M2). After a failure a `command` value of any length still matches, so the probe
    answers and receipts both lessons, by the number of values matched. At session start a short `file` value still
    matches the cwd. At a prompt every value needs 6 bytes, as it always did, and nothing is written."""
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', SHORT_VALUES)
    store.send_message(ids['tardis'], room, 'c2', LONG_VALUE)
    store.send_message(ids['tardis'], room, 'c3', lesson_body(claim='Short file.', command=(), file=('src',)))
    store.lessons_index(None)
    failed, _ = ask(store, clock, command=PROBE, error='! [rejected] main -> main (fetch first)')
    assert [(e['claim'], e.get('command')) for e in failed['lessons']] == [
        ('Short values.', 'git'), ('Long value.', 'push --force')]
    assert counts(store) == (2, 1)
    started, _ = ask(store, clock, cwd='/home/andy/src', branch='main')
    assert [(e['claim'], e.get('command')) for e in started['lessons']] == [('Short file.', None)]
    assert counts(store) == (3, 2)
    request = lessons.read_request(json.dumps({'ship': 'rio-grande', 'prompt': f'why did {PROBE} fail?'}))
    prompted, _ = lessons.query(request, store.data_dir, None, clock=lambda: clock[0], monotonic=lambda: 0.0)
    assert [(e['claim'], e['command']) for e in prompted['lessons']] == [('Long value.', 'push --force')]
    assert counts(store) == (3, 2)


def test_the_deadline_counts_from_the_request(lessons_station, fake_embedder):
    store, clock, ids, room = lessons_station
    two_lessons(store, ids, room, fake_embedder)
    asked = len(fake_embedder.requests)
    request = lessons.read_request(json.dumps({'ship': 'rio-grande', 'command': 'grep --include=*.py x'}))
    late, _ = lessons.query(request, store.data_dir, fake_embedder.path, clock=lambda: clock[0], monotonic=lambda: 0.9, started=0.0)
    assert [e['match'] for e in late['lessons']] == ['words'] and len(fake_embedder.requests) == asked   # 800 ms are gone


def counts(store):
    with store.transaction() as db:
        return tuple(db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in ('lesson_receipts', 'lesson_queries'))


@pytest.mark.parametrize('spent', [True, False])
def test_step_4_writes_nothing_once_the_hooks_budget_has_passed_inside_its_transaction(lessons_station, monkeypatch, spent):
    """Serenity's review of first-rail, S1: step 4 counts the hook's budget_ms from the request. A budget that runs out
    inside step 4's transaction (here while it reads the room) writes no receipt and no query row and answers nothing,
    since nobody is waiting to see it; one with time left writes them as before."""
    from superyak_peer.db import Store
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim='Words.', command=('--include=*',)))
    store.lessons_index(None)
    now, read = [0.0], Store._lessons_snapshot

    def slow_read(self, db):
        now[0] = 0.6 if spent else 0.4   # the hook gave 500 ms
        return read(self, db)
    monkeypatch.setattr(Store, '_lessons_snapshot', slow_read)
    request = lessons.read_request(json.dumps({'ship': 'rio-grande', 'command': 'grep --include=*.py x', 'budget_ms': 500}))
    answer, note = lessons.query(request, store.data_dir, None, clock=lambda: clock[0], monotonic=lambda: now[0], started=0.0)
    monkeypatch.undo()
    assert now[0] > 0 and note is None   # the room was read: the budget ran out inside the transaction
    if spent:
        assert answer == {'lessons': []} and counts(store) == (0, 0)
    else:
        assert [e['claim'] for e in answer['lessons']] == ['Words.'] and counts(store) == (1, 1)


def test_without_a_budget_step_4_has_no_deadline(lessons_station, monkeypatch):
    """No budget_ms, no one gives up on the answer: step 4 writes however long the room took to read."""
    from superyak_peer.db import Store
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim='Words.', command=('--include=*',)))
    store.lessons_index(None)
    now, read = [0.0], Store._lessons_snapshot
    monkeypatch.setattr(Store, '_lessons_snapshot', lambda self, db: (now.__setitem__(0, 60.0), read(self, db))[1])
    request = lessons.read_request(json.dumps({'ship': 'rio-grande', 'command': 'grep --include=*.py x'}))
    answer, _ = lessons.query(request, store.data_dir, None, clock=lambda: clock[0], monotonic=lambda: now[0], started=0.0)
    monkeypatch.undo()
    assert [e['claim'] for e in answer['lessons']] == ['Words.'] and counts(store) == (1, 1)


@pytest.mark.parametrize('holder', ['another process', 'another thread'])
def test_a_held_dispatch_gate_is_waited_for_only_until_the_budget_ends(lessons_station, holder):
    """S1's waits: the dispatch gate (another thread's, or another process's file lock) is waited for only until the
    hook's budget ends, opening the store included; then the answer is nothing and nothing is written. Unheld, the
    same request answers and writes."""
    import fcntl, threading, time
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim='Words.', command=('--include=*',)))
    store.lessons_index(None)
    request = lessons.read_request(json.dumps({'ship': 'rio-grande', 'command': 'grep --include=*.py x', 'budget_ms': 200}))
    held, release = threading.Event(), threading.Event()
    if holder == 'another thread':
        def hold():
            with store.dispatch_gate:
                held.set()
                release.wait(30)
        thread = threading.Thread(target=hold)
        thread.start()
        held.wait(30)
    else:   # a second open file description: flock refuses it as it would another process
        fd = os.open(store.data_dir / 'dispatch.lock', os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        began = time.monotonic()
        answer, note = lessons.query(request, store.data_dir, None, clock=lambda: clock[0])
        waited = time.monotonic() - began
    finally:
        if holder == 'another thread':
            release.set()
            thread.join(30)
        else:
            os.close(fd)
    assert (answer, note) == ({'lessons': []}, None) and waited < 5
    assert counts(store) == (0, 0)
    answer, _ = lessons.query(request, store.data_dir, None, clock=lambda: clock[0])
    assert [e['claim'] for e in answer['lessons']] == ['Words.'] and counts(store) == (1, 1)


@pytest.mark.journal('delete')  # a held reader blocks a commit only in rollback mode; its WAL twin is plan Task 7's
def test_the_commit_waits_for_a_reader_only_until_the_budget_ends(lessons_station, monkeypatch):
    """The fresh review's S1: the station's database keeps a rollback journal, so step 4's commit waits for every
    reader's SHARED lock, and a reader outside the dispatch gate (the nightly backup's copy) can hold one past the
    deadline check. Here a read-only connection takes SHARED while step 4 reads the room, and keeps it. The injected
    clock never reaches the deadline, so only the commit's wait can end this: SQLite waits the 300 ms the budget leaves,
    in real time, refuses the commit, and it is rolled back; the answer is nothing. Once the reader is gone, the same
    request writes."""
    import sqlite3, time
    from superyak_peer.db import Store
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim='Words.', command=('--include=*',)))
    store.lessons_index(None)
    request = lessons.read_request(json.dumps({'ship': 'rio-grande', 'command': 'grep --include=*.py x', 'words_only': True,
                                               'budget_ms': 300}))
    reader, read = sqlite3.connect(store.db_path.as_uri() + '?mode=ro', uri=True, isolation_level=None), Store._lessons_snapshot

    def read_beside_a_reader(self, db):
        reader.execute('BEGIN')
        reader.execute('SELECT count(*) FROM users').fetchone()   # SHARED, held until the read transaction ends
        return read(self, db)
    monkeypatch.setattr(Store, '_lessons_snapshot', read_beside_a_reader)
    try:
        began = time.monotonic()
        answer, note = lessons.query(request, store.data_dir, None, clock=lambda: clock[0], monotonic=lambda: 0.0, started=0.0)
        waited = time.monotonic() - began
    finally:
        monkeypatch.undo()
        reader.execute('ROLLBACK') if reader.in_transaction else None
        reader.close()
    assert (answer, note) == ({'lessons': []}, None) and 0.25 < waited < 5   # the budget's 300 ms, never SQLite's 30 s
    assert counts(store) == (0, 0)
    answer, _ = lessons.query(request, store.data_dir, None, clock=lambda: clock[0], monotonic=lambda: 0.0, started=0.0)
    assert [e['claim'] for e in answer['lessons']] == ['Words.'] and counts(store) == (1, 1)


def held_reader(store):
    """A read-only connection holding SHARED, as the nightly backup's copy does, until it is closed."""
    import sqlite3
    reader = sqlite3.connect(store.db_path.as_uri() + '?mode=ro', uri=True, isolation_level=None)
    reader.execute('BEGIN')
    reader.execute('SELECT count(*) FROM users').fetchone()
    return reader


@pytest.mark.journal('delete')  # a held reader blocks a commit only in rollback mode; its WAL twin is plan Task 7's
@pytest.mark.parametrize('words_only', [True, False], ids=['words only', 'with Near'])
def test_a_reader_from_before_the_query_is_waited_for_only_until_the_budget_ends(lessons_station, words_only):
    """fix:lessons-query-open-and-budget-bounds: a reader that holds SHARED from before the query starts (the nightly
    backup's copy) made opening the store wait SQLite's 30 s and then raise "database is locked". Opening the store now
    waits what the budget leaves, no more and no less: the injected clock never reaches the deadline, so only SQLite's
    real-time wait can end it (the review's S1). Then the answer is nothing, nothing is written, and a lock is never
    reported as "embedder unavailable" (C24, the review's N4: with Near and no embedder too). Once the reader is gone,
    the same request writes."""
    import time
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim='Words.', command=('--include=*',)))
    store.lessons_index(None)
    request = lessons.read_request(json.dumps({'ship': 'rio-grande', 'command': 'grep --include=*.py x',
                                               'words_only': words_only, 'budget_ms': 300}))
    reader = held_reader(store)
    try:
        began = time.monotonic()
        answer, note = lessons.query(request, store.data_dir, None, clock=lambda: clock[0], monotonic=lambda: 0.0, started=0.0)
        waited = time.monotonic() - began
    finally:
        reader.execute('ROLLBACK')
        reader.close()
    assert (answer, note) == ({'lessons': []}, None) and 0.25 < waited < 5   # the budget's 300 ms, never SQLite's 30 s
    assert counts(store) == (0, 0)
    answer, _ = lessons.query(request, store.data_dir, None, clock=lambda: clock[0], monotonic=lambda: 0.0, started=0.0)
    assert [e['claim'] for e in answer['lessons']] == ['Words.'] and counts(store) == (1, 1)


@pytest.mark.journal('delete')  # a held reader blocks a commit only in rollback mode; its WAL twin is plan Task 7's
def test_the_query_verb_answers_nothing_within_its_budget_beside_a_reader(lessons_station, tmp_path):
    """The review's S3, through the process the hook runs: beside a held reader, `query` with budget_ms 3000 exits 0
    with {"lessons": []} inside its budget, and writes no receipt (before the fix: 30 s, then a traceback). The budget
    is 3 s because importing the store alone takes about 0.35 s on the Pi: a smaller one is spent before the store is
    opened, and the test would pass without opening it (the re-check's S3)."""
    import time
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim='Words.', command=('--include=*',)))
    store.lessons_index(None)
    config = tmp_path / 'runtime.json'
    config.write_text(json.dumps({'embedder_socket': str(tmp_path / 'none.sock')}))
    request = json.dumps({'ship': 'rio-grande', 'command': 'grep --include=*.py x', 'words_only': True, 'budget_ms': 3000})
    reader = held_reader(store)
    try:
        began = time.monotonic()
        done = run_lessons('query', '--data-dir', store.data_dir, '--runtime-config', config, stdin=request)
        waited = time.monotonic() - began
    finally:
        reader.execute('ROLLBACK')
        reader.close()
    assert (done.returncode, done.stdout) == (0, '{"lessons": []}') and waited < 10, done.stderr   # room for start-up
    assert counts(store) == (0, 0)


def test_opening_the_store_fails_loudly_for_anything_but_a_lock(lessons_station, monkeypatch):
    """The review's N1: only SQLITE_BUSY at open means "late". Any other database error there still raises."""
    import sqlite3
    from superyak_peer.db import Store
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim='Words.', command=('--include=*',)))
    store.lessons_index(None)   # a lesson to match, so the query goes on to open the store
    request = lessons.read_request(json.dumps({'ship': 'rio-grande', 'command': 'grep --include=*.py x', 'words_only': True,
                                               'budget_ms': 300}))

    def broken(self, *args, **kwargs):
        raise sqlite3.OperationalError('disk I/O error')
    monkeypatch.setattr(Store, '__init__', broken)
    with pytest.raises(sqlite3.OperationalError, match='disk I/O error'):
        lessons.query(request, store.data_dir, None, clock=lambda: clock[0], monotonic=lambda: 0.0, started=0.0)


@pytest.mark.parametrize('budget', [10 ** 309, 10 ** 400], ids=['1e309', '1e400'])
def test_a_budget_too_large_for_a_float_is_clamped_never_a_crash(lessons_station, budget):
    """fix:lessons-query-open-and-budget-bounds: JSON gives Python an integer of any size, and 10**309 ms is past what a
    float holds, so the query crashed with OverflowError. read_request clamps budget_ms to BUDGET_CAP_MS (an hour:
    no hook waits that long), and the query answers as it would without one."""
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim='Words.', command=('--include=*',)))
    store.lessons_index(None)
    request = lessons.read_request(json.dumps({'ship': 'rio-grande', 'command': 'grep --include=*.py x', 'budget_ms': budget}))
    assert request['budget_ms'] == lessons.BUDGET_CAP_MS == 3_600_000
    answer, note = lessons.query(request, store.data_dir, None, clock=lambda: clock[0])
    assert [e['claim'] for e in answer['lessons']] == ['Words.'] and counts(store) == (1, 1)


def test_a_budget_past_what_a_lock_can_wait_is_clamped_never_a_crash(lessons_station):
    """The fresh review's N1: budget_ms has no upper bound, and 10**13 ms is past threading.TIMEOUT_MAX seconds. The
    bounded wait clamps to it (and SQLite's commit wait to its own 30 s), so the query answers as it would without one."""
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim='Words.', command=('--include=*',)))
    store.lessons_index(None)
    request = {**lessons.read_request(json.dumps({'ship': 'rio-grande', 'command': 'grep --include=*.py x'})),
               'budget_ms': 10 ** 13}   # past read_request's own clamp, so the gate's clamp is what this pins (review S2)
    answer, note = lessons.query(request, store.data_dir, None, clock=lambda: clock[0])
    assert [e['claim'] for e in answer['lessons']] == ['Words.'] and counts(store) == (1, 1)


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
    site-packages at all (-S); importing them with bytecode off writes no __pycache__. Both clocks are pinned before the
    import binds them as answer_prompt's defaults, so the 90 ms budget is never spent by a loaded machine."""
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
            f'time.time = lambda: {LESSON_TIME + 10!r}; time.monotonic = lambda: 0.0\n'
            'from superyak_peer import lessons\n'
            "request = lessons.read_request(json.dumps({'ship': 'rio-grande', 'prompt': 'why does it say no matches found', 'budget_ms': 90}))\n"
            f'print(lessons.dumps(lessons.answer_prompt(request, {str(store.data_dir)!r}, None)))')
    done = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', code], capture_output=True, text=True, cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)['lessons'][0]['claim'] == 'Words.'
    assert not list(checkout.rglob('__pycache__'))


# The Task 10 amendment: could_hold, Tardis's check before a Bash command, in process (City of AI 2af70b05)
def test_could_hold_takes_a_command_value_of_6_bytes_and_never_one_of_5(lessons_station):
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim='Six.', command=('sed -i',)))
    store.send_message(ids['tardis'], room, 'c2', lesson_body(claim='Five.', command=('tar x',)))
    store.send_message(ids['tardis'], room, 'c3', lesson_body(claim='Six bytes.', command=('ééé',)))   # 3 characters
    store.send_message(ids['tardis'], room, 'c4', lesson_body(claim='Five bytes.', command=('ééx',)))
    store.send_message(ids['tardis'], room, 'c5', lesson_body(claim='Error.', command=('qqqq',), error=('no matches found',),
                                                              file=('Makefile',)))
    store.lessons_index(None)

    def hold(command):
        return lessons.could_hold(command, 'rio-grande', store.data_dir)
    assert hold('sed -i s/a/b/ notes.txt') is True
    assert hold('tar xf a.tar') is False   # 5 bytes: it matches, but can't hold
    assert hold('echo ééé') is True and hold('echo ééx') is False   # bytes, not characters
    assert hold('ls -la') is False   # no match
    assert hold('grep "no matches found" Makefile') is False   # an error or file value never holds a command
    assert hold('x' * 294 + 'sed -i') is True and hold('x' * 295 + 'sed -i') is False   # cut to 300 characters, as the hook cuts


def test_could_hold_skips_the_ships_own_lessons_its_learned_from_and_a_ship_outside_the_room(lessons_station):
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim='Tardis.', command=('sed -i',)))
    store.send_message(ids['tardis'], room, 'c2', lesson_body(claim='Taught.', command=('awk -F',), learned='rio-grande'))
    lesson_ship(store, ids['andy'], 'defiant')   # a ship on this peer, never added to the room
    store.lessons_index(None)
    assert lessons.could_hold('sed -i s/a/b/ f', 'rio-grande', store.data_dir) is True
    assert lessons.could_hold('sed -i s/a/b/ f', 'tardis', store.data_dir) is False   # its own
    assert lessons.could_hold('awk -F: x f', 'rio-grande', store.data_dir) is False   # learned from it
    for stranger in ('defiant', 'andy', 'odo'):   # a ship outside the room, a person, no account
        assert lessons.could_hold('sed -i s/a/b/ f', stranger, store.data_dir) is False, stranger


def test_could_hold_skips_a_lesson_in_seen_and_one_whose_matched_values_are_all_short(lessons_station):
    """The hold contract (M2 and S1): True only when some lesson not in `seen` has a `command` value of at least
    HOLD_BYTES in the command, as the words-only query answers. So once the hook passes the ids it will send, a head
    whose only holding lesson was shown already (at a prompt, say) asks no query at all."""
    store, clock, ids, room = lessons_station
    also = lesson_body(claim='Also long.', command=('origin main',))
    for n, body in enumerate((SHORT_VALUES, LONG_VALUE, also)):
        store.send_message(ids['tardis'], room, f'c{n}', body)
    store.lessons_index(None)
    short, long_, other = (store.check_lesson(ids['tardis'], body)['short'] for body in (SHORT_VALUES, LONG_VALUE, also))

    def hold(*seen, command=PROBE):
        return lessons.could_hold(command, 'rio-grande', store.data_dir, list(seen))
    assert hold() is True and hold(long_) is True and hold(other) is True and hold(short) is True
    assert hold(long_, other) is False   # only "Short values." is left, and git and push can't hold
    assert hold(command='git push') is False and hold(command='git push --force') is True
    assert lessons.could_hold(PROBE, 'rio-grande', store.data_dir) is True   # the three-argument call keeps working
    assert lessons.could_hold(PROBE, 'rio-grande', store.data_dir, (long_, other)) is False   # any collection of ids
    assert lessons.could_hold(PROBE, 'rio-grande', store.data_dir, frozenset({long_})) is True
    for bad in (None, 3, long_, [None], ['nope'], [long_.upper()], {long_: 1}, [short] * (lessons.SEEN_MAX + 1)):
        assert lessons.could_hold(PROBE, 'rio-grande', store.data_dir, bad) is False, bad
        with pytest.raises(ValueError, match='seen'):   # the query refuses every one: one rule, seen_ok
            lessons.read_request(json.dumps({'ship': 'rio-grande', 'command': PROBE, 'words_only': True, 'seen': bad}))
    assert lessons.could_hold(PROBE, 'rio-grande', store.data_dir, [short] * lessons.SEEN_MAX) is True


def test_could_hold_is_false_with_no_index_or_a_damaged_one_and_answers_from_a_stale_one(lessons_station, tmp_path):
    """It ignores the index's age: the full query re-checks retractions and membership in step 4, so a stale index can
    only make it say True too often (here, for a lesson retracted since the last run), never miss a hold."""
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim='Tardis.', command=('sed -i',)))
    assert lessons.could_hold('sed -i s/a/b/ f', 'rio-grande', store.data_dir) is False   # no index run yet
    assert lessons.could_hold('sed -i s/a/b/ f', 'rio-grande', tmp_path / 'no-such-peer') is False
    store.lessons_index(None)
    path = store.data_dir / lessons.INDEX_FILE
    os.utime(path, (0, 0))   # decades old
    assert lessons.could_hold('sed -i s/a/b/ f', 'rio-grande', store.data_dir) is True
    key = store.check_lesson(ids['tardis'], lesson_body(claim='Tardis.', command=('sed -i',)))['lesson_id']
    store.send_message(ids['andy'], room, 'r1', 'retract ' + key)
    assert lessons.could_hold('sed -i s/a/b/ f', 'rio-grande', store.data_dir) is True   # until the next index run
    assert ask(store, clock, command='sed -i s/a/b/ f', words_only=True)[0] == {'lessons': []}   # step 4 never names it
    path.write_bytes(lessons.INDEX_MAGIC + b'\x00\x00\x00\x09{"lessons"')
    assert lessons.could_hold('sed -i s/a/b/ f', 'rio-grande', store.data_dir) is False
    (tmp_path / 'folder' / lessons.INDEX_FILE).mkdir(parents=True)   # can't be read at all
    assert lessons.could_hold('sed -i s/a/b/ f', 'rio-grande', tmp_path / 'folder') is False


def test_could_hold_runs_on_the_standard_library_alone_and_opens_only_the_index_to_read_it(lessons_station, tmp_path):
    """The hook calls it in process before a Bash command, from the system python3 with no site-packages and bytecode
    off. An audit hook sees every file it opens, and any socket, database or file change: only the index, read."""
    import shutil, subprocess, sys
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim='Tardis.', command=('sed -i',)))
    store.lessons_index(None)
    shown = store.check_lesson(ids['tardis'], lesson_body(claim='Tardis.', command=('sed -i',)))['short']
    package = Path(lessons.__file__).parent
    checkout = tmp_path / 'checkout'
    (checkout / 'superyak_peer').mkdir(parents=True)
    for name in ('__init__.py', 'common.py', 'lessons.py'):
        shutil.copy(package / name, checkout / 'superyak_peer' / name)
    before = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in store.data_dir.rglob('*')}
    code = (f'import json, sys; sys.dont_write_bytecode = True; sys.path.insert(0, {str(checkout)!r})\n'
            'from superyak_peer import lessons\n'
            'events = []\n'
            'sys.addaudithook(lambda event, args: events.append([event, *map(str, args)]) if event == "open" or '
            'event.partition(".")[0] in ("os", "shutil", "socket", "sqlite3", "subprocess") else None)\n'
            f'got = [lessons.could_hold(c, "rio-grande", {str(store.data_dir)!r}, *s) for c, s in '
            f'(("sed -i s/a/b/ f", ()), ("ls -la", ()), ("sed -i s/a/b/ f", ([{shown!r}],)))]\n'
            'seen = list(events)\n'
            'modules = sorted(m for m in sys.modules if m.startswith("superyak_peer") or "sqlite" in m)\n'
            'print(json.dumps({"got": got, "events": seen, "modules": modules}))')
    done = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', code], capture_output=True, text=True, cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    got, index = json.loads(done.stdout), str(store.data_dir / lessons.INDEX_FILE)
    assert got['got'] == [True, False, False]   # the third with the lesson in seen
    assert [event[:3] for event in got['events']] == [['open', index, 'r']] * 3   # no other file, no socket, no database
    writes = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
    assert all(int(event[3]) & writes == 0 for event in got['events'])   # opened to read, and nothing else
    assert got['modules'] == ['superyak_peer', 'superyak_peer.common', 'superyak_peer.lessons']
    assert not list(checkout.rglob('__pycache__'))
    assert {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in store.data_dir.rglob('*')} == before


def test_could_hold_is_true_exactly_when_the_words_only_query_answers_given_the_same_seen(lessons_station):
    """could_hold stands in for the full query before a Bash command (section 8's hold), so for every command of a
    fixture, every asking ship and every `seen` the hook could send, it is True exactly when the query, words only,
    answers anything; and since the hold contract (M2) the query answers there only lessons carrying a `command` of at
    least 6 bytes, the value the hook holds on. The fixture matches at most 3 lessons per command, so the query's limit
    never hides one (past 3 matches could_hold can only say True too often)."""
    store, clock, ids, room = lessons_station
    for n, (claim, command, error, learned) in enumerate((
            ('Six.', ('sed -i',), (), 'own'), ('Also six.', ('s/a/b/',), (), 'own'), ('Five.', ('tar x',), (), 'own'),
            ('Short.', ('make', 'zz'), (), 'own'), ('Both.', ('make', 'make check'), (), 'own'),
            ('Six bytes.', ('ééé',), (), 'own'), ('Five bytes.', ('ééx',), (), 'own'),
            ('Error.', ('qqqq',), ('no matches found',), 'own'), ('Taught.', ('awk -F',), (), 'rio-grande'))):
        store.send_message(ids['tardis'], room, f't{n}', lesson_body(claim=claim, command=command, error=error, learned=learned))
    store.send_message(ids['rio-grande'], room, 'r1', lesson_body(ship='rio-grande', claim='Rio.', command=('git rm',)))
    store.lessons_index(None)
    commands = ('sed -i s/a/b/ f', 'tar xf a.tar', 'make check -j4', 'make all', 'echo ééé', 'echo ééx',
                'grep "no matches found" .', "awk -F: '{print $1}' f", 'git rm -r build', 'ls', '',
                'x' * 294 + 'sed -i', 'x' * 295 + 'sed -i')
    said = {}
    for ship in ('rio-grande', 'tardis', 'odo'):
        for command in commands:
            answer, _ = ask(store, clock, command=command[:300], words_only=True, ship=ship)   # the hook cuts to 300
            assert all(len(e['command'].encode('utf-8')) >= lessons.HOLD_BYTES for e in answer['lessons'])
            got = [e['id'] for e in answer['lessons']]
            said[ship, command] = len(got)
            assert lessons.could_hold(command, ship, store.data_dir) is bool(got), (ship, command)
            for n in range(1, len(got) + 1):   # seen holds the first n it answered: True while one is left
                again, _ = ask(store, clock, command=command[:300], words_only=True, ship=ship, seen=got[:n])
                assert [e['id'] for e in again['lessons']] == got[n:], (ship, command, n)
                assert lessons.could_hold(command, ship, store.data_dir, got[:n]) is (n < len(got)), (ship, command, n)
    assert sorted((key, n) for key, n in said.items() if n) == sorted([
        (('rio-grande', 'sed -i s/a/b/ f'), 2), (('rio-grande', 'make check -j4'), 1), (('rio-grande', 'echo ééé'), 1),
        (('rio-grande', 'x' * 294 + 'sed -i'), 1), (('tardis', 'git rm -r build'), 1)])


# Task 12: receipts and segments
def test_lessons_list_gives_andy_each_full_id_and_its_retract_line(lessons_station):
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim='Kept.'))
    store.send_message(ids['tardis'], room, 'c2', lesson_body(claim='Gone.'))
    gone = store.check_lesson(ids['tardis'], lesson_body(claim='Gone.'))['lesson_id']
    store.send_message(ids['andy'], room, 'r1', 'retract ' + gone)
    kept = store.check_lesson(ids['tardis'], lesson_body(claim='Kept.'))['lesson_id']
    listed = run_lessons('list', '--data-dir', store.data_dir)
    assert listed.returncode == 0 and f'  retract {kept}' in listed.stdout.splitlines() and gone not in listed.stdout
    assert f'{lessons.short_lesson_id(kept)}  tardis  Kept.' in listed.stdout.splitlines()


def test_receipts_list_newest_first_with_ids_ships_and_angles_only(lessons_station, fake_embedder):
    store, clock, ids, room = lessons_station
    two_lessons(store, ids, room, fake_embedder)
    ask(store, clock, fake_embedder.path, command='grep --include=*.py x')
    done = run_lessons('receipts', '--data-dir', store.data_dir)
    lines = done.stdout.strip().splitlines()
    assert done.returncode == 0 and len(lines) == 2 and all('rio-grande' in line and 'from tardis' in line for line in lines)
    assert {line.split()[-1] for line in lines} == {'words', 'rad'} and 'grep' not in done.stdout and 'Words.' not in done.stdout


def test_segments_pair_two_ships_own_lessons_and_never_a_copy(lessons_peers, fake_embedder):
    """The rail is counted honestly (goal 1): a lesson that came from another ship is never its ship's own, even reworded.
    `reworded` passes every other rule against `a` (another author, on another peer, with another text, at angle 0), so
    only `learned from: own` keeps it out; `copy`, with `a`'s text, the digest rule would also drop."""
    pi, pi_fed, pids = lessons_peers['peers']['pi']
    tardis, tardis_fed, tids = lessons_peers['peers']['tardis']
    a = lesson_body(ship='tardis', claim='Read before you trust a count.', command=('grep -c',))
    b = lesson_body(ship='rio-grande', claim='Never trust a keyword count over reading.', command=('grep -c',))
    copy = lesson_body(ship='rio-grande', claim='Read before you trust a count.', command=('grep -c',), learned='tardis')
    reworded = lesson_body(ship='rio-grande', claim='Read the matching lines before you believe a tally.', command=('grep -c',),
                           learned='tardis')
    for body in (a, b, copy, reworded):
        fake_embedder.vectors[lessons.embedded_text(lessons.parse_post(body))] = [1.0, 0.0, 0.0, 0.0]
    tardis.send_message(tids['tardis'], lessons_peers['key'], 't1', a)
    lessons_peers['deliver']('tardis', 'pi')
    pi.send_message(pids['rio-grande'], lessons_peers['room'], 'p1', b)
    pi.send_message(pids['rio-grande'], lessons_peers['room'], 'p2', copy)
    pi.send_message(pids['rio-grande'], lessons_peers['room'], 'p3', reworded)
    pi.lessons_index(fake_embedder.path)
    index = lessons.read_index(pi.data_dir / lessons.INDEX_FILE)
    taught = [item for item in index['lessons'] if item['learned_from'] == 'tardis']
    assert len(taught) == 2 and all(item['vector'] is not None for item in taught)   # both indexed, with vectors
    found = lessons.segments(index)
    assert [(x[0], x[1], x[4]) for x in found] == [('rio-grande', 'tardis', 0.0)]
    short = lambda peer, body: lessons.short_lesson_id(lessons.lesson_id(peer, lessons.parse_post(body)))
    assert [x[2:4] for x in found] == [(short(pi_fed.identity.peer_id, b), short(tardis_fed.identity.peer_id, a))]
    listed = run_lessons('segments', '--data-dir', pi.data_dir)
    assert listed.stdout.startswith('rio-grande and tardis: 1 segment\n') and 'count' not in listed.stdout
    assert short(pi_fed.identity.peer_id, reworded) not in listed.stdout


# Task 13: unread leaves the lessons room out
def test_unread_leaves_the_lessons_room_out_counts_it_and_passes_it(lessons_station):
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body())
    store.send_message(ids['tardis'], room, 'c2', lesson_body(claim='Two.'))
    store.send_message(ids['andy'], room, 'r1', 'retract ' + store.check_lesson(ids['tardis'], lesson_body(claim='Two.'))['lesson_id'])
    with store.transaction() as db:
        store._post_as_system(db, room, 'notice-1', 'A station notice.')
    talk = store.create_room(ids['andy'], 'Talk', [ids['rio-grande']])['id']
    store.send_message(ids['andy'], talk, 'm1', 'hello')
    plain = store.unread(ids['rio-grande'], 'd', 30)   # first: a new cursor starts where the ship has read furthest
    assert len(plain['messages']) == 5 and 'lesson_count' not in plain   # without the flag, exactly today's
    got = store.unread(ids['rio-grande'], 'c', 30, breakouts=True)
    assert [m['body'] for m in got['messages']] == ['hello'] and got['breakout_counts'] == {}
    assert got['lesson_count'] == 2   # two lessons; the retraction and the station's notice are not new lessons
    store.advance(ids['rio-grande'], 'c', got['messages'][-1]['event_id'])
    assert 'lesson_count' not in store.unread(ids['rio-grande'], 'c', 30, breakouts=True)   # R35: only when it says something


def test_the_backfills_copies_are_not_new_lessons_on_the_unread_line(tmp_path, lessons_peers):
    """Final review N4: when an add carries the chain's lessons into its new room (section 3), the copies are old
    lessons laid again, so the Pi's unread line doesn't count them, any more than the add's notice; a lesson laid in the
    new room afterwards still counts."""
    from superyak_peer.db import Store
    from superyak_peer.federation import Federation
    pi, pi_fed, pids = lessons_peers['peers']['pi']
    tardis, tardis_fed, tids = lessons_peers['peers']['tardis']
    room, deliver, clock, rio = lessons_peers['room'], lessons_peers['deliver'], lessons_peers['clock'], pids['rio-grande']
    tardis.send_message(tids['tardis'], lessons_peers['key'], 't1', lesson_body())
    deliver('tardis', 'pi')
    pi.send_message(rio, room, 'p1', lesson_body(ship='rio-grande', claim='Mine.', command=('make check',)))
    assert pi.unread(rio, 'c', 30, breakouts=True)['lesson_count'] == 1   # tardis's; its own never reaches its unread
    mac = Store(tmp_path / 'mac', clock=lambda: clock[0])
    mac_fed = Federation(mac, endpoint='https://mac:7437')
    andy_m = mac.create_user('andy', 'Andy Example', 'a-long-password', is_admin=True)['id']
    contact = paired(pi_fed, pids['andy'], mac_fed.card(mac.lessons_ship('serenity', 'andy')['id']))['id']
    paired(mac_fed, andy_m, pi_fed.card(pids['andy']))
    both = [tardis_fed.identity.peer_id, mac_fed.identity.peer_id]
    pi.station_lessons_room('andy', room[:6], 'rio-grande', both, pi.station_lessons_room('andy', room[:6], 'rio-grande', both)['confirm'])
    new = pi.add_participants(pids['andy'], room, [contact])
    assert new['lessons_carried'] == 2
    assert 'lesson_count' not in pi.unread(rio, 'c', 30, breakouts=True)   # tardis's copy, rio-grande's own, the notice
    pi_fed.sync_once(send=lambda card, prepare: (mac_fed if card['peer_id'] == mac_fed.identity.peer_id else tardis_fed).receive(prepare()))
    tardis.send_message(tids['tardis'], f"{pi_fed.identity.peer_id}:{new['id']}", 't2', lesson_body(claim='After the add.'))
    deliver('tardis', 'pi')
    assert pi.unread(rio, 'c', 30, breakouts=True)['lesson_count'] == 1


def test_a_wait_adds_up_the_lessons_it_left_out():
    from superyak_peer.inbox import with_earlier_noise
    earlier = {'breakout_counts': {}, 'breakout_titles': {}, 'lesson_count': 2}
    assert with_earlier_noise(earlier, {'breakout_counts': {}, 'breakout_titles': {}, 'lesson_count': 1})['lesson_count'] == 3
    assert 'lesson_count' not in with_earlier_noise({'breakout_counts': {}, 'breakout_titles': {}}, {'breakout_counts': {}, 'breakout_titles': {}})


AGENT = Path(__file__).resolve().parents[2] / 'agent'


@pytest.mark.skipif(not (AGENT / 'superyak_agent').is_dir(), reason='needs agent/ from the full repository')
def test_a_lesson_never_kicks_a_ship_and_the_kick_never_hides_one_from_the_session(lessons_station, monkeypatch):
    """Task 13 beside main's kick (agent/superyak_agent/kick.py): the kick reads unread without breakouts=mentions, on
    its own cursor, so Task 13 doesn't change what it sees. The lessons room's doors refuse an @name and a reply label,
    so no post there mentions a ship or replies to one, and none kicks; a mention and a reply elsewhere still do, and a
    reply still carries replies_to_me on both reads. The kick passing the lessons moves only its own cursor: the
    session's breakouts=mentions read still counts them."""
    from superyak_peer.common import Problem
    monkeypatch.syspath_prepend(str(AGENT.parent / 'team'))
    monkeypatch.syspath_prepend(str(AGENT))
    from superyak_agent.kick import Kick
    store, clock, ids, room = lessons_station
    rio = ids['rio-grande']
    assert store.unread(rio, 'session', 30, breakouts=True)['messages'] == []   # the session's cursor, before anything
    with pytest.raises(Problem, match='mentions no one'):
        store.send_message(ids['tardis'], room, 'x1', lesson_body(claim='Ask @rio-grande first.'))
    first = store.send_message(ids['tardis'], room, 'c1', lesson_body())['id']
    with pytest.raises(Problem, match='no reply label'):
        store.send_message(ids['tardis'], room, 'x2', lesson_body(claim='Two.'), reply_to=first)
    store.send_message(ids['tardis'], room, 'c2', lesson_body(claim='Two.'))
    talk = store.create_room(ids['andy'], 'Talk', [rio])['id']
    mine = store.send_message(rio, talk, 'm0', 'my post')['id']
    mention = store.send_message(ids['andy'], talk, 'm1', '@rio-grande look')['id']
    reply = store.send_message(ids['andy'], talk, 'm2', 'seen it', reply_to=mine)['id']

    class Stop(BaseException):
        pass

    class Client:   # the kick's StationClient, answered by the store in process
        def __init__(self):
            self.reads, self.flags = [], []

        def unread(self, cursor, limit=30, wait=0, breakouts=None):
            if self.reads:
                raise Stop()
            self.flags.append(breakouts)
            self.reads.append(store.unread(rio, cursor, limit, breakouts=breakouts == 'mentions'))
            return self.reads[-1]

        def advance(self, cursor, to):
            return store.advance(rio, cursor, to)

    client, lines = Client(), []
    with pytest.raises(Stop):
        Kick(client, 'rio-grande', out=lines.append, clock=lambda: clock[0], sleep=lambda s: None).run()
    assert client.flags == [None]   # the kick never asks for breakouts=mentions
    seen = client.reads[0]['messages']
    assert [m['room_title'] for m in seen] == ['Lessons', 'Lessons', 'Talk', 'Talk']   # the lessons reach it, and pass it
    assert not any(m.get('mentions_me') or m.get('replies_to_me') for m in seen if m['room_title'] == 'Lessons')
    assert lines == [f'station: kick {mention} in Talk from andy (mentions rio-grande)',
                     f'station: kick {reply} in Talk from andy (replies to rio-grande)']
    session = store.unread(rio, 'session', 30, breakouts=True)   # the kick's cursor moved; the session's didn't
    assert session['lesson_count'] == 2 and [m['body'] for m in session['messages']] == ['@rio-grande look', 'seen it']
    assert [m.get('replies_to_me') for m in session['messages']] == [None, True]
