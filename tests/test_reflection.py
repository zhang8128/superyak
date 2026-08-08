import uuid
import pytest
from datetime import datetime, timezone, timedelta
from reflection import Reflector


def test_usage_analysis(tmp_db, fake_embedding):
    tmp_db.add_episode(id="ep-1", session_id="s1", content="a", embedding=fake_embedding())
    tmp_db.add_episode(id="ep-2", session_id="s1", content="b", embedding=fake_embedding())
    tmp_db.increment_episode_access("ep-1")
    tmp_db.increment_episode_access("ep-1")

    r = Reflector(tmp_db)
    usage = r.analyze_usage()
    assert usage["most_accessed"][0]["id"] == "ep-1"
    assert usage["most_accessed"][0]["accessed_count"] == 2


def test_gap_detection(tmp_db):
    tmp_db.add_log_entry(id="l1", event_type="recall", layer="episode",
                         target_ids=[], context={"query": "deployment process"})
    tmp_db.add_log_entry(id="l2", event_type="recall", layer="episode",
                         target_ids=["ep-1"], context={"query": "SQLite"})

    r = Reflector(tmp_db)
    gaps = r.detect_gaps()
    assert len(gaps) == 1
    assert "deployment" in gaps[0]["query"]


def test_instinct_health(tmp_db):
    tmp_db.add_instinct(id="i1", trigger="t", action="a", source_semantic_ids=[])
    for _ in range(2):
        tmp_db.update_instinct_followed("i1")
    for _ in range(8):
        tmp_db.update_instinct_overridden("i1")

    r = Reflector(tmp_db)
    health = r.instinct_health()
    assert health[0]["reliability"] == pytest.approx(0.2)
    assert health[0]["recommendation"] == "weaken_or_remove"


def test_staleness_detection(tmp_db, fake_embedding):
    old_date = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    tmp_db.add_semantic(id="sem-1", content="old fact", kind="fact",
                        confidence=0.5, embedding=fake_embedding(), source_episode_ids=[])
    tmp_db.conn.execute("UPDATE semantics SET created_at=? WHERE id='sem-1'", (old_date,))
    tmp_db.conn.commit()

    r = Reflector(tmp_db, staleness_days=30)
    stale = r.detect_staleness()
    assert len(stale) == 1
    assert stale[0]["id"] == "sem-1"


def test_contradiction_detection(tmp_db, fake_embedding):
    emb = fake_embedding()
    tmp_db.add_semantic(id="sem-1", content="old fact", kind="fact",
                        confidence=0.7, embedding=emb, source_episode_ids=[])
    tmp_db.add_semantic(id="sem-2", content="new fact", kind="fact",
                        confidence=0.5, embedding=emb, source_episode_ids=[])
    tmp_db.contradict_semantic("sem-1", contradicted_by="sem-2")

    r = Reflector(tmp_db)
    contradictions = r.detect_contradictions()
    assert len(contradictions) == 1
    assert contradictions[0]["id"] == "sem-1"
    assert contradictions[0]["contradicted_by"] == "sem-2"


def test_introspect(tmp_db, fake_embedding):
    tmp_db.add_semantic(id="s1", content="fact 1", kind="fact", confidence=0.7,
                        embedding=fake_embedding(), source_episode_ids=[])
    tmp_db.add_semantic(id="s2", content="pref 1", kind="preference", confidence=0.9,
                        embedding=fake_embedding(), source_episode_ids=[])
    tmp_db.add_instinct(id="i1", trigger="t", action="a", source_semantic_ids=[])

    r = Reflector(tmp_db)
    result = r.introspect()
    assert "fact" in result["semantics_by_kind"]
    assert len(result["instincts"]) == 1
    assert "health_metrics" in result


def test_reflect_dispatches_focus(tmp_db):
    r = Reflector(tmp_db)
    result = r.reflect(focus="usage")
    assert "usage" in result
    result_all = r.reflect()
    assert "usage" in result_all
    assert "gaps" in result_all
    assert "instincts" in result_all


def test_category_evolution_focus_returns_report_but_no_focus_stays_unchanged(tmp_db):
    """Catches category diagnostics leaking into the default reflection response."""
    report = {
        "available": True,
        "flags": {
            "enabled": True,
            "shadow": True,
            "influence_recall": False,
            "auto_commit": False,
        },
        "counts_by_dimension": {"0": 3, "1": 2},
        "proposal_dispositions": {"proposed": 1, "committed": 0, "rejected": 2, "superseded": 0},
        "current_epoch": "epoch-7",
        "recent_boundaries": [{"kind": "soft", "score": 0.4, "context_id": "context-2"}],
        "compiler_truncations": 4,
        "quota_pressure": {"state": "normal", "used_bytes": 12, "quota_bytes": 100},
        "last_error": None,
    }
    reflector = Reflector(tmp_db, category_reporter=lambda: report)

    assert reflector.reflect(focus="category_evolution") == {"category_evolution": report}
    assert "category_evolution" not in reflector.reflect()


def test_category_evolution_focus_absent_and_failure_shapes_are_content_safe(tmp_db):
    """Catches absent/error reporters changing shape or exposing exception text."""
    assert Reflector(tmp_db).reflect(focus="category_evolution") == {
        "category_evolution": {"available": False}
    }

    def fail():
        raise RuntimeError("private report details")

    assert Reflector(tmp_db, category_reporter=fail).reflect(focus="category_evolution") == {
        "category_evolution": {"available": False, "error": "RuntimeError"}
    }


def test_unobserved_instinct_recommendation(tmp_db):
    """Never-fired instincts are 'unobserved' — they may influence through channels the system doesn't track."""
    tmp_db.add_instinct(id="i-unobserved", trigger="t", action="a", source_semantic_ids=[])
    r = Reflector(tmp_db)
    health = r.instinct_health()
    assert len(health) == 1
    assert health[0]["recommendation"] == "unobserved"
    assert health[0]["reliability"] == 0.0


def test_reflect_detects_genome_drift(tmp_db, tmp_path):
    """Drift detection finds overlapping but diverged instinct actions."""
    import sqlite3

    genome_db = tmp_path / "genome.db"
    conn = sqlite3.connect(str(genome_db))
    conn.execute("CREATE TABLE instincts (action TEXT, strength REAL)")
    conn.execute("INSERT INTO instincts VALUES ('prefer simple direct clear approaches always', 0.8)")
    conn.commit()
    conn.close()

    tmp_db.add_instinct(
        id="i1", trigger="complexity", action="prefer complex direct clear decomposition always",
        source_semantic_ids=[]
    )

    r = Reflector(tmp_db, genome_db_path=str(genome_db))
    drift = r.detect_genome_drift()
    assert len(drift) == 1
    assert drift[0]["type"] == "potential_drift"
    assert "prefer simple" in drift[0]["genome_instinct"]
    assert "prefer complex" in drift[0]["local_instinct"]


def test_reflect_no_genome_returns_empty(tmp_db):
    """Reflector without genome path returns empty drift list."""
    r = Reflector(tmp_db)
    assert r.detect_genome_drift() == []


def test_introspect_reports_lane_counts(tmp_db):
    import uuid as _uuid
    tmp_db.add_episode(id=str(_uuid.uuid4()), session_id="s", content="a personal one")
    tmp_db.add_episode(id=str(_uuid.uuid4()), session_id="s", content="a work one", lane="work")
    reflector = Reflector(tmp_db, 30)
    result = reflector.introspect()
    assert result["health_metrics"]["lanes"]["episodes"] == {"personal": 1, "work": 1}


def test_signal_health(tmp_path, tmp_db):
    """signal_health returns message count from signals db."""
    import sqlite3

    signals_db = tmp_path / "signals.db"
    conn = sqlite3.connect(str(signals_db))
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, body TEXT)")
    conn.execute("INSERT INTO messages (body) VALUES ('hello')")
    conn.execute("INSERT INTO messages (body) VALUES ('world')")
    conn.commit()
    conn.close()

    r = Reflector(tmp_db, signals_db_path=str(signals_db))
    health = r.signal_health()
    assert health is not None
    assert health["total_messages"] == 2


def test_instinct_context_health(tmp_db):
    """Per-context health should show follow/override ratio per context."""
    sem_id = str(uuid.uuid4())
    emb = [0.1] * 768
    tmp_db.add_semantic(id=sem_id, content="test", kind="preference",
                        confidence=0.5, embedding=emb, source_episode_ids=[])
    tmp_db.add_instinct(
        id="inst-ctx", trigger="preference", action="be terse",
        source_semantic_ids=[sem_id],
    )
    from storage import _pack_embedding
    packed = _pack_embedding(emb)
    for _ in range(3):
        tmp_db.add_instinct_context_feedback(
            instinct_id="inst-ctx", context_text="building",
            context_embedding=packed, followed=True,
        )
    tmp_db.add_instinct_context_feedback(
        instinct_id="inst-ctx", context_text="reflecting",
        context_embedding=packed, followed=False,
    )

    from reflection import Reflector
    reflector = Reflector(tmp_db)
    health = reflector.instinct_context_health()
    assert len(health) >= 1
    inst_health = [h for h in health if h["id"] == "inst-ctx"][0]
    assert "contexts" in inst_health
    contexts = {c["context"]: c["follow_ratio"] for c in inst_health["contexts"]}
    assert contexts["building"] == 1.0
    assert contexts["reflecting"] == 0.0


def test_reflect_instinct_contexts_focus(tmp_db):
    """reflect(focus='instinct_contexts') should return context health."""
    from reflection import Reflector
    reflector = Reflector(tmp_db)
    result = reflector.reflect("instinct_contexts")
    assert "instinct_contexts" in result


def test_reflect_classifications(tmp_db, fake_embedding):
    """reflect(focus='classifications') should return recent episode classifications."""
    tmp_db.add_episode(id="ep-cls-1", session_id="s1", content="I prefer verbose explanations", embedding=fake_embedding())
    tmp_db.add_episode(id="ep-cls-2", session_id="s1", content="Remember to use async/await", embedding=fake_embedding())

    from reflection import Reflector
    reflector = Reflector(tmp_db)
    result = reflector.reflect(focus="classifications")

    assert "classifications" in result
    assert "recent_episodes" in result["classifications"]
    episodes = result["classifications"]["recent_episodes"]
    assert len(episodes) >= 2
    ids = [ep["id"] for ep in episodes]
    assert "ep-cls-1" in ids
    assert "ep-cls-2" in ids
    for ep in episodes:
        assert "heuristic_kinds" in ep
        assert "model_suggested" in ep
        assert "content" in ep


def test_reflect_resonances(tmp_db, fake_embedding):
    """reflect(focus='resonances') should return the resonance network."""
    emb = fake_embedding()
    tmp_db.add_episode(id="ep-res-1", session_id="s1", content="episode one", embedding=emb)
    tmp_db.add_episode(id="ep-res-2", session_id="s1", content="episode two", embedding=emb)
    tmp_db.add_resonance(
        id_a="ep-res-1", layer_a="episode",
        id_b="ep-res-2", layer_b="episode",
        similarity=0.9, weight=1.0,
    )

    from reflection import Reflector
    reflector = Reflector(tmp_db)
    result = reflector.reflect(focus="resonances")

    assert "resonances" in result
    assert "network" in result["resonances"]
    assert "total" in result["resonances"]
    assert "orphans" in result["resonances"]
    network = result["resonances"]["network"]
    assert len(network) >= 1
    entry = network[0]
    assert "a" in entry
    assert "b" in entry
    assert "strength" in entry
    assert "co_occurrences" in entry


def test_reflect_instinct_clusters(tmp_db):
    """reflect(focus='instinct_clusters') shows cluster structure."""
    from reflection import Reflector

    storage = tmp_db
    emb = [0.1] * 768
    storage.add_instinct("i1", "preference", "coding instinct", [], embedding=emb)
    storage.add_instinct("i2", "preference", "also coding", [], embedding=emb)
    storage.create_cluster("c1", maturity="confirmed", temperament=0.3)
    storage.add_to_cluster("i1", "c1", strength=0.8)
    storage.add_to_cluster("i2", "c1", strength=0.6)

    storage.record_co_fire("i1", "i2", followed=True)
    storage.record_co_fire("i1", "i2", followed=True)
    storage.record_co_fire("i1", "i2", followed=False)

    reflector = Reflector(storage)
    result = reflector.reflect(focus="instinct_clusters")
    assert "instinct_clusters" in result

    clusters = result["instinct_clusters"]
    assert len(clusters) >= 1

    c = clusters[0]
    assert "members" in c
    assert "temperament" in c
    assert "maturity" in c
    assert len(c["members"]) == 2


def test_vital_signs_warns_on_core_inflation(tmp_db, fake_embedding):
    for i in range(10):
        tmp_db.add_episode(id=f"ep-{i}", session_id="s1", content=f"e{i}",
                           embedding=fake_embedding())
    tmp_db.mark_core_batch([f"ep-{i}" for i in range(8)])

    r = Reflector(tmp_db)
    vs = r.vital_signs()
    assert vs["core_fraction"] == pytest.approx(0.8)
    assert any("core" in w.lower() for w in vs["warnings"])


def test_vital_signs_healthy_core_fraction_no_warning(tmp_db, fake_embedding):
    for i in range(10):
        tmp_db.add_episode(id=f"ep-{i}", session_id="s1", content=f"e{i}",
                           embedding=fake_embedding())
    tmp_db.mark_core("ep-0")

    r = Reflector(tmp_db)
    vs = r.vital_signs()
    assert vs["core_fraction"] == pytest.approx(0.1)
    assert not any("core" in w.lower() for w in vs["warnings"])
    assert "lanes" in vs


def test_vital_signs_detects_frozen_instinct_loop(tmp_db):
    for i in range(3):
        tmp_db.add_instinct(id=f"i{i}", trigger="t", action=f"a{i}", source_semantic_ids=[])

    r = Reflector(tmp_db)
    vs = r.vital_signs()
    assert vs["instinct_feedback"]["frozen"] is True
    assert vs["instinct_feedback"]["total_fired"] == 0
    assert any("instinct" in w.lower() for w in vs["warnings"])


def test_vital_signs_thawed_when_feedback_flows(tmp_db):
    for i in range(3):
        tmp_db.add_instinct(id=f"i{i}", trigger="t", action=f"a{i}", source_semantic_ids=[])
    tmp_db.update_instinct_followed("i0")

    r = Reflector(tmp_db)
    vs = r.vital_signs()
    assert vs["instinct_feedback"]["frozen"] is False


def test_reflect_routes_vital_signs_focus(tmp_db):
    r = Reflector(tmp_db)
    out = r.reflect(focus="vital_signs")
    assert "vital_signs" in out
    assert "core_fraction" in out["vital_signs"]


class TestSourceFidelity:
    """Pure cosine between a semantic and the centroid of its source embeddings."""

    def test_identical_is_one(self):
        from reflection import _source_fidelity
        assert _source_fidelity([1.0, 0.0], [[1.0, 0.0]]) == 1.0

    def test_orthogonal_is_zero(self):
        from reflection import _source_fidelity
        assert _source_fidelity([0.0, 1.0], [[1.0, 0.0]]) == 0.0

    def test_sits_at_centroid_of_two_sources(self):
        from reflection import _source_fidelity
        # semantic [1,1] vs centroid of [1,0],[0,1] = [0.5,0.5] → cosine 1.0
        assert _source_fidelity([1.0, 1.0], [[1.0, 0.0], [0.0, 1.0]]) == pytest.approx(1.0)

    def test_zero_vector_is_zero_not_nan(self):
        from reflection import _source_fidelity
        assert _source_fidelity([0.0, 0.0], [[0.0, 0.0]]) == 0.0


def _emb(*hot, dim=768):
    v = [0.0] * dim
    for i in hot:
        v[i] = 1.0
    return v


def test_analyze_fidelity_separates_reconcilable_and_lost(tmp_db):
    # High-fidelity semantic: its embedding matches its source.
    tmp_db.add_episode(id="ep-h", session_id="s", content="h", embedding=_emb(0))
    tmp_db.add_semantic("sem-h", "faithful", kind="fact", confidence=0.9,
                        embedding=_emb(0), source_episode_ids=["ep-h"])
    # Low-fidelity semantic: embedding orthogonal to its source.
    tmp_db.add_episode(id="ep-l", session_id="s", content="l", embedding=_emb(0))
    tmp_db.add_semantic("sem-l", "drifted", kind="fact", confidence=0.9,
                        embedding=_emb(1), source_episode_ids=["ep-l"])
    # Unreconcilable semantic: its only source decays to cold (link CASCADE-deleted).
    tmp_db.add_episode(id="ep-g", session_id="s", content="g", embedding=_emb(0))
    tmp_db.add_semantic("sem-g", "orphaned", kind="fact", confidence=0.9,
                        embedding=_emb(0), source_episode_ids=["ep-g"])
    tmp_db.prune_episode_ids(["ep-g"])

    r = Reflector(tmp_db)
    rep = r.analyze_fidelity()
    assert rep["semantics_total"] == 3
    assert rep["reconcilable"] == 2
    assert rep["unreconcilable"] == 1
    assert rep["lowest"][0]["semantic_id"] == "sem-l"
    assert rep["lowest"][0]["fidelity"] == pytest.approx(0.0, abs=1e-6)


def test_reflect_routes_fidelity_focus(tmp_db):
    r = Reflector(tmp_db)
    out = r.reflect(focus="fidelity")
    assert "fidelity" in out
    assert out["fidelity"]["semantics_total"] == 0


def test_gravity_warning_fires_above_threshold():
    from reflection import _gravity_warning, GRAVITY_WARN
    warning = _gravity_warning(GRAVITY_WARN + 0.05)
    assert warning is not None
    assert "concentrat" in warning.lower() or "gravity" in warning.lower()


def test_gravity_warning_silent_below_threshold():
    from reflection import _gravity_warning, GRAVITY_WARN
    assert _gravity_warning(GRAVITY_WARN - 0.3) is None


def test_vital_signs_gravity_failure_is_not_silent(tmp_db, fake_embedding, monkeypatch):
    # A failed graph build must NOT report 0.0 (the healthiest reading) — that
    # would hide a real failure behind a perfect score. It reports None + warns.
    tmp_db.add_episode(id="ep-0", session_id="s1", content="e", embedding=fake_embedding())
    import graph
    def boom(self):
        raise RuntimeError("graph build failed")
    monkeypatch.setattr(graph.MemoryGraph, "analyze", boom)

    r = Reflector(tmp_db)
    vs = r.vital_signs()
    assert vs["graph_concentration"]["degree_gini"] is None
    assert any("gravity" in w.lower() and "unavailable" in w.lower() for w in vs["warnings"])


def test_default_reflect_excludes_graph_scan(tmp_db, fake_embedding):
    # The no-focus reflect() must not pay for a full graph traversal — mirrors
    # how cohesion and persistence are excluded from the default. Explicit
    # focus="vital_signs" still computes it.
    tmp_db.add_episode(id="ep-0", session_id="s1", content="e", embedding=fake_embedding())
    r = Reflector(tmp_db)

    default = r.reflect()["vital_signs"]
    assert default["graph_concentration"]["degree_gini"] is None

    focused = r.reflect(focus="vital_signs")["vital_signs"]
    assert focused["graph_concentration"]["degree_gini"] == 0.0


def test_vital_signs_surfaces_graph_concentration(tmp_db, fake_embedding):
    # One semantic distilled from five episodes = a provenance star.
    ep_ids = []
    for i in range(5):
        eid = f"ep-{i}"
        tmp_db.add_episode(id=eid, session_id="s1", content=f"e{i}",
                           embedding=fake_embedding())
        ep_ids.append(eid)
    tmp_db.add_semantic("sem-0", "hub", kind="fact", confidence=0.9,
                        embedding=fake_embedding(), source_episode_ids=ep_ids)

    r = Reflector(tmp_db)
    vs = r.vital_signs()
    assert vs["graph_concentration"]["degree_gini"] == pytest.approx(0.3333, abs=1e-3)
    # A 6-node star sits below the pathological threshold — no warning.
    assert not any("concentrat" in w.lower() for w in vs["warnings"])


def test_vital_signs_core_fraction_over_personal_lane(tmp_db):
    from reflection import Reflector
    import uuid as _uuid
    # 2 personal (1 core) + 2 work episodes
    for i, (lane, core) in enumerate([("personal", True), ("personal", False),
                                      ("work", False), ("work", False)]):
        eid = str(_uuid.uuid4())
        tmp_db.add_episode(id=eid, session_id="s", content=f"episode {i}", lane=lane)
        if core:
            tmp_db.mark_core(eid)
    reflector = Reflector(tmp_db, 30)
    vs = reflector.vital_signs()
    assert vs["personal_episode_count"] == 2  # personal only
    assert vs["core_fraction"] == 0.5        # 1 of 2 personal
    assert vs["lanes"] == {"episodes": {"personal": 2, "work": 2},
                           "semantics": {"personal": 0, "work": 0}}
