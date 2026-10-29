"""Every route shares one event loop, so no async function reads or writes the store on it (Tardis's nit, 2026-10-29).

A store call takes the process lock and can wait on SQLite's, so made on the loop it stalls every other request,
health included. Identity checks read the store too (`current_user` the session, `member` and `ship_member` the key).
The sync `def` routes already run on the threadpool; the async ones hand both over themselves, in every module that
registers routes (app, door, peer and source routes), as Tardis asked.
"""
import ast
import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import superyak_peer.app

PACKAGE = Path(superyak_peer.app.__file__).parent
IDENTITY = {'actor', 'member', 'ship_member', 'current_user'}
SERVICES = {'store', 'fed', 'manager', 'sources'}  # the names route modules reach the store through
ON_THE_LOOP = {'store.inbox_wait_slot'}  # an in-memory count of a ship's waits, with no store read
WAITING = {'peer_routes.py:sync'}  # federation-pull rewrites it in this shape (Tardis, 2026-10-29); goes when it lands


def dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return '.'.join([node.id, *reversed(parts)])


def calls_on_the_loop(read=Path.read_text):
    found = []
    for path in sorted(PACKAGE.glob('*.py')):
        for function in ast.walk(ast.parse(read(path))):
            if not isinstance(function, ast.AsyncFunctionDef):
                continue
            for node in ast.walk(function):
                name = dotted(node.func) if isinstance(node, ast.Call) else None
                if name is None or name in ON_THE_LOOP:
                    continue
                if name in IDENTITY or name.split('.')[0] in SERVICES or name.startswith('app.state.'):
                    found.append(f'{path.name}:{function.name}:{node.lineno} calls {name}()')
    return found


def test_no_async_function_in_the_package_calls_the_store_or_an_identity_check_on_the_loop():
    assert [found for found in calls_on_the_loop() if found.rsplit(':', 1)[0] not in WAITING] == []


def test_each_waiting_exception_is_still_needed():
    """When federation-pull lands, `sync` runs its calls on the threadpool, this fails, and its WAITING entry goes."""
    assert WAITING <= {found.rsplit(':', 1)[0] for found in calls_on_the_loop()}


@pytest.mark.parametrize('module,fixed,broken,expected', [
    ('app.py', 'return await run_in_threadpool(store.rename_user, ', 'return store.rename_user(', 'app.py:rename_me:'),
    ('source_routes.py', 'return await run_in_threadpool(manager.create, ', 'return manager.create(',
     'source_routes.py:data_source_create:'),
    ('peer_routes.py', 'who = await caller(current_user, request)\n        data = await body(request)',
     'who = actor(request)\n        data = await body(request)', 'peer_routes.py:pair:'),
])
def test_the_walk_sees_a_call_put_back_on_the_loop(module, fixed, broken, expected):
    def read(path):
        source = path.read_text()
        if path.name != module:
            return source
        assert source.count(fixed) == 1
        return source.replace(fixed, broken)
    assert any(found.startswith(expected) for found in calls_on_the_loop(read))


def ship_client(app, key):
    return TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver', 'authorization': f'Bearer {key}'})


def docked(store, owner_id, name):
    started = store.start_docking(name, 'test-host')
    ship = store.confirm_docking(owner_id, started['id'], started['code'])
    return ship, store.docking_status(started['id'], started['secret'])['key']


def recording(monkeypatch, store, *names):
    seen = []
    for name in names:
        real = getattr(store, name)

        def record(*args, _name=name, _real=real, **kwargs):
            try:
                asyncio.get_running_loop()
                seen.append((_name, 'loop'))
            except RuntimeError:
                seen.append((_name, 'worker'))
            return _real(*args, **kwargs)
        monkeypatch.setattr(store, name, record)
    return seen


@pytest.mark.parametrize('method,path,payload,write', [
    ('patch', '/api/me', {'name': 'Patient Two'}, 'rename_user'),
    ('post', '/api/chats', {'title': 'A room', 'member_ids': []}, 'create_room'),
    ('post', '/api/invitations', {}, 'invite'),
])
def test_a_person_route_checks_the_session_and_writes_on_a_worker(env, monkeypatch, method, path, payload, write):
    app, clients, *_ = env
    client = clients[2]  # the organizer, an admin, so the invitation route answers too
    seen = recording(monkeypatch, app.state.store, 'session', write)
    response = getattr(client, method)(path, json=payload)
    assert response.status_code < 300, response.text
    assert ('session', 'worker') in seen and (write, 'worker') in seen
    assert all(where == 'worker' for _, where in seen), seen


def test_a_ship_route_checks_the_key_and_writes_on_a_worker(env, monkeypatch):
    app, _, users, _ = env
    store = app.state.store
    _, key = docked(store, users[0]['id'], 'serenity')
    seen = recording(monkeypatch, store, 'ship_for_key', 'station_watch')
    response = ship_client(app, key).post('/api/ships/me/watch', json={'minutes': 5},
                                          headers={'x-superyak-session': 'session-one'})
    assert response.status_code == 200, response.text
    assert seen == [('ship_for_key', 'worker'), ('station_watch', 'worker')]


def test_a_ship_message_is_written_on_a_worker(env, monkeypatch):
    app, clients, users, _ = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'], 'serenity')
    room = clients[0].post('/api/chats', json={'title': 'Work', 'member_ids': [ship['id']]}).json()
    seen = recording(monkeypatch, store, 'ship_for_key', 'send_message')
    response = ship_client(app, key).post(f'/api/chats/{room["id"]}/messages',
                                          json={'client_message_id': 'm1', 'body': 'hello'})
    assert response.status_code == 201, response.text
    assert seen == [('ship_for_key', 'worker'), ('send_message', 'worker')]


def test_an_anonymous_write_runs_on_a_worker(env, monkeypatch):
    app, *_ = env
    seen = recording(monkeypatch, app.state.store, 'request_access', 'start_docking')
    client = TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'})
    assert client.post('/api/access-requests', json={'name': 'Willa', 'contact': 'w@example.org'}).status_code == 201
    assert client.post('/api/dockings', json={'ship_name': 'defiant', 'machine': 'host'}).status_code == 201
    assert seen == [('request_access', 'worker'), ('start_docking', 'worker')]


def test_the_identity_check_still_comes_before_the_body(env):
    """The order holds: a ship key on a person's route gets 403 for the key, not 400 for a body that isn't JSON."""
    app, _, users, _ = env
    _, key = docked(app.state.store, users[0]['id'], 'serenity')
    response = ship_client(app, key).post('/api/grants', content=b'not json', headers={'content-type': 'application/json'})
    assert response.status_code == 403
    assert response.json()['error'] == 'Ship keys cannot use this route'
