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
