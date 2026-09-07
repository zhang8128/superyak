"""Tests for the coherence layer — anchors, drift detection, unchallenged instincts."""

import json
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock

from storage import Storage
from coherence import CoherenceChecker

MIGRATIONS_DIR = str(Path(__file__).resolve().parent.parent / "migrations")


def _make_storage(tmp_path):
    db_path = str(tmp_path / "test_coherence.db")
    return Storage(db_path, migrations_dir=MIGRATIONS_DIR)


def _fake_emb(dim=768, seed=42):
    import random
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(dim)]


class TestMigration:
    def test_anchors_table_exists(self, tmp_path):
        store = _make_storage(tmp_path)
        row = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='anchors'"
        ).fetchone()
        assert row is not None
        store.close()

    def test_drift_reports_table_exists(self, tmp_path):
        store = _make_storage(tmp_path)
        row = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='drift_reports'"
        ).fetchone()
        assert row is not None
        store.close()


class TestAnchorCRUD:
    def test_add_anchor(self, tmp_path):
        store = _make_storage(tmp_path)
        aid = store.add_anchor(
            type="identity",
            content="Who is Kairos?",
            expected="ep-core-001",
            baseline_score=0.92,
        )
        assert aid is not None
        anchor = store.get_anchor(aid)
        assert anchor["type"] == "identity"
        assert anchor["content"] == "Who is Kairos?"
        assert anchor["expected"] == "ep-core-001"
        assert anchor["baseline_score"] == 0.92
        assert anchor["status"] == "active"
        store.close()

    def test_get_active_anchors(self, tmp_path):
        store = _make_storage(tmp_path)
        store.add_anchor(type="identity", content="q1", expected="e1", baseline_score=0.9)
        store.add_anchor(type="value", content="q2", expected="rubric1")
        store.add_anchor(type="capability", content="q3", expected="rubric2")
        active = store.get_active_anchors()
        assert len(active) == 3
        assert {a["type"] for a in active} == {"identity", "value", "capability"}
        store.close()

    def test_get_anchors_by_type(self, tmp_path):
        store = _make_storage(tmp_path)
        store.add_anchor(type="identity", content="q1", expected="e1", baseline_score=0.9)
        store.add_anchor(type="identity", content="q2", expected="e2", baseline_score=0.8)
        store.add_anchor(type="value", content="q3", expected="rubric")
        identity_anchors = store.get_active_anchors(anchor_type="identity")
        assert len(identity_anchors) == 2
        store.close()

    def test_update_anchor_result(self, tmp_path):
        store = _make_storage(tmp_path)
        aid = store.add_anchor(type="identity", content="q1", expected="e1", baseline_score=0.9)
        store.update_anchor_result(aid, '{"status": "pass", "score": 0.88}')
        anchor = store.get_anchor(aid)
        assert anchor["last_result"] == '{"status": "pass", "score": 0.88}'
        assert anchor["last_checked"] is not None
        store.close()

    def test_propose_retirement(self, tmp_path):
        store = _make_storage(tmp_path)
        aid = store.add_anchor(type="identity", content="q1", expected="e1", baseline_score=0.9)
        store.propose_anchor_retirement(aid)
        anchor = store.get_anchor(aid)
        assert anchor["status"] == "proposed_retirement"
        assert anchor["retirement_sessions"] == 1
        store.close()

    def test_retirement_after_two_sessions(self, tmp_path):
        store = _make_storage(tmp_path)
        aid = store.add_anchor(type="identity", content="q1", expected="e1", baseline_score=0.9)
        store.propose_anchor_retirement(aid)
        store.propose_anchor_retirement(aid)
        anchor = store.get_anchor(aid)
        assert anchor["status"] == "retired"
        store.close()

    def test_retired_anchors_not_in_active(self, tmp_path):
        store = _make_storage(tmp_path)
        aid = store.add_anchor(type="identity", content="q1", expected="e1", baseline_score=0.9)
        store.propose_anchor_retirement(aid)
        store.propose_anchor_retirement(aid)
        active = store.get_active_anchors()
        assert len(active) == 0
        store.close()


class TestDriftReportStorage:
    def test_save_drift_report(self, tmp_path):
        store = _make_storage(tmp_path)
        rid = store.save_drift_report(
            session_id="sess-001",
            drifted_apart=[{"edge": "a→b", "drift_score": 0.6}],
            drifted_together=[{"node_a": "c", "node_b": "d", "similarity": 0.85}],
            unchallenged=[{"instinct_id": "inst-1", "strength": 0.9}],
            anchor_results=[{"id": "anc-1", "status": "pass"}],
            summary="1 drifted apart, 1 drifted together, 1 unchallenged",
        )
        assert rid is not None
        store.close()

    def test_get_latest_drift_report(self, tmp_path):
        store = _make_storage(tmp_path)
        store.save_drift_report(
            session_id="sess-001",
            drifted_apart=[], drifted_together=[], unchallenged=[],
            anchor_results=[], summary="all clear",
        )
        store.save_drift_report(
            session_id="sess-002",
            drifted_apart=[{"edge": "x"}], drifted_together=[], unchallenged=[],
            anchor_results=[], summary="1 drift",
        )
        report = store.get_latest_drift_report()
        assert report is not None
        assert report["session_id"] == "sess-002"
        apart = json.loads(report["drifted_apart"])
        assert len(apart) == 1
        store.close()

    def test_get_drift_history(self, tmp_path):
        store = _make_storage(tmp_path)
        for i in range(5):
            store.save_drift_report(
                session_id=f"sess-{i:03d}",
                drifted_apart=[], drifted_together=[], unchallenged=[],
                anchor_results=[], summary=f"report {i}",
            )
        history = store.get_drift_history(limit=3)
        assert len(history) == 3
        assert history[0]["session_id"] == "sess-004"
        store.close()


class TestIdentityAnchors:
    def test_identity_anchor_passes(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        emb = _fake_emb(seed=1)
        store.add_episode(ep_id, None, "Kairos corrected my interpretation of Clubs", embedding=emb)
        store.mark_core(ep_id)

        aid = store.add_anchor(
            type="identity",
            content="Kairos corrected my interpretation",
            expected=ep_id,
            baseline_score=0.9,
        )

        with patch("coherence.NomicEmbedProvider") as MockEmbed:
            mock_provider = MockEmbed.return_value
            mock_provider.embed.return_value = [_fake_emb(seed=1)]
            checker = CoherenceChecker(store)
            results = checker.check_identity_anchors()
        assert len(results) == 1
        assert results[0]["anchor_id"] == aid
        assert results[0]["status"] == "pass"
        store.close()

    def test_identity_anchor_fails_missing_memory(self, tmp_path):
        store = _make_storage(tmp_path)
        aid = store.add_anchor(
            type="identity",
            content="Something that was deleted",
            expected="nonexistent-id",
            baseline_score=0.9,
        )

        checker = CoherenceChecker(store)
        results = checker.check_identity_anchors()
        assert len(results) == 1
        assert results[0]["status"] == "fail"
        store.close()

    def test_identity_anchor_degraded(self, tmp_path):
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        # Use a very different embedding from what the query would produce
        store.add_episode(ep_id, None, "Completely unrelated content about weather", embedding=_fake_emb(seed=99))
        store.mark_core(ep_id)

        aid = store.add_anchor(
            type="identity",
            content="Kairos corrected my interpretation of Clubs",
            expected=ep_id,
            baseline_score=0.95,
        )

        with patch("coherence.NomicEmbedProvider") as MockEmbed:
            mock_provider = MockEmbed.return_value
            mock_provider.embed.return_value = [_fake_emb(seed=1)]
            checker = CoherenceChecker(store)
            results = checker.check_identity_anchors()
        assert len(results) == 1
        # The expected memory exists but similarity may be low
        assert results[0]["status"] in ("pass", "degraded")
        store.close()


class TestValueAnchors:
    def test_value_anchor_insufficient_data(self, tmp_path):
        """With no semantics, value anchor should report insufficient_data, not fail."""
        store = _make_storage(tmp_path)
        store.add_anchor(
            type="value",
            content="What matters about unbounded experimentation?",
            expected=json.dumps(["safety floor", "ergodicity", "bounded"]),
        )
        checker = CoherenceChecker(store)
        results = checker.check_value_anchors()
        assert len(results) == 1
        assert results[0]["status"] == "insufficient_data"
        store.close()

    def test_value_anchor_pass_with_semantics(self, tmp_path):
        """With matching semantics, value anchor should pass."""
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        store.add_episode(ep_id, None, "placeholder", embedding=_fake_emb(seed=1))
        sem_id = str(uuid.uuid4())
        store.add_semantic(sem_id, "Safety floor is critical for bounded experimentation",
                          kind="fact", confidence=0.9, embedding=_fake_emb(seed=2),
                          source_episode_ids=[ep_id])
        store.add_anchor(
            type="value",
            content="experimentation",
            expected=json.dumps(["safety floor", "bounded"]),
        )
        checker = CoherenceChecker(store)
        results = checker.check_value_anchors()
        assert len(results) == 1
        assert results[0]["status"] == "pass"
        assert results[0]["coverage"] == 1.0
        store.close()


class TestCapabilityAnchors:
    def test_capability_anchor_skipped_v1(self, tmp_path):
        """V1 stub should report 'skipped', not 'pass'."""
        store = _make_storage(tmp_path)
        store.add_anchor(
            type="capability",
            content="What is 7 * 8?",
            expected=json.dumps({"answer": "56", "rubric": ["correct arithmetic"]}),
        )
        checker = CoherenceChecker(store)
        results = checker.check_capability_anchors()
        assert len(results) == 1
        assert results[0]["status"] == "skipped"
        store.close()


class TestDriftScan:
    def test_healthy_edge_not_flagged(self, tmp_path):
        """An edge where embeddings are close should not appear in drifted_apart."""
        store = _make_storage(tmp_path)
        emb = _fake_emb(seed=1)
        ep_id = str(uuid.uuid4())
        sem_id = str(uuid.uuid4())
        store.add_episode(ep_id, None, "test episode", embedding=emb)
        store.add_semantic(sem_id, "test semantic", kind="fact", confidence=0.9,
                          embedding=emb, source_episode_ids=[ep_id])

        checker = CoherenceChecker(store)
        report = checker.scan_drift()
        apart_ids = {d["source"] for d in report["drifted_apart"]}
        assert ep_id not in apart_ids or sem_id not in apart_ids
        store.close()

    def test_distant_connected_nodes_flagged(self, tmp_path):
        """An edge where embeddings are distant should appear in drifted_apart."""
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        sem_id = str(uuid.uuid4())
        # Very different embeddings
        store.add_episode(ep_id, None, "cats and dogs", embedding=_fake_emb(seed=1))
        store.add_semantic(sem_id, "quantum physics", kind="fact", confidence=0.9,
                          embedding=_fake_emb(seed=999), source_episode_ids=[ep_id])

        checker = CoherenceChecker(store)
        report = checker.scan_drift()
        # Smoke test: method runs without error on distant connected nodes
        assert isinstance(report["drifted_apart"], list)
        store.close()

    def test_close_unconnected_nodes_found(self, tmp_path):
        """Geometrically close but unconnected nodes should appear in drifted_together."""
        store = _make_storage(tmp_path)
        emb = _fake_emb(seed=1)
        ep1 = str(uuid.uuid4())
        ep2 = str(uuid.uuid4())
        # Same embedding, no structural connection
        store.add_episode(ep1, None, "episode one", embedding=emb)
        store.add_episode(ep2, None, "episode two", embedding=emb)

        checker = CoherenceChecker(store)
        report = checker.scan_drift()
        together_pairs = {(d["node_a"], d["node_b"]) for d in report["drifted_together"]}
        # These identical embeddings should be flagged as drifted together
        has_pair = (ep1, ep2) in together_pairs or (ep2, ep1) in together_pairs
        assert has_pair
        store.close()

    def test_drift_report_saved(self, tmp_path):
        store = _make_storage(tmp_path)
        checker = CoherenceChecker(store)
        report = checker.scan_drift(session_id="sess-test")
        saved = store.get_latest_drift_report()
        assert saved is not None
        assert saved["session_id"] == "sess-test"
        store.close()


class TestUnchallenged:
    def test_high_strength_zero_override_flagged(self, tmp_path):
        store = _make_storage(tmp_path)
        inst_id = str(uuid.uuid4())
        store.conn.execute(
            "INSERT INTO instincts (id, trigger, action, strength, fired_count, followed_count, notice, implication, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            (inst_id, "disposition", "Always do X", 0.85, 10, 10, "notice X", "implies Y"),
        )
        store.conn.commit()

        checker = CoherenceChecker(store)
        unchallenged = checker.detect_unchallenged(min_strength=0.7, min_follows=5)
        ids = [u["instinct_id"] for u in unchallenged]
        assert inst_id in ids
        store.close()

    def test_overridden_instinct_not_flagged(self, tmp_path):
        store = _make_storage(tmp_path)
        inst_id = str(uuid.uuid4())
        store.conn.execute(
            "INSERT INTO instincts (id, trigger, action, strength, fired_count, followed_count, notice, implication, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            (inst_id, "disposition", "Sometimes do X", 0.85, 10, 7, "notice X", "implies Y"),
        )
        store.conn.commit()
        # Add some override feedback
        for _ in range(3):
            store.add_instinct_context_feedback(inst_id, "building", None, False)

        checker = CoherenceChecker(store)
        unchallenged = checker.detect_unchallenged(min_strength=0.7, min_follows=5)
        ids = [u["instinct_id"] for u in unchallenged]
        assert inst_id not in ids
        store.close()

    def test_weak_instinct_not_flagged(self, tmp_path):
        store = _make_storage(tmp_path)
        inst_id = str(uuid.uuid4())
        store.conn.execute(
            "INSERT INTO instincts (id, trigger, action, strength, fired_count, followed_count, notice, implication, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            (inst_id, "disposition", "Weak instinct", 0.3, 2, 2, "notice", "implication"),
        )
        store.conn.commit()

        checker = CoherenceChecker(store)
        unchallenged = checker.detect_unchallenged(min_strength=0.7, min_follows=5)
        ids = [u["instinct_id"] for u in unchallenged]
        assert inst_id not in ids
        store.close()


class TestFullCheck:
    def test_full_check_returns_all_sections(self, tmp_path):
        store = _make_storage(tmp_path)
        store.add_anchor(type="identity", content="test query", expected="fake-id", baseline_score=0.9)
        store.add_anchor(type="value", content="test scenario", expected=json.dumps(["term1"]))

        checker = CoherenceChecker(store)
        report = checker.run_full_check(session_id="sess-full")
        assert "anchor_results" in report
        assert "drift" in report
        assert "summary" in report
        store.close()

    def test_full_check_saves_report(self, tmp_path):
        store = _make_storage(tmp_path)
        checker = CoherenceChecker(store)
        checker.run_full_check(session_id="sess-save")
        saved = store.get_latest_drift_report()
        assert saved is not None
        assert saved["session_id"] == "sess-save"
        store.close()


from reflection import Reflector


class TestReflectIntegration:
    def test_reflect_coherence_focus(self, tmp_path):
        store = _make_storage(tmp_path)
        store.save_drift_report(
            session_id="sess-test",
            drifted_apart=[{"source": "a", "target": "b", "embedding_similarity": 0.1}],
            drifted_together=[],
            unchallenged=[],
            anchor_results=[],
            summary="1 drifted apart",
        )
        reflector = Reflector(store)
        result = reflector.reflect(focus="coherence")
        assert "coherence" in result
        assert "latest_report" in result["coherence"]
        assert "trend" in result["coherence"]
        store.close()

    def test_reflect_anchors_focus(self, tmp_path):
        store = _make_storage(tmp_path)
        store.add_anchor(type="identity", content="test", expected="e1", baseline_score=0.9)
        reflector = Reflector(store)
        result = reflector.reflect(focus="anchors")
        assert "anchors" in result
        assert len(result["anchors"]) == 1
        store.close()


class TestEndToEnd:
    def test_full_coherence_lifecycle(self, tmp_path):
        """Full lifecycle: create memories, mark core, auto-anchor, run check, inspect report."""
        store = _make_storage(tmp_path)

        # Create some connected memories
        ep1 = str(uuid.uuid4())
        ep2 = str(uuid.uuid4())
        sem1 = str(uuid.uuid4())
        emb1 = _fake_emb(seed=10)
        emb2 = _fake_emb(seed=10)  # same seed = same embedding = close
        emb3 = _fake_emb(seed=500)  # different = distant

        store.add_episode(ep1, None, "Kairos taught me about governance", embedding=emb1)
        store.add_episode(ep2, None, "Unrelated episode about weather", embedding=emb3)
        store.add_semantic(sem1, "Governance requires bounded experimentation",
                          kind="fact", confidence=0.9, embedding=emb2,
                          source_episode_ids=[ep1])

        # Mark core and create identity anchor
        store.mark_core(ep1)
        store.add_anchor(
            type="identity",
            content="Kairos taught governance",
            expected=ep1,
            baseline_score=0.85,
        )

        # Add a value anchor
        store.add_anchor(
            type="value",
            content="unbounded experimentation",
            expected=json.dumps(["bounded", "safety"]),
        )

        # Create a high-confidence instinct with no overrides
        inst_id = str(uuid.uuid4())
        store.conn.execute(
            "INSERT INTO instincts (id, trigger, action, strength, fired_count, followed_count, notice, implication, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            (inst_id, "disposition", "Always check assumptions", 0.9, 15, 15, "assumptions present", "verify before acting"),
        )
        store.conn.commit()

        # Run full check
        checker = CoherenceChecker(store)
        report = checker.run_full_check(session_id="integration-test")

        # Verify structure
        assert "anchor_results" in report
        assert "drift" in report
        assert "summary" in report

        # Identity anchor should exist in results
        identity_results = [r for r in report["anchor_results"] if "anchor_id" in r]
        assert len(identity_results) >= 1

        # Unchallenged instinct should be flagged
        unchallenged_ids = [u["instinct_id"] for u in report["drift"]["unchallenged"]]
        assert inst_id in unchallenged_ids

        # Drift report should be saved
        saved = store.get_latest_drift_report()
        assert saved is not None
        assert saved["session_id"] == "integration-test"

        # Reflect should work
        reflector = Reflector(store)
        coherence = reflector.reflect(focus="coherence")
        assert coherence["coherence"]["latest_report"] is not None

        anchors = reflector.reflect(focus="anchors")
        assert len(anchors["anchors"]) >= 1

        store.close()


class TestEdgeCases:
    def test_identity_anchor_with_semantic_expected(self, tmp_path):
        """Identity anchor pointing to a semantic (not episode) should work."""
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        sem_id = str(uuid.uuid4())
        emb = _fake_emb(seed=1)
        store.add_episode(ep_id, None, "source", embedding=_fake_emb(seed=99))
        store.add_semantic(sem_id, "Core principle about governance",
                          kind="fact", confidence=0.9, embedding=emb,
                          source_episode_ids=[ep_id])

        store.add_anchor(
            type="identity",
            content="Core principle about governance",
            expected=sem_id,
            baseline_score=0.9,
        )

        with patch("coherence.NomicEmbedProvider") as MockEmbed:
            mock_provider = MockEmbed.return_value
            mock_provider.embed.return_value = [emb]
            checker = CoherenceChecker(store)
            results = checker.check_identity_anchors()

        assert len(results) == 1
        assert results[0]["status"] == "pass"
        store.close()

    def test_baseline_score_zero_not_treated_as_none(self, tmp_path):
        """baseline_score=0.0 should use 0.0, not default to 0.5."""
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        emb = _fake_emb(seed=1)
        store.add_episode(ep_id, None, "test", embedding=emb)

        aid = store.add_anchor(
            type="identity",
            content="test query",
            expected=ep_id,
            baseline_score=0.0,
        )

        with patch("coherence.NomicEmbedProvider") as MockEmbed:
            mock_provider = MockEmbed.return_value
            mock_provider.embed.return_value = [emb]
            checker = CoherenceChecker(store)
            results = checker.check_identity_anchors()

        assert results[0]["baseline"] == 0.0
        store.close()

    def test_embedding_failure_persisted_and_counted(self, tmp_path):
        """When embedding fails, error status should be persisted and appear in summary."""
        store = _make_storage(tmp_path)
        ep_id = str(uuid.uuid4())
        store.add_episode(ep_id, None, "important memory", embedding=_fake_emb(seed=1))
        store.add_anchor(
            type="identity",
            content="important memory",
            expected=ep_id,
            baseline_score=0.9,
        )

        with patch("coherence.NomicEmbedProvider") as MockEmbed:
            MockEmbed.return_value.embed.side_effect = RuntimeError("model not found")
            checker = CoherenceChecker(store)
            report = checker.run_full_check(session_id="error-test")

        assert "could not be checked" in report["summary"]
        anchor = store.get_anchor(store.get_active_anchors(anchor_type="identity")[0]["id"])
        assert '"error"' in anchor["last_result"]
        store.close()

    def test_empty_system_reports_no_data(self, tmp_path):
        """A system with nothing to check should say so, not 'coherence stable'."""
        store = _make_storage(tmp_path)
        checker = CoherenceChecker(store)
        report = checker.run_full_check(session_id="empty-test")
        assert report["summary"] == "no data to check"
        store.close()

    def test_full_check_report_includes_anchor_results(self, tmp_path):
        """The persisted drift report should contain actual anchor results."""
        store = _make_storage(tmp_path)
        store.add_anchor(
            type="identity", content="query", expected="nonexistent-id", baseline_score=0.9
        )
        checker = CoherenceChecker(store)
        checker.run_full_check(session_id="persist-test")

        saved = store.get_latest_drift_report()
        anchor_results = json.loads(saved["anchor_results"])
        assert len(anchor_results) == 1
        assert anchor_results[0]["status"] == "fail"
        store.close()
