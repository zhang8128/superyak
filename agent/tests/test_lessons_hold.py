"""The lessons side of the shared hold entry before a Bash command (first rail spec section 8, decision 8). The entry
is Serenity's (`run_agent.py hold`): it renders every Hold, keeps the cap of 3 a session and saves the record only when
it prints. The provider is tested here alone, with a plain record dict and the stub query."""
import json
import time

import pytest

from superyak_agent import holds, lessons_hold, lessons_hook as lh
from test_lessons_hook import A, B, C, D, Rail, lesson, transcript_line

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


def ask(rail, command=COMMAND, limit=3, rec=None, **fields):
    return lessons_hold.candidates(command, record(rail=rail, **fields) if rec is None else rec, time.time(), limit,
                                   settings=rail.settings, env={})


def key(command, id_, session='s1'):
    return f'lesson:{lh.session_key(session)}:{lessons_hold.head_digest(command)}:{id_}'


def test_a_command_value_of_at_least_6_bytes_holds_once_with_the_specs_reason(rail):
    found = lesson(A, ship='serenity', command=GLOB)
    rail.answers(found)
    assert ask(rail) == [holds.Hold('lesson', key(COMMAND, A), lh.hold_reason(found))]
    assert rail.sent() == [{'ship': 'tardis', 'command': COMMAND, 'words_only': True, 'limit': 3, 'seen': []}]


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
    got = lessons_hold.candidates(COMMAND, record(rail=rail), time.monotonic(), 3, settings=rail.settings,
                                  env={'SUPERYAK_RUN': value})
    assert bool(got) is holds and len(rail.sent()) == int(holds)


@pytest.mark.parametrize('bad', [None, [], {}, {'session': None}, {'session': 's1'}, {'session': {'id': ''}},
                                 {'session': {'id': 7}}, {'session': {'transcript': None}}])
def test_a_record_without_a_session_holds_nothing(rail, bad):
    rail.answers(lesson(A, command=GLOB))
    assert lessons_hold.candidates(COMMAND, bad, time.monotonic(), 3, settings=rail.settings, env={}) == []


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
