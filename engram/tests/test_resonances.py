"""Tests for lateral resonance associations."""
import pytest
from storage import Storage


@pytest.fixture
def store():
    return Storage(":memory:")


@pytest.fixture
def seeded(store):
    """Store with episodes for resonance testing."""
    store.add_episode(id="ep-1", session_id="s1", content="cats are great",
                      embedding=[0.1] * 768)
    store.add_episode(id="ep-2", session_id="s1", content="dogs are great",
                      embedding=[0.2] * 768)
    store.add_episode(id="ep-3", session_id="s1", content="fish are great",
                      embedding=[0.3] * 768)
    return store


def test_add_resonance(seeded):
    rid = seeded.add_resonance("ep-1", "episode", "ep-2", "episode",
                               similarity=0.65, weight=0.5)
    assert rid is not None


def test_canonical_ordering(seeded):
    """memory_a < memory_b lexicographically, regardless of arg order."""
    rid = seeded.add_resonance("ep-2", "episode", "ep-1", "episode",
                               similarity=0.65, weight=0.5)
    row = seeded.conn.execute("SELECT memory_a, memory_b FROM resonances WHERE id=?",
                              (rid,)).fetchone()
    assert row[0] == "ep-1"
    assert row[1] == "ep-2"


def test_update_existing_resonance(seeded):
    """Second add to same pair increments co_occurrences, preserves weight."""
    seeded.add_resonance("ep-1", "episode", "ep-2", "episode",
                         similarity=0.65, weight=0.5)
    seeded.add_resonance("ep-1", "episode", "ep-2", "episode",
                         similarity=0.66, weight=0.7)
    row = seeded.conn.execute("SELECT co_occurrences, weight FROM resonances").fetchone()
    assert row[0] == 2
    assert row[1] == pytest.approx(0.5)  # weight is a birth trait, never changes


def test_get_resonances_for(seeded):
    seeded.add_resonance("ep-1", "episode", "ep-2", "episode",
                         similarity=0.65, weight=0.5)
    seeded.add_resonance("ep-1", "episode", "ep-3", "episode",
                         similarity=0.60, weight=0.4)
    results = seeded.get_resonances_for("ep-1")
    assert len(results) == 2


def test_get_resonances_for_other_side(seeded):
    """Querying by memory_b also returns the resonance."""
    seeded.add_resonance("ep-1", "episode", "ep-2", "episode",
                         similarity=0.65, weight=0.5)
    results = seeded.get_resonances_for("ep-2")
    assert len(results) == 1


def test_strengthen_resonance(seeded):
    rid = seeded.add_resonance("ep-1", "episode", "ep-2", "episode",
                               similarity=0.65, weight=0.5)
    seeded.strengthen_resonance(rid, delta=0.1)
    row = seeded.conn.execute("SELECT strength FROM resonances WHERE id=?",
                              (rid,)).fetchone()
    assert row[0] == pytest.approx(0.6)


def test_strengthen_capped_at_1(seeded):
    rid = seeded.add_resonance("ep-1", "episode", "ep-2", "episode",
                               similarity=0.65, weight=0.5)
    seeded.strengthen_resonance(rid, delta=0.9)
    row = seeded.conn.execute("SELECT strength FROM resonances WHERE id=?",
                              (rid,)).fetchone()
    assert row[0] == 1.0


def test_weaken_resonance(seeded):
    rid = seeded.add_resonance("ep-1", "episode", "ep-2", "episode",
                               similarity=0.65, weight=0.5)
    seeded.weaken_resonance(rid, delta=0.05)
    row = seeded.conn.execute("SELECT strength FROM resonances WHERE id=?",
                              (rid,)).fetchone()
    assert row[0] == pytest.approx(0.45)


def test_weaken_floored_at_005(seeded):
    rid = seeded.add_resonance("ep-1", "episode", "ep-2", "episode",
                               similarity=0.65, weight=0.5)
    seeded.weaken_resonance(rid, delta=0.9)
    row = seeded.conn.execute("SELECT strength FROM resonances WHERE id=?",
                              (rid,)).fetchone()
    assert row[0] == 0.05


def test_cleanup_removes_orphans(seeded):
    seeded.add_resonance("ep-1", "episode", "ep-2", "episode",
                         similarity=0.65, weight=0.5)
    seeded.cleanup_resonances(["ep-1"])
    rows = seeded.conn.execute("SELECT count(*) FROM resonances").fetchone()
    assert rows[0] == 0


def test_get_vector_episode(seeded):
    vec = seeded.get_vector("episode", "ep-1")
    assert vec is not None
    assert len(vec) == 768


def test_get_vector_missing(seeded):
    vec = seeded.get_vector("episode", "nonexistent")
    assert vec is None


def test_get_vector_unknown_layer(seeded):
    vec = seeded.get_vector("unknown_layer", "ep-1")
    assert vec is None


def test_form_resonances_from_results(seeded):
    """Resonances form between co-occurring recall results in the resonance zone."""
    # Import will need to be from the server module
    # Since server.py does heavy init, test the logic directly via storage
    # Create resonance manually and verify the CRUD works for this flow
    rid = seeded.add_resonance("ep-1", "episode", "ep-2", "episode",
                               similarity=0.62, weight=0.5)
    assert rid is not None
    resonances = seeded.get_resonances_for("ep-1")
    assert len(resonances) == 1
    assert resonances[0]["similarity"] == pytest.approx(0.62)


def test_resonance_feedback_strengthen(seeded):
    """Strengthening increases strength by delta."""
    rid = seeded.add_resonance("ep-1", "episode", "ep-2", "episode",
                               similarity=0.65, weight=0.5)
    seeded.strengthen_resonance(rid, delta=0.1)
    r = seeded.get_resonances_for("ep-1")[0]
    assert r["strength"] == pytest.approx(0.6)


def test_resonance_feedback_weaken(seeded):
    """Weakening decreases strength by delta."""
    rid = seeded.add_resonance("ep-1", "episode", "ep-2", "episode",
                               similarity=0.65, weight=0.5)
    seeded.weaken_resonance(rid, delta=0.05)
    r = seeded.get_resonances_for("ep-1")[0]
    assert r["strength"] == pytest.approx(0.45)


def test_resonance_end_to_end(store, monkeypatch):
    """Full cycle: recalls build co-occurrence, PMI forms resonance, surface, feedback.

    `surface_resonances` is probabilistic by design: it surfaces the other side
    of a pair only when `random.random() < weight * strength`. With the 0.99
    weight and strength set below that is a 98% coin, so an unpatched test fails
    roughly one run in fifty, which is what made this test intermittently red in
    full-suite runs while passing in isolation. The draw is pinned here so the
    test measures the surfacing logic rather than the coin; the coin itself is
    covered by test_surfacing_respects_the_probabilistic_gate.
    """
    import numpy as np
    from resonance import form_resonances, surface_resonances

    base = np.random.randn(768).astype(np.float32)
    base /= np.linalg.norm(base)
    noise = np.random.randn(768).astype(np.float32)
    noise /= np.linalg.norm(noise)
    similar = 0.6 * base + 0.8 * noise
    similar /= np.linalg.norm(similar)

    store.add_episode(id="e2e-1", session_id="s1", content="thought about trees",
                      embedding=base.tolist())
    store.add_episode(id="e2e-2", session_id="s1", content="thought about forests",
                      embedding=similar.tolist())
    store.add_episode(id="e2e-3", session_id="s1", content="thought about rocks",
                      embedding=([0.5] * 768))

    # Seed recall history so PMI(e2e-1, e2e-2) > 0.
    # 5 recalls with [e2e-1, e2e-2], 2 recalls with [e2e-3] only.
    # total=7, freq(e2e-1)=5, freq(e2e-2)=5, cooc=5
    # PMI = log2( (5/7) / ((5/7)*(5/7)) ) = log2(7/5) ≈ 0.485 > 0
    for i in range(5):
        store.add_log_entry(id=f"e2e-r{i}", event_type="recall", layer="all",
                            target_ids=["e2e-1", "e2e-2"], context={})
    for i in range(5, 7):
        store.add_log_entry(id=f"e2e-r{i}", event_type="recall", layer="all",
                            target_ids=["e2e-3"], context={})

    results = [
        {"id": "e2e-1", "layer": "episode", "score": 0.9},
        {"id": "e2e-2", "layer": "episode", "score": 0.8},
    ]
    formed = form_resonances(store, results)
    resonances = store.get_resonances_for("e2e-1")
    assert len(resonances) >= 1, f"Expected resonance, formed={formed}"

    rid = resonances[0]["id"]
    store.conn.execute("UPDATE resonances SET weight=0.99, strength=0.99 WHERE id=?", (rid,))
    store.conn.commit()

    existing = {"e2e-1"}
    monkeypatch.setattr("resonance.random.random", lambda: 0.0)
    surfaced = surface_resonances(store, [{"id": "e2e-1", "layer": "episode"}],
                                  existing, max_resonant=2)
    assert len(surfaced) >= 1
    assert surfaced[0].get("resonant") is True

    store.strengthen_resonance(rid, delta=0.1)
    r = store.get_resonances_for("e2e-1")[0]
    assert r["strength"] >= 0.99


def test_prune_cleans_up_resonances(seeded):
    """Moving an episode to cold storage cleans up its resonances."""
    seeded.add_resonance("ep-1", "episode", "ep-2", "episode",
                         similarity=0.65, weight=0.5)
    seeded.conn.execute("UPDATE episodes SET decay_strength=0.01, compressed=1 WHERE id='ep-1'")
    seeded.conn.commit()
    seeded.prune_decayed(threshold=0.05)
    rows = seeded.conn.execute("SELECT count(*) FROM resonances").fetchone()
    assert rows[0] == 0


def test_get_recall_cooccurrences_empty(store):
    """No recall logs = empty co-occurrences."""
    result = store.get_recall_cooccurrences()
    assert result == {}


def test_get_recall_cooccurrences(store):
    """Two recalls with overlapping target_ids produce co-occurrences."""
    store.add_log_entry(id="r1", event_type="recall", layer="all",
                        target_ids=["a", "b", "c"],
                        context={"recall_id": "r1", "query": "test"})
    store.add_log_entry(id="r2", event_type="recall", layer="all",
                        target_ids=["a", "b", "d"],
                        context={"recall_id": "r2", "query": "test2"})
    result = store.get_recall_cooccurrences()
    pair_ab = result.get(("a", "b"), 0)
    assert pair_ab == 2
    pair_ac = result.get(("a", "c"), 0)
    assert pair_ac == 1
    pair_ad = result.get(("a", "d"), 0)
    assert pair_ad == 1


def test_get_memory_recall_frequency(store):
    """Count how many recalls each memory appears in."""
    store.add_log_entry(id="r1", event_type="recall", layer="all",
                        target_ids=["a", "b"], context={})
    store.add_log_entry(id="r2", event_type="recall", layer="all",
                        target_ids=["a", "c"], context={})
    freq = store.get_memory_recall_frequency()
    assert freq["a"] == 2
    assert freq["b"] == 1
    assert freq["c"] == 1


def test_compute_pmi_basic():
    """PMI > 0 for pairs that co-occur more than chance predicts."""
    from resonance import compute_pmi
    cooccurrences = {("a", "b"): 5, ("a", "c"): 1, ("b", "c"): 1}
    frequency = {"a": 6, "b": 6, "c": 2}
    total_recalls = 10
    pmi = compute_pmi(cooccurrences, frequency, total_recalls)
    assert pmi[("a", "b")] > 0
    assert pmi[("a", "c")] < 0


def test_compute_pmi_zero_frequency():
    """Zero-frequency memories should not appear in PMI."""
    from resonance import compute_pmi
    pmi = compute_pmi({("a", "b"): 1}, {"a": 0, "b": 1}, 10)
    assert len(pmi) == 0


def test_compute_pmi_insufficient_recalls():
    """PMI needs a minimum number of recalls to be meaningful."""
    from resonance import compute_pmi
    pmi = compute_pmi({("a", "b"): 1}, {"a": 1, "b": 1}, 2)
    assert len(pmi) == 0


def test_pmi_resonance_end_to_end(store):
    """Full cycle: multiple recalls build co-occurrence, PMI forms resonance."""
    store.add_episode(id="pmi-1", session_id="s1", content="about trees",
                      embedding=[0.1] * 768)
    store.add_episode(id="pmi-2", session_id="s1", content="about forests",
                      embedding=[0.2] * 768)
    store.add_episode(id="pmi-3", session_id="s1", content="about oceans",
                      embedding=[0.3] * 768)

    # Simulate 7 recalls: pmi-1 and pmi-2 co-occur in 5 recalls,
    # pmi-3 appears alone in 2 recalls.
    # Total: pmi-1 freq=5, pmi-2 freq=5, pmi-3 freq=2, cooc(1,2)=5
    # PMI(1,2) = log2((5/7) / ((5/7)*(5/7))) = log2(7/5) > 0
    for i in range(5):
        store.add_log_entry(
            id=f"recall-{i}", event_type="recall", layer="all",
            target_ids=["pmi-1", "pmi-2"], context={"recall_id": f"recall-{i}", "query": f"q{i}"},
        )
    for i in range(5, 7):
        store.add_log_entry(
            id=f"recall-{i}", event_type="recall", layer="all",
            target_ids=["pmi-3"], context={"recall_id": f"recall-{i}", "query": f"q{i}"},
        )

    from resonance import form_resonances
    results = [
        {"id": "pmi-1", "layer": "episode"},
        {"id": "pmi-2", "layer": "episode"},
        {"id": "pmi-3", "layer": "episode"},
    ]
    formed = form_resonances(store, results)

    # pmi-1 and pmi-2 co-occur more than chance predicts — should have positive PMI
    r12 = store.get_resonances_for("pmi-1")
    pair_with_2 = [r for r in r12 if r["memory_b"] == "pmi-2" or r["memory_a"] == "pmi-2"]
    assert len(pair_with_2) >= 1, f"Expected pmi-1/pmi-2 resonance, formed={formed}"


def test_pmi_no_resonance_below_threshold(store):
    """Pairs that co-occur at chance level don't form resonances."""
    store.add_episode(id="n-1", session_id="s1", content="a", embedding=[0.1] * 768)
    store.add_episode(id="n-2", session_id="s1", content="b", embedding=[0.2] * 768)

    # Both appear in every recall — PMI ≈ 0
    for i in range(6):
        store.add_log_entry(
            id=f"nr-{i}", event_type="recall", layer="all",
            target_ids=["n-1", "n-2"],
            context={"recall_id": f"nr-{i}", "query": f"q{i}"},
        )

    from resonance import form_resonances
    results = [{"id": "n-1", "layer": "episode"}, {"id": "n-2", "layer": "episode"}]
    formed = form_resonances(store, results)

    # Both appear in ALL recalls, so P(a,b) = P(a)*P(b), PMI = 0
    resonances = store.get_resonances_for("n-1")
    assert len(resonances) == 0, "Expected no resonance for chance-level co-occurrence"


def test_surfacing_respects_the_probabilistic_gate(seeded, monkeypatch):
    """The gate is `random.random() < weight * strength`, and it really gates."""
    from resonance import surface_resonances

    seeded.add_resonance("ep-1", "episode", "ep-2", "episode", similarity=0.9, weight=0.8)
    rid = seeded.get_resonances_for("ep-1")[0]["id"]
    seeded.conn.execute("UPDATE resonances SET weight=0.8, strength=0.5 WHERE id=?", (rid,))
    seeded.conn.commit()
    top = [{"id": "ep-1", "layer": "episode"}]

    monkeypatch.setattr("resonance.random.random", lambda: 0.39)   # below 0.8*0.5
    assert len(surface_resonances(seeded, top, {"ep-1"}, max_resonant=2)) == 1

    monkeypatch.setattr("resonance.random.random", lambda: 0.41)   # above 0.8*0.5
    assert surface_resonances(seeded, top, {"ep-1"}, max_resonant=2) == []
