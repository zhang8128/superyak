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

