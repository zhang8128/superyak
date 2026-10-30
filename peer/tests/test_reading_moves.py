"""The named pure reads off the gate (spec 2026-10-29-store-wal-mode D3, plan Task 5): each moved function runs on a WAL
store while another thread holds the dispatch gate and an open write, and changes no table and no file; no gated caller
reaches one; the inbox budget's shared state is locked; and one signed pull served twice at once is one replay."""
import ast
from collections import defaultdict
from contextlib import closing
import hashlib
import itertools
import json
from pathlib import Path
import sqlite3
import sys
import threading
from types import SimpleNamespace

import pytest

import superyak_peer
from superyak_peer import inbox
from superyak_peer.common import Problem
from superyak_peer.db import Store
from superyak_peer.federate import Federate
from superyak_peer.identity import canonical
from superyak_peer.journal_mode import switch_journal
from conftest import paired
from test_federation_outcomes import Clock, station
from test_federation_pull import request as pull_request
from test_presence import docked
from test_reading import gate_and_write_held, timed

# The functions D3 lets leave the gate, by module and qualified name. Every other read stays on transaction().
MOVED_READS = (
    'auth.Auth.session',
    'auth.Auth.session_is_valid',
    'auth.Auth.device_is_valid',
    'ships.Ships.ship_key_is_valid',
    'ships.Ships.station_rooms',
    'ships.Ships.station_notices',
    'connector.Connector.bearer',
    'federation.Federation._due_rows',
    'federation.Federation._pending_count',
    'federation.Federation._pull_keys',
    'federation.Federation._pull_left',
    'federate.Federate._requests',
    'federate.Federate.pull_cards',
    'federate.Federate._pushed',
    'room_board.RoomBoard.board_counts',
    'room_board.RoomBoard.board_view',
)
DAY = 86400
NOW = 1_800_000_000.0
RESOURCE = 'https://home.example/mcp'
SHIPS = ('serenity', 'tardis', 'defiant')

# Each moved read as the busy store's case calls it: what a route or a worker passes it there.
CALLS = {
    'auth.Auth.session': lambda s: s.store.session(s.token),
    'auth.Auth.session_is_valid': lambda s: s.store.session_is_valid(s.token),
    'auth.Auth.device_is_valid': lambda s: s.store.device_is_valid(s.device, 'andy'),
    'ships.Ships.ship_key_is_valid': lambda s: s.store.ship_key_is_valid(s.ship_key),
    'ships.Ships.station_rooms': lambda s: s.store.station_rooms('andy'),
    'ships.Ships.station_notices': lambda s: s.store.station_notices(),
    'connector.Connector.bearer': lambda s: s.store.bearer(s.access, RESOURCE),
    'federation.Federation._due_rows': lambda s: s.fed._due_rows(20),
    'federation.Federation._pending_count': lambda s: s.fed._pending_count(),
    'federation.Federation._pull_keys': lambda s: s.fed._pull_keys(s.pull_peer),
    'federation.Federation._pull_left': lambda s: s.fed._pull_left(s.pull_peer),
    'federate.Federate._requests': lambda s: s.federate._requests(),
    'federate.Federate.pull_cards': lambda s: s.federate.pull_cards(),
    'federate.Federate._pushed': lambda s: s.federate._pushed(),
    'room_board.RoomBoard.board_counts': lambda s: s.store.board_counts(s.ids['serenity']),
    'room_board.RoomBoard.board_view': lambda s: s.store.board_view(s.ids['andy']),
}


def tables(store):
    """A hash of every table, read on a connection of its own: in WAL it never sees the held write."""
    with closing(sqlite3.connect(store.db_path)) as db:
        return hashlib.sha256('\n'.join(db.iterdump()).encode()).hexdigest()


def files(store):
    """(name, size, mtime_ns) of every file under the data directory but the WAL's own two."""
    found = [path for path in store.data_dir.rglob('*') if path.is_file()]
    return sorted((str(path.relative_to(store.data_dir)), path.stat().st_size, path.stat().st_mtime_ns)
                  for path in found if path.name not in ('peer.sqlite3-wal', 'peer.sqlite3-shm'))


@pytest.fixture
def busy_wal_store(tmp_path):
    """A WAL store seeded with the rows a moved read could act on only on some data: a quiet breakout (a room read closes
    it lazily), a replaced room, docked ships, a pending docking, a received imprint with its staged request, a quiet pull
    peer and a failing push peer with an outbox row each, a connector grant and token, a board item and a claim, a
    moderate grant and a local layer; then the gate and an open write held on another thread until the case ends."""
    clock = Clock(NOW - 8 * DAY)  # the room and the peers come first, so the breakout and the pull peer are quiet by NOW
    store, andy, fed = station(tmp_path / 'station', 'andy', clock)
    switch_journal(store.data_dir, 'wal', active=lambda: [])
    ships = {name: docked(store, andy, name) for name in SHIPS}
    ids = {'andy': andy, **{name: ship['id'] for name, (ship, _) in ships.items()}}
    first = store.create_room(andy, 'All hands', [ids['serenity'], ids['tardis']])['id']
    hands = store.add_participants(andy, first, [ids['defiant']])['id']  # `first` is now a replaced room
    store.open_breakout(ids['serenity'], 'Side talk', ['tardis'])  # nobody speaks in it, so it is quiet by NOW
    peers = {'mac': station(tmp_path / 'mac', 'mo', clock, mode='pull'), 'push': station(tmp_path / 'push', 'pat', clock)}
    contacts = {}
    for key, (_, user, other) in peers.items():
        contacts[key] = paired(fed, andy, other.card(user))['id']
        paired(other, user, fed.card(andy))
    layer = store.create_layer(andy, {'body': 'hello', 'audience_users': list(contacts.values())})['id']
    store.activate_layer(andy, layer, 1)
    fed.collect()  # an outbox row for each peer
    clock.at = NOW
    store.start_docking('voyager', 'legion-go')  # waiting for its owner: a pending docking
    signed_in = store.login('andy', 'a-long-password', '127.0.0.1', public=False)
    store.post_item(andy, hands, 'wal-build', 'Build the WAL mode', 'build')
    store.claim(ids['serenity'], hands, 'wal-build', 'on it')
    store.make_moderate_grant(andy, ids['tardis'], hands)
    fed.make_due()  # every peer due now, and one sync request counted
    staged = b'{"kind": "imprint-request"}'
    (store.data_dir / 'imprints' / ('b' * 32)).mkdir(parents=True)
    (store.data_dir / 'imprints' / ('b' * 32) / 'request.json').write_bytes(staged)
    with store.transaction() as db:
        db.execute('UPDATE peer_delivery SET failures=3, failing_since=?, last_problem=? WHERE peer_id=?',
                   (NOW - 2 * DAY, 'OSError', peers['push'][2].identity.peer_id))
        db.execute('INSERT INTO imprint_requests(id, imprint_id, ship_id, owner_id, status, created, expires, request_sha256, '
                   "source_instance_id) VALUES(?,?,?,?,'received',?,?,?,?)", ('b' * 32, 'c0a8f5e2', ids['serenity'], andy,
                   int(NOW), int(NOW) + 600, hashlib.sha256(staged).hexdigest(), '3f2a9c1e'))
        db.execute("INSERT INTO oauth_clients VALUES('claude', 'Claude', 'authorization_code refresh_token', ?)", (NOW,))
        db.execute('INSERT INTO connector_grants(id, person_id, client_id, redirect_host, rooms, scope, created, ends) '
                   "VALUES('grant', ?, 'claude', 'claude.ai', ?, 'rooms.read', ?, ?)", (andy, json.dumps([hands]), NOW, NOW + DAY))
        grant = db.execute("SELECT * FROM connector_grants WHERE id='grant'").fetchone()
        access = store._mint(db, grant, 'rooms.read', RESOURCE, NOW)['access_token']
    seeded = SimpleNamespace(store=store, fed=fed, federate=Federate(fed), ids=ids, token=signed_in['token'],
                             device=signed_in['device'], ship_key=ships['serenity'][1], access=access, layer=layer,
                             pull_peer=peers['mac'][2].identity.peer_id)
    with gate_and_write_held(store):
        yield seeded


@pytest.mark.parametrize('name', MOVED_READS)
def test_each_moved_read_runs_while_the_gate_and_a_write_are_held(busy_wal_store, name):
    """D3 rule 2: with the gate and an open write held on another thread, the read answers within 200 ms, leaves every
    table as it was and changes no file but the -wal and -shm. A function still on transaction() waits at the join; one
    that writes (a lazy closure, a last_used), creates a file or opens its own transaction fails here too."""
    seeded = busy_wal_store
    before, done = (tables(seeded.store), files(seeded.store)), {}

    def call():
        try:
            done['value'], done['took'] = timed(lambda: CALLS[name](seeded))
        except BaseException as error:  # noqa: BLE001 - the assert below shows it
            done['error'] = error
    worker = threading.Thread(target=call, daemon=True)
    worker.start()
    worker.join(2)
    assert not worker.is_alive(), f'{name} waited for the gate'
    assert 'error' not in done, done.get('error')
    assert done['value'] and done['took'] < 0.2  # each case's seed gives it something to answer
    assert (tables(seeded.store), files(seeded.store)) == before


# ---- The transitive caller check: no production path reaches a moved read from inside the gate ----

PACKAGE = Path(superyak_peer.__file__).parent
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
GATED_CALLS = {'transaction', 'reading', 'bounded', 'DispatchGate'}
# The walk's named allowance: (the gated caller, the moved read the walk says it reaches), each with why it is not one.
ALLOWED = {}


def _own(nodes):
    """The nodes of a body, its lambdas included, without the functions and classes defined in it (each is walked as one
    of its own, and is reached only where it is named)."""
    todo = list(nodes)
    while todo:
        node = todo.pop()
        yield node
        todo.extend(child for child in ast.iter_child_nodes(node) if not isinstance(child, SCOPES))


def _parameters(args):
    return {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs + [v for v in (args.vararg, args.kwarg) if v]}


def _variables(function, nodes):
    """A function's parameters, its lambdas' and every name it assigns: loading one reads a variable, not a function."""
    found = _parameters(function.args)
    for node in nodes:
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            found.add(node.id)
        elif isinstance(node, ast.Lambda):
            found |= _parameters(node.args)
    return found


def _enters_the_gate(expr, bound):
    """Whether a with item enters the gate, a reading or a bounded gate wait: a call of .transaction(), .reading() or
    .bounded(), a DispatchGate, the dispatch_gate attribute, `gate` (send_pinned's `gate or nullcontext()`), or a name
    the function bound to one of these (lessons.query's `with bound:`)."""
    if isinstance(expr, ast.Name) and expr.id in bound:
        return True
    for node in ast.walk(expr):
        if isinstance(node, ast.Call):
            called = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', None)
            if called in GATED_CALLS:
                return True
        if (isinstance(node, ast.Attribute) and node.attr == 'dispatch_gate'
                or isinstance(node, ast.Name) and node.id == 'gate'):
            return True
    return False


class Package:
    """Every function in superyak_peer, by module and qualified name, and the functions each one's own body names, by
    name: a bare name means any function of that name in its module or imported from one, an attribute any method of
    that name in any class (or a function stored as an attribute, such as app.state.sign_in_lane), so the walk may find
    too much, never too little, for every call it can see."""

    def __init__(self):
        self.defs, self.methods, self.functions = {}, defaultdict(set), defaultdict(set)
        self.imported, self.modules, self.stored = defaultdict(dict), defaultdict(dict), defaultdict(set)
        trees = {path.stem: ast.parse(path.read_text(), str(path)) for path in sorted(PACKAGE.glob('*.py'))}
        for module, tree in trees.items():
            self._index(module, tree, [module], False)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level == 1:
                    for alias in node.names:
                        if node.module is None:
                            self.modules[module][alias.asname or alias.name] = alias.name
                        else:
                            self.imported[module][alias.asname or alias.name] = (node.module, alias.name)
        for module, tree in trees.items():
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Name):
                    for target in node.targets:
                        if isinstance(target, ast.Attribute):
                            self.stored[target.attr] |= self.functions[(module, node.value.id)]
        self.variables = {q: _variables(f, list(_own(f.body))) for q, (_, f) in self.defs.items()}
        self.names = {q: self.named(m, _own(f.body), self.variables[q]) for q, (m, f) in self.defs.items()}

    def _index(self, module, node, prefix, in_class):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                self._index(module, child, prefix + [child.name], True)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = '.'.join(prefix + [child.name])
                self.defs[qualified] = (module, child)
                (self.methods[child.name] if in_class else self.functions[(module, child.name)]).add(qualified)
                self._index(module, child, prefix + [child.name], False)
            else:
                self._index(module, child, prefix, in_class)

    def named(self, module, nodes, variables):
        """The functions these nodes name, as qualified names."""
        found = set()
        for node in nodes:
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in variables:
                found |= self.functions[(module, node.id)]
                if node.id in self.imported[module]:
                    found |= self.functions[self.imported[module][node.id]]
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                found |= self.methods[node.attr] | self.stored[node.attr]
                if isinstance(node.value, ast.Name) and node.value.id in self.modules[module]:
                    found |= self.functions[(self.modules[module][node.value.id], node.attr)]
        return found

    def reaching(self, start):
        """`start` and every function that names one, closed transitively."""
        reach, grown = set(start), True
        while grown:
            grown = False
            for qualified, named in self.names.items():
                if qualified not in reach and named & reach:
                    reach.add(qualified)
                    grown = True
        return reach

    def gated_callers(self, reach):
        """(caller, line, reached) for each with block entering the gate, a reading or a bounded wait whose body (or a
        later item of the same with) names a function in `reach`."""
        for qualified, (module, function) in self.defs.items():
            body = list(_own(function.body))
            bound = {target.id for node in body if isinstance(node, ast.Assign) and _enters_the_gate(node.value, ())
                     for target in node.targets if isinstance(target, ast.Name)}
            for block in body:
                if not isinstance(block, (ast.With, ast.AsyncWith)):
                    continue
                for i, item in enumerate(block.items):
                    if _enters_the_gate(item.context_expr, bound):
                        inside = [later.context_expr for later in block.items[i + 1:]] + block.body
                        reached = self.named(module, _own(inside), self.variables[qualified]) & reach
                        if reached:
                            yield qualified, block.lineno, sorted(reached)
                        break


def test_no_gated_caller_reaches_a_moved_read():
    """D3, the Review Focus: a production path that reaches a moved read while holding the gate (through a helper, a
    method passed as a value or a lambda) would have reading() refuse it at run time; this walk finds it first. Every
    moved name must be a function the walk knows, so a renamed one can't make the walk pass by finding nothing. A
    callback called only by its parameter's name (send_pinned's prepare) it can't see: there the refusal raises in
    both modes."""
    package = Package()
    assert [name for name in MOVED_READS if name not in package.defs] == []
    found = [(caller, line, reached) for caller, line, reached in package.gated_callers(package.reaching(MOVED_READS))
             if any((caller, name) not in ALLOWED for name in reached)]
    assert found == []


def test_inbox_budget_is_locked(tmp_path, monkeypatch):
    """D3: board_counts calls _inbox_budget outside the gate, so two threads can update one ship's minute at once. With
    the cap patched high, an advancing clock and a switch every microsecond, two threads of 10,000 updates leave 20,000
    entries; without the lock, one thread's read-modify-write drops the other's entries."""
    ticks = itertools.count()
    store = Store(tmp_path / 'station', signing=False, clock=lambda: NOW + next(ticks) * 1e-6)
    monkeypatch.setattr(inbox, 'READS_PER_MINUTE', 10 ** 9)

    def reads():
        for _ in range(10_000):
            store._inbox_budget('ship')
    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        threads = [threading.Thread(target=reads) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(300)
    finally:
        sys.setswitchinterval(interval)
    assert len(store._inbox_reads['ship']) == 20_000


def in_mode(store, mode):
    if mode == 'wal':
        switch_journal(store.data_dir, 'wal', active=lambda: [])
    else:
        with closing(sqlite3.connect(store.db_path)) as db:  # the suite may run in WAL; this case pins a mode
            db.execute('PRAGMA journal_mode=DELETE').fetchone()


@pytest.mark.parametrize('mode', ['wal', 'delete'])
def test_one_signed_pull_served_twice_at_once_is_one_replay(tmp_path, monkeypatch, mode):
    """Tardis's pin: serve_pull's prune, replay floor, nonce lookup and INSERT stay one gated BEGIN IMMEDIATE, in both
    modes. Two threads serve the same signed request, and _replay_floor makes each caller signal, then wait up to 0.3 s
    for the other: the correct code goes on after 0.3 s, since the second caller can't enter (a barrier would deadlock
    it). Exactly one is served and the other answers 409 Replay, with one pull_nonces row and no 500. A split check
    would reach the primary key as an IntegrityError, or the per-origin lock as 409 Busy."""
    clock = Clock()
    listener, mac = station(tmp_path / 'a', 'alice', clock), station(tmp_path / 'mac', 'mo', clock, mode='pull')
    paired(listener[2], listener[1], mac[2].card(mac[1]))
    paired(mac[2], mac[1], listener[2].card(listener[1]))
    in_mode(listener[0], mode)
    raw = canonical(pull_request(mac, listener, clock))
    floor, arrived, both = listener[2]._replay_floor, [], threading.Event()

    def meeting(db):
        arrived.append(threading.get_ident())
        if len(arrived) == 2:
            both.set()
        both.wait(0.3)
        return floor(db)
    monkeypatch.setattr(listener[2], '_replay_floor', meeting)
    outcomes = []

    def serve():
        try:
            outcomes.append(listener[2].serve_pull(raw))
        except Problem as answer:
            outcomes.append((answer.status, answer.message))
        except Exception as error:  # noqa: BLE001 - what the route would answer with a 500
            outcomes.append(error)
    threads = [threading.Thread(target=serve) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert len(arrived) == 2
    assert [o['ok'] for o in outcomes if isinstance(o, dict)] == [True]
    assert [o for o in outcomes if not isinstance(o, dict)] == [(409, 'Replay')]
    with listener[0].transaction() as db:
        assert db.execute('SELECT count(*) FROM pull_nonces WHERE origin=?', (mac[2].identity.peer_id,)).fetchone()[0] == 1
