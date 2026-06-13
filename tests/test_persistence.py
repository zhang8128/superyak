"""Tests for the persistence layer — schema, math, scores."""

import json


class TestMigration021:
    def test_table_exists(self, tmp_db):
        names = {r[0] for r in tmp_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "persistence_scores" in names


class TestScoreCache:
    def test_upsert_and_get(self, tmp_db):
        tmp_db.upsert_persistence_scores([
            {"episode_id": "e1", "redundancy": 0.9, "uniqueness": 0.1,
             "generativity": 0.0},
            {"episode_id": "e2", "redundancy": 0.2, "uniqueness": 0.8,
             "generativity": 1.5},
        ])
        scores = tmp_db.get_persistence_scores()
        assert scores["e1"]["redundancy"] == 0.9
        assert scores["e2"]["generativity"] == 1.5
        # upsert replaces
        tmp_db.upsert_persistence_scores([
            {"episode_id": "e1", "redundancy": 0.5, "uniqueness": 0.5,
             "generativity": 0.5}])
        assert tmp_db.get_persistence_scores()["e1"]["redundancy"] == 0.5


from config import load_config


class TestPersistenceConfig:
    def test_defaults(self, tmp_path):
        cfg = load_config(tmp_path)
        p = cfg.persistence
        assert p.enabled is False
        assert p.min_split_band == 0.10
        assert p.redundancy_floor == 0.85
        assert p.protect_threshold == 0.6
        assert p.generativity_threshold == 0.0
        assert p.cold_uninvited_p == 0.05

    def test_toml_override(self, tmp_path):
        (tmp_path / ".engram").mkdir()
        (tmp_path / ".engram" / "config.toml").write_text(
            "[persistence]\nenabled = true\nredundancy_floor = 0.7\n")
        cfg = load_config(tmp_path)
        assert cfg.persistence.enabled is True
        assert cfg.persistence.redundancy_floor == 0.7


import numpy as np

import persistence


def _cluster(axis: int, n: int, noise: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    c = np.zeros(768); c[axis] = 1.0
    return c + noise * rng.standard_normal((n, 768))


class TestFiltration:
    def test_duplicate_pair_one_redundant_one_carrier(self):
        base = _cluster(0, 1, 0.0, 1)[0]
        far = np.zeros(768); far[1] = 1.0
        X = np.vstack([base, base + 1e-6, far, far + 0.3 * _cluster(1, 1, 1.0, 2)[0] * 0])
        # points 0,1 are near-duplicates; 2,3 give the filtration room
        f = persistence.build_filtration(X)
        red = persistence.redundancy(f)
        uniq = persistence.uniqueness(f)
        assert red[0] > 0.99 and red[1] > 0.99      # both covered by the other
        assert min(uniq[0], uniq[1]) < 0.05          # one lineage dies instantly
        assert max(uniq[0], uniq[1]) > 0.5           # the carrier persists

    def test_isolated_point_is_unique_not_redundant(self):
        X = np.vstack([_cluster(0, 8, 0.03, 3), _cluster(5, 1, 0.0, 4)])
        f = persistence.build_filtration(X)
        red = persistence.redundancy(f)
        uniq = persistence.uniqueness(f)
        assert red[8] < 0.3
        assert uniq[8] > 0.9

    def test_tiny_inputs(self):
        f0 = persistence.build_filtration(np.zeros((0, 768)))
        assert f0.n == 0
        f1 = persistence.build_filtration(_cluster(0, 1, 0.0, 5))
        assert persistence.uniqueness(f1)[0] == 1.0
        assert persistence.redundancy(f1)[0] == 0.0   # nothing covers it


class TestSplitBand:
    def test_separated_parts_have_wide_band(self):
        a = _cluster(0, 8, 0.03, 6)
        b = _cluster(1, 8, 0.03, 7)
        X = np.vstack([a, b])
        band = persistence.split_band(X, list(range(8)), list(range(8, 16)))
        assert band > 0.3

    def test_arbitrary_cut_of_one_cluster_has_no_band(self):
        X = _cluster(0, 16, 0.05, 8)
        band = persistence.split_band(X, list(range(8)), list(range(8, 16)))
        assert band < 0.05


class TestFiltrationInvariants:
    def test_carrier_conservation(self):
        # exactly one survivor lineage (death=inf) in a connected set
        X = _cluster(0, 20, 0.2, 42)
        f = persistence.build_filtration(X)
        assert int(np.isfinite(f.death).sum()) == f.n - 1

    def test_score_arrays_match_n(self):
        X = _cluster(0, 7, 0.1, 43)
        f = persistence.build_filtration(X)
        assert len(persistence.redundancy(f)) == f.n
        assert len(persistence.uniqueness(f)) == f.n

    def test_split_band_interleaved_indices(self):
        # scattered (non-contiguous) index sets — where np.ix_ bugs would hide
        X = _cluster(0, 12, 0.05, 44)
        band = persistence.split_band(X, [0, 2, 4, 6], [1, 3, 5, 7])
        assert band <= 0.05  # an arbitrary interleaved cut has no band

    def test_all_duplicates_uniqueness_all_ones(self):
        base = _cluster(0, 1, 0.0, 45)[0]
        X = np.vstack([base] * 5)
        f = persistence.build_filtration(X)
        assert (persistence.uniqueness(f) == 1.0).all()


class TestComputeScores:
    def test_scores_cover_episodes_with_vectors(self, tmp_db, fake_embedding):
        from config import PersistenceConfig
        for i in range(5):
            tmp_db.add_episode(id=f"e{i}", session_id="s", content=f"ep {i}",
                               embedding=fake_embedding())
        tmp_db.add_episode(id="no-vec", session_id="s", content="no vector")
        out = persistence.compute_scores(tmp_db, PersistenceConfig())
        assert set(out) == {f"e{i}" for i in range(5)}   # no-vec excluded
        cached = tmp_db.get_persistence_scores()
        assert set(cached) == set(out)

    def test_generativity_from_distant_resonances(self, tmp_db, fake_embedding):
        from config import PersistenceConfig
        for i in range(3):
            tmp_db.add_episode(id=f"e{i}", session_id="s", content=f"ep {i}",
                               embedding=fake_embedding())
        # behaviorally close, geometrically far: low similarity, many co-occurrences
        tmp_db.conn.execute(
            "INSERT INTO resonances (id, memory_a, layer_a, memory_b, layer_b,"
            " similarity, weight, strength, co_occurrences, created_at, last_seen)"
            " VALUES ('r1', 'e0', 'episode', 'e1', 'episode', 0.1, 1.0, 0.5, 5,"
            " '2026-01-01', '2026-01-01')")
        tmp_db.conn.commit()
        out = persistence.compute_scores(tmp_db, PersistenceConfig())
        assert out["e0"]["generativity"] == out["e1"]["generativity"] > 4.0
        assert out["e2"]["generativity"] == 0.0


class TestAudit:
    def test_audit_unchecked_events(self, tmp_db, fake_embedding):
        from config import PersistenceConfig
        import numpy as np
        # two separated groups as the peers' provenance
        rngs = [np.random.default_rng(s) for s in (1, 2)]
        for p, (axis, rng) in enumerate(zip((0, 1), rngs)):
            sem = f"peer-{p}"
            eps = []
            for i in range(4):
                eid = f"p{p}e{i}"
                c = np.zeros(768); c[axis] = 1.0
                v = (c + 0.03 * rng.standard_normal(768))
                tmp_db.add_episode(id=eid, session_id="s", content=f"x{p}{i}",
                                   embedding=(v / np.linalg.norm(v)).tolist())
                eps.append(eid)
            tmp_db.add_semantic(id=sem, content=f"peer {p}", kind="fact",
                                confidence=0.8, embedding=fake_embedding(),
                                source_episode_ids=eps)
        tmp_db.log_subdivision_event(id="ev1", parent_id="old-hub",
                                     peer_ids=["peer-0", "peer-1"],
                                     energy_before=0.8, energy_after=0.1,
                                     dl_cost=0.05, persistence_checked=False,
                                     site="sleep")
        report = persistence.audit_unchecked_events(tmp_db, PersistenceConfig())
        assert len(report) == 1
        assert report[0]["event_id"] == "ev1"
        assert report[0]["band"] > 0.10
        assert report[0]["would_pass"] is True
