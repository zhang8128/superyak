"""Every route shares one event loop, so no async function reads or writes the store on it (Tardis's nit, 2026-10-29).

A store call takes the process lock and can wait on SQLite's, so made on the loop it stalls every other request,
health included. Identity checks read the store too (`current_user` the session, `member` and `ship_member` the key).
The sync `def` routes already run on the threadpool; the async ones hand both over themselves, in every module that
registers routes (app, door, peer and source routes), as Tardis asked.
"""
import ast
import asyncio
import functools
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
HANDOFFS = {'run_in_threadpool', 'asyncio.to_thread'}  # by exact name: a function of the package's own is no handoff


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


def bindings(node):
    """(target, value) pairs an assignment makes, pairing a tuple of names with a tuple of values one to one."""
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    for target in targets:
        if isinstance(target, ast.Tuple) and isinstance(node.value, ast.Tuple) and len(target.elts) == len(node.value.elts):
            yield from zip(target.elts, node.value.elts)
        else:
            yield target, node.value


def services_in(tree):
    """The service names, plus any name the module binds to one: `s = app.state.store`, or `s, n = store, 1`, makes `s`
    one too."""
    assignments = [pair for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value
                   is not None for pair in bindings(node)]
    services, grew = set(SERVICES), True
    while grew:
        grew = False
        for target, value in assignments:
            source = dotted(value)
            if (source is not None and reaches_the_store(source, services) and isinstance(target, ast.Name)
                    and target.id not in services):
                services.add(target.id)
                grew = True
    return services


def calls_in(node, skip_nested=False):
    """The dotted names a node calls. With skip_nested, as an async function runs them on the loop: a nested function
    is walked on its own, and a lambda handed to run_in_threadpool or asyncio.to_thread runs on a worker."""
    stack = list(ast.iter_child_nodes(node))
    while stack:
        node = stack.pop()
        if skip_nested and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name = dotted(node.func) if isinstance(node, ast.Call) else None
        if name is not None:
            yield node.lineno, name
        handed_over = skip_nested and name in HANDOFFS
        stack.extend(child for child in ast.iter_child_nodes(node) if not (handed_over and isinstance(child, ast.Lambda)))


def facts(source):
    return _facts(source, frozenset(SERVICES), HELD_AT, frozenset(ON_THE_LOOP), frozenset(HANDOFFS))


@functools.lru_cache(maxsize=None)
def _facts(source, *_globals):
    """What the walk needs from one module, read once per source: its service names, each sync function's calls (a
    method is called as `self.<name>`), its sibling imports (module, name, local name) and each async function's calls
    on the loop."""
    tree = ast.parse(source)
    methods = {id(node) for cls in ast.walk(tree) if isinstance(cls, ast.ClassDef) for node in cls.body
               if isinstance(node, ast.FunctionDef)}
    sync = [('self.' + node.name if id(node) in methods else node.name, frozenset(name for _, name in calls_in(node)))
            for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    imports = [(node.module, alias.name, alias.asname or alias.name) for node in ast.walk(tree)
               if isinstance(node, ast.ImportFrom) and node.level == 1 for alias in node.names]
    loops = [(node.name, tuple(calls_in(node, skip_nested=True))) for node in ast.walk(tree)
             if isinstance(node, ast.AsyncFunctionDef)]
    return frozenset(services_in(tree)), tuple(sync), tuple(imports), tuple(loops)


def blocking_helpers(services, sync, imported=frozenset()):
    """The identity checks and `imported` (blocking helpers this module imports), plus every sync function or method
    in the module that calls one of them, the store or another such helper."""
    blocking = set(IDENTITY) | set(imported)
    direct = {called_as for called_as, calls in sync
              if any(name not in ON_THE_LOOP and reaches_the_store(name, services) for name in calls)}
    blocking |= direct
    grew = True
    while grew:
        grew = False
        for called_as, calls in sync:
            if called_as not in blocking and (calls - ON_THE_LOOP) & blocking:
                blocking.add(called_as)
                grew = True
    return blocking


def calls_on_the_loop(read=Path.read_text):
    """(module, async function, line, call) for each call that reads the store on the event loop."""
    modules = {path: facts(read(path)) for path in sorted(PACKAGE.rglob('*.py'))}
    blocking = {path: blocking_helpers(known[0], known[1]) for path, known in modules.items()}
    for _ in range(3):  # a helper imported from a sibling module, under any local name, counts as blocking there too
        for path, (services, sync, imports, _) in modules.items():
            imported = {local for module, name, local in imports if module
                        and name in blocking.get(path.parent / f'{module.replace(".", "/")}.py', set())}
            imported |= {f'{local}.{helper}' for module, name, local in imports if module is None  # `from . import m`
                         for helper in blocking.get(path.parent / f'{name}.py', set()) if '.' not in helper}
            blocking[path] = blocking_helpers(services, sync, imported)
    found = []
    for path, (services, _, _, loops) in modules.items():
        for function, calls in loops:
            for line, name in calls:
                if name not in ON_THE_LOOP and (name in blocking[path] or reaches_the_store(name, services)):
                    found.append((path.name, function, line, name))
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
    # Tardis's: an alias made by unpacking a tuple
    ('app.py', "return await run_in_threadpool(store.drop_item, who, key, data.get('key'))",
     "s, k = store, key\n        return s.drop_item(who, k, data.get('key'))", ('app.py', 'chat_board_drop', 's.drop_item')),
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


def reading(module, *changes):
    """A read for calls_on_the_loop with each (fixed, broken) change made once in one module."""
    def read(path):
        source = path.read_text()
        if path.name != module:
            return source
        for fixed, broken in changes:
            assert source.count(fixed) == 1, fixed
            source = source.replace(fixed, broken)
        return source
    return read


def test_a_helper_imported_under_another_name_is_seen():
    read = reading('app.py',
                   ('from .peer_routes import federation_lifespan, install, sign_first\n',
                    'from .peer_routes import federation_lifespan, install, sign_first as sign_now\n'),
                   ('            return await run_in_threadpool(store.shorten_imprint, ',
                    '            sign_now(store)\n            return await run_in_threadpool(store.shorten_imprint, '))
    assert ('app.py', 'imprint_shorten', 'sign_now') in {(m, f, n) for m, f, _, n in calls_on_the_loop(read)}


def test_a_lambda_handed_to_asyncio_to_thread_is_off_the_loop():
    read = reading('app.py', ("return await run_in_threadpool(store.drop_item, who, key, data.get('key'))",
                              "return await asyncio.to_thread(lambda: store.drop_item(who, key, data.get('key')))"))
    assert not [found for found in calls_on_the_loop(read) if found[1] == 'chat_board_drop']


def test_a_lambda_handed_to_a_function_of_our_own_is_on_the_loop():
    """Only run_in_threadpool and asyncio.to_thread hand work over: a package function ending in `to_thread` runs
    its argument where it's called (the guard-nits review's must-fix)."""
    read = reading('app.py',
                   ('def actor(request):\n', 'def hand_to_thread(work):\n    return work()\n\n\ndef actor(request):\n'),
                   ("return await run_in_threadpool(store.drop_item, who, key, data.get('key'))",
                    "return hand_to_thread(lambda: store.drop_item(who, key, data.get('key')))"))
    assert ('app.py', 'chat_board_drop', 'store.drop_item') in {(m, f, n) for m, f, _, n in calls_on_the_loop(read)}


def test_a_nested_function_handed_to_the_threadpool_is_off_the_loop():
    read = reading('app.py', ("return await run_in_threadpool(store.drop_item, who, key, data.get('key'))",
                              "def work():\n            return store.drop_item(who, key, data.get('key'))\n"
                              "        return await run_in_threadpool(work)"))
    assert not [found for found in calls_on_the_loop(read) if found[1] == 'chat_board_drop']


def test_a_helper_reached_through_an_imported_sibling_module_is_seen():
    read = reading('app.py', ('from .agent_version import agent_update\n',
                              'from .agent_version import agent_update\nfrom . import peer_routes as pr\n'),
                   ('            return await run_in_threadpool(store.shorten_imprint, ',
                    '            pr.sign_first(store)\n            return await run_in_threadpool(store.shorten_imprint, '))
    assert ('app.py', 'imprint_shorten', 'pr.sign_first') in {(m, f, n) for m, f, _, n in calls_on_the_loop(read)}


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
             ('POST', '/api/dockings'), ('POST', '/federation/events'),
             ('POST', '/register'),  # the connector's registration is public by design (spec r4, D18)
             ('POST', '/authorize/signin')}  # its identity is in its body: the signed request and the password


def routes_of(app):
    for route in app.routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, 'original_router'):  # FastAPI keeps an included router as one object (Serenity, Task 3)
            yield from (inner for inner in route.original_router.routes if isinstance(inner, APIRoute))


def anonymous_answers(app, origin, monkeypatch):
    """Each async write route's answer to an anonymous caller sending a body that isn't JSON, whether the route read
    the body before answering, and the endpoints seen. Every route-level read (body(), json(), form(), a hand parse)
    goes through Request.stream; the size bound below the routes reads at the ASGI level, so it isn't counted."""
    from starlette.requests import Request
    reads, real = [], Request.stream

    def watched(self):
        reads.append(self.url.path)
        return real(self)
    monkeypatch.setattr(Request, 'stream', watched)
    anonymous = TestClient(app, base_url=origin, headers={'origin': origin},
                           client=('127.0.0.1', 50000))  # tailnet, so PublicRoute lets it reach the route
    answers, seen = {}, set()
    for route in routes_of(app):
        if not inspect.iscoroutinefunction(route.endpoint):
            continue
        for method in sorted(route.methods - {'GET', 'HEAD'}):
            if (method, route.path) in ANONYMOUS:
                seen.add(route.endpoint.__name__)
                continue
            url = re.sub(r'\{[^}]+\}', '1', route.path)
            reads.clear()
            response = anonymous.request(method, url, content=b'not json', headers={'content-type': 'application/json'})
            answers[(method, route.path)] = (response.status_code, bool(reads))
            seen.add(route.endpoint.__name__)
    return answers, seen


def test_every_async_write_checks_identity_before_it_reads_the_body(tmp_path, monkeypatch):
    """Anonymous, with a body that isn't JSON: each route refuses (401 or 403) without reading its body. A route that
    reads first answers 400 to the JSON, or reads a form and then refuses; either fails here. The app has the imprint
    routes on, and the peer router's routes are walked too."""
    app = create_app(tmp_path / 'peer', allowed_origins=['http://testserver'], imprints_dir=tmp_path / 'imprints')
    answers, seen = anonymous_answers(app, 'http://testserver', monkeypatch)
    assert {'ship_brief', 'chat_send', 'grant_make', 'assist', 'preview', 'pair', 'sync', 'imprint_part'} <= seen
    assert {route: answer for route, answer in answers.items() if answer[0] not in (401, 403) or answer[1]} == {}


def test_the_connector_routes_are_walked_too(tmp_path, monkeypatch):
    """Tardis's forward point: with the connector on, its async write routes join the walk. Each one either takes no
    identity by design and is listed in ANONYMOUS (`/register`, spec r4 D18), or refuses an anonymous caller without
    reading its body. Today only /register is async; a route Task 5 makes async meets this the day it does."""
    origin = 'https://home.example'
    app = create_app(tmp_path / 'peer', allowed_origins=['http://testserver', origin], public_origin=origin)
    answers, seen = anonymous_answers(app, origin, monkeypatch)
    assert 'register' in seen
    assert {route: answer for route, answer in answers.items() if answer[0] not in (401, 403) or answer[1]} == {}


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
