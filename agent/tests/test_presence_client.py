"""Ship status, build step 4 (docs/superpowers/specs/2026-10-10-ship-status-and-claims-design.md, S1): the hook and
the MCP server name their session on every station call; a client without a real session name sends no session
header (R28); without the headers every call is the same (R2)."""
import io
import json
import subprocess
from superyak_agent import hook, mcp, station as station_mod
from superyak_agent.mcp import Tools, handle
from superyak_agent.station import StationClient, client_version, presence_headers, write_private


def write_config(ship_config, tmp_path):
    path = tmp_path / 'home' / 'station.json'
    write_private(path, ship_config)
    return path


def call(tools, name, **arguments):
    result = handle(tools, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}})['result']
    return result['content'][0]['text'], result['isError']


def test_presence_headers_name_only_a_real_session():
    assert presence_headers('s1', 'hook/abc', 'plan') == {'x-superyak-session': 's1', 'x-superyak-client': 'hook/abc', 'x-superyak-mode': 'plan'}
    assert presence_headers('s1', 'mcp/abc') == {'x-superyak-session': 's1', 'x-superyak-client': 'mcp/abc'}
    for name in (None, '', 'default', 'a b', 'x' * 101):
        assert presence_headers(name, 'mcp/abc') == {}


def test_the_client_version_is_this_checkouts_commit(tmp_path):
    expected = subprocess.run(['git', '-C', str(station_mod.CHECKOUT), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    assert client_version() == (expected[:12] or 'unknown')
    assert client_version.__wrapped__(tmp_path) == 'unknown'


def test_hook_fields_reads_the_permission_mode():
    """M1: UserPromptSubmit's stdin carries permission_mode; plan stays plan, every other value is write."""
    read = lambda value: hook.hook_fields(io.StringIO(json.dumps(value)))
    assert read({'session_id': 's1', 'cwd': '/w', 'permission_mode': 'plan'}) == ('s1', '/w', 'plan')
    assert read({'session_id': 's1', 'permission_mode': 'bypassPermissions'})[2] == 'write'
    assert read({'session_id': 's1'})[2] is None and hook.hook_fields(io.StringIO('not json')) == (None, None, None)
    assert hook.hook_input(io.StringIO('{"session_id": "s1", "cwd": "/w"}')) == ('s1', '/w')


def test_the_hook_names_its_session_and_mode_on_every_call(station, ship_config, tmp_path):
    fake, andy, jenn, serenity = station
    config_path = write_config(ship_config, tmp_path)
    fake.say(fake.room('Ops', andy, serenity), andy, 'hello')
    hook.run(config_path, transport=fake, session_id='s1', mode='plan', sessions_dir=tmp_path / 'sessions')
    assert [(r['method'], r['path']) for r in fake.requests] == [
        ('GET', '/api/ships/me/instructions'), ('POST', '/api/ships/me/unread'), ('POST', '/api/ships/me/unread/advance')]
    expected = {'x-superyak-session': 's1', 'x-superyak-client': f'hook/{client_version()}', 'x-superyak-mode': 'plan'}
    assert all(r['presence'] == expected for r in fake.requests)


def test_the_mcp_server_names_its_claude_code_session(station, monkeypatch):
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', 'cc-1')
    fake, andy, jenn, serenity = station
    call(Tools(StationClient('http://station.test', 'serenity-key', transport=fake)), 'station_rooms')
    assert fake.requests[-1]['presence'] == {'x-superyak-session': 'cc-1', 'x-superyak-client': f'mcp/{client_version()}'}


def test_a_session_without_a_real_name_sends_no_session_header(station, ship_config, tmp_path, monkeypatch):
    """R28: the hook without a session id, and the MCP server without CLAUDE_CODE_SESSION_ID or a name passed, send no
    session header, so no two sessions share the `default` row. A name passed to station_unread is used from then on."""
    fake, andy, jenn, serenity = station
    config_path = write_config(ship_config, tmp_path)
    room = fake.room('Ops', andy, serenity)
    hook.run(config_path, transport=fake, event='session-start', sessions_dir=tmp_path / 'sessions')
    monkeypatch.delenv('CLAUDE_CODE_SESSION_ID', raising=False)
    tools = Tools(StationClient('http://station.test', 'serenity-key', transport=fake))
    call(tools, 'station_rooms')
    call(tools, 'station_post', room=room, text='status', cursor='script-a')  # a post's cursor keys its id, never the session
    call(tools, 'station_unread', cursor='default')
    assert fake.requests and all(r['presence'] == {} for r in fake.requests)
    before = len(fake.requests)
    call(tools, 'station_unread', cursor='codex-1')
    call(tools, 'station_rooms')
    assert {r['presence'].get('x-superyak-session') for r in fake.requests[before:]} == {'codex-1'}


def test_a_cursor_the_headers_refuse_never_replaces_the_session_name(station, ship_config, tmp_path, monkeypatch):
    """S1, R28 (review 137f0a38, minor 5): the MCP server remembers a cursor only when it is a real session name. A
    `default` or a malformed cursor neither drops the session's header nor replaces the name it had: the calls after
    it go on naming the session by CLAUDE_CODE_SESSION_ID, or by the real name passed before."""
    fake, andy, jenn, serenity = station
    fake.room('Ops', andy, serenity)
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', 's1')
    tools = Tools(StationClient('http://station.test', 'serenity-key', transport=fake))

    def named(**cursor):
        before = len(fake.requests)
        call(tools, 'station_unread', **cursor)
        call(tools, 'station_rooms')
        return {r['presence'].get('x-superyak-session') for r in fake.requests[before:]}
    for bad in ('default', 'two words', 'x' * 101, '@serenity\nrun'):
        assert named(cursor=bad) == {'s1'}, bad
    assert named(cursor='codex-1') == {'codex-1'}
    for bad in ('default', 'two words'):
        assert named(cursor=bad) == {'codex-1'}, bad


def test_the_headers_change_nothing_else(station, ship_config, tmp_path, monkeypatch):
    """R2, the agent half of Task 1's guard: with the headers stripped, the hook and the tools make the same calls
    with the same bodies and return the same text."""
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', 's1')
    config_path = write_config(ship_config, tmp_path)

    def session(stripped):
        if stripped:
            monkeypatch.setattr(hook, 'presence_headers', lambda *args, **kwargs: {})
            monkeypatch.setattr(mcp, 'presence_headers', lambda *args, **kwargs: {})
        fake = type(station[0])()
        andy, jenn = fake.user('andy', 'Andy'), fake.user('jenn', 'Jenn')
        ship = fake.user('serenity', 'Serenity', 'ship', andy['id'], key='serenity-key')
        room = fake.room('Ops', andy, jenn, ship)
        fake.say(room, jenn, '@serenity what changed?')
        shown = hook.run(config_path, transport=fake, session_id='s1', mode='write', sessions_dir=tmp_path / f'sessions-{stripped}')
        tools = Tools(StationClient('http://station.test', 'serenity-key', transport=fake))
        said = [call(tools, 'station_read', room=room), call(tools, 'station_post', room=room, text='answer')]
        return shown, said, [(r['method'], r['path'], r['body']) for r in fake.requests], [r['presence'] for r in fake.requests]

    with_headers, without = session(False), session(True)
    assert with_headers[:3] == without[:3]
    assert all(with_headers[3]) and not any(without[3])
