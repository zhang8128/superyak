"""The timing check's script (C37, review M2): its fixture is the bound, its measures and report, the embedder's
restart, and the hook's in-process path run for real."""
import json
import runpy
import subprocess
import sys
from pathlib import Path
import pytest
from superyak_peer import lessons
from conftest import LESSON_TIME, lesson_body

TIMING = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts' / 'lessons_timing.py'))


def test_the_fixture_is_the_bound(tmp_path, fake_embedder):
    clock = TIMING['Clock'](1_800_000_000.0)
    built = TIMING['build_fixture'](tmp_path / 'peer', fake_embedder.path, clock)
    assert built == {'status': 'written', 'lessons': 128, 'vectors': 128}
    index = lessons.read_index(tmp_path / 'peer' / lessons.INDEX_FILE)
    body = TIMING['bound_lesson']('rio-grande', 31)
    parsed = lessons.parse_post(body)
    assert len(parsed.claim.encode()) == 160 and len(parsed.why.encode()) == 300 and len(parsed.file) == 8
    assert len(body.encode()) <= 4096 and sorted(index['ships']) == sorted(TIMING['SHIPS'])
    request = TIMING['requests']()
    assert [len(request['query'][f]) for f in ('cwd', 'branch', 'command', 'error')] == [200, 200, 300, 300]
    assert len(request['prompt']['prompt']) == 2000


def test_measure_spawns_each_run_with_its_own_spawn_time_and_the_report_gates_the_hook_path():
    ticks, seen = iter(range(0, 10_000, 5)), []
    def fake(argv, **kwargs):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=b'{"lessons": []}', stderr=b'peak-kib 20480\n')
    walls = iter(float(n) for n in range(100))
    first, rest, peak = TIMING['measure'](['hook', TIMING['SPAWNED']], {'ship': 'x'}, 50, run=fake,
                                          timer=lambda: next(ticks) / 1000, wall=lambda: next(walls))
    assert first == 5 and len(rest) == 50 and peak == 20.0 and [a[1] for a in seen[:2]] == ['0.0', '1.0']
    assert TIMING['p95']([float(n) for n in range(1, 51)]) == 48.0
    text = TIMING['report']({'query': (900.0, [100.0] * 50, 40.0), 'hook': (90.0, [200.0] * 50, 20.0),
                             'prompt': (300.0, [300.0] * 50, 20.0)}, (400.0, [120.0] * 50))
    lines = text.splitlines()
    assert lines[1].endswith('p95 under 150 ms: NO') and lines[2].endswith('not gated') and text.endswith('FAIL')
    assert 'NEAR=off' in lines[4]
    good = TIMING['report']({'query': (900.0, [100.0] * 50, 40.0), 'hook': (90.0, [90.0] * 50, 20.0),
                             'prompt': (300.0, [300.0] * 50, 20.0)}, (90.0, [60.0] * 50))
    assert good.endswith('PASS') and 'Near can finish' in good   # the subprocess path over 150 ms doesn't fail it


def test_the_restart_waits_until_the_embedder_answers(fake_embedder):
    calls, clock = [], [0.0]
    TIMING['restart']('superyak-embedder', fake_embedder.path, run=lambda argv, check: calls.append(argv),
                      clock=lambda: clock[0], sleep=lambda s: None)
    assert calls == [['systemctl', '--user', 'restart', 'superyak-embedder']]
    def later(seconds):
        clock[0] += seconds
    with pytest.raises(SystemExit, match='did not answer'):
        TIMING['restart']('superyak-embedder', fake_embedder.path.with_name('gone'), run=lambda argv, check: None,
                          clock=lambda: clock[0], sleep=later)


def test_the_embedders_own_time_is_measured_on_the_prompt(fake_embedder):
    ticks = iter(range(0, 1000, 7))
    first, rest = TIMING['measure_embed'](fake_embedder.path, 'p' * 2000, 3, timer=lambda: next(ticks) / 1000)
    assert first == pytest.approx(7) and rest == pytest.approx([7, 7, 7]) and [len(r['texts'][0]) for r in fake_embedder.requests] == [2000] * 4


def test_the_hook_path_runs_in_a_fresh_interpreter_without_site_packages(lessons_station):
    store, clock, ids, room = lessons_station
    store.send_message(ids['tardis'], room, 'c1', lesson_body(claim='Words.', error=('no matches found',)))
    store.lessons_index(None)
    pinned = repr(LESSON_TIME + 10)
    hook = [sys.executable, '-I', '-S', '-B', '-c', TIMING['HOOK'], TIMING['SPAWNED'], str(TIMING['CHECKOUT']),
            str(store.data_dir), '/nonexistent', pinned]
    first, rest, peak = TIMING['measure'](hook, {'ship': 'rio-grande', 'prompt': 'why does it say no matches found', 'seen': []},
                                          1, wall=lambda: LESSON_TIME + 10)
    assert len(rest) == 1 and 0 < peak < 64


# Reviews B and C: two more measures at the bound, reported beside the gated paths.
def test_could_hold_is_timed_in_process_at_the_bound(tmp_path, fake_embedder):
    """Review C, concern 3: could_hold's own time, in process, against the bound's index (4 ships x 32 lessons, every
    command value 120 bytes). The request's command matches nothing, so each call reads and scans the whole index; a
    command holding another ship's value would hold."""
    clock, data = TIMING['Clock'](1_800_000_000.0), tmp_path / 'peer'
    TIMING['build_fixture'](data, fake_embedder.path, clock)
    ticks = iter(range(0, 10_000, 3))
    first, rest, held = TIMING['measure_could_hold'](data, TIMING['requests']()['query']['command'], 3,
                                                     timer=lambda: next(ticks) / 1000)
    assert first == pytest.approx(3) and rest == pytest.approx([3, 3, 3]) and held is False
    other = 'grep ' + TIMING['value']('command', 'tardis', 5, 2, 120)
    assert TIMING['measure_could_hold'](data, other, 0)[2] is True
    assert TIMING['measure_could_hold'](data, 'grep ' + TIMING['value']('command', 'rio-grande', 5, 2, 120), 0)[2] is False  # its own


def test_one_door_is_timed_with_the_room_at_the_bound(tmp_path, fake_embedder):
    """Review B, concern 3: a post into the lessons room through send_message, whose door rebuilds the room's history
    in its transaction, with the room at the bound; and the door's checks alone (check_lesson), which post nothing.
    Each post re-lays one of a ship's own lessons, so it passes every check and the live lessons stay at the bound."""
    from superyak_peer.db import Store
    clock, data = TIMING['Clock'](1_800_000_000.0), tmp_path / 'peer'
    TIMING['build_fixture'](data, fake_embedder.path, clock)
    door = TIMING['measure_door'](data, clock, 3)
    assert set(door) == {'post', 'checks'} and all(len(rest) == 3 and first > 0 for first, rest in door.values())
    store = Store(data, clock=clock)
    assert len(store.lessons_list()) == 128
    with store.transaction() as db:
        room = store._lessons_chain(db)[-1]
        assert db.execute('SELECT count(*) FROM messages WHERE room_id=?', (room,)).fetchone()[0] == 128 + 4


def test_the_two_measures_are_reported_beside_and_gate_nothing():
    results = {'query': (900.0, [100.0] * 50, 40.0), 'hook': (90.0, [90.0] * 50, 20.0), 'prompt': (300.0, [300.0] * 50, 20.0)}
    slow = {'post': (9000.0, [9000.0] * 50), 'checks': (8000.0, [8000.0] * 50)}
    text = TIMING['report'](results, (90.0, [60.0] * 50), (5000.0, [5000.0] * 50, False), slow)
    lines = text.splitlines()
    assert text.endswith('PASS') and len(lines) == 8 and lines[:5] == TIMING['report'](results, (90.0, [60.0] * 50)).splitlines()[:5]
    assert lines[5].startswith('could_hold, in process at the bound: first 5000 ms; 50 calls') and 'held: no' in lines[5]
    assert lines[6].startswith('door at the bound, one post into the lessons room: first 9000 ms; 50 posts')
    assert 'its checks alone (check_lesson) p95 8000 ms' in lines[6]
    assert all(line.endswith('gates nothing') for line in lines[5:7])
    failed = TIMING['report']({**results, 'hook': (90.0, [200.0] * 50, 20.0)}, None, (1.0, [1.0] * 50, False),
                              {'post': (1.0, [1.0] * 50), 'checks': (1.0, [1.0] * 50)})
    assert failed.endswith('FAIL')
