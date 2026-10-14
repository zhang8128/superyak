"""Watch by default W3: station_watch records this session's own choice for the hook (requirements 4 and 9)."""
from superyak_agent import mcp
from superyak_agent.mcp import Tools, handle
from superyak_agent.station import StationClient, read_json, session_key, write_private


def tools_for(fake, sessions):
    return Tools(StationClient('http://station.test', 'serenity-key', transport=fake), sessions_dir=sessions)


def call(tools, name, **arguments):
    result = handle(tools, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}})['result']
    return result['content'][0]['text'], result['isError']


def test_station_watch_records_the_sessions_choice(station, tmp_path, monkeypatch):
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', 'cc-1')
    fake, andy, jenn, serenity = station
    sessions = tmp_path / 'sessions'
    tools = tools_for(fake, sessions)
    path = sessions / f'{session_key("cc-1")}.watch'
    assert not call(tools, 'station_watch', minutes=45, writable=False)[1]
    got = read_json(path)
    assert got['choice'] == 45 and got['writable'] is False and isinstance(got['seen'], float)
    assert not call(tools, 'station_watch', minutes=0)[1]
    assert read_json(path)['choice'] == 'off'


def test_a_call_naming_another_cursor_records_nothing(station, tmp_path, monkeypatch):
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', 'cc-1')
    fake, andy, jenn, serenity = station
    sessions = tmp_path / 'sessions'
    tools = tools_for(fake, sessions)
    assert not call(tools, 'station_watch', minutes=0, cursor='other-name')[1]
    assert not sessions.exists() or list(sessions.iterdir()) == []


def test_without_a_sessions_folder_nothing_is_written(station, tmp_path, monkeypatch):
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', 'cc-1')
    fake, andy, jenn, serenity = station
    tools = Tools(StationClient('http://station.test', 'serenity-key', transport=fake))
    assert not call(tools, 'station_watch', minutes=0)[1]
    assert list(tmp_path.iterdir()) == []


def test_a_refused_call_records_nothing(station, tmp_path, monkeypatch):
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', 'cc-1')
    fake, andy, jenn, serenity = station
    sessions = tmp_path / 'sessions'

    def refusing(method, url, headers, data):
        if method == 'POST' and url.endswith('/api/ships/me/watch'):
            return 400, b'{"error": "minutes is a whole number from 0 to 120"}'
        return fake(method, url, headers, data)
    tools = Tools(StationClient('http://station.test', 'serenity-key', transport=refusing), sessions_dir=sessions)
    assert call(tools, 'station_watch', minutes=0)[1]
    assert not sessions.exists() or list(sessions.iterdir()) == []


def test_an_opt_out_that_cannot_be_saved_says_so(station, tmp_path, monkeypatch):
    """Security review of 68bcd23 (fail-open opt-out), the writing side: the station ends the watch either way, but if
    the session's "off" can't be saved the hook would take the watch again, so the reply says so."""
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', 'cc-1')
    fake, andy, jenn, serenity = station
    sessions = tmp_path / 'sessions'
    sessions.write_text('a file where the folder should be')  # so <sessions>/<key>.watch can't be written
    tools = tools_for(fake, sessions)
    text, error = call(tools, 'station_watch', minutes=0)
    assert not error and "opt-out couldn't be saved" in text
    text, error = call(tools, 'station_watch', minutes=30)
    assert not error and "couldn't be saved" not in text


def test_the_tool_says_minutes_zero_turns_the_default_off():
    [tool] = [t for t in mcp.TOOLS if t[0] == 'station_watch']
    assert 'turns that default off for the rest of this session' in tool[1]


def test_serve_gives_the_tools_the_ships_sessions_folder(ship_config, tmp_path, monkeypatch):
    config = tmp_path / 'home' / 'station.json'
    write_private(config, ship_config)
    seen = {}
    monkeypatch.setattr(mcp, 'serve_with', lambda tools, *streams: seen.setdefault('tools', tools))
    mcp.serve(config)
    assert seen['tools'].sessions_dir == tmp_path / 'home' / 'sessions'
