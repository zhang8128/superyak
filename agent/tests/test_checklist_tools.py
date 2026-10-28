"""Checklists in the station tools: checklist_run, checklist_propose and the claim moment (spec, Running it out loud;
Renegotiation; claim, exactly)."""
import json
import time
from pathlib import Path
from types import SimpleNamespace
import pytest
from superyak_agent import checklist_firing as fp, checklists as cl, holds
from superyak_agent.mcp import Tools, claim_guard, handle
from superyak_agent.station import StationClient
from conftest import board_item
from checklist_fakes import checkout, trust_dirs, write_list
from test_ship_hook_claims import Ships


def call(tools, name, **arguments):
    result = handle(tools, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}})['result']
    return result['content'][0]['text'], result['isError']


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@pytest.fixture
def ship(station, monkeypatch):
    fake, andy, jenn, serenity = station
    home = Path.home() / '.superyak'
    repo = checkout(Path.home() / 'Projects' / 'superyak',
                    ('before-work', {'when': 'claim', 'items': ('Name the purpose.', 'Say who notices.')}),
                    ('why-we-build', {'when': 'start', 'read': 'yes', 'body': 'Why.'}),
                    ('reflect', {'when': 'every 3h', 'post': 'r-reflect', 'items': ('What happened?',)}))
    trust_dirs(home / 'checklists', repo / '.superyak' / 'checklists')
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', 's1')
    with holds.open_record(holds.record_path(home / 'sessions', 's1'), time.monotonic() + 1) as rec:
        holds.touch(rec.data, 0.0, str(repo))
        rec.save()
    client = StationClient('http://station.test', 'serenity-key', transport=fake)
    return SimpleNamespace(fake=fake, andy=andy, serenity=serenity, home=home, repo=repo, client=client,
                           tools=Tools(client, home=home, clock=lambda: 1000.0), runs=home / 'checklists' / 'runs.jsonl',
                           fired=home / 'checklists' / 'fired.jsonl', session=holds.record_path(home, 's1').stem)


def key(ship, list_id):
    return cl.list_key(ship.repo / '.superyak' / 'checklists', list_id)


def run(ship, answers, list_id='before-work', version=1, moment='claim', tools=None):
    return call(tools or ship.tools, 'checklist_run', key=key(ship, list_id), version=version, moment=moment, answers=answers)


def test_a_run_is_recorded_with_exactly_its_fields_and_privately(ship):
    answers = [{'answer': 'caught', 'reason': 'the base was on the old history'}, {'answer': 'done-before-asked'}]
    assert not run(ship, answers)[1]
    assert lines(ship.runs) == [{'time': 1000.0, 'session': ship.session, 'key': key(ship, 'before-work'), 'version': 1,
                                 'moment': 'claim', 'answers': answers}]
    assert oct(ship.runs.stat().st_mode & 0o777) == '0o600'


def test_a_read_list_run_has_no_answers(ship):
    assert not run(ship, [], 'why-we-build', moment='start')[1] and run(ship, [{'answer': 'done'}], 'why-we-build', moment='start')[1]


@pytest.mark.parametrize('reason', ['ask jo@example.org', 'call +1 415 555 0100', 'call (415) 555-0100',
                                    'token AbCdEfGh1234567890AbCdEfGh123456', 'x' * 201, 'two\nlines'])
def test_a_reason_with_person_data_a_key_or_more_than_one_line_is_refused_without_saying_which(ship, reason):
    text, error = run(ship, [{'answer': 'skipped', 'reason': reason}, {'answer': 'done'}])
    assert error and text.endswith(fp.REASON_REFUSED) and not ship.runs.exists()


@pytest.mark.parametrize('reason', ['2026-10-27', 'v3.2.1', 'abc1234', 'ABCDEF0123456789abcdef0123456789ABCDEF01',
                                    'ABCDEF0123456789abcdef0123456789ABCDEF0123456789abcdef0123456789',
                                    'docs/superpowers/specs/2026-10-27-checklists-design', 'law §2', 'person'])
def test_ordinary_reasons_pass(ship, reason):
    assert not run(ship, [{'answer': 'skipped', 'reason': reason}, {'answer': 'n/a'}])[1]


def test_skipped_needs_a_reason_and_only_skipped_or_caught_may_carry_one(ship):
    assert run(ship, [{'answer': 'skipped'}, {'answer': 'done'}])[1]
    assert run(ship, [{'answer': 'done', 'reason': 'because'}, {'answer': 'done'}])[1]
    assert run(ship, [{'answer': 'maybe'}, {'answer': 'done'}])[1]
    assert not run(ship, [{'answer': 'skipped', 'reason': 'law §2'}, {'answer': 'n/a'}])[1]


def test_the_count_follows_the_loaded_list_but_an_edited_lists_fired_version_is_kept(ship):    # Review Focus 4
    assert run(ship, [{'answer': 'done'}])[1]                                   # v1 has two items
    write_list(ship.repo / '.superyak' / 'checklists', 'before-work', when='claim', version=2, items=('A.', 'B.', 'C.'))
    assert not run(ship, [{'answer': 'done'}, {'answer': 'done'}])[1] and lines(ship.runs)[-1]['version'] == 1


def test_a_refused_run_is_recorded_with_why(ship, monkeypatch):
    tools = Tools(ship.client, guard=claim_guard(ship.home / 'station.json'), home=ship.home, clock=lambda: 1000.0)
    monkeypatch.setenv('SUPERYAK_RUN', '1')
    assert run(ship, [], tools=tools)[1]
    assert lines(ship.runs) == [{'time': 1000.0, 'session': ship.session, 'key': key(ship, 'before-work'), 'version': 1,
                                 'moment': 'claim', 'refused': 'run'}]


@pytest.fixture
def ships(monkeypatch, tmp_path, station, ship_config):
    return Ships(monkeypatch, tmp_path, station, ship_config)


def test_a_standing_down_ships_refusal_is_recorded_as_claimed(ships, monkeypatch):
    monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(ships.repo))
    home = Path(ships.machine_config).parent
    tools = Tools(StationClient('http://station.test', 'serenity-key', transport=ships.fake),
                  guard=claim_guard(ships.machine_config), home=home, clock=lambda: 1000.0)
    assert call(tools, 'checklist_run', key='0123abcd/before-work', version=1, moment='claim', answers=[])[1]
    assert lines(home / 'checklists' / 'runs.jsonl')[-1]['refused'] == 'claimed'


def test_propose_drafts_a_post_for_the_lists_room_and_posts_nothing(ship):
    before = len(ship.fake.requests)
    text, error = call(ship.tools, 'checklist_propose', key=key(ship, 'reflect'), change='Add an item: name the hour lost.',
                       reason='Three reviews this week lost an hour to the queue.')
    assert not error and len(ship.fake.requests) == before
    assert 'station_post room=r-reflect' in text and '\nProposal: Add an item: name the hour lost.' in text
    assert 'by 1970-01-01 00:30 UTC' in text and 'Three reviews this week' in text and 'no runs yet' in text
    text = call(ship.tools, 'checklist_propose', key=key(ship, 'before-work'), change='Drop item 2.', reason='It never caught anything.')[0]
    assert f'station_post room={cl.ALL_HANDS}' in text and 'explicit yes' in text
    assert text.endswith('A killer: item climbs only to automation, never down to being remembered.')   # section 2's N4


def test_claiming_an_open_board_item_fires_the_claim_lists_once_for_that_item(ship):
    room = ship.fake.room('Ops', ship.andy, ship.serenity)
    ship.fake.board[room] = [board_item('build:a', room_id=room), board_item('build:b', room_id=room)]
    first = call(ship.tools, 'station_claim', room=room, key='build:a')[0]
    assert '- [ ] Name the purpose.' in first and first.index('You hold') < first.index('Checklist ')
    assert 'Checklist ' not in call(ship.tools, 'station_claim', room=room, key='build:a')[0]         # a renewal
    assert '- [ ] Name the purpose.' in call(ship.tools, 'station_claim', room=room, key='build:b')[0]
    assert [f['moment'] for f in lines(ship.fired)] == ['claim', 'claim']


@pytest.mark.parametrize('state', [None, 'done'])
def test_a_plain_claim_or_a_closed_item_fires_nothing(ship, state):
    room = ship.fake.room('Ops', ship.andy, ship.serenity)
    if state:
        ship.fake.board[room] = [board_item('build:a', state=state, room_id=room)]
    assert 'Checklist ' not in call(ship.tools, 'station_claim', room=room, key='build:a')[0]


def test_without_a_session_id_a_list_fires_once_per_item_per_server_process(ship, monkeypatch):
    monkeypatch.delenv('CLAUDE_CODE_SESSION_ID')
    monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(ship.repo))
    room = ship.fake.room('Ops', ship.andy, ship.serenity)
    ship.fake.board[room] = [board_item('build:a', room_id=room)]
    tools = Tools(ship.client, home=ship.home, clock=lambda: 1000.0)
    assert 'Checklist ' in call(tools, 'station_claim', room=room, key='build:a')[0]
    assert 'Checklist ' not in call(tools, 'station_claim', room=room, key='build:a')[0]
    assert 'Checklist ' in call(Tools(ship.client, home=ship.home), 'station_claim', room=room, key='build:a')[0]
    assert lines(ship.fired)[0]['session'].startswith('proc-')


def test_claim_lists_come_from_the_records_cwd_else_the_session_project(ship, monkeypatch, tmp_path):
    room = ship.fake.room('Ops', ship.andy, ship.serenity)
    ship.fake.board[room] = [board_item(f'build:{n}', room_id=room) for n in range(3)]
    assert 'Checklist ' in call(ship.tools, 'station_claim', room=room, key='build:0')[0]             # the record's cwd
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', 's2')                                                  # no record yet
    monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(ship.repo))
    assert 'Checklist ' in call(ship.tools, 'station_claim', room=room, key='build:1')[0]
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', 's3')
    monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(tmp_path))
    assert 'Checklist ' not in call(ship.tools, 'station_claim', room=room, key='build:2')[0]


def test_two_claim_lists_at_most_and_the_rest_named(ship):
    for list_id in ('a-first', 'b-second'):
        write_list(ship.repo / '.superyak' / 'checklists', list_id, when='claim')
    room = ship.fake.room('Ops', ship.andy, ship.serenity)
    ship.fake.board[room] = [board_item('build:a', room_id=room)]
    text = call(ship.tools, 'station_claim', room=room, key='build:a')[0]
    assert text.count('\nChecklist ') == 2 and cl.more_line(['before-work']) in text


# --- fix round 1 ---

def test_a_failed_fired_log_write_never_hides_the_list(ship):
    ship.fired.mkdir(parents=True)                                    # every append to it fails
    room = ship.fake.room('Ops', ship.andy, ship.serenity)
    ship.fake.board[room] = [board_item('build:a', room_id=room)]
    assert '- [ ] Name the purpose.' in call(ship.tools, 'station_claim', room=room, key='build:a')[0]
    assert 'Checklist ' not in call(ship.tools, 'station_claim', room=room, key='build:a')[0]
    with holds.open_record(holds.record_path(ship.home / 'sessions', 's1'), time.monotonic() + 1) as rec:
        assert rec.data['items'][key(ship, 'before-work')]


def test_a_locked_record_shows_no_list_and_no_error_and_the_renewal_shows_it(ship):
    import fcntl
    room = ship.fake.room('Ops', ship.andy, ship.serenity)
    ship.fake.board[room] = [board_item('build:a', room_id=room)]
    fd = holds._lock(holds.record_path(ship.home / 'sessions', 's1'), time.monotonic() + 1, time.monotonic)
    try:
        started = time.monotonic()
        text, error = call(ship.tools, 'station_claim', room=room, key='build:a')
        assert not error and 'You hold' in text and 'Checklist ' not in text and time.monotonic() - started < 3
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        import os
        os.close(fd)
    assert '- [ ] Name the purpose.' in call(ship.tools, 'station_claim', room=room, key='build:a')[0]


def test_propose_counts_the_answers_of_the_last_runs_per_item(ship):
    run(ship, [{'answer': 'done'}, {'answer': 'caught', 'reason': 'old base'}])
    run(ship, [{'answer': 'done'}, {'answer': 'n/a'}])
    text = call(ship.tools, 'checklist_propose', key=key(ship, 'before-work'), change='Drop item 2.', reason='Rarely useful.')[0]
    assert 'Runs: last 2 runs; item 1: done 2; item 2: caught 1, n/a 1' in text


@pytest.mark.parametrize('how', ['act', 'raises'])
def test_a_guard_refusal_with_an_unexplained_verdict_is_recorded_as_unknown(ship, monkeypatch, how):
    from superyak_agent import acting
    if how == 'raises':
        def boom(*args):
            raise RuntimeError('x')
        monkeypatch.setattr(acting, 'verdict', boom)
    tools = Tools(ship.client, guard=lambda: 'refused', home=ship.home, clock=lambda: 1000.0)
    assert run(ship, [], tools=tools)[1]
    assert lines(ship.runs)[-1]['refused'] == 'unknown'


def test_a_hook_run_is_not_a_run_for_the_refusal_record(ship, monkeypatch):
    monkeypatch.setenv('SUPERYAK_RUN', 'hook')
    tools = Tools(ship.client, guard=lambda: 'refused', home=ship.home, clock=lambda: 1000.0)
    run(ship, [], tools=tools)
    assert lines(ship.runs)[-1]['refused'] != 'run'


def test_the_checklist_tools_refuse_without_a_home(ship):
    tools = Tools(ship.client)
    for text, error in (run(ship, [], tools=tools),
                        call(tools, 'checklist_propose', key=key(ship, 'reflect'), change='x', reason='y')):
        assert error and 'no ship home' in text
