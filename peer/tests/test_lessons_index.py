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
