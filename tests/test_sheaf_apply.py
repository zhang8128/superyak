"""Tests for sheaf-cohesion storage: migration 020 + accessors."""

from __future__ import annotations

import json

import numpy as np
import pytest

import sheaf


class TestMigration020:
    def test_tables_exist(self, tmp_db):
        names = {r[0] for r in tmp_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert {"subdivision_events", "semantic_peers", "subdivision_queue"} <= names


class TestSubdivisionAccessors:
    def test_log_and_get_subdivision_event(self, tmp_db):
        tmp_db.log_subdivision_event(
            id="ev-1", parent_id="sem-1", peer_ids=["p1", "p2"],
            energy_before=0.9, energy_after=0.2, dl_cost=0.15,
            persistence_checked=False, site="sleep",
        )
        events = tmp_db.get_subdivision_events(limit=5)
        assert len(events) == 1
        assert events[0]["parent_id"] == "sem-1"
        assert json.loads(events[0]["peer_ids"]) == ["p1", "p2"]
        assert events[0]["persistence_checked"] == 0
        assert events[0]["site"] == "sleep"

    def test_add_and_get_semantic_peers(self, tmp_db):
        tmp_db.add_semantic_peer(peer_id="p1", parent_id="sem-1", residual_energy=0.1)
        tmp_db.add_semantic_peer(peer_id="p2", parent_id="sem-1", residual_energy=0.2)
        peers = tmp_db.get_semantic_peers("sem-1")
        assert {p["peer_id"] for p in peers} == {"p1", "p2"}

    def test_queue_roundtrip(self, tmp_db):
        tmp_db.queue_subdivision("sem-1", {"parts": [["e1"], ["e2"]], "gain": 0.5})
        queued = tmp_db.get_queued_subdivisions()
        assert len(queued) == 1
        assert json.loads(queued[0]["verdict"])["gain"] == 0.5
        # re-queue replaces, not duplicates
        tmp_db.queue_subdivision("sem-1", {"gain": 0.6})
        assert len(tmp_db.get_queued_subdivisions()) == 1
        tmp_db.dequeue_subdivision("sem-1")
        assert tmp_db.get_queued_subdivisions() == []


def _seed_semantic(tmp_db, fake_embedding, n_eps=6):
    eps = []
    for i in range(n_eps):
        eid = f"ep-{i}"
        tmp_db.add_episode(id=eid, session_id="s", content=f"episode {i}",
                           embedding=fake_embedding())
        eps.append(eid)
    tmp_db.add_semantic(id="sem-1", content="conflated hub", kind="fact",
                        confidence=0.8, embedding=fake_embedding(),
                        source_episode_ids=eps, lane="personal")
    return eps


def _verdict(eps):
    return sheaf.Verdict(
        semantic_id="sem-1", split=True,
        parts=[eps[:3], eps[3:5]], ambiguous=[eps[5]],
        energy_before=0.9, part_energies=[0.1, 0.1], gain=0.7,
        dl_cost=0.15, persistence_checked=False, worst_edges=[],
    )


class TestApplySubdivision:
    def test_full_split(self, tmp_db, fake_embedding):
        eps = _seed_semantic(tmp_db, fake_embedding)
        result = sheaf.apply_subdivision(
            tmp_db, _verdict(eps),
            peer_contents=["peer one", "peer two"],
            hub_content="the shared residue",
            embed_fn=lambda text: fake_embedding(), site="sleep",
        )
        assert len(result["peer_ids"]) == 2
        p1 = tmp_db.get_semantic(result["peer_ids"][0])
        assert p1["content"] == "peer one"
        assert p1["kind"] == "fact" and p1["lane"] == "personal"
        assert set(p1["source_episode_ids"]) == set(eps[:3])
        hub = tmp_db.get_semantic("sem-1")
        assert hub["content"] == "the shared residue"     # episodes remained
        assert hub["source_episode_ids"] == [eps[5]]      # only the ambiguous one
        assert {p["peer_id"] for p in tmp_db.get_semantic_peers("sem-1")} \
            == set(result["peer_ids"])
        events = tmp_db.get_subdivision_events()
        assert events[0]["parent_id"] == "sem-1" and events[0]["site"] == "sleep"
        # peers are recallable: vectors exist
        for pid in result["peer_ids"]:
            row = tmp_db.conn.execute(
                "SELECT 1 FROM semantic_vectors WHERE id = ?", (pid,)).fetchone()
            assert row is not None

    def test_hub_content_kept_when_emptied(self, tmp_db, fake_embedding):
        eps = _seed_semantic(tmp_db, fake_embedding)
        v = _verdict(eps)
        v.parts = [eps[:3], eps[3:]]   # nothing ambiguous, hub empties
        v.ambiguous = []
        sheaf.apply_subdivision(tmp_db, v, ["peer one", "peer two"],
                                hub_content="ignored",
                                embed_fn=lambda t: fake_embedding(), site="sleep")
        hub = tmp_db.get_semantic("sem-1")
        assert hub["content"] == "conflated hub"   # left as-is per spec
        assert hub["source_episode_ids"] == []

    def test_atomicity_on_failure(self, tmp_db, fake_embedding):
        eps = _seed_semantic(tmp_db, fake_embedding)

        def exploding_embed(text):
            raise RuntimeError("embedder died mid-split")

        with pytest.raises(RuntimeError):
            sheaf.apply_subdivision(tmp_db, _verdict(eps), ["a", "b"],
                                    hub_content=None,
                                    embed_fn=exploding_embed, site="sleep")
        # store unchanged: no peers, provenance intact, no events
        assert tmp_db.get_semantic_peers("sem-1") == []
        assert set(tmp_db.get_semantic("sem-1")["source_episode_ids"]) == set(eps)
        assert tmp_db.get_subdivision_events() == []

    def test_peer_count_mismatch_rejected(self, tmp_db, fake_embedding):
        eps = _seed_semantic(tmp_db, fake_embedding)
        with pytest.raises(ValueError):
            sheaf.apply_subdivision(tmp_db, _verdict(eps), ["only one"],
                                    hub_content=None,
                                    embed_fn=lambda t: fake_embedding(), site="sleep")

    def test_part_energy_count_mismatch_rejected(self, tmp_db, fake_embedding):
        # zip() truncates silently — a short part_energies must not half-mint
        eps = _seed_semantic(tmp_db, fake_embedding)
        v = _verdict(eps)
        v.part_energies = [0.1]   # 2 parts, 1 energy
        with pytest.raises(ValueError):
            sheaf.apply_subdivision(tmp_db, v, ["peer one", "peer two"],
                                    hub_content=None,
                                    embed_fn=lambda t: fake_embedding(), site="sleep")
        # nothing was minted
        assert tmp_db.get_semantic_peers("sem-1") == []
        assert set(tmp_db.get_semantic("sem-1")["source_episode_ids"]) == set(eps)

    def test_hub_vector_dropped_on_content_rewrite(self, tmp_db, fake_embedding):
        # the orphan-vector backfill only re-embeds MISSING rows, so the
        # executor must drop the stale hub vector when it rewrites content
        eps = _seed_semantic(tmp_db, fake_embedding)
        sheaf.apply_subdivision(tmp_db, _verdict(eps), ["peer one", "peer two"],
                                hub_content="the shared residue",
                                embed_fn=lambda t: fake_embedding(), site="sleep")
        row = tmp_db.conn.execute(
            "SELECT 1 FROM semantic_vectors WHERE id = 'sem-1'").fetchone()
        assert row is None

    def test_hub_vector_kept_when_content_untouched(self, tmp_db, fake_embedding):
        eps = _seed_semantic(tmp_db, fake_embedding)
        v = _verdict(eps)
        v.parts = [eps[:3], eps[3:]]
        v.ambiguous = []
        v.part_energies = [0.1, 0.1]
        sheaf.apply_subdivision(tmp_db, v, ["peer one", "peer two"],
                                hub_content=None,
                                embed_fn=lambda t: fake_embedding(), site="sleep")
        row = tmp_db.conn.execute(
            "SELECT 1 FROM semantic_vectors WHERE id = 'sem-1'").fetchone()
        assert row is not None


class TestFullRecompressCleansPeers:
    def test_reset_all_clears_peer_and_queue_rows(self, tmp_db, fake_embedding):
        from compress import Compressor
        from config import CompressionConfig
        tmp_db.add_semantic(id="sem-1", content="hub", kind="fact",
                            confidence=0.8, embedding=fake_embedding(),
                            source_episode_ids=[])
        tmp_db.add_semantic_peer(peer_id="p1", parent_id="sem-1", residual_energy=0.1)
        tmp_db.queue_subdivision("sem-1", {"gain": 0.5})
        tmp_db.log_subdivision_event(id="ev1", parent_id="sem-1", peer_ids=["p1"],
                                     energy_before=0.5, energy_after=0.1,
                                     dl_cost=0.15, persistence_checked=False,
                                     site="sleep")
        comp = Compressor(tmp_db, None, config=CompressionConfig())
        comp._reset_all()
        assert tmp_db.get_semantic_peers("sem-1") == []
        assert tmp_db.get_queued_subdivisions() == []
        # audit trail survives intentionally
        assert tmp_db.get_subdivision_events() != []
