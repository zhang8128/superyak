"""Checklists: the hold entry, its checklists provider and the seam lessons share (spec, The hold; the ships' seam)."""
import io
import json
import os
import random
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
import pytest
from superyak_agent import acting, checklist_firing as fp, checklists as cl, hold, holds, hook, lessons_hold
from checklist_fakes import checkout, trust_dirs, write_list
from test_ship_hook_claims import Ships

AGENT = Path(__file__).resolve().parents[1]
RUN_AGENT = AGENT / 'run_agent.py'
BASE = '- [ ] Base on 60dd851.'


@pytest.fixture
def ship():
    home = Path.home() / '.superyak'
    repo = checkout(Path.home() / 'Projects' / 'superyak',
                    ('before-push', {'when': 'command git push', 'version': 3, 'items': ('Base on 60dd851.',)}),
                    ('merging-to-main', {'when': 'command git push origin main', 'items': ('Verdict posted.',)}))
    trust_dirs(home / 'checklists', repo / '.superyak' / 'checklists')
    (home / 'station.json').write_text('{}')                      # docked: the hold acts only in a ship home (Ruling 44)
    return SimpleNamespace(home=home, repo=repo)


def payload(ship, command, **extra):
    return {'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'session_id': 's1', 'cwd': str(ship.repo),
            'tool_input': {'command': command}, **extra}


def decide(ship, command, now=10.0, lessons=None, **extra):
    return hold.decide(payload(ship, command, **extra), ship.home, now, time.monotonic(), lessons=lessons)


def saved(ship):
    return json.loads(holds.record_path(ship.home / 'sessions', 's1').read_text())


def test_a_matching_command_is_held_once_in_the_rails_words(ship):
    out = decide(ship, 'git push origin feature')
    spec = out['hookSpecificOutput']
    assert set(out) == {'hookSpecificOutput'} and set(spec) == {'hookEventName', 'permissionDecision', 'permissionDecisionReason'}
    assert (spec['hookEventName'], spec['permissionDecision']) == ('PreToolUse', 'deny')
    reason = spec['permissionDecisionReason']
    assert reason.startswith('Held once: checklist before-push v3 applies. It is a checklist, not a refusal.\n\nChecklist ')
    assert reason.endswith('\n\nRe-run the same command if you still want it.') and BASE in reason


def test_the_re_run_passes_and_prints_nothing(ship):
    assert decide(ship, 'git push origin feature') and decide(ship, 'git push origin feature', now=20.0) is None


def test_three_holds_a_session_then_lists_come_as_context_with_the_result(ship):
    outs = [decide(ship, f'git push origin b{n}', now=10.0 + n)['hookSpecificOutput'] for n in range(5)]
    assert [o.get('permissionDecision') for o in outs] == ['deny'] * 3 + [None] * 2
    assert set(outs[3]) == {'hookEventName', 'additionalContext'} and BASE in outs[3]['additionalContext']


def test_past_the_cap_merging_to_main_still_shows_at_git_push_origin_main(ship):
    for n in range(3):
        decide(ship, f'git push origin b{n}', now=10.0 + n)
    context = decide(ship, 'git push origin main', now=20.0)['hookSpecificOutput']['additionalContext']
    assert '- [ ] Verdict posted.' in context and BASE in context


def test_lessons_share_the_cap_and_get_three_minus_the_checklists_in_the_deny(ship):     # the ships' seam
    asked = []

    def lessons(command, record, now, limit):
        asked.append(limit)
        key = f'lesson:{command}'
        record.setdefault('lessons', []).append(key)
        head = 'Held once: lesson L1 from tardis applies.' if limit == 3 else 'Lesson L1 from tardis'
        return [holds.Hold('lesson', key, f'{head}\n[the fenced lesson for {command}]')]
    one = decide(ship, 'git push origin a', lessons=lessons)['hookSpecificOutput']['permissionDecisionReason']
    assert one.startswith('Held once: checklist before-push') and one.index('Checklist ') < one.index('Lesson L1 from tardis')
    two = decide(ship, 'npm test', now=11.0, lessons=lessons)['hookSpecificOutput']['permissionDecisionReason']
    assert two.startswith('Held once: lesson L1 from tardis applies.') and 'Checklist ' not in two
    three = decide(ship, 'git push origin main', now=12.0, lessons=lessons)['hookSpecificOutput']
    assert three['permissionDecision'] == 'deny' and three['permissionDecisionReason'].count('\nChecklist ') == 2
    four = decide(ship, 'git push origin b', now=13.0, lessons=lessons)['hookSpecificOutput']
    assert set(four) == {'hookEventName', 'additionalContext'} and 'Lesson' not in four['additionalContext']
    assert decide(ship, 'npm run build', now=14.0, lessons=lessons) is None
    assert asked == [2, 3, 1]                  # 3 minus the checklists in the deny; not asked once no hold is left
    record = saved(ship)
    assert record['holds'] == 3 and record['lessons'] == ['lesson:git push origin a', 'lesson:npm test', 'lesson:git push origin main']


def test_the_lessons_stub_returns_nothing():
    assert lessons_hold.candidates('git push origin x', {}, 0.0, 3) == []


def test_never_allow_ask_or_updated_input_across_many_commands(ship):
    rng, seen = random.Random(7), set()
    words = ['git', 'push', 'origin', 'main', ';', '&&', '|', '(', '`', '"', "'", 'echo', 'ls', 'x']
    for n in range(300):
        out = decide(ship, ' '.join(rng.choice(words) for _ in range(rng.randint(1, 8))), now=float(n))
        if out is not None:
            spec = out['hookSpecificOutput']
            assert set(out) == {'hookSpecificOutput'} and spec['hookEventName'] == 'PreToolUse'
            assert spec.get('permissionDecision') in (None, 'deny') and 'updatedInput' not in json.dumps(out)
            assert set(spec) <= {'hookEventName', 'permissionDecision', 'permissionDecisionReason', 'additionalContext'}
            seen.add(spec.get('permissionDecision', 'context'))
    assert seen == {'deny', 'context'}                                   # plan review S11: it asserted something


def test_a_subagent_is_never_held(ship):
    assert decide(ship, 'git push origin x', agent_id='a1', agent_type='Explore') is None


@pytest.mark.parametrize('bad', [{'tool_name': 'Read'}, {'hook_event_name': 'PostToolUse'}, {'tool_input': {'command': 5}},
                                 {'tool_input': 'git push'}, {'session_id': None}])
def test_anything_but_a_main_agents_bash_call_prints_nothing(ship, bad):
    assert hold.decide({**payload(ship, 'git push x'), **bad}, ship.home, 10.0, time.monotonic()) is None


@pytest.mark.parametrize('stdin', ['', 'not json', '[]', '{"tool_input": {"command": 5}}'])
def test_malformed_input_exits_0_and_prints_nothing(ship, stdin):                        # plan review S9
    out = io.StringIO()
    assert hold.main(['--config', str(ship.home / 'station.json')], stdin=io.StringIO(stdin), stdout=out) == 0
    assert out.getvalue() == ''


def test_no_hold_in_a_watcher_or_teamd_run(ship, monkeypatch):
    monkeypatch.setenv('SUPERYAK_RUN', '1')
    assert decide(ship, 'git push origin x') is None


def test_past_its_read_time_it_prints_nothing_and_never_hangs(ship, monkeypatch):     # Review Focus 3
    never = threading.Event()
    monkeypatch.setattr(cl, 'find', lambda *a, **k: never.wait())
    began = time.monotonic()
    assert decide(ship, 'git push origin x') is None and time.monotonic() - began < 1.2
    never.set()
    monkeypatch.undo()
    assert hold.decide(payload(ship, 'git push origin x'), ship.home, 10.0, time.monotonic() - 0.2) is None


def test_a_hung_registry_or_cwd_read_never_stalls_the_bash_call(ship, monkeypatch):    # Review Focus 3, plan review M2
    never = threading.Event()
    monkeypatch.setattr(acting, 'verdict', lambda *a, **k: never.wait())
    began = time.monotonic()
    assert decide(ship, 'git push origin x') is None and time.monotonic() - began < 1.2
    never.set()


def test_past_one_second_it_prints_nothing_and_records_no_hold(ship):
    def slow(command, record, now, limit):
        time.sleep(1.1)
        return []
    assert decide(ship, 'git push origin x', lessons=slow) is None
    time.sleep(0.3)                                     # the abandoned worker lets go of the record
    assert decide(ship, 'git push origin x', now=20.0)['hookSpecificOutput']['permissionDecision'] == 'deny'


def test_a_slow_log_append_never_hides_a_recorded_hold(ship, monkeypatch):               # plan review S1
    real = holds.append_line
    monkeypatch.setattr(holds, 'append_line', lambda path, line: (time.sleep(1.5), real(path, line)))
    out = decide(ship, 'git push origin x')
    assert out['hookSpecificOutput']['permissionDecision'] == 'deny' and saved(ship)['holds'] == 1


def test_a_list_edited_between_the_hold_and_the_re_run_lets_it_pass(ship):            # Review Focus 4
    assert decide(ship, 'git push origin x')
    write_list(ship.repo / '.superyak' / 'checklists', 'before-push', when='command git push', version=4,
               items=('Base on 60dd851.', 'A new item.'))
    assert decide(ship, 'git push origin x', now=20.0) is None


def test_parallel_holds_never_pass_three(ship, monkeypatch):                          # Review Focus 2
    monkeypatch.setattr(fp, 'READ_SECONDS', 5.0)        # plan review S5: this pins the cap, not the clock
    monkeypatch.setattr(fp, 'HOLD_SECONDS', 5.0)
    gate, outs = threading.Barrier(6), [None] * 6

    def one(n):
        gate.wait()
        outs[n] = decide(ship, f'git push origin p{n}', now=10.0 + n)
    threads = [threading.Thread(target=one, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    decisions = [o['hookSpecificOutput'].get('permissionDecision') for o in outs]
    assert decisions.count('deny') == 3 and decisions.count(None) == 3 and saved(ship)['holds'] == 3


def test_the_hold_never_runs_anything_from_a_list(ship, monkeypatch):
    def refuse(*a, **k):
        raise AssertionError('ran something')
    for target, name in ((subprocess, 'run'), (subprocess, 'Popen'), (os, 'system')):
        monkeypatch.setattr(target, name, refuse)
    write_list(ship.repo / '.superyak' / 'checklists', 'sneaky', when='command git push', items=('$(touch x) `rm -rf ~`',))
    assert '$(touch x)' in decide(ship, 'git push origin x')['hookSpecificOutput']['permissionDecisionReason']


PROBE = ('import atexit, runpy, sys\n'
         'atexit.register(lambda: sys.stderr.write("MODULES " + " ".join(sorted(sys.modules)) + "\\n"))\n'
         'sys.argv = [sys.argv[1], "hold", "--config", sys.argv[2]]\n'
         'runpy.run_path(sys.argv[0], run_name="__main__")\n')


@pytest.mark.parametrize('command, shows', [('ls -la', False), ('git push origin x', True)])
def test_the_hold_imports_no_station_claims_or_network(ship, command, shows):
    done = subprocess.run([sys.executable, '-c', PROBE, str(RUN_AGENT), str(ship.home / 'station.json')],
                          input=json.dumps(payload(ship, command)), capture_output=True, text=True, timeout=30)
    modules = set(done.stderr.split('MODULES ', 1)[1].split())
    assert done.returncode == 0 and bool(done.stdout) == shows
    assert not modules & {'superyak_agent.station', 'superyak_agent.claims', 'superyak_agent.hook', 'urllib.request', 'http.client'}
    assert ('superyak_team.teamlib' in modules) == shows                # the fence loads only to show a list


@pytest.fixture
def ships(monkeypatch, tmp_path, station, ship_config):
    return Ships(monkeypatch, tmp_path, station, ship_config)


def test_the_hook_and_the_hold_agree_on_which_ship_acts(ships):
    for config in (ships.machine_config, ships.project_config):
        write_list(Path(config).parent / 'checklists', 'mine', when='start; command git push')
    for n, where in enumerate((ships.repo, ships.repo / 'sub', ships.wt, ships.elsewhere, ships.plain)):
        for config in (ships.machine_config, ships.project_config):
            home = Path(config).parent
            sid = f's{n}-{home.name}'
            shown = '- [ ] Do the thing.' in hook.run(config, transport=ships.fake, event='session-start', source='startup',
                                                      session_id=sid, cwd=str(where))
            held = hold.decide({'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'session_id': sid, 'cwd': str(where),
                                'tool_input': {'command': 'git push origin x'}}, home, 10.0, time.monotonic()) is not None
            assert shown == held, (where, home)


# Beyond the brief: the amendments (record['session'], lessons isolation), Ruling 34's placement, the log line, a
# locked record, an unreadable ships folder (Task 1's carry) and the dispatch in __main__.

def test_the_session_is_in_the_record_before_any_provider_is_asked(ship):
    seen = []

    def lessons(command, record, now, limit):
        seen.append(record.get('session'))
        return []
    decide(ship, 'git push origin x', lessons=lessons, transcript_path='/t/s1.jsonl')
    assert seen == [{'id': 's1', 'transcript': '/t/s1.jsonl'}] and saved(ship)['session'] == seen[0]
    decide(ship, 'git push origin y', now=11.0, lessons=lessons, transcript_path=7)
    assert seen[1] == {'id': 's1', 'transcript': None}


BROKEN = ['raises', 'not holds', 'over its limit', 'over its bytes', 'empty text', 'SystemExit', 'KeyboardInterrupt',
          'a set in the record']


@pytest.mark.parametrize('broken', BROKEN)
def test_a_failing_lessons_provider_never_silences_a_checklist(ship, broken):          # Ruling 44: dropped, never cut
    def lessons(command, record, now, limit):
        record.setdefault('lessons', []).append('half-done')
        if broken == 'raises':
            raise RuntimeError('lessons broke')
        if broken == 'SystemExit':
            raise SystemExit(2)
        if broken == 'KeyboardInterrupt':
            raise KeyboardInterrupt
        if broken == 'not holds':
            return [{'kind': 'lesson', 'key': 'k', 'text': 'not a Hold'}]
        if broken == 'over its limit':
            return [holds.Hold('lesson', f'k{n}', 'Lesson ' + 'z' * 1990) for n in range(5)]
        if broken == 'over its bytes':
            return [holds.Hold('lesson', 'k', 'Lesson ' + '\u00e9' * 997)]           # 1,004 characters, 2,001 bytes
        if broken == 'empty text':
            return [holds.Hold('lesson', 'k', '')]
        record['lessons'] = {'heads': {1, 2}}                                     # not JSON
        return [holds.Hold('lesson', 'k', 'Lesson L1 from tardis')]
    assert decide(ship, 'npm test', now=9.0, lessons=lessons) is None
    outs = [decide(ship, f'git push origin b{n}', now=10.0 + n, lessons=lessons)['hookSpecificOutput'] for n in range(5)]
    assert [o.get('permissionDecision') for o in outs] == ['deny'] * 3 + [None] * 2
    for out in outs[:3]:
        reason = out['permissionDecisionReason']
        assert reason.startswith('Held once: checklist before-push') and 'Lesson' not in reason and len(reason) <= 9500
    assert 'lessons' not in saved(ship) and saved(ship)['holds'] == 3


def test_a_lessons_provider_can_not_reset_the_cap(ship):                                   # Ruling 44
    def lessons(command, record, now, limit):
        record['holds'] = 0
        return [holds.Hold('lesson', f'k{now}', 'Lesson L1 from tardis')]
    outs = [decide(ship, f'git push origin b{n}', now=10.0 + n, lessons=lessons)['hookSpecificOutput'] for n in range(5)]
    assert [o.get('permissionDecision') for o in outs] == ['deny'] * 3 + [None] * 2 and saved(ship)['holds'] == 3
    assert all(o['permissionDecisionReason'].startswith('Held once: checklist') and len(o['permissionDecisionReason']) <= 9500
               for o in outs[:3])


@pytest.mark.parametrize('config', [None, '', 'station.json'])
def test_an_undocked_machine_is_never_touched(config, tmp_path, monkeypatch):           # Ruling 44
    repo = checkout(Path.home() / 'Projects' / 'superyak', ('before-push', {'when': 'command git push', 'items': ('x.',)}))
    trust_dirs(tmp_path / 'elsewhere', repo / '.superyak' / 'checklists')
    monkeypatch.chdir(tmp_path)
    call = {'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'session_id': 's1', 'cwd': str(repo),
            'tool_input': {'command': 'git push origin x'}}
    out = io.StringIO()
    assert hold.main([] if config is None else ['--config', config], stdin=io.StringIO(json.dumps(call)), stdout=out) == 0
    assert out.getvalue() == '' and not (Path.home() / '.superyak').exists() and sorted(tmp_path.iterdir()) == [tmp_path / 'elsewhere']


def test_a_reader_that_closed_stdout_still_gets_exit_0(ship):                           # Ruling 44
    proc = subprocess.Popen([sys.executable, str(RUN_AGENT), 'hold', '--config', str(ship.home / 'station.json')],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    proc.stdout.close()
    proc.stdout = None
    _, err = proc.communicate(json.dumps(payload(ship, 'git push origin x')).encode(), timeout=30)
    assert proc.returncode == 0 and saved(ship)['holds'] == 1, err


def test_the_hold_path_never_imports_argparse(ship):                                    # Ruling 44
    done = subprocess.run([sys.executable, '-c', PROBE, str(RUN_AGENT), str(ship.home / 'station.json')],
                          input=json.dumps(payload(ship, 'git push origin x')), capture_output=True, text=True, timeout=30)
    assert done.stdout and 'argparse' not in done.stderr.split('MODULES ', 1)[1].split()


def test_a_hold_logs_each_list_it_showed(ship):
    decide(ship, 'git push origin main')
    log = ship.home / 'checklists' / 'fired.jsonl'
    lines = [json.loads(line) for line in log.read_text().splitlines()]
    session = holds.record_path(ship.home / 'sessions', 's1').stem
    assert [(ln['key'].split('/')[1], ln['version'], ln['moment'], ln['session'], ln['time']) for ln in lines] == [
        ('before-push', 3, 'command', session, 10.0), ('merging-to-main', 1, 'command', session, 10.0)]
    assert set(lines[0]) == {'time', 'session', 'key', 'version', 'moment'} and log.stat().st_mode & 0o777 == 0o600


def big(n):
    return 'x' * n


@pytest.mark.parametrize('sizes, past, shown', [
    ((5300,), False, 1), ((5301,), False, 0),                 # one list beside two lessons' room: 5300 + 200 + 4000
    ((3000, 4298), False, 2), ((3000, 4299), False, 1),       # two beside one: 3000 + 2 + 4298 + 200 + 2000
    ((3000, 6498), True, 2), ((3000, 6499), True, 1),         # past the cap only the lists count: 9,500
    ((10, 10), False, 2)])
def test_lists_are_placed_whole_in_the_rest_of_the_budget(sizes, past, shown):                     # Ruling 34
    from checklist_fakes import loaded
    lists = tuple(loaded(f'l{n}', 'command git push', order=n) for n in range(len(sizes)))
    provider = hold.checklist_hold.ChecklistProvider(lists, {l.key: big(s) for l, s in zip(lists, sizes)})
    record = {'first': 0.0, 'holds': 3 if past else 0}
    got = provider.candidates('git push origin x', record, 10.0, 2)
    assert [h.kind for h in got] == ['checklist'] * shown and [h.key for h in got] == [l.key for l in lists[:shown]]
    digest = fp.command_digest('git push origin x')
    assert all(record['passed'][l.key] == [digest] for l in lists)           # placed or passed: the re-run passes
    assert [l.key in record.get('fired', {}) for l in lists] == [n < shown for n in range(len(lists))]


def test_a_locked_record_prints_nothing_in_time(ship):
    path = holds.record_path(ship.home / 'sessions', 's1')
    with holds.open_record(path, time.monotonic() + 1):
        began = time.monotonic()
        assert decide(ship, 'git push origin x') is None and time.monotonic() - began < 1.2
    assert decide(ship, 'git push origin x', now=20.0)['hookSpecificOutput']['permissionDecision'] == 'deny'


def test_a_record_taken_past_its_read_time_prints_nothing(ship):
    def late(real=time.monotonic):          # the worker's clock runs 0.5 s ahead: it takes the record past the 150 ms
        return real() + (0.5 if threading.current_thread().name == hold.WORKER else 0.0)
    assert hold.decide(payload(ship, 'git push origin x'), ship.home, 10.0, late(), monotonic=late) is None
    assert holds.record_path(ship.home / 'sessions', 's1').read_text() == ''


def test_an_unreadable_ships_folder_fails_quiet(ship):                                   # Task 1's review
    ships = acting.ships_root()
    ships.mkdir(parents=True)
    ships.chmod(0)
    try:
        began = time.monotonic()
        assert decide(ship, 'git push origin x') is None and time.monotonic() - began < 1.2
    finally:
        ships.chmod(0o700)


def test_main_dispatches_hold_first_and_ignores_unknown_flags(ship, monkeypatch, capsys):
    from superyak_agent import __main__ as entry
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(payload(ship, 'git push origin x'))))
    assert entry.main(['hold', '--surprise', '--config', str(ship.home / 'station.json'), '-x']) == 0
    out = json.loads(capsys.readouterr().out)
    assert out['hookSpecificOutput']['permissionDecision'] == 'deny'


def test_the_hold_is_named_in_help(capsys):
    from superyak_agent import __main__ as entry
    with pytest.raises(SystemExit):
        entry.main(['--help'])
    assert 'hold' in capsys.readouterr().out
