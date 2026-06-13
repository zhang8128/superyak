"""Forgetting surfaces: guarded prune, protections, decay modulation,
core-promotion gate."""

import numpy as np

import persistence
from config import PersistenceConfig


def _emb(axis, noise, seed):
    rng = np.random.default_rng(seed)
    v = np.zeros(768); v[axis] = 1.0
    v = v + noise * rng.standard_normal(768)
    return (v / np.linalg.norm(v)).tolist()


def _decayed_episode(tmp_db, eid, embedding, **kw):
    tmp_db.add_episode(id=eid, session_id="s", content=f"content {eid}",
                       embedding=embedding)
    tmp_db.conn.execute(
        "UPDATE episodes SET decay_strength = 0.01, compressed = 1 WHERE id = ?",
        (eid,))
    tmp_db.conn.commit()


class TestGuardedPrune:
    def test_redundant_decayed_evicts_unique_decayed_survives(self, tmp_db):
        # five near-duplicates (redundant) + one isolate (unique), all decayed
        for i in range(5):
            _decayed_episode(tmp_db, f"dup-{i}", _emb(0, 0.01, i))
        _decayed_episode(tmp_db, "iso", _emb(5, 0.0, 99))
        cfg = PersistenceConfig(enabled=True)
        n = persistence.guarded_prune(tmp_db, cfg)
        assert n >= 1
        remaining = {r[0] for r in tmp_db.conn.execute(
            "SELECT id FROM episodes").fetchall()}
        assert "iso" in remaining                      # unique protected
        assert any(f"dup-{i}" not in remaining for i in range(5))  # some evicted
        # carrier of the duplicate cluster survives (one copy always kept)
        assert any(f"dup-{i}" in remaining for i in range(5))
        # evicted went to cold, not destroyed
        cold = tmp_db._cold_storage()
        assert cold.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] >= 1

    def test_anchor_reference_protects(self, tmp_db):
        for i in range(5):
            _decayed_episode(tmp_db, f"dup-{i}", _emb(0, 0.01, i))
        tmp_db.add_anchor(type="identity", content="who am I",
                          expected="dup-0")
        cfg = PersistenceConfig(enabled=True)
        persistence.guarded_prune(tmp_db, cfg)
        remaining = {r[0] for r in tmp_db.conn.execute(
            "SELECT id FROM episodes").fetchall()}
        assert "dup-0" in remaining

    def test_generativity_protects_when_threshold_set(self, tmp_db):
        for i in range(5):
            _decayed_episode(tmp_db, f"dup-{i}", _emb(0, 0.01, i))
        tmp_db.conn.execute(
            "INSERT INTO resonances (id, memory_a, layer_a, memory_b, layer_b,"
            " similarity, weight, strength, co_occurrences, created_at, last_seen)"
            " VALUES ('r1', 'dup-1', 'episode', 'zzz', 'semantic', 0.1, 1.0,"
            " 0.5, 5, '2026-01-01', '2026-01-01')")
        tmp_db.conn.commit()
        cfg = PersistenceConfig(enabled=True, generativity_threshold=1.0)
        persistence.guarded_prune(tmp_db, cfg)
        remaining = {r[0] for r in tmp_db.conn.execute(
            "SELECT id FROM episodes").fetchall()}
        assert "dup-1" in remaining

    def test_preview_matches_action_and_reports_reasons(self, tmp_db):
        for i in range(5):
            _decayed_episode(tmp_db, f"dup-{i}", _emb(0, 0.01, i))
        _decayed_episode(tmp_db, "iso", _emb(5, 0.0, 99))
        cfg = PersistenceConfig(enabled=True)
        persistence.compute_scores(tmp_db, cfg)
        preview = persistence.evaluate_prune(tmp_db, cfg)
        protected_ids = {p["id"] for p in preview["protected"]}
        assert "iso" in protected_ids
        reasons = {p["id"]: p["reasons"] for p in preview["protected"]}
        assert "unique" in reasons["iso"]


class TestPruneHardening:
    def test_partition_is_disjoint(self, tmp_db):
        for i in range(5):
            _decayed_episode(tmp_db, f"dup-{i}", _emb(0, 0.01, i))
        cfg = PersistenceConfig(enabled=True)
        persistence.compute_scores(tmp_db, cfg)
        v = persistence.evaluate_prune(tmp_db, cfg)
        protected_ids = {p["id"] for p in v["protected"]}
        assert protected_ids.isdisjoint(set(v["evict"]))
        assert len(protected_ids) + len(v["evict"]) == v["candidates"]

    def test_no_score_row_protects(self, tmp_db):
        # decayed+compressed but NO vector -> no score row -> protected
        tmp_db.add_episode(id="novec", session_id="s", content="no vector")
        tmp_db.conn.execute(
            "UPDATE episodes SET decay_strength = 0.01, compressed = 1"
            " WHERE id = 'novec'")
        tmp_db.conn.commit()
        cfg = PersistenceConfig(enabled=True)
        v = persistence.evaluate_prune(tmp_db, cfg)
        prot = {p["id"]: p["reasons"] for p in v["protected"]}
        assert "novec" in prot and "no-vector-no-evidence" in prot["novec"]

    def test_retired_anchor_does_not_protect(self, tmp_db):
        for i in range(5):
            _decayed_episode(tmp_db, f"dup-{i}", _emb(0, 0.01, i))
        aid = tmp_db.add_anchor(type="identity", content="q", expected="dup-1")
        tmp_db.conn.execute(
            "UPDATE anchors SET status = 'retired' WHERE id = ?", (aid,))
        tmp_db.conn.commit()
        assert "dup-1" not in persistence._anchored_episode_ids(tmp_db.conn)
        aid2 = tmp_db.add_anchor(type="identity", content="q", expected="dup-2")
        tmp_db.conn.execute(
            "UPDATE anchors SET status = 'proposed_retirement' WHERE id = ?",
            (aid2,))
        tmp_db.conn.commit()
        assert "dup-2" in persistence._anchored_episode_ids(tmp_db.conn)

    def test_zero_generativity_threshold_ignored(self, tmp_db):
        for i in range(5):
            _decayed_episode(tmp_db, f"dup-{i}", _emb(0, 0.01, i))
        cfg = PersistenceConfig(enabled=True)  # generativity_threshold = 0.0
        persistence.compute_scores(tmp_db, cfg)
        v = persistence.evaluate_prune(tmp_db, cfg)
        for p in v["protected"]:
            assert "generative" not in p["reasons"]
