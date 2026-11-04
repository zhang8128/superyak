"""Shared fixtures for engram tests."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from storage import Storage


MIGRATIONS_DIR = str(Path(__file__).resolve().parent.parent / "migrations")


@pytest.fixture
def tmp_db(tmp_path):
    """Create a Storage instance backed by a temp DB."""
    db_path = str(tmp_path / "test.db")
    store = Storage(db_path, migrations_dir=MIGRATIONS_DIR)
    yield store
    store.close()


@pytest.fixture
def sample_entity():
    """Return a dict with test entity data."""
    return {
        "id": "ent-001",
        "name": "Storage",
        "entity_type": "class",
        "description": "Wraps SQLite for the knowledge graph",
        "metadata": {"file": "storage.py", "line": 10},
    }


@pytest.fixture
def fake_embedding():
    """Return a factory for random float embeddings."""
    def _make(dim: int = 768) -> list[float]:
        return [random.uniform(-1.0, 1.0) for _ in range(dim)]
    return _make


@pytest.fixture(autouse=True)
def _close_server_generations():
    """Close every server generation a test's server._init() opened.

    _init() hands its storage, knowledge graph, watcher and observers to a
    cleanup coordinator registered with atexit. Tests reset server globals
    but never ran the coordinator, so each one pinned its resources until the
    suite exited: about 210 MB per test for the Kuzu knowledge graph alone,
    which drove a full run past 5 GB and contributed to the 2026-10-02 crash.
    """
    import atexit
    import sys
    import threading

    server = sys.modules.get("server")
    if server is None:
        yield
        return
    created = []
    cls = server._ServerGenerationCleanup
    real_init = cls.__init__

    def recording_init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        created.append(self)

    cls.__init__ = recording_init
    try:
        yield
    finally:
        cls.__init__ = real_init
        for coordinator in created:
            if not coordinator.cleanup_complete:
                # Bounded: a test that left an operation admitted would
                # otherwise block teardown forever.
                worker = threading.Thread(target=coordinator, daemon=True)
                worker.start()
                worker.join(timeout=10)
            atexit.unregister(coordinator)
            if coordinator in server._server_atexit_callbacks:
                server._server_atexit_callbacks.remove(coordinator)


@pytest.fixture(autouse=True)
def _deterministic_rng():
    """Start every test from a fixed random state.

    Engram's stochastic paths draw from Python's global generator: resonance
    birth weights and probabilistic surfacing, compression and graph edge
    weights, the recall wander's weighted choice, the uninvited and daydream
    slots, and dream residue noise. Several tests run threads, and a thread
    that draws from the same global stream changes the sequence the main thread
    sees, so a draw that decides an assertion can differ between runs of the
    identical suite. That is what made the resonance end-to-end test fail about
    one full-suite run in fifty while passing every time in isolation.

    Seeding here makes each test's draws reproducible without changing any
    production default, and it does not hide genuine probabilistic behaviour: a
    test that asserts on a specific outcome should still pin the draw itself,
    as tests/test_resonances.py does.
    """
    random.seed(1729)
    try:
        import numpy as np
    except ImportError:
        pass
    else:
        np.random.seed(1729)


# The suite-wide check runs on ledgers under this many projected rows (the plan's re-check, S8): U24's reference
# ledger, rebuilt by 811,000 appends, would be recomputed per append.
PROJECTION_CHECK_ROWS = 5000


@pytest.fixture(autouse=True)
def _projection_follows_every_append():
    """The projection digest plan's Task 3 (S8), in place of a random-act generator: after every `Ledger._append` in
    this suite, on a ledger that keeps the digest and holds under PROJECTION_CHECK_ROWS projected rows,
    `meta.projection` and `projection_parts` are the tables recomputed (`projection_now`), read in one transaction.
    ENGRAM_PROJECTION_CHECK=off turns it off (the budget tests, and a test whose own assert must be the one that
    fails). It sets and restores the method itself, not through the `monkeypatch` fixture: an autouse fixture that
    took `monkeypatch` would set it up before a test's `tmp_path`, so it would undo a test's patches after `tmp_path`'s
    teardown had run with them (an `os.open` patched in tests/test_categories_v2.py broke its rmtree)."""
    import os

    import permission_ledger
    real = permission_ledger.Ledger._append

    def checked(self, *args, **kwargs):
        seq = real(self, *args, **kwargs)
        if os.environ.get("ENGRAM_PROJECTION_CHECK") != "off":
            # a fresh file (rebuild, migrate) carries its parts in memory until `_finish_fresh` writes them
            _check_projection(self.conn, seq, self._carried if self._fresh else None)
        return seq

    permission_ledger.Ledger._append = checked
    try:
        yield
    finally:
        permission_ledger.Ledger._append = real


def _check_projection(conn, seq, carried=None):
    import permission_ledger
    conn.execute("BEGIN")
    try:
        meta = {k: v for k, v in conn.execute("SELECT key, value FROM meta")}
        if "projection_parts" not in meta:
            return                                       # a ledger made before the digest keeps none (D5)
        held = carried if carried is not None else permission_ledger._read_parts(meta["projection_parts"])
        if sum(n for n, _ in held.values()) >= PROJECTION_CHECK_ROWS:
            return
        whole, parts = permission_ledger.projection_now(conn)
    finally:
        conn.execute("COMMIT")
    differs = [p for p in parts if parts[p] != held[p]]
    stored = f"{seq}:{permission_ledger._parts_digest(held)}" if carried is not None else meta["projection"]
    assert stored == f"{seq}:{whole}" and not differs, (
        f"meta.projection is not the tables after seq {seq}: {stored} against {seq}:{whole}, the parts "
        f"that differ: {differs}")


@pytest.fixture
def route_open(monkeypatch):
    """Route waits until trails ships (`imprint_filter.ROUTE_OPEN`, Serenity's
    condition S1). Every test here runs with the value that ships unless it
    takes this fixture; production never opens it. The tests of what route
    does take it (24 functions when it was made opt-in, Serenity's note 1), so
    that code stays tested for the day trails lands. A child process doesn't
    see it: the Pi measurements open route in their route children alone with
    `imprint_route_open` (tests/imprint_support.py)."""
    import imprint_filter
    monkeypatch.setattr(imprint_filter, "ROUTE_OPEN", True)


@pytest.fixture
def route_closed():
    """`imprint_filter.ROUTE_OPEN` as it ships: what every test here has unless
    it takes `route_open`. Named by the tests that depend on it."""
