"""Compression-time sheaf gate tests.

Fixture: 10 episodes split 5/5 between two directions cos_theta=0.50 apart
(noise=0.005). With cluster_similarity=0.30 (threshold=0.70) both directions
land in one cluster. Sheaf energy ≈ 0.24 > dl_cost=0.15, so the gate triggers.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from compress import Compressor
from config import CohesionConfig, CompressionConfig


def _emb(v: np.ndarray, noise: float, seed: int) -> list[float]:
    rng = np.random.default_rng(seed)
    v = np.array(v, dtype=float)
    v = v + noise * rng.standard_normal(768)
    return (v / np.linalg.norm(v)).tolist()


# Two directions 60° apart (cos=0.5) — conflation fixture
_V_A = np.zeros(768)
_V_A[0] = 1.0

_V_B = np.zeros(768)
_V_B[0] = 0.5
_V_B[1] = math.sqrt(1 - 0.5 ** 2)  # ≈ 0.866

# With cluster_similarity=0.30 (distance threshold=0.70), both groups land in
# the same cluster.  Sheaf energy ≈ 0.24 > dl_cost=0.15 → split fires.
_COMPRESS_CFG = CompressionConfig(cluster_similarity=0.30)
_COHESION_ON = CohesionConfig(enabled=True, dl_cost=0.15)
_COHESION_OFF = CohesionConfig(enabled=False)


class FakeEmbedder:
    """Returns the pre-computed vector for known texts; random otherwise."""

    def __init__(self, table: dict[str, list[float]]):
        self._table = table

    def embed(self, texts: list[str], prefix: str | None = None) -> list[list[float] | None]:
        results = []
        for t in texts:
            if t in self._table:
                results.append(self._table[t])
            else:
                rng = np.random.default_rng(abs(hash(t)) % (2 ** 31))
                v = rng.standard_normal(768)
                results.append((v / np.linalg.norm(v)).tolist())
        return results


def _make_conflated_db(tmp_db) -> dict[str, list[float]]:
    """Populate tmp_db with 10 conflated episodes; return content→embedding table."""
    table: dict[str, list[float]] = {}
    for i in range(10):
        content = f"episode about topic {'A' if i < 5 else 'B'} number {i}"
        emb = _emb(_V_A if i < 5 else _V_B, 0.005, i)
        table[content] = emb
        tmp_db.add_episode(
            id=f"ep-{i}",
            session_id="s",
            content=content,
            embedding=emb,
        )
    return table


@pytest.fixture
def conflated_compressor(tmp_db):
    table = _make_conflated_db(tmp_db)
    comp = Compressor(
        tmp_db,
        FakeEmbedder(table),
        config=_COMPRESS_CFG,
        cohesion_config=_COHESION_ON,
    )
    return comp, tmp_db


class TestCompressionGate:
    def test_conflated_cluster_is_pre_partitioned(self, conflated_compressor):
        """Gate splits a conflated cluster into sub-clusters with split_group set."""
        comp, _db = conflated_compressor
        preview = comp.cluster_episodes()
        split = [c for c in preview["clusters"] if c.get("split_group")]
        assert split, "expected at least one split cluster"
        groups: dict[str, list] = {}
        for c in split:
            groups.setdefault(c["split_group"], []).append(c)
        assert any(len(v) >= 2 for v in groups.values()), (
            "each split_group must have ≥ 2 sub-clusters"
        )
        assert all("cohesion" in c for c in split), (
            "every split sub-cluster must carry cohesion metadata"
        )

    def test_split_group_covers_all_episodes(self, conflated_compressor):
        """All 10 episodes must appear across the split sub-clusters."""
        comp, _db = conflated_compressor
        preview = comp.cluster_episodes()
        split = [c for c in preview["clusters"] if c.get("split_group")]
        all_ep_ids = {ep["id"] for c in split for ep in c["episodes"]}
        assert len(all_ep_ids) == 10

    def test_sibling_resonance_after_commit(self, conflated_compressor):
        """After commit, sibling semantics get resonance edges and a subdivision_event row."""
        comp, db = conflated_compressor
        preview = comp.cluster_episodes()
        split = [c for c in preview["clusters"] if c.get("split_group")]
        if not split:
            pytest.skip("clustering separated the topics on its own")

        summaries = []
        for c in preview["clusters"]:
            summaries.append({
                "content": f"summary of {len(c['episodes'])} eps",
                "kind": "fact",
                "action": "new",
            })
        result = comp.commit(preview["compress_id"], summaries)
        assert result["semantics_created"] >= 2

        # At least one semantic-semantic resonance should exist for each split group
        row = db.conn.execute(
            "SELECT COUNT(*) FROM resonances"
            " WHERE layer_a = 'semantic' AND layer_b = 'semantic'"
        ).fetchone()
        assert row[0] >= 1, "expected ≥ 1 sibling resonance after commit"

        ev = db.conn.execute(
            "SELECT site FROM subdivision_events"
        ).fetchone()
        assert ev is not None, "expected a subdivision_events row"
        assert ev[0] == "compress", f"site should be 'compress', got {ev[0]!r}"

        # Fix 1: real energies and cluster: namespace prefix
        events = db.conn.execute(
            "SELECT parent_id, energy_before, energy_after FROM subdivision_events"
            " WHERE site = 'compress'").fetchall()
        assert len(events) == 1                          # exactly one per group
        assert events[0][0].startswith("cluster:")
        assert events[0][1] > 0.0                        # real energies recorded

        # Fix 2: real centroid cosine similarity on sibling resonance edges
        sims = db.conn.execute(
            "SELECT similarity FROM resonances WHERE layer_a = 'semantic'"
            " AND layer_b = 'semantic'").fetchall()
        assert all(s[0] != 0.0 for s in sims)            # real centroid cosine

    def test_gate_disabled_no_partitioning(self, tmp_db):
        """With cohesion disabled, cluster_episodes must NOT set split_group."""
        table = _make_conflated_db(tmp_db)
        comp = Compressor(
            tmp_db,
            FakeEmbedder(table),
            config=_COMPRESS_CFG,
            cohesion_config=_COHESION_OFF,
        )
        preview = comp.cluster_episodes()
        assert all(not c.get("split_group") for c in preview["clusters"]), (
            "disabled gate must not set split_group on any cluster"
        )

    def test_gate_none_no_partitioning(self, tmp_db):
        """With cohesion_config=None (default), cluster_episodes must NOT set split_group."""
        table = _make_conflated_db(tmp_db)
        comp = Compressor(
            tmp_db,
            FakeEmbedder(table),
            config=_COMPRESS_CFG,
        )
        preview = comp.cluster_episodes()
        assert all(not c.get("split_group") for c in preview["clusters"]), (
            "no cohesion_config must not set split_group on any cluster"
        )

    def test_split_reinforce_cluster_keeps_match_on_one_part_only(self, tmp_db):
        """On split of a reinforce cluster, only the part nearest the matched semantic
        keeps action='reinforce'; all other parts get action='new', match=None.

        Fixture: 10 conflated episodes (5 on A-axis, 5 on B-axis, 60° apart).
        A semantic is pre-placed on the A-axis so the conflated centroid (cos≈0.865
        to sem-a) clears the reinforce_threshold=0.80.  After the sheaf gate splits
        the cluster, part A (cos≈0.998 to sem-a) keeps the match; part B (cos≈0.498)
        must get action='new' and match=None.
        """
        table: dict[str, list[float]] = {}
        for i in range(10):
            content = f"episode about topic {'A' if i < 5 else 'B'} number {i}"
            emb = _emb(_V_A if i < 5 else _V_B, 0.005, i)
            table[content] = emb
            tmp_db.add_episode(
                id=f"ep-r{i}",
                session_id="s",
                content=content,
                embedding=emb,
            )

        # Semantic placed on topic-A direction (no noise)
        sem_a_emb = _emb(_V_A, 0.0, 999)
        tmp_db.add_semantic(
            id="sem-a",
            content="topic A knowledge",
            kind="fact",
            confidence=0.8,
            embedding=sem_a_emb,
            source_episode_ids=[],
        )

        # reinforce_threshold=0.80: conflated centroid (cos≈0.865) clears it;
        # part B (cos≈0.498) does not.
        cfg = CompressionConfig(cluster_similarity=0.30, reinforce_threshold=0.80)
        comp = Compressor(
            tmp_db,
            FakeEmbedder(table),
            config=cfg,
            cohesion_config=_COHESION_ON,
        )
        preview = comp.cluster_episodes()
        split = [c for c in preview["clusters"] if c.get("split_group")]
        assert split, "fixture must produce a split cluster"

        reinforcers = [c for c in split if c.get("action") == "reinforce"]
        assert len(reinforcers) == 1, (
            f"exactly one part should keep action='reinforce', got {len(reinforcers)}: "
            f"{[c['action'] for c in split]}"
        )
        assert reinforcers[0]["match"]["id"] == "sem-a", (
            f"reinforcer should reference sem-a, got {reinforcers[0].get('match')}"
        )

        others = [c for c in split if c is not reinforcers[0]]
        assert all(c["action"] == "new" and c.get("match") is None for c in others), (
            f"all non-reinforcer parts must have action='new' and match=None; "
            f"got {[(c['action'], c.get('match')) for c in others]}"
        )

        # The reinforcer should hold the topic-A episodes
        assert all("topic A" in e["content"] for e in reinforcers[0]["episodes"]), (
            "the reinforcer part should contain only topic-A episodes"
        )
