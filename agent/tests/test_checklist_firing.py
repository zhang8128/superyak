"""Checklists: the shared record, when a list is due, and the logs (spec, Firing, exactly; the ships' hold seam)."""
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
import pytest
from superyak_agent import checklist_firing as fp, holds, hook
from checklist_fakes import loaded

H = 3600.0
AGENT = Path(__file__).resolve().parents[1]


def names(due):
    return [l.checklist.id for l, _ in due]


def fresh(now=0.0, source=None):
    record = {}
    holds.touch(record, now, None)
    fp.begin(record, source)
    return record


def test_start_is_due_only_after_a_startup_clear_or_fork():
    lists = [loaded('s', 'start')]
    for source in fp.START_SOURCES:
        assert names(fp.due_at_event(lists, fresh(source=source), None, 0.0)) == ['s']
    for source in ('resume', 'compact', None):
        assert fp.due_at_event(lists, fresh(source=source), None, 0.0) == []


def test_start_and_enter_fire_once_a_session_and_clear_forgets_start(tmp_path):
    lists = [loaded('s', 'start'), loaded('e', 'enter', location=tmp_path)]
    record = fresh(source='startup')
    due = fp.due_at_event(lists, record, str(tmp_path), 0.0)
    assert [(l.checklist.id, kinds) for l, kinds in due] == [('e', ('enter',)), ('s', ('start',))]
    fp.mark_fired(record, due, 0.0)
    fp.begin(record, 'resume')
    assert fp.due_at_event(lists, record, str(tmp_path), 60.0) == []
    fp.begin(record, 'clear')
    assert names(fp.due_at_event(lists, record, str(tmp_path), 120.0)) == ['s']


def test_every_first_fires_n_hours_after_the_first_event_then_n_hours_after_it_last_fired():
    lists, record = [loaded('reflect', 'every 3h')], fresh(0.0)
    assert fp.due_at_event(lists, record, None, 3 * H - 1) == []
    due = fp.due_at_event(lists, record, None, 3 * H)
    assert names(due) == ['reflect']
    fp.mark_fired(record, due, 3 * H + 600)
    assert fp.due_at_event(lists, record, None, 6 * H + 599) == []
    assert names(fp.due_at_event(lists, record, None, 6 * H + 600)) == ['reflect']


def test_due_lists_come_longest_wait_first_then_nearest_then_by_id():
    lists = [loaded('far-old', 'every 1h', order=1), loaded('near-b', 'every 1h'), loaded('near-a', 'every 1h'),
             loaded('far-tie', 'every 1h', order=1)]
    record = fresh(0.0)
    fp.mark_fired(record, [(l, ('every',)) for l in lists[1:]], 1 * H)
    assert names(fp.due_at_event(lists, record, None, 2 * H)) == ['far-old', 'near-a', 'near-b', 'far-tie']


def test_a_deferred_list_is_not_starved_over_a_day():
    lists = [loaded('why-we-build', 'start; every 3h', read='yes', body='Why.'), loaded('each-hour', 'every 1h'),
             loaded('reflect', 'every 3h')]
    record, fired = fresh(0.0, 'startup'), {l.checklist.id: [] for l in lists}
    for n in range(24 * 6 + 1):                                 # an event every 10 minutes for a day
        due = fp.due_at_event(lists, record, None, n * 600.0)[:fp.LISTS_PER_EVENT]
        fp.mark_fired(record, due, n * 600.0)
        for l, _ in due:
            fired[l.checklist.id].append(n * 600.0)
    for list_id, hours in (('each-hour', 1), ('reflect', 3), ('why-we-build', 3)):
        for start in range(hours, 24, hours):
            assert any(start * H <= t < (start + hours) * H for t in fired[list_id]), (list_id, start)


def test_a_command_list_holds_each_distinct_command_once_and_a_deferred_list_passes_it():
    lists = [loaded('a', 'command git push'), loaded('b', 'command git push'), loaded('c', 'command git push')]
    record = fresh()
    due, digest = fp.due_at_command(lists, record, 'git push origin x', 10.0)
    assert names(due) == ['a', 'b', 'c'] and digest == hashlib.sha256(b'git push origin x').hexdigest()
    fp.mark_fired(record, due[:2], 10.0, digest=digest)
    fp.mark_passed(record, due[2:], digest)
    assert fp.due_at_command(lists, record, 'git push origin x', 20.0)[0] == []
    assert record['fired'][lists[0].key]['version'] == 1
    assert names(fp.due_at_command(lists, record, 'git push origin y', 30.0)[0])[0] == 'c'
    assert fp.due_at_command(lists, record, 'ls', 40.0)[0] == []


def test_claim_fires_once_for_each_item_and_never_on_a_renewal():
    lists, record = [loaded('before-work', 'claim')], fresh()
    item = fp.item_key('r1', 'build:a')
    fp.mark_fired(record, fp.due_at_claim(lists, record, item, 1.0), 1.0, item=item)
    assert fp.due_at_claim(lists, record, item, 2.0) == []
    assert names(fp.due_at_claim(lists, record, fp.item_key('r1', 'build:b'), 3.0)) == ['before-work']


def test_the_record_is_private_written_in_place_and_keeps_first_seen_and_cwd(tmp_path):
    path = holds.record_path(tmp_path / 'sessions', 'abc')
    assert path == tmp_path / 'sessions' / 'ba7816bf8f01cfea.holds'
    with holds.open_record(path, time.monotonic() + 1) as rec:
        holds.touch(rec.data, 5.0, '/x')
        rec.save()
    inode = path.stat().st_ino
    with holds.open_record(path, time.monotonic() + 1) as rec:
        holds.touch(rec.data, 9.0, '/y')
        rec.save()
    with holds.open_record(path, time.monotonic() + 1) as rec:
        holds.touch(rec.data, 12.0, '/z')                    # no save: nothing written
    data = json.loads(path.read_text())
    assert path.stat().st_ino == inode and oct(path.stat().st_mode & 0o777) == '0o600'
    assert oct((tmp_path / 'sessions').stat().st_mode & 0o777) == '0o700'
    assert (data['first'], data['seen'], data['cwd']) == (5.0, 9.0, '/y')


@pytest.mark.parametrize('damaged', [b'', b'{', b'[]', b'null', b'\xff'])
def test_a_damaged_record_counts_as_empty(tmp_path, damaged):
    path = holds.record_path(tmp_path, 'abc')
    path.write_bytes(damaged)
    with holds.open_record(path, time.monotonic() + 1) as rec:
        assert rec.data == {}


def test_a_held_record_times_out_at_the_deadline(tmp_path):
    path = holds.record_path(tmp_path, 'abc')
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        with holds.open_record(path, started + 0.1):
            pass
    assert time.monotonic() - started < 0.5
    os.close(fd)


def test_a_record_unlinked_while_waiting_for_its_lock_is_reopened(tmp_path):           # plan review S2
    path = holds.record_path(tmp_path, 'abc')
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)

    def writer():
        with holds.open_record(path, time.monotonic() + 5) as rec:
            holds.touch(rec.data, 2.0, '/after')
            rec.save()
    waiting = threading.Thread(target=writer)
    waiting.start()
    time.sleep(0.1)
    path.unlink()                                             # a _prune elsewhere
    os.close(fd)
    waiting.join(5)
    assert json.loads(path.read_text())['cwd'] == '/after'


WRITER = ('import sys, time\nfrom pathlib import Path\nfrom superyak_agent import holds\n'
          'with holds.open_record(Path(sys.argv[1]), time.monotonic() + 10) as r:\n'
          '    r.data.setdefault("passed", {}).setdefault("k", []).append(sys.argv[2])\n'
          '    r.data["holds"] = r.data.get("holds", 0) + 1\n'
          '    r.save()\n')


def test_parallel_writers_never_lose_an_update(tmp_path):                       # Review Focus 2
    path = holds.record_path(tmp_path, 'abc')
    writers = [subprocess.Popen([sys.executable, '-c', WRITER, str(path), f'd{n}'], cwd=AGENT) for n in range(8)]
    assert [w.wait(30) for w in writers] == [0] * 8
    record = json.loads(path.read_text())
    assert sorted(record['passed']['k']) == [f'd{n}' for n in range(8)] and record['holds'] == 8


APPENDER = ('import sys\nfrom pathlib import Path\nfrom superyak_agent import holds\n'
            'for n in range(200):\n    holds.append_line(Path(sys.argv[1]), {"n": n, "pad": "x" * 300})\n')


def test_log_lines_are_private_and_whole_under_concurrent_appends(tmp_path):
    path = tmp_path / 'checklists' / 'fired.jsonl'
    writers = [subprocess.Popen([sys.executable, '-c', APPENDER, str(path)], cwd=AGENT) for _ in range(6)]
    assert [w.wait(30) for w in writers] == [0] * 6
    lines = path.read_text().splitlines()
    assert len(lines) == 1200 and all(json.loads(line)['pad'] == 'x' * 300 for line in lines)
    assert oct(path.stat().st_mode & 0o777) == '0o600'


def test_firing_and_miss_lines_hold_exactly_their_fields():
    assert fp.fired_line(5.0, 's', 'k/reflect', 2, 'every') == {'time': 5.0, 'session': 's', 'key': 'k/reflect', 'version': 2, 'moment': 'every'}
    assert fp.miss_line(5.0, 's', 'time') == {'time': 5.0, 'session': 's', 'miss': 'time'}
    assert fp.miss_line(5.0, 's', 'space', 'k/reflect', 2) == {'time': 5.0, 'session': 's', 'key': 'k/reflect', 'version': 2, 'miss': 'space'}


def test_the_output_budget_is_the_hooks():
    assert holds.OUTPUT_CHARS == hook.TOTAL_CHARS


def test_a_holds_file_ages_by_its_mtime_when_it_has_no_usable_seen(tmp_path):
    folder = tmp_path / 'sessions'
    folder.mkdir()
    old, young, saved = (holds.record_path(folder, n) for n in ('old', 'young', 'saved'))
    for path in (old, young):
        path.write_text('{')
    os.utime(old, (1.0, 1.0))
    with holds.open_record(saved, time.monotonic() + 1) as rec:
        holds.touch(rec.data, time.time() - 15 * 86400, None)
        rec.save()
    hook._prune(folder, None, time.time())
    assert sorted(p.name for p in folder.iterdir()) == [young.name]


def test_only_notices_shown_are_told():
    record = {}
    fp.mark_told(record, ['shown'])
    assert fp.told(record, 'shown') and not fp.told(record, 'cut for space')


def test_the_wheel_names_the_new_modules():
    text = (AGENT / 'pyproject.toml').read_text()
    for name in ('holds', 'checklist_firing'):
        assert f'"superyak_agent/{name}.py"' in text
