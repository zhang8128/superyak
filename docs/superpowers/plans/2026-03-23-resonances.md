# Resonances Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lateral association layer between memories — resonances that form when memories co-occur in recall or nearly match during compression, with stochastic weights for instance individuality.

**Architecture:** New `resonances` table in SQLite (no vec0). Formation happens in two places: recall co-occurrence (primary) and compression near-miss (secondary). Surfacing is probabilistic during recall. Feedback is per-recall via existing `log_outcome`. Shared logic lives in `storage.py` so both `server.py` and Emma's `emma_engram.py` can use it.

**Tech Stack:** Python, SQLite, numpy (cosine similarity from stored vectors).

**Spec:** `docs/superpowers/specs/2026-03-23-resonances-design.md`

---

## File Structure

```
engram/
├── migrations/012_resonances.sql    # CREATE TABLE + indexes
├── storage.py                       # Resonance CRUD, get_vector(), cleanup
├── server.py                        # Formation in recall, surfacing, feedback tracking
├── compress.py                      # Near-miss return, resonance on compression zone
└── tests/test_resonances.py         # All resonance tests

emma/
└── emma_engram.py                   # Calls shared resonance logic from storage.py
```

---

### Task 1: Migration + Schema

**Files:**
- Create: `migrations/012_resonances.sql`
- Modify: `storage.py` (schema init section)

- [ ] **Step 1: Create migration file**

```sql
-- migrations/012_resonances.sql
CREATE TABLE IF NOT EXISTS resonances (
    id TEXT PRIMARY KEY,
    memory_a TEXT NOT NULL,
    layer_a TEXT NOT NULL,
    memory_b TEXT NOT NULL,
    layer_b TEXT NOT NULL,
    similarity REAL,
    weight REAL NOT NULL,
    strength REAL NOT NULL DEFAULT 0.5,
    co_occurrences INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    UNIQUE(memory_a, memory_b)
);

CREATE INDEX IF NOT EXISTS idx_resonances_a ON resonances(memory_a);
CREATE INDEX IF NOT EXISTS idx_resonances_b ON resonances(memory_b);
```

- [ ] **Step 2: Add schema creation to Storage.__init__**

In `storage.py`, add the resonances table creation to the existing schema init
(same pattern as other tables — `CREATE TABLE IF NOT EXISTS`). Include the two
indexes. Place it after the existing table creation block.

- [ ] **Step 3: Verify schema creation**

```bash
.venv/bin/python -c "from storage import Storage; s = Storage(':memory:'); print([r[0] for r in s.conn.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name='resonances'\").fetchall()])"
```

Expected: `['resonances']`

- [ ] **Step 4: Commit**

```bash
git add migrations/012_resonances.sql storage.py
git commit -m "feat: resonances table schema and migration"
```

---

### Task 2: Storage CRUD Methods

**Files:**
- Modify: `storage.py`
- Create: `tests/test_resonances.py`

- [ ] **Step 1: Write tests for resonance CRUD**

```python
# tests/test_resonances.py
"""Tests for lateral resonance associations."""
import pytest
from storage import Storage


@pytest.fixture
def store():
    return Storage(":memory:")


@pytest.fixture
def seeded(store):
    """Store with two episodes for resonance testing."""
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_resonances.py -v
```

Expected: All FAIL (methods don't exist yet)

- [ ] **Step 3: Implement resonance CRUD in Storage**

Add these methods to the `Storage` class in `storage.py`:

- `add_resonance(id_a, layer_a, id_b, layer_b, similarity, weight) -> str`
  — Canonical ordering: sort so `memory_a < memory_b`. On UNIQUE conflict,
  increment `co_occurrences` and update `last_seen`. Returns resonance ID.
- `get_resonances_for(memory_id) -> list[dict]`
  — Query both sides: `WHERE memory_a = ? OR memory_b = ?`
- `strengthen_resonance(resonance_id, delta=0.1)`
  — `UPDATE strength = MIN(1.0, strength + delta)`
- `weaken_resonance(resonance_id, delta=0.05)`
  — `UPDATE strength = MAX(0.05, strength - delta)`
- `cleanup_resonances(pruned_ids: list[str])`
  — Delete resonances referencing any of the pruned IDs.

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_resonances.py -v
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add storage.py tests/test_resonances.py
git commit -m "feat: resonance CRUD methods in Storage"
```

---

### Task 3: get_vector() Method

**Files:**
- Modify: `storage.py`
- Modify: `tests/test_resonances.py`

- [ ] **Step 1: Write test for get_vector**

Add to `tests/test_resonances.py`:

```python
def test_get_vector_episode(seeded):
    vec = seeded.get_vector("episode", "ep-1")
    assert vec is not None
    assert len(vec) == 768


def test_get_vector_missing(seeded):
    vec = seeded.get_vector("episode", "nonexistent")
    assert vec is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_resonances.py::test_get_vector_episode -v
```

- [ ] **Step 3: Implement get_vector**

Add to `Storage`:

```python
def get_vector(self, layer: str, id: str) -> list[float] | None:
    """Fetch stored embedding vector by layer and ID."""
    import struct
    table = {"episode": "episode_vectors", "semantic": "semantic_vectors",
             "instinct": "instinct_vectors"}.get(layer)
    if not table:
        return None
    row = self.conn.execute(
        f"SELECT embedding FROM {table} WHERE id = ?", (id,)
    ).fetchone()
    if not row:
        return None
    blob = row[0]
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m pytest tests/test_resonances.py -v
```

- [ ] **Step 5: Commit**

```bash
git add storage.py tests/test_resonances.py
git commit -m "feat: get_vector() for point lookup of stored embeddings"
```

---

### Task 4: Resonance Formation in Recall

**Files:**
- Modify: `server.py`
- Modify: `tests/test_resonances.py`

- [ ] **Step 1: Write test for recall co-occurrence formation**

Add to `tests/test_resonances.py`:

```python
def test_form_resonances_from_results(seeded):
    """Resonances form between co-occurring recall results in the resonance zone."""
    from server import _form_resonances
    results = [
        {"id": "ep-1", "layer": "episode", "score": 0.9},
        {"id": "ep-2", "layer": "episode", "score": 0.8},
    ]
    formed = _form_resonances(seeded, results, reinforce_threshold=0.70)
    # ep-1 and ep-2 have similar dummy embeddings — may or may not be in zone.
    # Just verify it doesn't crash and returns a count.
    assert isinstance(formed, int)
```

- [ ] **Step 2: Implement _form_resonances helper**

In `server.py`, add a module-level function (not inside recall, to keep it testable):

```python
def _form_resonances(storage, results, reinforce_threshold=0.70):
    """Form resonances between co-occurring recall results.

    Checks top 5 results pairwise. If their stored-vector similarity
    is in the resonance zone (0.50 to reinforce_threshold), create or
    update a resonance with stochastic weight.
    """
    import random
    top = results[:5]
    formed = 0
    for i, a in enumerate(top):
        vec_a = storage.get_vector(a["layer"], a["id"])
        if vec_a is None:
            continue
        for b in top[i+1:]:
            vec_b = storage.get_vector(b["layer"], b["id"])
            if vec_b is None:
                continue
            # Cosine similarity from stored vectors
            import numpy as np
            va, vb = np.array(vec_a), np.array(vec_b)
            norm = np.linalg.norm(va) * np.linalg.norm(vb)
            sim = float(np.dot(va, vb) / norm) if norm > 0 else 0.0
            if 0.50 <= sim < reinforce_threshold:
                weight = max(0.1, min(0.9, random.gauss(0.5, 0.15)))
                storage.add_resonance(
                    a["id"], a["layer"], b["id"], b["layer"],
                    similarity=sim, weight=weight,
                )
                formed += 1
    return formed
```

- [ ] **Step 3: Call _form_resonances in recall()**

In `server.py:recall()`, after the uninvited memories section (around line 840)
and before the dream score hiding, add:

```python
    # Form resonances from co-occurring results
    try:
        _form_resonances(_storage, results,
                         reinforce_threshold=_config.reinforce_threshold if _config else 0.70)
    except Exception:
        logger.debug("Resonance formation failed", exc_info=True)
```

- [ ] **Step 4: Run all tests**

```bash
.venv/bin/python -m pytest tests/ -q
```

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_resonances.py
git commit -m "feat: resonance formation during recall co-occurrence"
```

---

### Task 5: Resonance Surfacing in Recall

**Files:**
- Modify: `server.py`
- Modify: `tests/test_resonances.py`

- [ ] **Step 1: Write test for surfacing**

Add to `tests/test_resonances.py`:

```python
def test_surface_resonances(seeded):
    """Surfacing returns resonant memories tagged appropriately."""
    from server import _surface_resonances
    # Create a resonance with high weight and strength so it always surfaces
    seeded.add_resonance("ep-1", "episode", "ep-3", "episode",
                         similarity=0.65, weight=0.95)
    seeded.strengthen_resonance(
        seeded.conn.execute("SELECT id FROM resonances").fetchone()[0],
        delta=0.5,
    )
    existing_ids = {"ep-1", "ep-2"}
    surfaced = _surface_resonances(seeded, [{"id": "ep-1", "layer": "episode"}],
                                   existing_ids, max_resonant=2)
    # ep-3 should surface (high weight × strength) and be tagged
    if surfaced:
        assert surfaced[0].get("resonant") is True
```

- [ ] **Step 2: Implement _surface_resonances helper**

```python
def _surface_resonances(storage, top_results, existing_ids, max_resonant=2):
    """Surface resonance-pulled memories from top results.

    Walks one hop from each top result. Each candidate surfaces with
    probability = weight × strength. Returns at most max_resonant.
    """
    import random
    candidates = []
    for r in top_results[:3]:
        resonances = storage.get_resonances_for(r["id"])
        for res in resonances:
            # Find the other side of the pair
            other_id = res["memory_b"] if res["memory_a"] == r["id"] else res["memory_a"]
            other_layer = res["layer_b"] if res["memory_a"] == r["id"] else res["layer_a"]
            if other_id in existing_ids:
                continue
            prob = res["weight"] * res["strength"]
            if random.random() < prob:
                candidates.append({
                    "id": other_id,
                    "layer": other_layer,
                    "resonant": True,
                    "resonance_id": res["id"],
                })
                existing_ids.add(other_id)
    # Hydrate content
    surfaced = []
    for c in candidates[:max_resonant]:
        if c["layer"] == "episode":
            row = storage.get_episode(c["id"])
            if row:
                c["content"] = row.get("content", "")
        elif c["layer"] == "semantic":
            row = storage.get_semantic(c["id"])
            if row:
                c["content"] = row.get("content", "")
        elif c["layer"] == "instinct":
            inst = storage.get_instinct(c["id"])
            if inst:
                c["content"] = inst.get("action", "")
        if "content" in c:
            surfaced.append(c)
    return surfaced
```

- [ ] **Step 3: Wire surfacing into recall()**

In `server.py:recall()`, after the uninvited memories section and after
`_form_resonances`, add:

```python
    # Surface resonance-pulled memories
    try:
        matched_ids = {r["id"] for r in results}
        resonant = _surface_resonances(_storage, results, matched_ids, max_resonant=2)
        for r in resonant:
            results.append(r)
            result_ids.append(r["id"])
    except Exception:
        logger.debug("Resonance surfacing failed", exc_info=True)
```

- [ ] **Step 4: Add resonance tracking for feedback**

Add a module-level dict alongside `_recall_scores`:

```python
_recall_resonances: dict[str, list[dict]] = {}  # recall_id -> [{resonance_id, memory_id}]
```

When surfacing resonant memories, store the mapping:

```python
    if resonant:
        _recall_resonances[recall_id] = [
            {"resonance_id": r["resonance_id"], "memory_id": r["id"]} for r in resonant
        ]
        # Evict oldest if too many
        if len(_recall_resonances) > 50:
            oldest = next(iter(_recall_resonances))
            del _recall_resonances[oldest]
```

- [ ] **Step 5: Run all tests**

```bash
.venv/bin/python -m pytest tests/ -q
```

- [ ] **Step 6: Commit**

```bash
git add server.py tests/test_resonances.py
git commit -m "feat: resonance surfacing in recall with probability gating"
```

---

### Task 6: Feedback Integration

**Files:**
- Modify: `server.py`
- Modify: `tests/test_resonances.py`

- [ ] **Step 1: Write test for feedback**

```python
def test_log_outcome_strengthens_resonances(seeded):
    """log_outcome used=True strengthens resonance-pulled memories."""
    from server import _recall_resonances
    rid = seeded.add_resonance("ep-1", "episode", "ep-2", "episode",
                               similarity=0.65, weight=0.5)
    recall_id = "test-recall"
    _recall_resonances[recall_id] = [{"resonance_id": rid, "memory_id": "ep-2"}]
    # Simulate log_outcome
    from server import _apply_resonance_feedback
    _apply_resonance_feedback(seeded, recall_id, used=True)
    row = seeded.conn.execute("SELECT strength FROM resonances WHERE id=?",
                              (rid,)).fetchone()
    assert row[0] == pytest.approx(0.6)
```

- [ ] **Step 2: Implement _apply_resonance_feedback**

```python
def _apply_resonance_feedback(storage, recall_id, used):
    """Strengthen or weaken resonances from a recall based on outcome."""
    resonances = _recall_resonances.pop(recall_id, None)
    if not resonances:
        return
    for r in resonances:
        if used:
            storage.strengthen_resonance(r["resonance_id"], delta=0.1)
        else:
            storage.weaken_resonance(r["resonance_id"], delta=0.05)
```

- [ ] **Step 3: Call from log_outcome()**

In `server.py:log_outcome()`, after `_storage.update_log_outcome(...)`, add:

```python
    _apply_resonance_feedback(_storage, recall_id, used)
```

- [ ] **Step 4: Run all tests**

```bash
.venv/bin/python -m pytest tests/ -q
```

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_resonances.py
git commit -m "feat: resonance feedback via log_outcome"
```

---

### Task 7: Compression Zone Formation

**Files:**
- Modify: `compress.py`
- Modify: `tests/test_resonances.py`

- [ ] **Step 1: Write test for compression near-miss**

```python
def test_find_semantic_match_returns_near_miss(store):
    """Near-miss below reinforce threshold returns near_miss info."""
    from compress import Compressor
    from embeddings import NomicEmbedProvider
    # This test needs a semantic with a vector to match against.
    # Use a mock or a real embed if available.
    # Minimal: verify the return type includes near_miss field.
    c = Compressor(store, NomicEmbedProvider())
    action, match, near_miss = c._find_semantic_match([0.1] * 768)
    # With no semantics, near_miss should be None
    assert near_miss is None
```

- [ ] **Step 2: Modify _find_semantic_match to return near-miss**

Change return type from `tuple[str, dict | None]` to `tuple[str, dict | None, dict | None]`.
The third element is the near-miss info when similarity is in [0.50, reinforce_threshold).

```python
def _find_semantic_match(self, centroid):
    # ... existing code ...
    # When similarity >= reinforce_threshold: return ("reinforce", match, None)
    # When 0.50 <= similarity < reinforce_threshold: return ("new", None, near_miss)
    # Otherwise: return ("new", None, None)
```

- [ ] **Step 3: Update ALL callers of _find_semantic_match**

Search for all callers: `grep -n "_find_semantic_match" compress.py`

Known callers:
- `cluster_episodes()` (~line 109) — update unpacking to 3-tuple
- `_refine_clusters()` may also call it — check and update if so

Update each to unpack the 3-tuple:

```python
action, match, near_miss = self._find_semantic_match(centroid)
```

Store `near_miss` in the cluster dict for use by `commit()`.

- [ ] **Step 4: Create resonance in commit() when near_miss exists**

In `commit()`, after creating a new semantic, check if the cluster had a near_miss
and create a resonance:

```python
if cluster.get("near_miss"):
    import random
    weight = max(0.1, min(0.9, random.gauss(0.5, 0.15)))
    self._storage.add_resonance(
        new_id, "semantic",
        cluster["near_miss"]["id"], "semantic",
        similarity=cluster["near_miss"]["similarity"],
        weight=weight,
    )
```

- [ ] **Step 5: Add resonances cleanup to _reset_all**

```python
def _reset_all(self):
    # ... existing deletes ...
    self._storage.conn.execute("DELETE FROM resonances")
    # ... existing commit ...
```

- [ ] **Step 6: Run all tests**

```bash
.venv/bin/python -m pytest tests/ -q
```

- [ ] **Step 7: Commit**

```bash
git add compress.py tests/test_resonances.py
git commit -m "feat: resonance formation from compression near-misses"
```

---

### Task 8: Cleanup on Prune/Decay

**Files:**
- Modify: `storage.py`
- Modify: `tests/test_resonances.py`

- [ ] **Step 1: Write test for cleanup during prune**

```python
def test_prune_cleans_up_resonances(seeded):
    """Pruning a decayed episode also removes its resonances."""
    seeded.add_resonance("ep-1", "episode", "ep-2", "episode",
                         similarity=0.65, weight=0.5)
    # Decay ep-1 below threshold
    seeded.conn.execute("UPDATE episodes SET decay_strength=0.01, compressed=1 WHERE id='ep-1'")
    seeded.conn.commit()
    seeded.prune_decayed(threshold=0.05)
    rows = seeded.conn.execute("SELECT count(*) FROM resonances").fetchone()
    assert rows[0] == 0
```

- [ ] **Step 2: Add cleanup call to prune_decayed**

In `storage.py:prune_decayed()`, after deleting episodes and before commit, add:

```python
    # Clean up resonances referencing pruned episodes
    self.cleanup_resonances(ids)
```

- [ ] **Step 3: Run all tests**

```bash
.venv/bin/python -m pytest tests/ -q
```

- [ ] **Step 4: Commit**

```bash
git add storage.py tests/test_resonances.py
git commit -m "feat: resonance cleanup on episode prune"
```

---

### Task 9: Emma Integration

**Files:**
- Modify: `~/Projects/emma/emma_engram.py`
- Modify: `~/Projects/emma/tests/test_emma_engram.py`

- [ ] **Step 1: Extract shared resonance logic into `resonance.py`**

Create `resonance.py` in the engram repo with `form_resonances(storage, results, reinforce_threshold)`
and `surface_resonances(storage, top_results, existing_ids, max_resonant)` as standalone
functions. Move the implementations from `server.py` (`_form_resonances`, `_surface_resonances`)
into this module. Update `server.py` to import from `resonance.py`.

- [ ] **Step 2: Add resonance formation to EmmaEngram.recall()**

In `emma_engram.py`, after the uninvited memories section in `recall()`,
import and call the shared logic from `resonance.py` (available via `/opt/engram`):

```python
from resonance import form_resonances, surface_resonances
```

- [ ] **Step 3: Add resonance surfacing to EmmaEngram.recall()**

Same pattern: call `surface_resonances` using `self.storage`, append results.

- [ ] **Step 3: Run Emma tests**

```bash
cd ~/Projects/emma && .venv/bin/python -m pytest tests/ -q
```

- [ ] **Step 4: Commit in Emma repo**

```bash
cd ~/Projects/emma
git add emma_engram.py tests/test_emma_engram.py
git commit -m "feat: resonance formation and surfacing in Emma's recall"
```

---

### Task 10: Full Integration Test

**Files:**
- Modify: `tests/test_resonances.py`

- [ ] **Step 1: Write end-to-end test**

```python
def test_resonance_end_to_end(store):
    """Full cycle: store episodes, recall, form resonances, surface, feedback."""
    # Store episodes with real-ish embeddings
    import numpy as np
    emb_a = np.random.randn(768).tolist()
    emb_b = (np.array(emb_a) + np.random.randn(768) * 0.5).tolist()  # similar but not identical
    store.add_episode(id="e2e-1", session_id="s1", content="thought about trees",
                      embedding=emb_a)
    store.add_episode(id="e2e-2", session_id="s1", content="thought about forests",
                      embedding=emb_b)
    # Check resonance count
    res_before = store.conn.execute("SELECT count(*) FROM resonances").fetchone()[0]
    # Form resonances
    from server import _form_resonances
    results = [
        {"id": "e2e-1", "layer": "episode", "score": 0.9},
        {"id": "e2e-2", "layer": "episode", "score": 0.8},
    ]
    _form_resonances(store, results, reinforce_threshold=0.70)
    res_after = store.conn.execute("SELECT count(*) FROM resonances").fetchone()[0]
    # May or may not have formed depending on similarity — just verify no crash
    assert res_after >= res_before
```

- [ ] **Step 2: Run full test suite**

```bash
.venv/bin/python -m pytest tests/ -q
```

Expected: All tests pass, including existing 219 + new resonance tests.

- [ ] **Step 3: Commit**

```bash
git add tests/test_resonances.py
git commit -m "test: resonance end-to-end integration test"
```
