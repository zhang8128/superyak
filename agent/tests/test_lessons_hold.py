"""The lessons side of the shared hold entry before a Bash command (first rail spec section 8, decision 8). The entry
is Serenity's (`run_agent.py hold`): it denies, records each hold it makes and keeps the cap of 3 a session. The
provider is tested here alone, with a fake record and the stub query."""
import json
import time

import pytest

from superyak_agent import lessons_hold, lessons_hook as lh
from test_lessons_hook import A, B, C, D, Rail, lesson, transcript_line

GLOB = '--include=*'  # the spec's illustration: a command value of 11 bytes
COMMAND = 'grep -rn --include=*.py TODO .'


def record(session='s1', rail=None, heads=(), holds=()):
    """What the provider reads from the entry's per-session record."""
    return {'session_id': session, 'transcript_path': str(rail.transcript) if rail else None, 'heads': list(heads),
            'holds': list(holds)}


@pytest.fixture
def rail(tmp_path):
    return Rail(tmp_path)


def ask(rail, command=COMMAND, limit=3, now=None, **fields):
    return lessons_hold.candidates(command, record(rail=rail, **fields), time.monotonic() if now is None else now, limit,
                                   settings=rail.settings, env={})


def key(command, id_, session='s1'):
    return f'lesson:{lh.session_key(session)}:{lessons_hold.head_digest(command)}:{id_}'


def test_a_command_value_of_at_least_6_bytes_holds_once_with_the_specs_reason(rail):
    found = lesson(A, ship='serenity', command=GLOB)
    rail.answers(found)
    assert ask(rail) == [{'kind': 'lesson', 'key': key(COMMAND, A), 'text': lh.hold_reason(found)}]
    assert rail.sent() == [{'ship': 'tardis', 'command': COMMAND, 'words_only': True, 'limit': 3, 'seen': []}]


def test_the_key_names_the_session_the_head_and_the_lesson(rail):
    rail.answers(lesson(A, command=GLOB))
    [hold] = ask(rail, command='FOO=1 grep -rn --include=*.md x')
    assert hold['key'] == key('grep -rn', A) == f'lesson:{lh.session_key("s1")}:{lh.digest("grep")}:{A}'


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
    assert ask(rail, holds=[hold['key']]) == []  # or only the hold it made
    assert ask(rail, command='grep -rn --include=*.md other', heads=[lessons_hold.head_digest(COMMAND)]) == []
    assert rail.sent() == []


def test_the_cap_of_3_a_session_is_the_entrys(rail):
    rail.answers(lesson(A, command=GLOB))
    made = [key('make test', B), key('uv run', C), key('npm test', D)]
    assert [h['key'] for h in ask(rail, holds=made)] == [key(COMMAND, A)]


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
    assert [h['key'] for h in ask(rail, holds=[key('make test', C)])] == [key(COMMAND, D)]
    rail.answers(*[lesson(i, command=GLOB) for i in (B, D)])
    assert [h['key'] for h in ask(rail, session='s1', holds=[key('make test', C)])] == [key(COMMAND, D)]
    assert rail.sent()[0]['seen'] == [A, B, C]


def test_a_slow_query_holds_nothing_within_1_s(rail):
    rail.answers(lesson(A, command=GLOB))
    rail.flag('sleep', '3')
    began = time.monotonic()
    assert ask(rail) == []
    assert time.monotonic() - began < 1.5


def test_the_second_counts_from_now(rail):
    rail.answers(lesson(A, command=GLOB))
    rail.flag('sleep', '0.6')
    assert ask(rail, now=time.monotonic() - 0.7) == []  # the entry began 0.7 s ago: 0.3 s left
    assert len(ask(rail, now=time.time(), session='s2')) == 1  # not a monotonic time: a whole second from here


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


@pytest.mark.parametrize('bad', [None, [], {'transcript_path': None}, {'session_id': ''}, {'session_id': 7}])
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
