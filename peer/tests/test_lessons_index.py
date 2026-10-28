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
