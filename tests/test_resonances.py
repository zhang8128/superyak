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


def test_resonance_end_to_end(store):
    """Full cycle: store, form resonance, surface, feedback."""
    import numpy as np
    from resonance import form_resonances, surface_resonances

    # Create two episodes with controlled similarity (~0.6, in resonance zone)
    base = np.random.randn(768).astype(np.float32)
    base /= np.linalg.norm(base)
    # Perturb to get ~0.6 cosine similarity
    noise = np.random.randn(768).astype(np.float32)
    noise /= np.linalg.norm(noise)
    similar = 0.6 * base + 0.8 * noise  # cos sim ≈ 0.6
    similar /= np.linalg.norm(similar)

    store.add_episode(id="e2e-1", session_id="s1", content="thought about trees",
                      embedding=base.tolist())
    store.add_episode(id="e2e-2", session_id="s1", content="thought about forests",
                      embedding=similar.tolist())

    # Form resonances
    results = [
        {"id": "e2e-1", "layer": "episode", "score": 0.9},
        {"id": "e2e-2", "layer": "episode", "score": 0.8},
    ]
    formed = form_resonances(store, results, reinforce_threshold=0.70)

    # Verify resonance was created (similarity should be ~0.6, in zone)
    resonances = store.get_resonances_for("e2e-1")
    assert len(resonances) >= 1, f"Expected resonance, formed={formed}"

    # Set high weight+strength so surfacing is near-certain
    rid = resonances[0]["id"]
    store.conn.execute("UPDATE resonances SET weight=0.99, strength=0.99 WHERE id=?", (rid,))
    store.conn.commit()

    # Surface
    existing = {"e2e-1"}
    surfaced = surface_resonances(store, [{"id": "e2e-1", "layer": "episode"}],
                                  existing, max_resonant=2)
    assert len(surfaced) >= 1
    assert surfaced[0].get("resonant") is True
    assert surfaced[0]["id"] == "e2e-2"

    # Feedback: strengthen
    store.strengthen_resonance(rid, delta=0.1)
    r = store.get_resonances_for("e2e-1")[0]
    assert r["strength"] >= 0.99  # was already 0.99, capped at 1.0


def test_prune_cleans_up_resonances(seeded):
    """Pruning a decayed episode also removes its resonances."""
    seeded.add_resonance("ep-1", "episode", "ep-2", "episode",
                         similarity=0.65, weight=0.5)
    seeded.conn.execute("UPDATE episodes SET decay_strength=0.01, compressed=1 WHERE id='ep-1'")
    seeded.conn.commit()
    seeded.prune_decayed(threshold=0.05)
    rows = seeded.conn.execute("SELECT count(*) FROM resonances").fetchone()
    assert rows[0] == 0
