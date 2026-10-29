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


def dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return '.'.join([node.id, *reversed(parts)])


# What app.state holds that blocks: the store, what reaches it, and the local model. Its other entries (an Event, flags,
# the sign-in lanes) are loop objects, so `app.state.` alone isn't one.
HELD = ('store', 'federation', 'interchange', 'data_sources', 'assistant')
HELD_AT = tuple(f'{owner}.{held}' for owner in ('app.state', 'request.app.state') for held in HELD) + ('self.store',)


def reaches_the_store(name, services):
    return name.split('.')[0] in services or any(name == root or name.startswith(root + '.') for root in HELD_AT)


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


def sync_functions(tree):
    """(the name a call uses, the function) for each sync function: a method is called as `self.<name>`."""
    methods = {id(node) for cls in ast.walk(tree) if isinstance(cls, ast.ClassDef) for node in cls.body
               if isinstance(node, ast.FunctionDef)}
    return [('self.' + node.name if id(node) in methods else node.name, node)
            for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]


def blocking_helpers(tree, services, imported=frozenset()):
    """The identity checks and `imported` (blocking helpers this module imports), plus every sync function or method
    in the module that calls one of them, the store or another such helper."""
    functions = sync_functions(tree)
    blocking, grew = set(IDENTITY) | set(imported), True
    while grew:
        grew = False
        for called_as, function in functions:
            if called_as in blocking:
                continue
            for node in ast.walk(function):
                name = dotted(node.func) if isinstance(node, ast.Call) else None
                if name is not None and name not in ON_THE_LOOP and (name in blocking or reaches_the_store(name, services)):
                    blocking.add(called_as)
                    grew = True
                    break
    return blocking


def on_the_loop(function):
    """The nodes of an async function that run on the loop. A nested function is walked on its own, and a lambda handed
    to run_in_threadpool runs on a worker."""
    stack = list(ast.iter_child_nodes(function))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        yield node
        handed_over = isinstance(node, ast.Call) and (dotted(node.func) or '').endswith('run_in_threadpool')
        stack.extend(child for child in ast.iter_child_nodes(node) if not (handed_over and isinstance(child, ast.Lambda)))


def imports_from_siblings(tree):
    """(sibling module, name) for each `from .module import name`."""
    return [(node.module, alias.asname or alias.name) for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module for alias in node.names]


def calls_on_the_loop(read=Path.read_text):
    """(module, async function, line, call) for each call that reads the store on the event loop."""
    trees = {path: ast.parse(read(path)) for path in sorted(PACKAGE.rglob('*.py'))}
    services = {path: services_in(tree) for path, tree in trees.items()}
    blocking = {path: blocking_helpers(tree, services[path]) for path, tree in trees.items()}
    for _ in range(3):  # a helper imported from a sibling module counts as that module's blocking helper
        for path, tree in trees.items():
            imported = {name for module, name in imports_from_siblings(tree)
                        if name in blocking.get(path.parent / f'{module.replace(".", "/")}.py', set())}
            blocking[path] = blocking_helpers(tree, services[path], imported)
    found = []
    for path, tree in trees.items():
        for function in ast.walk(tree):
            if not isinstance(function, ast.AsyncFunctionDef):
                continue
            for node in on_the_loop(function):
                name = dotted(node.func) if isinstance(node, ast.Call) else None
                if name is None or name in ON_THE_LOOP:
                    continue
                if name in blocking[path] or reaches_the_store(name, services[path]):
                    found.append((path.name, function.name, node.lineno, name))
    return found


def test_no_async_function_in_the_package_calls_the_store_or_an_identity_check_on_the_loop():
    assert calls_on_the_loop() == []


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
    ('peer_routes.py', 'await run_in_threadpool(fed.make_due)\n',
     'await run_in_threadpool(fed.make_due)\n        fed.connections(who)\n', ('peer_routes.py', 'sync', 'fed.connections')),
    # the re-check's: a method reached through self, and a helper imported from a sibling module
    ('app.py', 'await run_in_threadpool(self.valid, key, token)', 'self.valid(key, token)',
     ('app.py', 'refusal', 'self.valid')),
    ('app.py', 'return await run_in_threadpool(store.shorten_imprint, ',
     'sign_first(store)\n            return await run_in_threadpool(store.shorten_imprint, ',
     ('app.py', 'imprint_shorten', 'sign_first')),
    # the last pass's: an alias of self.store, and a held object reached through app.state
    ('app.py', '        if (key is not None or token is not None) and await run_in_threadpool(self.valid, key, token):',
     '        s = self.store\n        if s.session_is_valid(token):', ('app.py', 'refusal', 's.session_is_valid')),
    ('app.py', "return await run_in_threadpool(store.rename_user, who, data.get('name'))",
     "app.state.federation.status(who)\n        return await run_in_threadpool(store.rename_user, who, data.get('name'))",
     ('app.py', 'rename_me', 'app.state.federation.status')),
])
def test_the_walk_sees_a_call_put_back_on_the_loop(module, fixed, broken, expected):
    def read(path):
        source = path.read_text()
        if path.name != module:
            return source
        assert source.count(fixed) == 1
        return source.replace(fixed, broken)
    assert expected in {(module, function, name) for module, function, _, name in calls_on_the_loop(read)}


def test_a_lambda_handed_to_the_threadpool_is_off_the_loop():
    def read(path):
        source = path.read_text()
        if path.name != 'app.py':
            return source
        fixed = "return await run_in_threadpool(store.drop_item, who, key, data.get('key'))"
        assert source.count(fixed) == 1
        return source.replace(fixed, "return await run_in_threadpool(lambda: store.drop_item(who, key, data.get('key')))")
    assert not [found for found in calls_on_the_loop(read) if found[1] == 'chat_board_drop']


def test_a_loop_object_on_app_state_is_not_the_store():
    """federation-pull's wake is an asyncio.Event on app.state: setting it on the loop is right, and isn't flagged."""
    def read(path):
        source = path.read_text()
        if path.name != 'app.py':
            return source
        fixed = "return await run_in_threadpool(store.rename_user, who, data.get('name'))"
        assert source.count(fixed) == 1
        return source.replace(fixed, 'app.state.sync_wake.set()\n        ' + fixed)
    assert not [found for found in calls_on_the_loop(read) if found[1] == 'rename_me']


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
    anonymous = TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'},
                           client=('127.0.0.1', 50000))  # tailnet, so PublicRoute lets it reach the route
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
