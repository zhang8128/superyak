# HOLA Write-Time Innovation → Core-Promotion Gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record a write-time "innovation" score on each episode (its distance from the compressed semantic layer) and use it to decline core-promotion of episodes the semantic layer already covers.

**Architecture:** A new nullable `episodes.innovation` column, populated inside `Storage.add_episode` from a same-lane nearest-semantic lookup (frozen at write time). The existing compress-time core-promotion (compress.py) gains a second decline condition gated by `CompressionConfig.core_innovation_floor`. A distribution readout is exposed via `reflect(focus="persistence")` for tuning the floor. Recall is untouched.

**Tech Stack:** Python 3, SQLite + sqlite-vec (vec0), numpy, pytest. Spec: `docs/superpowers/specs/2026-07-07-hola-innovation-design.md`.

## Global Constraints

- Innovation is measured against **same-lane semantics only** (a personal episode ignores work semantics — the lane firewall must not leak into an identity decision).
- Innovation is **frozen at write time**; never recompute it at compress time (a centroid-nearest episode would look low-innovation against the semantic it helped create).
- **NULL innovation = "no signal"** (cold start / pre-migration rows). Treat NULL as "gate does not fire." **No backfill.**
- The gate can only ever **subtract** a promotion that would happen today; it never adds one. Net core-count effect ≤ 0.
- `core_innovation_floor` default is **0.05**, runs **unconditionally** (NOT behind `[persistence] enabled`); **0.0 disables** the gate and reproduces current behavior exactly.
- Do **not** modify the recall path (`_apply_recall_bias` and its global blur stay as-is).
- Embeddings are 768-dim. Run tests with `.venv/bin/python -m pytest`.

---

## File Structure

- `migrations/022_hola_innovation.sql` — **create** — adds the `innovation` column.
- `storage.py` — **modify** — add `Storage.compute_innovation`; populate innovation in `add_episode`.
- `config.py` — **modify** — add `CompressionConfig.core_innovation_floor`.
- `compress.py` — **modify** — add module-level `_innovation_permits_core`; wire it into the core-promotion block (compress.py:518–529).
- `persistence.py` — **modify** — add `innovation_distribution(storage)`.
- `reflection.py` — **modify** — surface innovation distribution in `analyze_persistence`.
- `tests/test_innovation.py` — **create** — all new tests live together.

---

### Task 1: Migration — add the `innovation` column

**Files:**
- Create: `migrations/022_hola_innovation.sql`
- Test: `tests/test_innovation.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `episodes.innovation` (nullable `REAL`) on any DB opened by `Storage`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_innovation.py`:

```python
from pathlib import Path
import struct

from storage import Storage


def _vec(i, dim=768):
    """Unit basis vector with a 1 at index i."""
    v = [0.0] * dim
    v[i] = 1.0
    return v


def _mk(tmp_path):
    return Storage(str(tmp_path / "graph.db"))


def test_migration_adds_innovation_column(tmp_path):
    s = _mk(tmp_path)
    cols = {r[1] for r in s.conn.execute("PRAGMA table_info(episodes)").fetchall()}
    assert "innovation" in cols
    s.conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_innovation.py::test_migration_adds_innovation_column -v`
Expected: FAIL — `assert 'innovation' in cols` (column absent).

- [ ] **Step 3: Create the migration**

Create `migrations/022_hola_innovation.sql`:

```sql
-- 022: HOLA write-time innovation — per-episode distance from the compressed
-- (semantic) layer at write time. Feeds the compress-time core-promotion gate.
-- NULL = no signal (cold start / pre-migration). Spec:
-- docs/superpowers/specs/2026-07-07-hola-innovation-design.md
ALTER TABLE episodes ADD COLUMN innovation REAL;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_innovation.py::test_migration_adds_innovation_column -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add migrations/022_hola_innovation.sql tests/test_innovation.py
git commit -m "feat(hola): add episodes.innovation column (migration 022)"
```

---

### Task 2: Compute and persist innovation at write time

**Files:**
- Modify: `storage.py` (add `compute_innovation`; edit `add_episode` at storage.py:354–383)
- Test: `tests/test_innovation.py`

**Interfaces:**
- Consumes: `episodes.innovation` column (Task 1); `_pack_embedding`, `struct` (already imported in storage.py).
- Produces: `Storage.compute_innovation(embedding: list[float], lane: str = "personal") -> float | None`; `add_episode` now stores innovation for every write with an embedding.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_innovation.py`:

```python
def test_compute_innovation_none_without_semantics(tmp_path):
    s = _mk(tmp_path)
    assert s.compute_innovation(_vec(0), lane="personal") is None
    s.conn.close()


def test_compute_innovation_zero_for_duplicate(tmp_path):
    s = _mk(tmp_path)
    s.add_semantic(id="s1", content="a fact about x", kind="fact",
                   confidence=0.8, embedding=_vec(0), source_episode_ids=[])
    innov = s.compute_innovation(_vec(0), lane="personal")
    assert innov is not None and innov < 1e-6
    s.conn.close()


def test_compute_innovation_high_for_novel(tmp_path):
    s = _mk(tmp_path)
    s.add_semantic(id="s1", content="a fact about x", kind="fact",
                   confidence=0.8, embedding=_vec(0), source_episode_ids=[])
    innov = s.compute_innovation(_vec(1), lane="personal")
    assert innov is not None and innov > 0.99
    s.conn.close()


def test_add_episode_persists_innovation(tmp_path):
    s = _mk(tmp_path)
    s.add_semantic(id="s1", content="a fact about x", kind="fact",
                   confidence=0.8, embedding=_vec(0), source_episode_ids=[])
    s.add_episode(id="e1", session_id=None, content="episode content here",
                  embedding=_vec(0), lane="personal")
    row = s.conn.execute("SELECT innovation FROM episodes WHERE id='e1'").fetchone()
    assert row[0] is not None and row[0] < 1e-6
    s.conn.close()


def test_add_episode_innovation_null_cold_start(tmp_path):
    s = _mk(tmp_path)
    s.add_episode(id="e1", session_id=None, content="episode content here",
                  embedding=_vec(0), lane="personal")
    row = s.conn.execute("SELECT innovation FROM episodes WHERE id='e1'").fetchone()
    assert row[0] is None
    s.conn.close()


def test_innovation_is_lane_pure(tmp_path):
    s = _mk(tmp_path)
    # Only a WORK semantic exists.
    s.add_semantic(id="s1", content="a work fact", kind="fact",
                   confidence=0.8, embedding=_vec(0),
                   source_episode_ids=[], lane="work")
    # A personal episode identical to that work semantic still sees no
    # personal semantics -> None (work never feeds personal identity).
    assert s.compute_innovation(_vec(0), lane="personal") is None
    s.conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_innovation.py -k "innovation and not migration" -v`
Expected: FAIL — `AttributeError: 'Storage' object has no attribute 'compute_innovation'`.

- [ ] **Step 3: Add `compute_innovation` to `storage.py`**

Add this method to the `Storage` class (place it directly above `add_episode` at storage.py:354):

```python
    def compute_innovation(self, embedding: list[float], lane: str = "personal") -> float | None:
        """Write-time innovation: 1 − max cosine similarity to same-lane semantics.

        HOLA's ‖e‖ analog — how poorly the compressed (semantic) layer of this
        lane can reconstruct the episode. Returns None when the lane has no
        semantics (cold start): NULL means 'no signal', not 'maximally novel'.
        Same-lane only: core promotion is a personal-identity decision, so a
        personal episode must never be measured against work semantics.
        """
        import numpy as np
        rows = self.conn.execute(
            "SELECT sv.embedding FROM semantic_vectors sv "
            "JOIN semantics s ON s.id = sv.id WHERE s.lane = ?",
            (lane,),
        ).fetchall()
        if not rows:
            return None
        C = np.array(
            [struct.unpack(f"<{len(r[0]) // 4}f", r[0]) for r in rows],
            dtype=np.float64,
        )
        C = C / (np.linalg.norm(C, axis=1, keepdims=True) + 1e-12)
        v = np.asarray(embedding, dtype=np.float64)
        v = v / (np.linalg.norm(v) + 1e-12)
        max_sim = float(np.clip((C @ v).max(), 0.0, 1.0))
        return 1.0 - max_sim
```

- [ ] **Step 4: Populate innovation in `add_episode`**

In `add_episode` (storage.py:354–370), compute innovation from the embedding and lane, then include it in the INSERT. Replace the body up to and including the episodes INSERT:

Existing (storage.py:365–370):

```python
        now = _now_iso()
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        self.conn.execute(
            "INSERT INTO episodes (id, session_id, content, episode_type, context, created_at, content_hash, lane) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (id, session_id, content, episode_type, json.dumps(context) if context is not None else None, now, content_hash, lane),
        )
```

Replace with:

```python
        now = _now_iso()
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        innovation = (
            self.compute_innovation(embedding, lane) if embedding is not None else None
        )
        self.conn.execute(
            "INSERT INTO episodes (id, session_id, content, episode_type, context, created_at, content_hash, lane, innovation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (id, session_id, content, episode_type, json.dumps(context) if context is not None else None, now, content_hash, lane, innovation),
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_innovation.py -k "innovation and not migration" -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add storage.py tests/test_innovation.py
git commit -m "feat(hola): compute write-time innovation in add_episode (same-lane)"
```

---

### Task 3: Config floor + compress-time promotion gate

**Files:**
- Modify: `config.py` (`CompressionConfig` at config.py:40–44)
- Modify: `compress.py` (add module-level `_innovation_permits_core`; edit the promotion block at compress.py:518–529)
- Test: `tests/test_innovation.py`

**Interfaces:**
- Consumes: `episodes.innovation` (Task 1/2); `self._config` (a `CompressionConfig`) and `self._storage.get_episode` (returns a dict including `innovation`) inside `Compressor`.
- Produces: `CompressionConfig.core_innovation_floor: float = 0.05`; module function `compress._innovation_permits_core(innovation: float | None, floor: float) -> bool`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_innovation.py`:

```python
def test_config_default_floor():
    from config import CompressionConfig
    assert CompressionConfig().core_innovation_floor == 0.05


def test_gate_null_innovation_permits():
    from compress import _innovation_permits_core
    assert _innovation_permits_core(None, 0.05) is True


def test_gate_floor_zero_permits_everything():
    from compress import _innovation_permits_core
    assert _innovation_permits_core(0.0, 0.0) is True
    assert _innovation_permits_core(0.001, 0.0) is True


def test_gate_declines_below_floor():
    from compress import _innovation_permits_core
    assert _innovation_permits_core(0.02, 0.05) is False


def test_gate_permits_at_or_above_floor():
    from compress import _innovation_permits_core
    assert _innovation_permits_core(0.05, 0.05) is True
    assert _innovation_permits_core(0.9, 0.05) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_innovation.py -k "config_default_floor or gate_" -v`
Expected: FAIL — `AttributeError` on `core_innovation_floor` / `ImportError` for `_innovation_permits_core`.

- [ ] **Step 3: Add the config field**

In `config.py`, `CompressionConfig` (config.py:40–44), add the field:

```python
@dataclass
class CompressionConfig:
    auto_threshold: int = 10
    cluster_similarity: float = 0.75
    reinforce_threshold: float = 0.70
    instinct_confidence: float = 0.75
    core_innovation_floor: float = 0.05
```

- [ ] **Step 4: Add the gate helper to `compress.py`**

Add at module level in `compress.py` (near the top, after imports):

```python
def _innovation_permits_core(innovation: float | None, floor: float) -> bool:
    """Core-promotion gate. An episode already well-predicted by the semantic
    layer at write time (low innovation) adds no coverage by becoming
    decay-exempt — the semantic already holds it. NULL innovation (cold start /
    pre-migration) and floor <= 0 mean the gate does not fire."""
    if innovation is None or floor <= 0.0:
        return True
    return innovation >= floor
```

- [ ] **Step 5: Wire the gate into the promotion block**

In `compress.py`, replace the promotion block (compress.py:518–529):

Existing:

```python
                if lane != "work" and centroid is not None and source_ids:
                    centroid_nearest = self._find_centroid_nearest_id(
                        cluster["episodes"], centroid, source_ids,
                    )
                    if centroid_nearest:
                        from persistence import core_promotion_allowed
                        if core_promotion_allowed(self._storage, centroid_nearest,
                                                  self._persistence):
                            self._storage.mark_core(centroid_nearest)
                        else:
                            logger.info("core promotion declined (redundant vs core"
                                        " set): %s", centroid_nearest)
```

Replace with:

```python
                if lane != "work" and centroid is not None and source_ids:
                    centroid_nearest = self._find_centroid_nearest_id(
                        cluster["episodes"], centroid, source_ids,
                    )
                    if centroid_nearest:
                        from persistence import core_promotion_allowed
                        ep = self._storage.get_episode(centroid_nearest)
                        innovation = ep.get("innovation") if ep else None
                        floor = (self._config.core_innovation_floor
                                 if self._config else 0.0)
                        if not _innovation_permits_core(innovation, floor):
                            logger.info("core promotion declined (low innovation"
                                        " %.3f < floor %.3f): %s",
                                        innovation, floor, centroid_nearest)
                        elif core_promotion_allowed(self._storage, centroid_nearest,
                                                    self._persistence):
                            self._storage.mark_core(centroid_nearest)
                        else:
                            logger.info("core promotion declined (redundant vs core"
                                        " set): %s", centroid_nearest)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_innovation.py -k "config_default_floor or gate_" -v`
Expected: PASS (5 tests).

- [ ] **Step 7: Commit**

```bash
git add config.py compress.py tests/test_innovation.py
git commit -m "feat(hola): decline core-promotion below innovation floor"
```

---

### Task 4: Surface innovation distribution via reflect

**Files:**
- Modify: `persistence.py` (add `innovation_distribution`)
- Modify: `reflection.py` (`analyze_persistence` at reflection.py:562–576)
- Test: `tests/test_innovation.py`

**Interfaces:**
- Consumes: `episodes.innovation` (Task 1/2); `np` (already imported in persistence.py).
- Produces: `persistence.innovation_distribution(storage) -> dict` with keys `count` and (when count > 0) `mean`, `min`, `max`, `histogram`; surfaced under `reflect(focus="persistence")["persistence"]["innovation"]`.

> **Note (refines spec §5):** the spec mentioned a "count of innovation-declined promotions." A running decline tally would need new persisted state; the distribution readout below satisfies the same intent (tune the floor from evidence) with zero new state, so we ship the distribution only.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_innovation.py`:

```python
def test_innovation_distribution_empty(tmp_path):
    from persistence import innovation_distribution
    s = _mk(tmp_path)
    assert innovation_distribution(s)["count"] == 0
    s.conn.close()


def test_innovation_distribution_stats(tmp_path):
    from persistence import innovation_distribution
    s = _mk(tmp_path)
    for eid, innov in [("e1", 0.2), ("e2", 0.8)]:
        s.conn.execute(
            "INSERT INTO episodes (id, content, created_at, innovation, lane) "
            "VALUES (?, ?, '2026-07-07T00:00:00Z', ?, 'personal')",
            (eid, "content", innov),
        )
    s.conn.execute(
        "INSERT INTO episodes (id, content, created_at, innovation, lane) "
        "VALUES ('e3', 'content', '2026-07-07T00:00:00Z', NULL, 'personal')"
    )
    s.conn.commit()
    d = innovation_distribution(s)
    assert d["count"] == 2
    assert abs(d["mean"] - 0.5) < 1e-6
    assert d["min"] == 0.2 and d["max"] == 0.8
    assert sum(d["histogram"]) == 2
    s.conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_innovation.py -k "distribution" -v`
Expected: FAIL — `ImportError: cannot import name 'innovation_distribution'`.

- [ ] **Step 3: Add `innovation_distribution` to `persistence.py`**

Add at module level in `persistence.py`:

```python
def innovation_distribution(storage) -> dict:
    """Distribution of write-time innovation over episodes, for tuning
    core_innovation_floor from evidence. NULL rows are excluded."""
    rows = storage.conn.execute(
        "SELECT innovation FROM episodes WHERE innovation IS NOT NULL"
    ).fetchall()
    vals = [r[0] for r in rows]
    if not vals:
        return {"count": 0}
    arr = np.array(vals, dtype=np.float64)
    return {
        "count": len(vals),
        "mean": round(float(arr.mean()), 4),
        "min": round(float(arr.min()), 4),
        "max": round(float(arr.max()), 4),
        "histogram": [int(x) for x in np.histogram(arr, bins=5, range=(0.0, 1.0))[0]],
    }
```

- [ ] **Step 4: Surface it in `analyze_persistence`**

In `reflection.py`, edit `analyze_persistence` (reflection.py:565–576) to import and include the distribution:

Change the import (reflection.py:565–567) from:

```python
        from persistence import (audit_unchecked_events, classify_hubs,
                                 compute_scores, evaluate_prune,
                                 flag_redundant_cores)
```

to:

```python
        from persistence import (audit_unchecked_events, classify_hubs,
                                 compute_scores, evaluate_prune,
                                 flag_redundant_cores, innovation_distribution)
```

And add one key to the returned dict (reflection.py:570–576):

```python
        return {
            "enabled": bool(getattr(cfg, "enabled", False)),
            "forgetting_preview": evaluate_prune(self._storage, cfg),
            "hubs": classify_hubs(self._storage, cfg),
            "flagged_cores": flag_redundant_cores(self._storage, cfg),
            "conjunct_audit": audit_unchecked_events(self._storage, cfg),
            "innovation": innovation_distribution(self._storage),
        }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_innovation.py -k "distribution" -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add persistence.py reflection.py tests/test_innovation.py
git commit -m "feat(hola): surface innovation distribution in reflect(persistence)"
```

---

### Task 5: Full-suite regression check

**Files:** none (verification only).

**Interfaces:**
- Consumes: everything above.
- Produces: confidence that no existing behavior regressed.

- [ ] **Step 1: Run the whole test file**

Run: `.venv/bin/python -m pytest tests/test_innovation.py -v`
Expected: PASS (all tasks' tests).

- [ ] **Step 2: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all tests pass (the prior 624 plus the new ones). If any compression test that asserts core-promotion now fails, confirm it seeds episodes whose innovation is NULL (cold-start) or ≥ 0.05 — the gate must not change behavior for NULL innovation. Fix by seeding semantics/innovation appropriately in the test, not by weakening the gate.

- [ ] **Step 3: Commit (only if step 2 required test adjustments)**

```bash
git add -A
git commit -m "test(hola): adjust promotion tests for innovation gate"
```

---

## Self-Review

**1. Spec coverage:**
- Write-time innovation, same-lane, frozen, computed in `add_episode` → Task 2. ✓
- Nullable column + migration + NULL=no-signal + no backfill → Task 1 + Task 2. ✓
- Compress-time gate composing with `core_promotion_allowed`, decline-only → Task 3. ✓
- `core_innovation_floor` in `CompressionConfig`, default 0.05, 0.0 disables, unconditional → Task 3. ✓
- Observability via `reflect(focus="persistence")` → Task 4 (distribution readout; decline-counter dropped, deviation noted). ✓
- Out of scope (recall, cross-rung coordination, new promotion routes, backfill) → none of the tasks touch these. ✓

**2. Placeholder scan:** No TBD/TODO; every code and test step shows complete code and exact commands. ✓

**3. Type consistency:** `compute_innovation(embedding, lane) -> float | None` (Task 2) is consumed by `add_episode` (Task 2) and its stored value read via `get_episode(...).get("innovation")` (Task 3). `_innovation_permits_core(innovation, floor) -> bool` defined and consumed in Task 3. `innovation_distribution(storage) -> dict` defined in Task 4 (persistence.py) and imported in reflection.py Task 4. `CompressionConfig.core_innovation_floor` defined Task 3, read via `self._config` in the same task. Names consistent across tasks. ✓
