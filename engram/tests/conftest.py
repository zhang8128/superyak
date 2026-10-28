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


@pytest.fixture(autouse=True, scope="session")
def _enforce_raised_as_before():
    """The gate act refuses `enforce` until the ledger's projection digest lands
    (`permission_ledger.ENFORCE_WAITS`, Serenity's pre-merge item 5). The tests
    of what `enforce` does raise it as before, so that code stays tested for
    the day the digest lands; tests/test_permissions_premerge_fixes.py puts the
    refusal back to test it. Session-wide, so module and session fixtures that
    raise the gate (the U24 reference house) see it too."""
    import permission_ledger
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(permission_ledger, "ENFORCE_WAITS", None)
        yield


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
