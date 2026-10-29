"""Every route shares one event loop, so no async function reads or writes the store on it (Tardis's nit, 2026-10-29).

A store call takes the process lock and can wait on SQLite's, so made on the loop it stalls every other request,
health included. Identity checks read the store too (`current_user` the session, `member` and `ship_member` the key).
The sync `def` routes already run on the threadpool; the async ones hand both over themselves, in every module that
registers routes (app, door, peer and source routes), as Tardis asked.
"""
import ast
import asyncio
import inspect
import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import superyak_peer.app
from superyak_peer.app import create_app

PACKAGE = Path(superyak_peer.app.__file__).parent
IDENTITY = {'actor', 'member', 'ship_member', 'current_user'}
SERVICES = {'store', 'fed', 'manager', 'sources'}  # the names route modules reach the store through
ON_THE_LOOP = {'store.inbox_wait_slot'}  # an in-memory count of a ship's waits, with no store read
# federation-pull rewrites `sync` in this shape (Tardis, 2026-10-29). These two calls, and no new one, wait for it.
WAITING = {('peer_routes.py', 'sync', 'actor'), ('peer_routes.py', 'sync', 'fed.status')}


def dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return '.'.join([node.id, *reversed(parts)])


def reaches_the_store(name, services):
    return name.split('.')[0] in services or name.startswith(('app.state.', 'request.app.state.'))


def services_in(tree):
    """The service names, plus any name the module binds to one: `s = app.state.store` makes `s` one too."""
    services, grew = set(SERVICES), True
    while grew:
        grew = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                source = dotted(node.value)
                if source is not None and reaches_the_store(source, services):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if isinstance(target, ast.Name) and target.id not in services:
                            services.add(target.id)
                            grew = True
    return services


def blocking_helpers(tree, services):
    """The identity checks, plus every sync function in the module that calls one, the store or another such helper."""
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    blocking, grew = set(IDENTITY), True
    while grew:
        grew = False
        for function in functions:
            if function.name in blocking:
                continue
            for node in ast.walk(function):
                name = dotted(node.func) if isinstance(node, ast.Call) else None
                if name is not None and name not in ON_THE_LOOP and (name in blocking or reaches_the_store(name, services)):
                    blocking.add(function.name)
                    grew = True
                    break
    return blocking


def calls_on_the_loop(read=Path.read_text):
    """(module, async function, line, call) for each call that reads the store on the event loop."""
    found = []
    for path in sorted(PACKAGE.rglob('*.py')):
        tree = ast.parse(read(path))
        services = services_in(tree)
        blocking = blocking_helpers(tree, services)
        for function in ast.walk(tree):
            if not isinstance(function, ast.AsyncFunctionDef):
                continue
            for node in ast.walk(function):
                name = dotted(node.func) if isinstance(node, ast.Call) else None
                if name is None or name in ON_THE_LOOP:
                    continue
                if name in blocking or reaches_the_store(name, services):
                    found.append((path.name, function.name, node.lineno, name))
    return found


def test_no_async_function_in_the_package_calls_the_store_or_an_identity_check_on_the_loop():
    assert [found for found in calls_on_the_loop() if (found[0], found[1], found[3]) not in WAITING] == []


def test_each_waiting_exception_is_still_needed():
    """When federation-pull lands, `sync` runs these calls on the threadpool, this fails, and WAITING goes."""
    assert WAITING <= {(module, function, name) for module, function, _, name in calls_on_the_loop()}


@pytest.mark.parametrize('module,fixed,broken,expected', [
    ('app.py', 'return await run_in_threadpool(store.rename_user, ', 'return store.rename_user(',
     ('app.py', 'rename_me', 'store.rename_user')),
    ('source_routes.py', 'return await run_in_threadpool(manager.create, ', 'return manager.create(',
     ('source_routes.py', 'data_source_create', 'manager.create')),
    ('peer_routes.py', 'who = await caller(current_user, request)\n        data = await body(request)',
     'who = actor(request)\n        data = await body(request)', ('peer_routes.py', 'pair', 'actor')),
    # the review's survivors: an alias, the store through the request, a helper on the loop, a new call in sync
    ('app.py', "return await run_in_threadpool(store.drop_item, who, key, data.get('key'))",
     "db = store\n        return db.drop_item(who, key, data.get('key'))", ('app.py', 'chat_board_drop', 'db.drop_item')),
    ('app.py', 'return await run_in_threadpool(store.link_item, ', 'return request.app.state.store.link_item(',
     ('app.py', 'chat_board_link', 'request.app.state.store.link_item')),
    ('peer_routes.py', 'await run_in_threadpool(admin_check, await caller(current_user, request))',
     'admin_check(await caller(current_user, request))', ('peer_routes.py', 'preview', 'admin_check')),
    ('peer_routes.py', 'await run_in_threadpool(fed.sync_once)\n',
     'await run_in_threadpool(fed.sync_once)\n        fed.connections(who)\n', ('peer_routes.py', 'sync', 'fed.connections')),
])
def test_the_walk_sees_a_call_put_back_on_the_loop(module, fixed, broken, expected):
    def read(path):
        source = path.read_text()
        if path.name != module:
            return source
        assert source.count(fixed) == 1
        return source.replace(fixed, broken)
    assert expected not in WAITING
    assert expected in {(module, function, name) for module, function, _, name in calls_on_the_loop(read)}


# Routes that take no identity: signing in, redeeming an invitation, asking for access, starting a docking, and a
# federation delivery, which is checked by its signature.
ANONYMOUS = {('POST', '/api/login'), ('POST', '/api/invitations/redeem'), ('POST', '/api/access-requests'),
             ('POST', '/api/dockings'), ('POST', '/federation/events')}


def routes_of(app):
    for route in app.routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, 'original_router'):  # FastAPI keeps an included router as one object (Serenity, Task 3)
            yield from (inner for inner in route.original_router.routes if isinstance(inner, APIRoute))


def test_every_async_write_checks_identity_before_it_reads_the_body(tmp_path):
    """Anonymous, with a body that isn't JSON: a route that reads the body first answers 400, not 401 or 403. The app
    has the imprint routes on, and the peer router's routes are walked too."""
    app = create_app(tmp_path / 'peer', allowed_origins=['http://testserver'], imprints_dir=tmp_path / 'imprints')
    anonymous = TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'})
    answers, seen = {}, set()
    for route in routes_of(app):
        if not inspect.iscoroutinefunction(route.endpoint):
            continue
        for method in sorted(route.methods - {'GET', 'HEAD'}):
            if (method, route.path) in ANONYMOUS:
                continue
            url = re.sub(r'\{[^}]+\}', '1', route.path)
            response = anonymous.request(method, url, content=b'not json', headers={'content-type': 'application/json'})
            answers[(method, route.path)] = response.status_code
            seen.add(route.endpoint.__name__)
    assert {'ship_brief', 'chat_send', 'grant_make', 'assist', 'preview', 'pair', 'sync', 'imprint_part'} <= seen
    assert {route: status for route, status in answers.items() if status not in (401, 403)} == {}


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
