# agent/tests/test_hook_watch_default.py
"""Watch by default (docs/superpowers/specs/2026-10-14-watch-default-design.md, W1-W6, requirements 1-9)."""
import json

import pytest

from superyak_agent import hook
from superyak_agent.station import ON_WATCH_LINE, session_key, write_private

DAY = 86400


def setup(station, ship_config, tmp_path):
    fake, andy, jenn, serenity = station
    config = tmp_path / 'home' / 'station.json'
    write_private(config, ship_config)
    return fake, serenity, config, tmp_path / 'home' / 'sessions'


def prompt(fake, config, sessions, now, mode='write', messages=True, sid='cc-1', transport=None):
    return hook.run(config, transport=transport or fake, event='prompt', session_id=sid, sessions_dir=sessions,
                    messages=messages, mode=mode, clock=lambda: now)


def declared(fake):
    return [r['body'] for r in fake.requests if r['method'] == 'POST' and r['path'] == '/api/ships/me/watch']


def choose(sessions, choice, sid='cc-1', seen=1000.0):
    sessions.mkdir(parents=True, exist_ok=True)
    write_private(sessions / f'{session_key(sid)}.watch', dict(choice, seen=seen))


def test_the_key_is_shared():
    assert session_key('cc-1') == hook._session_file('/s', 'cc-1').name[:16]
    assert len(session_key('\udcff odd')) == 16  # a lone surrogate encodes, as the hook's file name always did


def test_a_write_prompt_declares_once_then_again_after_a_gap(station, ship_config, tmp_path):
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)
    prompt(fake, config, sessions, 1000.0)
    assert declared(fake) == [{'minutes': 20, 'writable': True}]
    prompt(fake, config, sessions, 1000.0 + 19 * 60)
    assert len(declared(fake)) == 1  # within the lease: the prompt's own calls renew it
    prompt(fake, config, sessions, 1000.0 + 19 * 60 + 21 * 60)
    assert declared(fake)[-1] == {'minutes': 20, 'writable': True} and len(declared(fake)) == 2


def test_no_declaration_in_plan_mode_with_messages_off_or_without_a_session(station, ship_config, tmp_path):
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)
    prompt(fake, config, sessions, 1000.0, mode='plan')
    prompt(fake, config, sessions, 1000.0, messages=False)
    hook.run(config, transport=fake, event='prompt', session_id=None, sessions_dir=sessions, messages=True,
             mode='write', clock=lambda: 1000.0)
    prompt(fake, config, sessions, 1000.0, mode=None)
    assert declared(fake) == []


def test_no_declaration_inside_a_watcher_run(station, ship_config, tmp_path, monkeypatch):
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)
    monkeypatch.setenv('SUPERYAK_RUN', '1')
    prompt(fake, config, sessions, 1000.0)
    assert declared(fake) == []


def test_an_opt_out_sticks(station, ship_config, tmp_path):
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)
    choose(sessions, {'choice': 'off'})
    for n in range(3):
        prompt(fake, config, sessions, 1000.0 + n * 3600)
    assert declared(fake) == []


@pytest.mark.parametrize('text', ['{not json', '[1]', '{"choice": 500}', '{"choice": true}', '{"choice": "on"}'])
def test_a_choice_the_hook_cannot_read_counts_as_off(station, ship_config, tmp_path, text):
    """Security review of 68bcd23: the opt-out must stick, so a .watch file that isn't a JSON object, or holds a
    choice that is neither "off" nor 1-120 minutes, counts as "off". Only a missing file means the default."""
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)
    sessions.mkdir(parents=True)
    (sessions / f'{session_key("cc-1")}.watch').write_text(text)
    prompt(fake, config, sessions, 1000.0)
    prompt(fake, config, sessions, 1000.0 + 3600)
    assert declared(fake) == []


def test_the_sessions_own_choice_sets_minutes_and_writable(station, ship_config, tmp_path):
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)
    choose(sessions, {'choice': 45, 'writable': False})
    prompt(fake, config, sessions, 1000.0)
    assert declared(fake) == [{'minutes': 45, 'writable': False}]
    prompt(fake, config, sessions, 1000.0 + 44 * 60)
    assert len(declared(fake)) == 1  # its own lease decides the gap


def test_plan_mode_lets_go_of_a_default_once_and_write_mode_takes_it_again(station, ship_config, tmp_path):
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)
    prompt(fake, config, sessions, 1000.0)
    prompt(fake, config, sessions, 1060.0, mode='plan')
    prompt(fake, config, sessions, 1120.0, mode='plan')
    prompt(fake, config, sessions, 1180.0)
    assert declared(fake) == [{'minutes': 20, 'writable': True}, {'minutes': 0, 'writable': False},
                              {'minutes': 20, 'writable': True}]


def test_plan_mode_leaves_a_self_declared_watch_alone(station, ship_config, tmp_path):
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)
    choose(sessions, {'choice': 30, 'writable': True})
    prompt(fake, config, sessions, 1000.0)
    prompt(fake, config, sessions, 1060.0, mode='plan')
    assert declared(fake) == [{'minutes': 30, 'writable': True}]


def test_a_seen_in_the_future_declares(station, ship_config, tmp_path):
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)
    sessions.mkdir(parents=True)
    write_private(sessions / f'{session_key("cc-1")}.prompted', {'seen': 99999999.0, 'held': True})
    prompt(fake, config, sessions, 1000.0)
    assert len(declared(fake)) == 1


def test_a_damaged_prompted_file_counts_as_absent(station, ship_config, tmp_path):
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)
    sessions.mkdir(parents=True)
    (sessions / f'{session_key("cc-1")}.prompted').write_text('[1, 2]')
    prompt(fake, config, sessions, 1000.0)
    assert declared(fake) == [{'minutes': 20, 'writable': True}]


def test_a_refused_declaration_is_silent_and_retried(station, ship_config, tmp_path):
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)

    def refusing(method, url, headers, data):
        if method == 'POST' and url.endswith('/api/ships/me/watch'):
            fake.requests.append({'method': method, 'path': '/api/ships/me/watch', 'body': json.loads(data)})
            return 429, b'{"error": "A ship can have at most 10 sessions on watch; end one first"}'
        return fake(method, url, headers, data)
    first = prompt(fake, config, sessions, 1000.0, transport=refusing)
    assert len(declared(fake)) == 1 and 'watch' not in first.lower()
    prompt(fake, config, sessions, 1060.0)
    assert len(declared(fake)) == 2  # .prompted wasn't written, so the next prompt tries again


def test_the_output_is_the_same_with_or_without_the_declaration(station, ship_config, tmp_path, monkeypatch):
    """Requirement 5: with no mention to hand over, the output is byte-for-byte the same."""
    import copy
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)
    room = fake.room('Ops', fake.users['u-andy'], serenity)
    fake.say(room, fake.users['u-andy'], 'hello')
    twin = copy.deepcopy(fake)  # the same station, so the only difference is the feature
    with_default = prompt(fake, config, sessions, 1000.0)
    monkeypatch.setattr(hook, '_watch_default', lambda *a, **k: None)
    without = prompt(twin, config, tmp_path / 'other-sessions', 1000.0)
    assert with_default == without and 'hello' in without
    assert len(declared(fake)) == 1 and declared(twin) == []


def test_the_stations_on_watch_line_tells_the_session_at_once(station, ship_config, tmp_path):
    """W5 and requirement 5: the declaration runs before the inbox, so the same prompt's messages come with the
    station's own on-watch line when a mention is there to hand over. The hook adds no text of its own."""
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)
    room = fake.room('Ops', fake.users['u-andy'], serenity)
    fake.say(room, fake.users['u-andy'], '@serenity a question')
    shown = prompt(fake, config, sessions, 1000.0)
    assert ON_WATCH_LINE in shown and len(declared(fake)) == 1


def test_prune_keeps_the_current_sessions_files_and_drops_old_ones(tmp_path):
    folder = tmp_path / 'sessions'
    folder.mkdir()
    now = 100 * DAY
    current, old, fresh_off = session_key('cc-now'), session_key('cc-old'), session_key('cc-off')
    for name, seen in [(f'{current}.json', 1.0), (f'{current}.watch', 1.0), (f'{current}.prompted', 1.0),
                       (f'{old}.watch', now - 15 * DAY), (f'{old}.prompted', now - 15 * DAY),
                       (f'{fresh_off}.watch', now - DAY)]:
        write_private(folder / name, {'seen': seen, 'choice': 'off'} if name.endswith('.watch') else {'seen': seen})
    hook._prune(folder, folder / f'{current}.json', now)
    assert sorted(p.name for p in folder.iterdir()) == sorted([f'{current}.json', f'{current}.watch',
                                                              f'{current}.prompted', f'{fresh_off}.watch'])


def test_a_prompt_in_the_lease_s_last_minute_declares_again(station, ship_config, tmp_path):
    """Final review of 97a9e8c, Important 1: the station renews a lease at most once per 30 s, so its lease can end up to
    30 s before seen + lease. The hook declares again in the lease's last minute instead of trusting it."""
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)
    prompt(fake, config, sessions, 1000.0)
    prompt(fake, config, sessions, 1000.0 + 20 * 60 - 30)
    assert len(declared(fake)) == 2
