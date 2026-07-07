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


def test_compute_innovation_none_without_semantics(tmp_path):
    s = _mk(tmp_path)
    assert s.compute_innovation(_vec(0), lane="personal") is None
    s.conn.close()


def test_compute_innovation_zero_for_duplicate(tmp_path):
    s = _mk(tmp_path)
    s.add_semantic(id="s1", content="a fact about x", kind="fact",
                   confidence=0.8, embedding=_vec(0), source_episode_ids=[])
    innov = s.compute_innovation(_vec(0), lane="personal")
    assert innov is not None and innov < 1e-6
    s.conn.close()


def test_compute_innovation_high_for_novel(tmp_path):
    s = _mk(tmp_path)
    s.add_semantic(id="s1", content="a fact about x", kind="fact",
                   confidence=0.8, embedding=_vec(0), source_episode_ids=[])
    innov = s.compute_innovation(_vec(1), lane="personal")
    assert innov is not None and innov > 0.99
    s.conn.close()


def test_add_episode_persists_innovation(tmp_path):
    s = _mk(tmp_path)
    s.add_semantic(id="s1", content="a fact about x", kind="fact",
                   confidence=0.8, embedding=_vec(0), source_episode_ids=[])
    s.add_episode(id="e1", session_id=None, content="episode content here",
                  embedding=_vec(0), lane="personal")
    row = s.conn.execute("SELECT innovation FROM episodes WHERE id='e1'").fetchone()
    assert row[0] is not None and row[0] < 1e-6
    s.conn.close()


def test_add_episode_innovation_null_cold_start(tmp_path):
    s = _mk(tmp_path)
    s.add_episode(id="e1", session_id=None, content="episode content here",
                  embedding=_vec(0), lane="personal")
    row = s.conn.execute("SELECT innovation FROM episodes WHERE id='e1'").fetchone()
    assert row[0] is None
    s.conn.close()


def test_innovation_is_lane_pure(tmp_path):
    s = _mk(tmp_path)
    # Only a WORK semantic exists.
    s.add_semantic(id="s1", content="a work fact", kind="fact",
                   confidence=0.8, embedding=_vec(0),
                   source_episode_ids=[], lane="work")
    # A personal episode identical to that work semantic still sees no
    # personal semantics -> None (work never feeds personal identity).
    assert s.compute_innovation(_vec(0), lane="personal") is None
    s.conn.close()


def test_config_default_floor():
    from config import CompressionConfig
    assert CompressionConfig().core_innovation_floor == 0.05


def test_gate_null_innovation_permits():
    from compress import _innovation_permits_core
    assert _innovation_permits_core(None, 0.05) is True


def test_gate_floor_zero_permits_everything():
    from compress import _innovation_permits_core
    assert _innovation_permits_core(0.0, 0.0) is True
    assert _innovation_permits_core(0.001, 0.0) is True


def test_gate_declines_below_floor():
    from compress import _innovation_permits_core
    assert _innovation_permits_core(0.02, 0.05) is False


def test_gate_permits_at_or_above_floor():
    from compress import _innovation_permits_core
    assert _innovation_permits_core(0.05, 0.05) is True
    assert _innovation_permits_core(0.9, 0.05) is True


def test_innovation_distribution_empty(tmp_path):
    from persistence import innovation_distribution
    s = _mk(tmp_path)
    assert innovation_distribution(s)["count"] == 0
    s.conn.close()


def test_innovation_distribution_stats(tmp_path):
    from persistence import innovation_distribution
    s = _mk(tmp_path)
    for eid, innov in [("e1", 0.2), ("e2", 0.8)]:
        s.conn.execute(
            "INSERT INTO episodes (id, content, created_at, innovation, lane) "
            "VALUES (?, ?, '2026-07-07T00:00:00Z', ?, 'personal')",
            (eid, "content", innov),
        )
    s.conn.execute(
        "INSERT INTO episodes (id, content, created_at, innovation, lane) "
        "VALUES ('e3', 'content', '2026-07-07T00:00:00Z', NULL, 'personal')"
    )
    s.conn.commit()
    d = innovation_distribution(s)
    assert d["count"] == 2
    assert abs(d["mean"] - 0.5) < 1e-6
    assert d["min"] == 0.2 and d["max"] == 0.8
    assert sum(d["histogram"]) == 2
    s.conn.close()
