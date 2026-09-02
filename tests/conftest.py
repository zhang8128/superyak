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

