"""Persistence surfaces: gate conjunct, audit, reflect, cold-uninvited."""

import math

import numpy as np
import pytest

import sheaf
from config import PersistenceConfig


def _two_orthogonal(n_per: int = 10, noise: float = 0.05):
    a = np.zeros(768); a[0] = 1.0
    b = np.zeros(768); b[1] = 1.0
    rng1, rng2 = np.random.default_rng(1), np.random.default_rng(2)
    X = np.vstack([a + noise * rng1.standard_normal((n_per, 768)),
                   b + noise * rng2.standard_normal((n_per, 768))])
    return [f"e{i}" for i in range(2 * n_per)], X


class TestGateConjunct:
    def test_disabled_behaves_like_stub(self):
        ids, X = _two_orthogonal()
        v = sheaf.subdivision_test("s1", ids, X, dl_cost=0.15)
        assert v.persistence_checked is False
        assert v.persistence_band is None
        assert v.split is True

    def test_enabled_records_band_and_passes_clean_split(self):
        ids, X = _two_orthogonal()
        cfg = PersistenceConfig(enabled=True)
        v = sheaf.subdivision_test("s1", ids, X, dl_cost=0.15,
                                   persistence_cfg=cfg)
        assert v.persistence_checked is True
        assert v.persistence_band is not None and v.persistence_band > 0.10
        assert v.split is True

    def test_enabled_blocks_when_energy_passes_but_persistence_fails(self):
        rng = np.random.default_rng(0)
        a = np.zeros(768); b = np.zeros(768); b[0] = 0.05  # near-touching blobs
        X = np.vstack([a + 0.08 * rng.standard_normal((8, 768)),
                       b + 0.08 * rng.standard_normal((8, 768))])
        ids = [f"e{i}" for i in range(16)]
        off = sheaf.subdivision_test("s1", ids, X, dl_cost=0.05)
        on = sheaf.subdivision_test("s1", ids, X, dl_cost=0.05,
                                    persistence_cfg=PersistenceConfig(enabled=True))
        assert off.split is True                  # energy conjunct alone would split
        assert on.persistence_checked is True
        assert on.persistence_band < PersistenceConfig().min_split_band
        assert on.split is False                  # persistence is the blocker


class TestCompressSiteAudit:
    def test_compress_event_records_real_persistence_check(self, tmp_db):
        """compress-site subdivision_events row must carry persistence_checked=1
        when the Compressor was constructed with persistence enabled."""
        import math

        import numpy as np

        from compress import Compressor
        from config import CohesionConfig, CompressionConfig

        def _emb(v, noise, seed):
            rng = np.random.default_rng(seed)
            v = np.array(v, dtype=float)
            v = v + noise * rng.standard_normal(768)
            return (v / np.linalg.norm(v)).tolist()

        # Two directions 60° apart (cos=0.5) — same conflated fixture as
        # test_sheaf_compress.py's test_sibling_resonance_after_commit
        V_A = np.zeros(768); V_A[0] = 1.0
        V_B = np.zeros(768); V_B[0] = 0.5; V_B[1] = math.sqrt(1 - 0.5 ** 2)

        table: dict[str, list[float]] = {}
        for i in range(10):
            content = f"episode about topic {'A' if i < 5 else 'B'} number {i}"
            emb = _emb(V_A if i < 5 else V_B, 0.005, i)
            table[content] = emb
            tmp_db.add_episode(
                id=f"ep-{i}",
                session_id="s",
                content=content,
                embedding=emb,
            )

        class FakeEmbedder:
            def __init__(self, t):
                self._t = t

            def embed(self, texts, prefix=None):
                results = []
                for t in texts:
                    if t in self._t:
                        results.append(self._t[t])
                    else:
                        rng = np.random.default_rng(abs(hash(t)) % (2 ** 31))
                        v = rng.standard_normal(768)
                        results.append((v / np.linalg.norm(v)).tolist())
                return results

        persistence_cfg = PersistenceConfig(enabled=True)
        comp = Compressor(
            tmp_db,
            FakeEmbedder(table),
            config=CompressionConfig(cluster_similarity=0.30),
            cohesion_config=CohesionConfig(enabled=True, dl_cost=0.15),
            persistence_config=persistence_cfg,
        )
        preview = comp.cluster_episodes()
        split = [c for c in preview["clusters"] if c.get("split_group")]
        if not split:
            pytest.skip("clustering separated the topics on its own — fixture not conflated")

        # Verify the split actually happened (gate fired with persistence enabled)
        # The 60° fixture has wide separation so the persistence band should pass
        # and the split should still occur.

        summaries = []
        for c in preview["clusters"]:
            summaries.append({
                "content": f"summary of {len(c['episodes'])} eps",
                "kind": "fact",
                "action": "new",
            })
        comp.commit(preview["compress_id"], summaries)

        # The subdivision_events row must record persistence_checked = 1
        row = tmp_db.conn.execute(
            "SELECT persistence_checked FROM subdivision_events WHERE site = 'compress'"
        ).fetchone()
        assert row is not None, (
            "no compress-site subdivision_events row — split may have been blocked "
            "by persistence; check the band value via sheaf.subdivision_test directly"
        )
        assert row[0] == 1, (
            f"expected persistence_checked=1, got {row[0]!r}; "
            "compress.py commit site is still hardcoding False"
        )


from reflection import Reflector


def _emb_list(axis, noise, seed):
    rng = np.random.default_rng(seed)
    v = np.zeros(768); v[axis] = 1.0
    v = v + noise * rng.standard_normal(768)
    return (v / np.linalg.norm(v)).tolist()


class TestReflectPersistence:
    def test_focus_returns_previews_and_classification(self, tmp_db):
        eps = []
        for i in range(10):
            eid = f"e{i}"
            tmp_db.add_episode(id=eid, session_id="s", content=f"ep {i}",
                               embedding=_emb_list(0 if i < 5 else 1, 0.03, i))
            eps.append(eid)
        tmp_db.add_semantic(id="hub-1", content="bimodal hub", kind="fact",
                            confidence=0.8, embedding=_emb_list(0, 0.3, 11),
                            source_episode_ids=eps)
        from config import PersistenceConfig
        r = Reflector(tmp_db, persistence_config=PersistenceConfig())
        out = r.reflect(focus="persistence")
        p = out["persistence"]
        assert "forgetting_preview" in p and "hubs" in p
        assert "conjunct_audit" in p and "flagged_cores" in p
        hub = [h for h in p["hubs"] if h["semantic_id"] == "hub-1"][0]
        assert hub["classification"] == "multi-modal"

    def test_empty_store(self, tmp_db):
        from config import PersistenceConfig
        out = Reflector(tmp_db,
                        persistence_config=PersistenceConfig()).reflect(
                            focus="persistence")
        assert out["persistence"]["hubs"] == []


class TestColdUninvited:
    def test_sample_cold_random(self, tmp_db, fake_embedding):
        tmp_db.add_episode(id="e1", session_id="s", content="soon cold",
                           embedding=fake_embedding())
        tmp_db.conn.execute(
            "UPDATE episodes SET decay_strength = 0.01, compressed = 1"
            " WHERE id = 'e1'")
        tmp_db.conn.commit()
        tmp_db.prune_decayed()
        out = tmp_db.sample_cold_random(k=1)
        assert len(out) == 1 and out[0]["id"] == "e1"
        assert tmp_db.sample_cold_random(k=5)[0]["content"] == "soon cold"

    def test_empty_cold_returns_nothing(self, tmp_db):
        assert tmp_db.sample_cold_random(k=1) == []
