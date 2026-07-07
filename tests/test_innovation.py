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
