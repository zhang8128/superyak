"""reflect(focus='cohesion') and peer-edge neighbor tests."""

import numpy as np

from reflection import Reflector


def _emb(axis, noise, seed):
    rng = np.random.default_rng(seed)
    v = np.zeros(768); v[axis] = 1.0
    v = v + noise * rng.standard_normal(768)
    return (v / np.linalg.norm(v)).tolist()


class TestReflectCohesion:
    def test_focus_returns_ranked_energies(self, tmp_db):
        eps = []
        for i in range(8):
            eid = f"e{i}"
            tmp_db.add_episode(id=eid, session_id="s", content=f"ep {i}",
                               embedding=_emb(0 if i < 4 else 1, 0.05, i))
            eps.append(eid)
        tmp_db.add_semantic(id="sem-1", content="conflated", kind="fact",
                            confidence=0.8, embedding=_emb(0, 0.3, 9),
                            source_episode_ids=eps)
        r = Reflector(tmp_db)
        out = r.reflect(focus="cohesion")
        coh = out["cohesion"]
        assert coh["semantics_measured"] == 1
        assert coh["hottest"][0]["semantic_id"] == "sem-1"
        assert coh["hottest"][0]["energy"] > 0.8
        assert "recent_events" in coh and "queued" in coh

    def test_empty_store(self, tmp_db):
        out = Reflector(tmp_db).reflect(focus="cohesion")
        assert out["cohesion"]["semantics_measured"] == 0


class TestPeerNeighbors:
    def test_peer_edge_appears(self, tmp_db):
        for sid in ("sem-1", "peer-1"):
            tmp_db.add_semantic(id=sid, content=f"content {sid}", kind="fact",
                                confidence=0.8, embedding=_emb(0, 0.1, 1),
                                source_episode_ids=[])
        tmp_db.add_semantic_peer(peer_id="peer-1", parent_id="sem-1",
                                 residual_energy=0.1)
        neighbors = tmp_db.get_neighbors("sem-1")
        peer = [n for n in neighbors if n["connection_type"] == "peer"]
        assert peer and peer[0]["id"] == "peer-1"
        # and symmetric from the peer side
        back = [n for n in tmp_db.get_neighbors("peer-1")
                if n["connection_type"] == "peer"]
        assert back and back[0]["id"] == "sem-1"


class TestGraphViewPeers:
    def test_peer_edges_in_memory_graph(self, tmp_db):
        from graph import MemoryGraph
        for sid in ("sem-1", "peer-1"):
            tmp_db.add_semantic(id=sid, content=f"content {sid}", kind="fact",
                                confidence=0.8, embedding=_emb(0, 0.1, 1),
                                source_episode_ids=[])
        tmp_db.add_semantic_peer(peer_id="peer-1", parent_id="sem-1",
                                 residual_energy=0.1)
        g = MemoryGraph(tmp_db)
        view = g.to_json("sem-1", depth=1)
        edge_types = {e.get("edge_type") for e in view.get("edges", [])}
        assert "peer" in edge_types
