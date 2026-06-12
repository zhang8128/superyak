"""Tests for sheaf-cohesion storage: migration 020 + accessors."""

from __future__ import annotations

import json


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
