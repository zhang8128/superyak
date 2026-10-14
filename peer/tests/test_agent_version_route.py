from fastapi.testclient import TestClient

from superyak_peer.agent_version import AgentHistory

BEHIND, CURRENT, STATION = 'aaaaaaaaaaaa', 'bbbbbbbbbbbb', 'cccccccccccc'


def ship_client(app, client=None):
    store = app.state.store
    ship = store.create_station_ship('odo', 'Odo')
    headers = {'origin': 'http://testserver', 'authorization': f'Bearer {store.issue_ship_key(ship["id"])}'}
    if client:
        headers |= {'x-superyak-session': 'session-1', 'x-superyak-client': client}
    return TestClient(app, base_url='http://testserver', headers=headers)


def test_a_ship_behind_gets_agent_update(env):
    app = env[0]
    app.state.agent_history = AgentHistory(STATION, frozenset({BEHIND}))
    body = ship_client(app, f'hook/{BEHIND}').get('/api/ships/me/instructions').json()
    assert body['agent_update'] == {'station': STATION}


def test_an_mcp_client_behind_gets_the_key_too(env):
    app = env[0]
    app.state.agent_history = AgentHistory(STATION, frozenset({BEHIND}))
    assert ship_client(app, f'mcp/{BEHIND}').get('/api/ships/me/instructions').json()['agent_update'] == {'station': STATION}


def test_every_other_case_is_byte_for_byte_todays_response(env):
    app = env[0]
    client = ship_client(app)
    app.state.agent_history = None
    today = client.get('/api/ships/me/instructions').content
    app.state.agent_history = AgentHistory(STATION, frozenset({BEHIND}))
    for headers in ({}, {'x-superyak-session': 's2', 'x-superyak-client': f'hook/{CURRENT}'},
                    {'x-superyak-session': 's3', 'x-superyak-client': 'hook/unknown'},
                    {'x-superyak-session': 's4', 'x-superyak-client': 'hook/not-hex!'},
                    {'x-superyak-client': f'hook/{BEHIND}'}):  # no session name: no presence at all
        assert client.get('/api/ships/me/instructions', headers=headers).content == today, headers


def test_create_app_has_no_history_unless_given(env):
    assert env[0].state.agent_history is None


def test_serve_passes_the_loaded_history_to_create_app(monkeypatch, tmp_path):
    import sys
    import types
    from superyak_peer import __main__ as cli, agent_version, app as app_module
    seen = {}
    monkeypatch.setattr(agent_version, 'load', lambda: AgentHistory(STATION, frozenset()))
    # serve imports create_app and uvicorn inside its branch (__main__.py:330-331), so patch where they are looked up
    monkeypatch.setattr(app_module, 'create_app', lambda *a, **kw: seen.update(kw) or object())
    monkeypatch.setitem(sys.modules, 'uvicorn', types.SimpleNamespace(run=lambda *a, **kw: None))
    cli.main(['serve', '--data-dir', str(tmp_path / 'd')])
    assert seen['agent_history'] == AgentHistory(STATION, frozenset())
