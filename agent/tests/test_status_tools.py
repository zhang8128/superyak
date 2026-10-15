"""Ship status, build step 4 (agent): station_watch and station_ships (S9), deferred mentions and the on-watch line in
the hook and station_unread (R26), station_post's reminder (R27), and the system author in every view (S11, R30)."""
from superyak_agent import hook
from superyak_agent.mcp import Tools, handle
from superyak_agent.station import DEFERRED_MARK, ON_WATCH_LINE, StationClient, source_label, write_private
from superyak_agent.watch import build_prompt


def tools_for(fake):
    return Tools(StationClient('http://station.test', 'serenity-key', transport=fake))


def call(tools, name, **arguments):
    result = handle(tools, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}})['result']
    return result['content'][0]['text'], result['isError']


def write_config(ship_config, tmp_path):
    path = tmp_path / 'home' / 'station.json'
    write_private(path, ship_config)
    return path


def test_station_watch_declares_and_ends_under_the_sessions_name(station, monkeypatch):
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', 'cc-1')
    fake, andy, jenn, serenity = station
    tools = tools_for(fake)
    text, error = call(tools, 'station_watch', minutes=30, writable=True, label='lead terminal')
    assert not error and text.startswith('On watch (writable) until ') and 'station_post reply_to=<its id>' in text
    assert fake.watches == {(serenity['id'], 'cc-1'): {'minutes': 30, 'writable': True, 'label': 'lead terminal'}}
    assert call(tools, 'station_watch', minutes=0)[0] == "This session is not on watch; your ship's watcher answers its mentions."
    assert fake.watches == {}


def test_without_a_session_name_station_watch_needs_a_cursor(station, monkeypatch):
    """S9: a Codex session watches under its own name."""
    monkeypatch.delenv('CLAUDE_CODE_SESSION_ID', raising=False)
    fake, andy, jenn, serenity = station
    tools = tools_for(fake)
    text, error = call(tools, 'station_watch', minutes=20)
    assert error and 'pass cursor' in text and fake.watches == {}
    assert not call(tools, 'station_watch', minutes=20, cursor='codex-lead')[1]
    assert list(fake.watches) == [(serenity['id'], 'codex-lead')]


def test_station_ships_shows_the_directory_as_labels(station):
    fake, andy, jenn, serenity = station
    fake.directory_rows = [
        {'id': serenity['id'], 'username': 'serenity', 'name': 'Serenity', 'owner_name': 'Andy', 'writable_on_watch': True,
         'live_runs': 1, 'last_seen': 1000.0, 'machine': 'andy-mac',
         'sessions': [{'name': 'cc-1', 'label': 'lead\nterminal', 'client': 'mcp/abc123', 'mode': 'write', 'live': True,
                       'on_watch': True, 'watch_until': 2200.0, 'first_seen': 900.0, 'last_seen': 1000.0}],
         'runs': [{'mode': 'read', 'started': 950.0}]},
        {'id': 'u-rio', 'username': 'rio-grande', 'name': 'Rio `Grande`', 'owner_name': 'Jenn', 'writable_on_watch': False,
         'live_runs': 0, 'last_seen': 900.0}]
    assert call(tools_for(fake), 'station_ships')[0].splitlines() == [
        'Serenity (@serenity), owner Andy: writable session on watch; live runs 1; last seen 1970-01-01 00:16 UTC',
        '  - session cc-1 "lead terminal": mcp/abc123, mode write, live, on watch until 1970-01-01 00:36 UTC',
        '  - read run since 1970-01-01 00:15 UTC',
        '  - machine andy-mac',
        'Rio Grande (@rio-grande), owner Jenn: no writable session on watch; live runs 0; last seen 1970-01-01 00:15 UTC']


def test_deferred_mentions_show_their_mark_in_the_hook_and_station_unread(station, ship_config, tmp_path, monkeypatch):
    """R26: the mark on the deferred mention only; its author is the one the station verified."""
    fake, andy, jenn, serenity = station
    config_path = write_config(ship_config, tmp_path)
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', 's2')
    tools = tools_for(fake)
    room = fake.room('Ops', andy, jenn, serenity)
    hook.run(config_path, transport=fake, session_id='s1', sessions_dir=tmp_path / 'sessions')  # both cursors start here
    call(tools, 'station_unread')
    asked = fake.say(room, jenn, '@serenity can you check the build?')
    fake.say(room, jenn, '@serenity and another thing, not deferred')
    fake.deferred_marks.add(asked['id'])
    shown = hook.run(config_path, transport=fake, session_id='s1', sessions_dir=tmp_path / 'sessions')
    assert shown.count(DEFERRED_MARK) == 1 and f'message {asked["id"]} {DEFERRED_MARK}:' in shown and 'Jenn (@jenn, person)' in shown
    text = call(tools, 'station_unread')[0]
    assert text.count(DEFERRED_MARK) == 1 and f'message {asked["id"]} [mentions you] {DEFERRED_MARK}' in text


def test_the_on_watch_line_shows_for_any_mention_before_it_is_deferred(station, ship_config, tmp_path, monkeypatch):
    """R26 (96d55368, edit 3): on a writable watch, a block holding a mention with no deferred mark yet still gets the
    line; a block with no mention, a session off watch, or one on a read-only watch, gets none."""
    fake, andy, jenn, serenity = station
    config_path = write_config(ship_config, tmp_path)
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', 's2')
    tools = tools_for(fake)
    room = fake.room('Ops', andy, jenn, serenity)
    run = lambda: hook.run(config_path, transport=fake, session_id='s1', sessions_dir=tmp_path / 'sessions')
    run()
    call(tools, 'station_unread')
    fake.watches[(serenity['id'], 's1')] = fake.watches[(serenity['id'], 's2')] = {'minutes': 20, 'writable': True, 'label': None}
    fake.say(room, jenn, 'no mention here')
    assert ON_WATCH_LINE not in run() and ON_WATCH_LINE not in call(tools, 'station_unread')[0]
    fake.say(room, jenn, '@serenity not deferred yet')
    shown, text = run(), call(tools, 'station_unread')[0]
    assert ON_WATCH_LINE in shown and DEFERRED_MARK not in shown and ON_WATCH_LINE in text
    fake.watches.clear()
    fake.say(room, jenn, '@serenity off watch now')
    assert ON_WATCH_LINE not in run() and ON_WATCH_LINE not in call(tools, 'station_unread')[0]
    for key in ((serenity['id'], 's1'), (serenity['id'], 's2')):  # R26 as amended (137f0a38, minor 4): writable only
        fake.watches[key] = {'minutes': 20, 'writable': False, 'label': None}
    fake.say(room, jenn, '@serenity on a read-only watch')
    assert ON_WATCH_LINE not in run() and ON_WATCH_LINE not in call(tools, 'station_unread')[0]


def test_station_post_without_reply_to_lists_the_deferred_mentions_here(station, monkeypatch):
    """R27, agent half."""
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', 'cc-1')
    fake, andy, jenn, serenity = station
    room = fake.room('Ops', andy, jenn, serenity)
    asked = fake.say(room, jenn, '@serenity a question')
    fake.deferred_here[room] = [asked['id']]
    tools = tools_for(fake)
    text = call(tools, 'station_post', room=room, text='thinking about it')[0]
    assert text.endswith(f' Deferred mentions in this room still waiting for a reply_to: {asked["id"]}.')
    assert 'Deferred' not in call(tools, 'station_post', room=room, text='answer', reply_to=asked['id'])[0]


def test_every_place_treats_the_system_author_as_s11_says(station, ship_config, tmp_path, monkeypatch):
    """R30, R31, agent half: describe names it "Station (@_station, system)" in station_read, the hook, station_unread
    and a run's prompt, and its message is labelled "station notice"; a person called "Station" is described as a
    person. The station half is Task 4's test of the same name."""
    fake, andy, jenn, serenity = station
    system = fake.user('_station', 'Station', 'system')
    config_path = write_config(ship_config, tmp_path)
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', 'cc-1')
    tools = tools_for(fake)
    room = fake.room('Ops', andy, jenn, serenity)
    hook.run(config_path, transport=fake, session_id='s1', sessions_dir=tmp_path / 'sessions')
    call(tools, 'station_unread')
    jenn['name'] = 'Station'
    notice = fake.say(room, system, 'Station notice: a mention of Serenity has waited 30 minutes.')
    fake.kinds[notice['id']] = 'notice'
    asked = fake.say(room, jenn, '@serenity a question')
    read = call(tools, 'station_read', room=room)[0]
    assert 'Station (@_station, system)' in read and f'message {notice["id"]} (station notice)' in read
    assert 'Station (@jenn, person)' in read and read.count('station notice') == 1
    shown = hook.run(config_path, transport=fake, session_id='s1', sessions_dir=tmp_path / 'sessions')
    assert 'Station (@_station, system)' in shown and '(station notice)' in shown
    assert 'Station (@_station, system)' in call(tools, 'station_unread')[0]
    prompt = build_prompt(fake.view(fake.rooms[room]), {'message_id': asked['id'], 'room_id': room, 'author': jenn}, 'serenity', 'read')
    assert 'Station (@_station, system), station notice' in prompt
    assert source_label({'source': {'kind': 'claim'}}) == 'claim'


def test_new_keys_change_nothing_for_code_that_ignores_them(station, ship_config, tmp_path):
    """R36, agent half (plan gate notes, 8afe2606): with the station holding a watch, a deferred mark and a deferred
    reply for this ship, the views that never read those keys show exactly the same text: the hook without a session
    id (the machine-wide cursor) and station_read. A regression guard, green by design: the station half
    (test_an_old_client_sees_todays_unread_and_post_responses) is what pins old clients' responses key for key."""
    def views(with_keys):
        fake = type(station[0])()
        andy, jenn = fake.user('andy', 'Andy'), fake.user('jenn', 'Jenn')
        ship = fake.user('serenity', 'Serenity', 'ship', andy['id'], key='serenity-key')
        room = fake.room('Ops', andy, jenn, ship)
        asked = fake.say(room, jenn, '@serenity what changed?')
        if with_keys:
            fake.watches[(ship['id'], 'default')] = {'minutes': 20, 'writable': True, 'label': None}
            fake.deferred_marks.add(asked['id'])
            fake.deferred_here[room] = [asked['id']]
        config_path = write_config(ship_config, tmp_path / f'keys-{with_keys}')
        shown = hook.run(config_path, transport=fake, state_path=tmp_path / f'state-{with_keys}.json', sessions_dir=tmp_path / f'sessions-{with_keys}')
        read = call(tools_for(fake), 'station_read', room=room)[0]
        return shown, read
    assert views(True) == views(False)
