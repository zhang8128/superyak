"""The lessons side of the shared hold entry before a Bash command (first rail spec section 8, decision 8). The entry
is Serenity's (`run_agent.py hold`): it renders every Hold, keeps the cap of 3 a session and saves the record only when
it prints. The provider is tested here alone, with a plain record dict and the stub query."""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from superyak_agent import holds, lessons_hold, lessons_hook as lh
from test_lessons_hook import A, B, C, D, Rail, lesson, transcript_line

AGENT = Path(__file__).resolve().parents[1]
GLOB = '--include=*'  # the spec's illustration: a command value of 11 bytes
COMMAND = 'grep -rn --include=*.py TODO .'


def record(session='s1', rail=None, heads=(), holds=()):
    """The entry's per-session record as the provider gets it: `session` set by the entry, `lessons` its own, and the
    entry's count of denies, which the provider leaves alone."""
    return {'session': {'id': session, 'transcript': str(rail.transcript) if rail else None},
            'lessons': {'heads': list(heads), 'holds': list(holds)}, 'holds': 0}


@pytest.fixture
def rail(tmp_path):
    return Rail(tmp_path)


def yes(command, ship, data_dir):
    """A could_hold that always says some lesson's command value is in the command, so the stub query decides."""
    return True


def ask(rail, command=COMMAND, limit=3, rec=None, could_hold=yes, **fields):
    return lessons_hold.candidates(command, record(rail=rail, **fields) if rec is None else rec, time.time(), limit,
                                   settings=rail.settings, env={}, could_hold=could_hold)


def key(command, id_, session='s1'):
    return f'lesson:{lh.session_key(session)}:{lessons_hold.head_digest(command)}:{id_}'


def test_a_command_value_of_at_least_6_bytes_holds_once_with_the_specs_reason(rail):
    found = lesson(A, ship='serenity', command=GLOB)
    rail.answers(found)
    assert ask(rail) == [holds.Hold('lesson', key(COMMAND, A), lh.hold_reason(found))]
    [sent] = rail.sent()
    assert type(sent.pop('budget_ms')) is int
    assert sent == {'ship': 'tardis', 'command': COMMAND, 'words_only': True, 'limit': 3, 'seen': []}


def test_the_hold_sends_a_budget_net_of_its_own_time_and_the_childs_start(rail):
    """rail-room-confirm's S1 (Rio Grande's heads-up): the query stops at its own start + budget_ms, writing no receipt
    past it. Counted from the query's main(), that end comes after the hook's by the child's start-up, so the hook
    sends only what it has left less START_MARGIN: the query's deadline falls inside the hook's, and a commit after
    the hook gave up can't write a receipt for a lesson nobody saw."""
    rail.answers(lesson(A, command=GLOB))
    ask(rail)
    [sent] = rail.sent()
    assert 0 <= sent['budget_ms'] <= (lh.COMMAND_LIMIT - lessons_hold.START_MARGIN) * 1000


def test_a_spent_budget_is_sent_as_zero_never_negative(rail, monkeypatch):
    monkeypatch.setattr(lessons_hold, 'START_MARGIN', 5.0)  # more than the whole second: nothing left for the query
    rail.answers(lesson(A, command=GLOB))
    ask(rail)
    assert [s['budget_ms'] for s in rail.sent()] == [0]


def test_the_key_names_the_session_the_head_and_the_lesson(rail):
    rail.answers(lesson(A, command=GLOB))
    [hold] = ask(rail, command='FOO=1 grep -rn --include=*.md x')
    assert hold.key == key('grep -rn', A) == f'lesson:{lh.session_key("s1")}:{lh.digest("grep")}:{A}'


@pytest.mark.parametrize('found, holds', [
    (lesson(A, command='abcde'), False),  # 5 bytes
    (lesson(A, command='é' * 3), True),  # 6 bytes in 3 characters
    (lesson(A, command='--include=*.md'), False),  # not in the command
    (lesson(A), False),  # the answer doesn't say which value matched
    (lesson(A, command=GLOB, match=0.3), False),  # near, never words
])
def test_only_a_command_value_of_6_bytes_found_in_the_command_holds(rail, found, holds):
    rail.answers(found)
    assert bool(ask(rail, command=f'grep -rn {GLOB}.py ééé abcde x')) is holds


def test_a_head_seen_before_asks_nothing_so_a_re_run_passes(rail):
    rail.answers(lesson(A, command=GLOB))
    [hold] = ask(rail)
    rail.sent()
    assert ask(rail, heads=[lessons_hold.head_digest(COMMAND)]) == []  # what the entry recorded at the first run
    assert ask(rail, holds=[hold.key]) == []  # or only the hold it made
    assert ask(rail, command='grep -rn --include=*.md other', heads=[lessons_hold.head_digest(COMMAND)]) == []
    assert rail.sent() == []


def test_the_cap_of_3_a_session_is_the_entrys(rail):
    rail.answers(lesson(A, command=GLOB))
    made = [key('make test', B), key('uv run', C), key('npm test', D)]
    assert [h.key for h in ask(rail, holds=made)] == [key(COMMAND, A)]


def test_limit_0_never_calls_the_query(rail):
    rail.answers(lesson(A, command=GLOB))
    assert ask(rail, limit=0) == [] and rail.sent() == []


@pytest.mark.parametrize('limit', [1, 2, 3])
def test_the_request_carries_the_limit_and_at_most_that_many_come_back(rail, limit):
    rail.answers(*[lesson(i, command=GLOB) for i in (A, B, C)])
    assert len(ask(rail, limit=limit)) == limit
    assert rail.sent()[0]['limit'] == limit
    rail.flag('ignore-limit')  # a query that answers more: still no more than the limit
    assert len(ask(rail, limit=limit, session='s2')) == limit


@pytest.mark.parametrize('limit', [4, -1, True, 1.0, None])
def test_a_limit_outside_0_to_3_asks_nothing(rail, limit):
    rail.answers(lesson(A, command=GLOB))
    assert ask(rail, limit=limit) == [] and rail.sent() == []


def test_only_unseen_lessons_hold_one_budget_with_every_other_event(rail):
    """A shown at session start (the hook's record), B at a prompt (the transcript), C held at another head (the
    entry's record): only D may hold, even from a query that ignores `seen`."""
    rail.answers(lesson(A, ship='serenity'))
    assert lh.run(rail.event('SessionStart', cwd='/'), rail.settings, env={})
    rail.shown_at_prompt(lesson(B, ship='serenity'))
    rail.flag('ignore-seen')
    rail.flag('ignore-limit')
    rail.answers(*[lesson(i, command=GLOB) for i in (A, D, C)])  # an answer holds at most 3
    rail.sent()
    assert [h.key for h in ask(rail, holds=[key('make test', C)])] == [key(COMMAND, D)]
    rail.answers(*[lesson(i, command=GLOB) for i in (B, D)])
    assert [h.key for h in ask(rail, session='s1', holds=[key('make test', C)])] == [key(COMMAND, D)]
    assert rail.sent()[0]['seen'] == [A, B, C]


def test_a_slow_query_holds_nothing_within_1_s(rail):
    rail.answers(lesson(A, command=GLOB))
    rail.flag('sleep', '3')
    began = time.monotonic()
    assert ask(rail) == []
    assert time.monotonic() - began < 1.5


def test_now_is_the_entrys_wall_time_and_the_second_counts_from_the_call(rail):
    rail.answers(lesson(A, command=GLOB))
    rail.flag('sleep', '0.6')
    assert len(ask(rail)) == 1


@pytest.mark.parametrize('flag, text', [('exit', '3'), ('raw', 'not json')])
def test_a_failing_query_or_missing_index_holds_nothing(rail, flag, text):
    rail.answers(lesson(A, command=GLOB))
    rail.flag(flag, text)
    assert ask(rail) == []


def test_a_transcript_not_read_to_its_end_holds_nothing(rail):
    rail.transcript.mkdir()
    rail.answers(lesson(A, command=GLOB))
    assert ask(rail) == [] and rail.sent() == []


@pytest.mark.parametrize('value, holds', [('watch', False), ('teamd', False), ('hook', True), ('', True)])
def test_superyak_run_other_than_hook_holds_nothing(rail, value, holds):
    rail.answers(lesson(A, command=GLOB))
    got = lessons_hold.candidates(COMMAND, record(rail=rail), time.time(), 3, settings=rail.settings,
                                  env={'SUPERYAK_RUN': value}, could_hold=yes)
    assert bool(got) is holds and len(rail.sent()) == int(holds)


@pytest.mark.parametrize('bad', [None, [], {}, {'session': None}, {'session': 's1'}, {'session': {'id': ''}},
                                 {'session': {'id': 7}}, {'session': {'transcript': None}}])
def test_a_record_without_a_session_holds_nothing(rail, bad):
    rail.answers(lesson(A, command=GLOB))
    assert lessons_hold.candidates(COMMAND, bad, time.time(), 3, settings=rail.settings, env={}, could_hold=yes) == []


@pytest.mark.parametrize('command', ['', '   ', 'FOO=1', None, 7])
def test_no_head_holds_nothing(rail, command):
    rail.answers(lesson(A, command=GLOB))
    assert ask(rail, command=command) == [] and rail.sent() == []


def test_the_provider_writes_nothing(rail):
    rail.answers(lesson(A, command=GLOB))
    (rail.data / 'record').unlink()
    before = sorted(p.relative_to(rail.root) for p in rail.root.rglob('*'))
    assert ask(rail)
    assert sorted(p.relative_to(rail.root) for p in rail.root.rglob('*')) == before


def test_a_lessons_first_deny_opens_with_held_once_and_after_a_checklist_each_lesson_has_its_own_line(rail):
    """Ruling 35: limit 3 means no checklist leads the deny. The entry ends every deny with its re-run line."""
    first, second = lesson(A, ship='serenity', command=GLOB), lesson(B, command=GLOB)
    rail.answers(first, second)
    assert [h.text for h in ask(rail)] == [lh.hold_reason(first), lh.hold_reason(second, first=False)]
    assert [h.text for h in ask(rail, limit=2, session='s2')] == [lh.hold_reason(first, first=False),
                                                                  lh.hold_reason(second, first=False)]
    assert lh.hold_reason(first).startswith(f'Held once: lesson {A} from serenity applies.\n')
    assert lh.hold_reason(second, first=False).startswith(f'{lh.HEADING}\nLesson {B} from tardis\n')
    assert not any('Re-run' in lh.hold_reason(l, first=f) for l in (first, second) for f in (True, False))


def test_a_lesson_over_lesson_bytes_is_not_offered_and_the_next_one_opens_the_deny(rail, monkeypatch):
    short, long = lesson(B, command=GLOB), lesson(A, command=GLOB, claim='Quote every glob in zsh, always.')
    monkeypatch.setattr(holds, 'LESSON_BYTES', len(lh.hold_reason(short).encode()))
    rail.answers(long, short)
    assert [(h.key, h.text) for h in ask(rail)] == [(key(COMMAND, B), lh.hold_reason(short))]


def test_the_provider_records_what_it_returns_in_its_own_entries(rail):
    """Ruling 33. The entry saves only when it prints, so a hold it drops leaves no trace."""
    rail.answers(lesson(A, command=GLOB))
    rec = record(rail=rail, heads=['h0'], holds=[key('make test', C)])
    [hold] = ask(rail, rec=rec)
    assert rec == {**record(rail=rail), 'lessons': {'heads': ['h0', lessons_hold.head_digest(COMMAND)],
                                                    'holds': [key('make test', C), hold.key]}}
    rail.answers()
    rec = record(rail=rail)
    assert ask(rail, command='make test', rec=rec) == []
    assert rec['lessons'] == {'heads': [lessons_hold.head_digest('make test')], 'holds': []}  # asked, nothing held


@pytest.mark.parametrize('flag, text', [('exit', '3'), ('sleep', '3')])
def test_a_failing_or_late_query_records_nothing_so_the_head_asks_again(rail, flag, text):
    rail.answers(lesson(A, command=GLOB))
    rail.flag(flag, text)
    rec = record(rail=rail)
    assert ask(rail, rec=rec) == [] and rec == record(rail=rail)


def test_a_session_keeps_at_most_heads_max_heads(rail, monkeypatch):
    monkeypatch.setattr(lessons_hold, 'HEADS_MAX', 2)
    rail.answers()
    rec = record(rail=rail, heads=['h0', 'h1'])
    ask(rail, rec=rec)
    assert rec['lessons']['heads'] == ['h1', lessons_hold.head_digest(COMMAND)]


def raises(command, ship, data_dir):
    raise OSError('no index')


@pytest.mark.parametrize('could_hold', [lambda *a: False, lambda *a: None, lambda *a: 'yes', lambda *a: 1, raises])
def test_the_query_runs_only_when_could_hold_says_true(rail, could_hold):
    """Rio Grande's could_hold: an `ls` costs an index read in process, never the store's 360 ms, and writes nothing."""
    rail.answers(lesson(A, command=GLOB))
    rec = record(rail=rail)
    assert ask(rail, rec=rec, could_hold=could_hold) == [] and rail.sent() == [] and rec == record(rail=rail)


def test_could_hold_gets_the_command_as_the_query_would_the_ship_and_the_data_dir(rail):
    asked = []
    rail.answers(lesson(A, command=GLOB))
    long = COMMAND + ' ' + 'x' * 400
    assert ask(rail, command=long, could_hold=lambda *a: asked.append(a) or True)
    settings = json.loads(rail.settings.read_text())
    assert asked == [(long[:lh.CUTS['command']], 'tardis', settings['data_dir'])]
    assert rail.sent()[0]['command'] == long[:lh.CUTS['command']]


@pytest.mark.parametrize('module, said', [
    (None, ['False', 'False']),  # a checkout without the rail's lessons module
    ('def could_hold(command, ship, data_dir):\n'
     '    return command == "git push" and ship == "tardis" and data_dir == "/d"\n', ['True', 'False']),
    ('def could_hold(command, ship, data_dir):\n    raise OSError("index")\n', ['False', 'False']),
    ('def could_hold(command, ship, data_dir):\n    return "yes"\n', ['False', 'False']),
])
def test_peer_could_hold_is_the_checkouts_lessons_in_process_writing_no_bytecode(tmp_path, module, said):
    package = tmp_path / 'peer' / 'superyak_peer'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text('')
    if module is not None:
        (package / 'lessons.py').write_text(module)
    code = ('import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); '
            'from superyak_agent import lessons_hold, lessons_hook; lessons_hook.CHECKOUT = Path(sys.argv[2]); '
            'print(lessons_hold.peer_could_hold("git push", "tardis", "/d"), '
            'lessons_hold.peer_could_hold("ls", "tardis", "/d"))')
    done = subprocess.run([sys.executable, '-I', '-c', code, str(AGENT), str(tmp_path)], capture_output=True, text=True,
                          timeout=60)
    assert done.stdout.split() == said, done.stderr
    assert not list(tmp_path.rglob('__pycache__'))


# Serenity's first-rail review, condition 2 (Tardis's hook half), pinned: a late query is killed at its deadline with
# everything it started, and the answer's `command` value, which is lesson text, is never shown, in a fence or out.

def gone(pid, within=2.0):
    """True once `ps` no longer lists the process, or lists it as a zombie, within `within` seconds."""
    until = time.monotonic() + within
    while time.monotonic() < until:
        stat = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True).stdout.strip()
        if not stat or stat.startswith('Z'):
            return True
        time.sleep(0.05)
    return False


def test_a_late_query_is_killed_at_its_deadline_with_everything_it_started(tmp_path):
    pids, stub = tmp_path / 'pids', tmp_path / 'slow_query.py'
    stub.write_text('import os, subprocess, sys, time\n'
                    'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])\n'
                    f'open({str(pids)!r}, "w").write(f"{{os.getpid()}} {{child.pid}}")\n'
                    'time.sleep(30)\n')
    settings = {'ship': 'tardis', 'data_dir': str(tmp_path), 'query': [sys.executable, str(stub)], 'state_dir': tmp_path}
    began = time.monotonic()
    assert lh.ask(settings, {'ship': 'tardis', 'command': 'x'}, began + 1.0) is None
    assert time.monotonic() - began < 2.0
    query, started = map(int, pids.read_text().split())
    assert gone(query) and gone(started)


def test_the_answers_command_value_is_never_shown(rail):
    """If the `command` value were shown it would be fenced like claim and why; it is never shown at all, since it only
    decides whether a hold applies. A marker in the value is in no hold, render or record."""
    value = '--include=MARKER7'
    rail.answers(lesson(A, command=value))
    rec = record(rail=rail)
    [hold] = ask(rail, command=f'grep -rn {value} .', rec=rec)
    assert 'MARKER7' not in hold.text and 'MARKER7' not in json.dumps(rec)
    assert 'MARKER7' not in lh.render([lesson(A, command=value)])
