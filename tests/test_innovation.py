import hashlib
import uuid

from storage import Storage


class FakeEmbeddingProvider:
    """Deterministic embeddings: same text -> same embedding.

    Mirrors the fake used in tests/test_compression.py so the real
    compression/core-promotion pipeline can run end-to-end without a live
    Ollama or embedding backend. Kept local to this file rather than
    imported, since test_compression.py has unrelated in-flight changes.
    """

    def embed(self, texts, **_kwargs):
        results = []
        for text in texts:
            h = hashlib.md5(text.encode()).digest()
            results.append([float(b) / 255.0 for b in h] * 48)  # 768 dims
        return results

    def dimension(self) -> int:
        return 768


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


def test_compute_innovation_returns_none_on_malformed_vector(tmp_path):
    """A shape-mismatched embedding must degrade to None, not raise.

    Without the guard, a mismatched dimension makes the internal `C @ v`
    matmul raise ValueError, which would otherwise propagate out of
    add_episode and fail the whole write. NULL = no signal, not a crash.
    """
    s = _mk(tmp_path)
    s.add_semantic(id="s1", content="a fact about x", kind="fact",
                   confidence=0.8, embedding=_vec(0), source_episode_ids=[])
    # Ragged relative to the stored 768-dim semantic vector.
    assert s.compute_innovation([0.1, 0.2, 0.3], lane="personal") is None
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


def test_innovation_distribution_excludes_work_lane(tmp_path):
    """The gate only ever fires for personal-lane episodes, so a work-lane
    episode with non-NULL innovation must not contaminate the tuning signal."""
    from persistence import innovation_distribution
    s = _mk(tmp_path)
    s.conn.execute(
        "INSERT INTO episodes (id, content, created_at, innovation, lane) "
        "VALUES ('e1', 'content', '2026-07-07T00:00:00Z', 0.2, 'personal')"
    )
    s.conn.execute(
        "INSERT INTO episodes (id, content, created_at, innovation, lane) "
        "VALUES ('e2', 'content', '2026-07-07T00:00:00Z', 0.9, 'work')"
    )
    s.conn.commit()
    d = innovation_distribution(s)
    assert d["count"] == 1
    assert d["min"] == 0.2 and d["max"] == 0.2
    s.conn.close()


# ---------------------------------------------------------------------------
# End-to-end: the gate actually declines/permits core promotion during real
# compression, not just the pure `_innovation_permits_core` helper.
# ---------------------------------------------------------------------------

def _seed_near_duplicate_episode(tmp_path):
    """A personal semantic plus a personal episode whose write-time
    embedding is identical to it — innovation ~= 0 for the episode.

    The clustering embedder (FakeEmbeddingProvider, hash-of-content-text)
    lives in a completely different vector space from the raw basis vectors
    used here for storage-level similarity, so the cluster's centroid never
    accidentally matches the seeded semantic (action stays 'new').
    """
    s = _mk(tmp_path)
    s.add_semantic(id="s1", content="an existing personal fact", kind="fact",
                   confidence=0.8, embedding=_vec(0), source_episode_ids=[])
    eid = str(uuid.uuid4())
    s.add_episode(id=eid, session_id="t", content="a formative correction",
                  embedding=_vec(0), lane="personal")
    ep = s.get_episode(eid)
    assert ep["innovation"] is not None and ep["innovation"] < 1e-6
    return s, eid


def test_low_innovation_declines_core_promotion_e2e(tmp_path):
    """Real compression path: the centroid-nearest episode is NOT marked
    core when its write-time innovation falls below the floor."""
    from compress import Compressor
    from config import CompressionConfig

    s, eid = _seed_near_duplicate_episode(tmp_path)
    config = CompressionConfig(core_innovation_floor=0.05)
    compressor = Compressor(s, FakeEmbeddingProvider(), config=config)

    result = compressor.cluster_episodes()
    assert result["compress_id"] is not None
    compressor.commit(result["compress_id"],
                      [{"content": "corrections change how I read",
                        "kind": "preference", "action": "new"}])

    ep = s.get_episode(eid)
    assert ep["core"] == 0
    s.conn.close()


def test_innovation_floor_zero_permits_core_promotion_e2e(tmp_path):
    """Mirror case: core_innovation_floor=0.0 disables the gate end-to-end,
    so the same near-duplicate episode IS marked core."""
    from compress import Compressor
    from config import CompressionConfig

    s, eid = _seed_near_duplicate_episode(tmp_path)
    config = CompressionConfig(core_innovation_floor=0.0)
    compressor = Compressor(s, FakeEmbeddingProvider(), config=config)

    result = compressor.cluster_episodes()
    assert result["compress_id"] is not None
    compressor.commit(result["compress_id"],
                      [{"content": "corrections change how I read",
                        "kind": "preference", "action": "new"}])

    ep = s.get_episode(eid)
    assert ep["core"] >= 1
    s.conn.close()
