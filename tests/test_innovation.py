from pathlib import Path
import struct

from storage import Storage


def _vec(i, dim=768):
    """Unit basis vector with a 1 at index i."""
    v = [0.0] * dim
    v[i] = 1.0
    return v


def _mk(tmp_path):
    return Storage(str(tmp_path / "graph.db"))


def test_migration_adds_innovation_column(tmp_path):
    s = _mk(tmp_path)
    cols = {r[1] for r in s.conn.execute("PRAGMA table_info(episodes)").fetchall()}
    assert "innovation" in cols
    s.conn.close()
