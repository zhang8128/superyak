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
