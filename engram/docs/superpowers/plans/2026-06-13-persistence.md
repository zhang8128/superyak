# Persistence Layer (Layer 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** H₀ persistence over similarity filtrations — fills the gate's persistence conjunct, adds redundancy/uniqueness/generativity-guarded forgetting on three surfaces, daydream cold surfacing, and read-only persistence diagnostics.

**Architecture:** New `persistence.py` computes single-linkage filtrations exactly via MST (scipy, no new required deps). Consumers: `sheaf.persistence_check` (split band), a guarded prune + decay modulation + core-promotion gate (all behind `[persistence] enabled=false`), `reflect(focus="persistence")` diagnostics (H₁ via optional `ripser`), and an unconditioned cold-storage draw in recall's uninvited slot.

**Tech Stack:** Python, numpy, scipy (`minimum_spanning_tree`), SQLite, optional `ripser` (import-guarded, diagnostics only).

**Spec:** `docs/superpowers/specs/2026-06-13-persistence-design.md`

---

## File structure

| File | Responsibility |
|---|---|
| `migrations/021_persistence.sql` (create) | `persistence_scores` cache table |
| `config.py` (modify) | `PersistenceConfig` + `[persistence]` TOML section |
| `persistence.py` (create) | Filtration math, scores, split band, guarded prune, promotion gate, audit, diagnostics helpers, calibration CLI |
| `sheaf.py` (modify) | `persistence_check` becomes real (band), `Verdict.persistence_band`, `subdivision_test(persistence_cfg=...)` |
| `storage.py` (modify) | `prune_episode_ids` refactor, `apply_decay(exponent_multipliers=...)`, `sample_cold_random`, score-cache accessors |
| `compress.py` (modify) | Core-promotion gate at the `mark_core(centroid_nearest)` site |
| `server.py` (modify) | Sleep step (score refresh), guarded prune switch, decay modulation, cold-uninvited draw, config threading |
| `reflection.py` (modify) | `reflect(focus="persistence")` |
| `tests/test_persistence.py` (create) | Math + scores + band unit tests |
| `tests/test_persistence_forgetting.py` (create) | Prune gate, protections, decay modulation, promotion gate |
| `tests/test_persistence_surfaces.py` (create) | reflect focus, conjunct in sheaf, audit, cold-uninvited |

Verified repo facts the tasks rely on: latest migration is 020; `prune_decayed` (storage.py:513) selects `decay_strength < ? AND compressed = 1 AND core = 0 AND dormant = 0` and moves rows to a sibling `cold.db` via `_cold_storage()`; `apply_decay` (storage.py:439) loops per episode with `core = 0`; core promotion is **already centroid-nearest-only** (compress.py:502–507 → `mark_core`); anchors are singleton rows — identity anchors hold a memory id in `expected` (mirror `get_active_anchors` for the active filter); recall's uninvited block (server.py:1096–1166) appends `"uninvited": True` results before the lane filter; `Reflector.__init__` already takes keyword `cohesion_config`; conftest provides `tmp_db` and `fake_embedding`.

**⚠ scipy MST trap (applies to Tasks 3, 4, 10):** `minimum_spanning_tree` treats 0 entries as "no edge". Duplicate points have distance 0. Always floor off-diagonal distances at `1e-9` before building the MST (`np.maximum(D, 1e-9)` with zero diagonal) — heights read back carry a negligible 1e-9 floor.

---

### Task 1: Migration 021 + storage accessors

**Files:**
- Create: `migrations/021_persistence.sql`
- Modify: `storage.py` (end of Storage class)
- Test: `tests/test_persistence.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the persistence layer — schema, math, scores."""

import json


class TestMigration021:
    def test_table_exists(self, tmp_db):
        names = {r[0] for r in tmp_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "persistence_scores" in names


class TestScoreCache:
    def test_upsert_and_get(self, tmp_db):
        tmp_db.upsert_persistence_scores([
            {"episode_id": "e1", "redundancy": 0.9, "uniqueness": 0.1,
             "generativity": 0.0},
            {"episode_id": "e2", "redundancy": 0.2, "uniqueness": 0.8,
             "generativity": 1.5},
        ])
        scores = tmp_db.get_persistence_scores()
        assert scores["e1"]["redundancy"] == 0.9
        assert scores["e2"]["generativity"] == 1.5
        # upsert replaces
        tmp_db.upsert_persistence_scores([
            {"episode_id": "e1", "redundancy": 0.5, "uniqueness": 0.5,
             "generativity": 0.5}])
        assert tmp_db.get_persistence_scores()["e1"]["redundancy"] == 0.5
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_persistence.py -v`
Expected: FAIL — table missing / `AttributeError: upsert_persistence_scores`

- [ ] **Step 3: Write the migration**

```sql
-- 021: persistence (Layer 4) — per-episode score cache for previews.
-- Decisions recompute live; this cache feeds reflect(focus="persistence").
-- Spec: docs/superpowers/specs/2026-06-13-persistence-design.md
CREATE TABLE IF NOT EXISTS persistence_scores (
    episode_id TEXT PRIMARY KEY,
    redundancy REAL NOT NULL,
    uniqueness REAL NOT NULL,
    generativity REAL NOT NULL,
    computed_at TEXT NOT NULL
);
```

- [ ] **Step 4: Add storage methods** (end of Storage class, same idioms as the sheaf accessors above them)

```python
# --- Persistence (migration 021) -----------------------------------------

def upsert_persistence_scores(self, scores: list[dict]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    self.conn.executemany(
        "INSERT OR REPLACE INTO persistence_scores"
        " (episode_id, redundancy, uniqueness, generativity, computed_at)"
        " VALUES (?, ?, ?, ?, ?)",
        [(s["episode_id"], s["redundancy"], s["uniqueness"],
          s["generativity"], now) for s in scores],
    )
    self.conn.commit()

def get_persistence_scores(self) -> dict[str, dict]:
    rows = self.conn.execute("SELECT * FROM persistence_scores").fetchall()
    return {r["episode_id"]: dict(r) for r in rows}
```

- [ ] **Step 5: Run tests (PASS), then full suite** `.venv/bin/python -m pytest tests/ -q` (584 currently) → all pass

- [ ] **Step 6: Commit**

```bash
git add migrations/021_persistence.sql storage.py tests/test_persistence.py
git commit -m "feat(persistence): migration 021 — score cache table + accessors"
```

---

### Task 2: PersistenceConfig

**Files:**
- Modify: `config.py`
- Test: `tests/test_persistence.py` (append)

- [ ] **Step 1: Write the failing test**

```python
from config import load_config


class TestPersistenceConfig:
    def test_defaults(self, tmp_path):
        cfg = load_config(tmp_path)
        p = cfg.persistence
        assert p.enabled is False
        assert p.min_split_band == 0.10
        assert p.redundancy_floor == 0.85
        assert p.protect_threshold == 0.6
        assert p.generativity_threshold == 0.0
        assert p.cold_uninvited_p == 0.05

    def test_toml_override(self, tmp_path):
        (tmp_path / ".engram").mkdir()
        (tmp_path / ".engram" / "config.toml").write_text(
            "[persistence]\nenabled = true\nredundancy_floor = 0.7\n")
        cfg = load_config(tmp_path)
        assert cfg.persistence.enabled is True
        assert cfg.persistence.redundancy_floor == 0.7
```

- [ ] **Step 2: Run to verify failure** — `AttributeError: 'EngramConfig' object has no attribute 'persistence'`

- [ ] **Step 3: Implement** (mirror CohesionConfig exactly — dataclass after it, field in EngramConfig, `persistence=PersistenceConfig(**raw.get("persistence", {})),` in load_config, section appended to `_DEFAULT_TOML`)

```python
@dataclass
class PersistenceConfig:
    # forgetting stays inert until read-only calibration clears it (spec)
    enabled: bool = False
    min_split_band: float = 0.10
    redundancy_floor: float = 0.85
    protect_threshold: float = 0.6
    generativity_threshold: float = 0.0  # 0 disables until calibrated
    cold_uninvited_p: float = 0.05
```

```toml
[persistence]
enabled = false
min_split_band = 0.10
redundancy_floor = 0.85
protect_threshold = 0.6
generativity_threshold = 0.0
cold_uninvited_p = 0.05
```

- [ ] **Step 4: Run tests (PASS), full suite** → all pass

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_persistence.py
git commit -m "feat(persistence): [persistence] config section"
```

---

### Task 3: persistence.py — filtration core

**Files:**
- Create: `persistence.py`
- Test: `tests/test_persistence.py` (append)

The math: distance `d = 1 − cos` on L2-normalized embeddings. One MST = the single-linkage filtration. Per-point **redundancy** = `1 − nn_distance` (clipped to [0,1]). Per-point **uniqueness**: process MST edges ascending with union-find (union by size); when two components merge, the smaller component's *carrier point* dies at that height (of two near-duplicates, one dies at ≈0 — redundant — and the survivor carries on — irreplaceable). `uniqueness = min(death, max_height) / max_height`; the final survivor gets 1.0. **Split band** for two parts: `(h_cross − max(h_internal)) / h_max` where `h_cross` = min inter-part distance, `h_internal` = a part's own max MST merge height, `h_max` = the whole neighborhood's max merge height. Negative or tiny band = flicker.

- [ ] **Step 1: Write the failing tests** (append)

```python
import numpy as np

import persistence


def _cluster(axis: int, n: int, noise: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    c = np.zeros(768); c[axis] = 1.0
    return c + noise * rng.standard_normal((n, 768))


class TestFiltration:
    def test_duplicate_pair_one_redundant_one_carrier(self):
        base = _cluster(0, 1, 0.0, 1)[0]
        far = np.zeros(768); far[1] = 1.0
        X = np.vstack([base, base + 1e-6, far, far + 0.3 * _cluster(1, 1, 1.0, 2)[0] * 0])
        # points 0,1 are near-duplicates; 2,3 give the filtration room
        f = persistence.build_filtration(X)
        red = persistence.redundancy(f)
        uniq = persistence.uniqueness(f)
        assert red[0] > 0.99 and red[1] > 0.99      # both covered by the other
        assert min(uniq[0], uniq[1]) < 0.05          # one lineage dies instantly
        assert max(uniq[0], uniq[1]) > 0.5           # the carrier persists

    def test_isolated_point_is_unique_not_redundant(self):
        X = np.vstack([_cluster(0, 8, 0.03, 3), _cluster(5, 1, 0.0, 4)])
        f = persistence.build_filtration(X)
        red = persistence.redundancy(f)
        uniq = persistence.uniqueness(f)
        assert red[8] < 0.3
        assert uniq[8] > 0.9

    def test_tiny_inputs(self):
        f0 = persistence.build_filtration(np.zeros((0, 768)))
        assert f0.n == 0
        f1 = persistence.build_filtration(_cluster(0, 1, 0.0, 5))
        assert persistence.uniqueness(f1)[0] == 1.0
        assert persistence.redundancy(f1)[0] == 0.0   # nothing covers it


class TestSplitBand:
    def test_separated_parts_have_wide_band(self):
        a = _cluster(0, 8, 0.03, 6)
        b = _cluster(1, 8, 0.03, 7)
        X = np.vstack([a, b])
        band = persistence.split_band(X, list(range(8)), list(range(8, 16)))
        assert band > 0.3

    def test_arbitrary_cut_of_one_cluster_has_no_band(self):
        X = _cluster(0, 16, 0.05, 8)
        band = persistence.split_band(X, list(range(8)), list(range(8, 16)))
        assert band < 0.05
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError: No module named 'persistence'`

- [ ] **Step 3: Implement `persistence.py`**

```python
"""Persistence (Layer 4) — H0 persistence over similarity filtrations.

Single-linkage filtration computed exactly via MST. One tree yields merge
heights, per-point redundancy (nearest-neighbor coverage), per-point
uniqueness (lineage survival across scales), and split persistence bands
for the subdivision gate's middle conjunct.

Spec: docs/superpowers/specs/2026-06-13-persistence-design.md
"""

import json
import logging
import struct
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import minimum_spanning_tree

logger = logging.getLogger(__name__)

_EPS = 1e-12
_MST_FLOOR = 1e-9  # scipy MST treats 0 as "no edge"; duplicates have d=0


def _unpack_embedding(blob: bytes) -> np.ndarray:
    return np.array(struct.unpack(f"<{len(blob) // 4}f", blob), dtype=np.float64)


def distance_matrix(X) -> np.ndarray:
    X = np.asarray(X, dtype=np.float64)
    Xn = X / (np.linalg.norm(X, axis=1, keepdims=True) + _EPS)
    D = 1.0 - Xn @ Xn.T
    np.fill_diagonal(D, 0.0)
    return np.maximum(D, 0.0)


def _mst_edges(D: np.ndarray) -> list[tuple[float, int, int]]:
    floored = np.maximum(D, _MST_FLOOR)
    np.fill_diagonal(floored, 0.0)
    t = minimum_spanning_tree(csr_matrix(floored)).tocoo()
    edges = sorted(zip(t.data.tolist(), t.row.tolist(), t.col.tolist()))
    return [(float(h), int(i), int(j)) for h, i, j in edges]


@dataclass
class Filtration:
    n: int
    nn_dist: np.ndarray   # per-point nearest-neighbor distance
    death: np.ndarray     # per-point lineage death height (inf = survivor)
    max_height: float     # final merge height of the whole set


def build_filtration(X) -> Filtration:
    n = len(X)
    if n == 0:
        return Filtration(0, np.zeros(0), np.zeros(0), 0.0)
    if n == 1:
        return Filtration(1, np.array([1.0]), np.array([np.inf]), 0.0)
    D = distance_matrix(X)
    off = D + np.diag(np.full(n, np.inf))
    nn = off.min(axis=1)
    edges = _mst_edges(D)
    death = np.full(n, np.inf)
    parent = list(range(n))
    size = [1] * n
    carrier = list(range(n))  # the point whose lineage the component carries

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for h, i, j in edges:
        ri, rj = find(i), find(j)
        if ri == rj:
            continue
        if size[ri] < size[rj]:
            ri, rj = rj, ri
        death[carrier[rj]] = h  # smaller component's lineage dies
        parent[rj] = ri
        size[ri] += size[rj]
    max_height = edges[-1][0] if edges else 0.0
    return Filtration(n, nn, death, max_height)


def redundancy(f: Filtration) -> np.ndarray:
    """1 - nn_distance, clipped to [0,1]: how completely neighbors cover it."""
    if f.n == 0:
        return np.zeros(0)
    if f.n == 1:
        return np.zeros(1)
    return np.clip(1.0 - f.nn_dist, 0.0, 1.0)


def uniqueness(f: Filtration) -> np.ndarray:
    """Normalized lineage persistence: how long it resists merging."""
    if f.n == 0:
        return np.zeros(0)
    if f.n == 1 or f.max_height <= _MST_FLOOR:
        return np.ones(f.n)
    return np.clip(np.minimum(f.death, f.max_height) / f.max_height, 0.0, 1.0)


def split_band(X, part_a: list[int], part_b: list[int]) -> float:
    """Persistence band of a proposed two-part split, normalized by the
    neighborhood's total merge range. <=0 means the parts interleave."""
    D = distance_matrix(X)
    h_cross = float(D[np.ix_(part_a, part_b)].min())

    def coalescence(idx):
        if len(idx) < 2:
            return 0.0
        edges = _mst_edges(D[np.ix_(idx, idx)])
        return edges[-1][0] if edges else 0.0

    h_int = max(coalescence(part_a), coalescence(part_b))
    full = _mst_edges(D)
    h_max = full[-1][0] if full else _EPS
    return float((h_cross - h_int) / max(h_max, _EPS))
```

- [ ] **Step 4: Run tests (PASS), full suite** → all pass

- [ ] **Step 5: Commit**

```bash
git add persistence.py tests/test_persistence.py
git commit -m "feat(persistence): filtration core — redundancy, uniqueness, split band"
```

---

### Task 4: the gate conjunct goes live in sheaf.py

**Files:**
- Modify: `sheaf.py` (`persistence_check`, `Verdict`, `subdivision_test`), call sites in `compress.py` and `sheaf.run_sleep_pass`, `server.py` config threading
- Test: `tests/test_persistence_surfaces.py` (create)

Behavior: `subdivision_test` gains keyword `persistence_cfg=None`. When None or `enabled=False` → exactly today's behavior (`persistence_checked=False`, conjunct vacuously true). When enabled → compute `split_band` on the assigned parts; conjunct passes iff `band >= persistence_cfg.min_split_band`; verdict records `persistence_checked=True` and `persistence_band`. `Verdict` gains field `persistence_band: float | None = None` (with default — existing constructors unaffected). The executor writes the verdict's `persistence_checked` into the event row as it already does. Call sites: the compress gate and `run_sleep_pass` pass `persistence_cfg` (threaded from server via a new `Compressor(persistence_config=...)` param and a new `run_sleep_pass(..., persistence_cfg=None)` keyword).

- [ ] **Step 1: Write the failing tests**

```python
"""Persistence surfaces: gate conjunct, audit, reflect, cold-uninvited."""

import numpy as np

import sheaf
from config import PersistenceConfig


def _two_orthogonal(n_per: int = 10, noise: float = 0.05):
    a = np.zeros(768); a[0] = 1.0
    b = np.zeros(768); b[1] = 1.0
    rng1, rng2 = np.random.default_rng(1), np.random.default_rng(2)
    X = np.vstack([a + noise * rng1.standard_normal((n_per, 768)),
                   b + noise * rng2.standard_normal((n_per, 768))])
    return [f"e{i}" for i in range(2 * n_per)], X


class TestGateConjunct:
    def test_disabled_behaves_like_stub(self):
        ids, X = _two_orthogonal()
        v = sheaf.subdivision_test("s1", ids, X, dl_cost=0.15)
        assert v.persistence_checked is False
        assert v.persistence_band is None
        assert v.split is True

    def test_enabled_records_band_and_passes_clean_split(self):
        ids, X = _two_orthogonal()
        cfg = PersistenceConfig(enabled=True)
        v = sheaf.subdivision_test("s1", ids, X, dl_cost=0.15,
                                   persistence_cfg=cfg)
        assert v.persistence_checked is True
        assert v.persistence_band is not None and v.persistence_band > 0.10
        assert v.split is True

    def test_enabled_blocks_flicker(self):
        # one blob, but force the gate's energy conjunct to pass by using a
        # tiny dl_cost: the persistence conjunct must be the one that blocks
        rng = np.random.default_rng(9)
        a = np.zeros(768); a[0] = 1.0
        X = a + 0.3 * rng.standard_normal((16, 768))
        ids = [f"e{i}" for i in range(16)]
        cfg = PersistenceConfig(enabled=True)
        v = sheaf.subdivision_test("s1", ids, X, dl_cost=0.0001,
                                   persistence_cfg=cfg)
        if v.parts:  # only meaningful when a partition was proposed
            assert v.persistence_checked is True
            if v.gain > 0.0001:          # energy conjunct passed
                assert v.split is (v.persistence_band >= cfg.min_split_band)
```

- [ ] **Step 2: Run to verify failure** — `TypeError: unexpected keyword argument 'persistence_cfg'`

- [ ] **Step 3: Implement in sheaf.py**

Add to Verdict (after `worst_edges`): `persistence_band: float | None = None`, and include `"persistence_band": self.persistence_band` in `to_dict()`.

Replace the stub:

```python
def persistence_check(parts_idx: list[list[int]], X: np.ndarray,
                      persistence_cfg) -> tuple[bool, bool, float | None]:
    """Layer 4 conjunct: does the split survive across filtration scales?

    Returns (passes, checked, band). Disabled/missing config preserves the
    historical stub behavior: vacuously true, recorded as unchecked.
    """
    if persistence_cfg is None or not getattr(persistence_cfg, "enabled", False):
        return True, False, None
    from persistence import split_band
    band = split_band(X, parts_idx[0], parts_idx[1])
    return band >= persistence_cfg.min_split_band, True, band
```

In `subdivision_test`, add keyword `persistence_cfg=None` and replace the final gate expression:

```python
    p_pass, p_checked, p_band = persistence_check(parts_idx, X, persistence_cfg)
    split = (gain > dl_cost * (len(parts_idx) - 1)) and p_pass
    return Verdict(
        semantic_id, split,
        [[episode_ids[i] for i in pi] for pi in parts_idx],
        [episode_ids[i] for i in idx["amb"]],
        res["energy"], part_energies, gain, dl_cost,
        p_checked, res["worst_edges"], p_band,
    )
```

(Also update the early `no_split` Verdict construction to pass `persistence_band=None` if positional args are used.)

Call sites:
- `run_sleep_pass(storage, embed_fn, framing_cfg, cfg, persistence_cfg=None)` — pass `persistence_cfg=persistence_cfg` into its `subdivision_test` call.
- compress.py gate: `Compressor.__init__` gains `persistence_config=None`, stored `self._persistence`; the gate's `subdivision_test(...)` call adds `persistence_cfg=self._persistence`.
- server.py: pass `persistence_config=_config.persistence` to `Compressor(...)` and `persistence_cfg=_config.persistence` to `run_sleep_pass(...)`.

- [ ] **Step 4: Run new tests + the full sheaf files + full suite** — all pass (existing sheaf tests prove disabled-path byte-compatibility)

- [ ] **Step 5: Commit**

```bash
git add sheaf.py compress.py server.py tests/test_persistence_surfaces.py
git commit -m "feat(persistence): gate conjunct live — split band checked when enabled"
```

---

### Task 5: scores computation + retroactive conjunct audit

**Files:**
- Modify: `persistence.py`
- Test: `tests/test_persistence.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
class TestComputeScores:
    def test_scores_cover_episodes_with_vectors(self, tmp_db, fake_embedding):
        from config import PersistenceConfig
        for i in range(5):
            tmp_db.add_episode(id=f"e{i}", session_id="s", content=f"ep {i}",
                               embedding=fake_embedding())
        tmp_db.add_episode(id="no-vec", session_id="s", content="no vector")
        out = persistence.compute_scores(tmp_db, PersistenceConfig())
        assert set(out) == {f"e{i}" for i in range(5)}   # no-vec excluded
        cached = tmp_db.get_persistence_scores()
        assert set(cached) == set(out)

    def test_generativity_from_distant_resonances(self, tmp_db, fake_embedding):
        from config import PersistenceConfig
        for i in range(3):
            tmp_db.add_episode(id=f"e{i}", session_id="s", content=f"ep {i}",
                               embedding=fake_embedding())
        # behaviorally close, geometrically far: low similarity, many co-occurrences
        tmp_db.conn.execute(
            "INSERT INTO resonances (id, memory_a, layer_a, memory_b, layer_b,"
            " similarity, weight, strength, co_occurrences, created_at, last_seen)"
            " VALUES ('r1', 'e0', 'episode', 'e1', 'episode', 0.1, 1.0, 0.5, 5,"
            " '2026-01-01', '2026-01-01')")
        tmp_db.conn.commit()
        out = persistence.compute_scores(tmp_db, PersistenceConfig())
        assert out["e0"]["generativity"] == out["e1"]["generativity"] > 4.0
        assert out["e2"]["generativity"] == 0.0


class TestAudit:
    def test_audit_unchecked_events(self, tmp_db, fake_embedding):
        from config import PersistenceConfig
        import numpy as np
        # two separated groups as the peers' provenance
        rngs = [np.random.default_rng(s) for s in (1, 2)]
        for p, (axis, rng) in enumerate(zip((0, 1), rngs)):
            sem = f"peer-{p}"
            eps = []
            for i in range(4):
                eid = f"p{p}e{i}"
                c = np.zeros(768); c[axis] = 1.0
                v = (c + 0.03 * rng.standard_normal(768))
                tmp_db.add_episode(id=eid, session_id="s", content=f"x{p}{i}",
                                   embedding=(v / np.linalg.norm(v)).tolist())
                eps.append(eid)
            tmp_db.add_semantic(id=sem, content=f"peer {p}", kind="fact",
                                confidence=0.8, embedding=fake_embedding(),
                                source_episode_ids=eps)
        tmp_db.log_subdivision_event(id="ev1", parent_id="old-hub",
                                     peer_ids=["peer-0", "peer-1"],
                                     energy_before=0.8, energy_after=0.1,
                                     dl_cost=0.05, persistence_checked=False,
                                     site="sleep")
        report = persistence.audit_unchecked_events(tmp_db, PersistenceConfig())
        assert len(report) == 1
        assert report[0]["event_id"] == "ev1"
        assert report[0]["band"] > 0.10
        assert report[0]["would_pass"] is True
```

- [ ] **Step 2: Run to verify failure** — no attribute `compute_scores` / `audit_unchecked_events`

- [ ] **Step 3: Implement** (append to persistence.py)

```python
def _episodes_with_vectors(conn, lane: str | None = None):
    sql = ("SELECT e.id, e.lane, ev.embedding FROM episodes e"
           " JOIN episode_vectors ev ON ev.id = e.id")
    args: tuple = ()
    if lane is not None:
        sql += " WHERE COALESCE(e.lane, 'personal') = ?"
        args = (lane,)
    rows = conn.execute(sql, args).fetchall()
    ids = [r["id"] for r in rows]
    X = np.stack([_unpack_embedding(r["embedding"]) for r in rows]) if rows else None
    return ids, X


def generativity_scores(conn) -> dict[str, float]:
    """Sum of co_occurrences x (1 - similarity) over episode resonance edges:
    behaviorally close, geometrically far = keeps getting reframed."""
    rows = conn.execute(
        "SELECT memory_a, layer_a, memory_b, layer_b, similarity,"
        " co_occurrences FROM resonances").fetchall()
    g: dict[str, float] = {}
    for r in rows:
        w = (r["co_occurrences"] or 1) * (1.0 - (r["similarity"] or 0.0))
        for mid, lay in ((r["memory_a"], r["layer_a"]),
                         (r["memory_b"], r["layer_b"])):
            if lay == "episode":
                g[mid] = g.get(mid, 0.0) + w
    return g


def compute_scores(storage, cfg) -> dict[str, dict]:
    """Per-episode redundancy/uniqueness (lane-pure filtrations) +
    generativity overlay. Refreshes the persistence_scores cache."""
    gen = generativity_scores(storage.conn)
    out: dict[str, dict] = {}
    for lane in ("personal", "work"):
        ids, X = _episodes_with_vectors(storage.conn, lane=lane)
        if not ids:
            continue
        f = build_filtration(X)
        red, uniq = redundancy(f), uniqueness(f)
        for i, eid in enumerate(ids):
            out[eid] = {"episode_id": eid,
                        "redundancy": float(red[i]),
                        "uniqueness": float(uniq[i]),
                        "generativity": float(gen.get(eid, 0.0))}
    if out:
        storage.upsert_persistence_scores(list(out.values()))
    return out


def audit_unchecked_events(storage, cfg) -> list[dict]:
    """Re-run the band check on subdivision events recorded before the
    conjunct existed (persistence_checked=0). Best-effort: uses the peers'
    CURRENT provenance; events whose peers lack >=1 vectored episode on
    both sides are skipped with a reason."""
    events = storage.conn.execute(
        "SELECT * FROM subdivision_events WHERE persistence_checked = 0"
    ).fetchall()
    report = []
    for ev in events:
        peer_ids = json.loads(ev["peer_ids"])
        parts: list[list[str]] = []
        for pid in peer_ids:
            rows = storage.conn.execute(
                "SELECT ss.episode_id FROM semantic_sources ss"
                " JOIN episode_vectors ev ON ev.id = ss.episode_id"
                " WHERE ss.semantic_id = ?", (pid,)).fetchall()
            parts.append([r["episode_id"] for r in rows])
        usable = [p for p in parts if p]
        if len(usable) < 2:
            report.append({"event_id": ev["id"], "parent_id": ev["parent_id"],
                           "band": None, "would_pass": None,
                           "skipped": "insufficient surviving provenance"})
            continue
        all_ids = [e for p in usable[:2] for e in p]
        X = np.stack([
            _unpack_embedding(storage.conn.execute(
                "SELECT embedding FROM episode_vectors WHERE id = ?",
                (e,)).fetchone()[0]) for e in all_ids])
        na = len(usable[0])
        band = split_band(X, list(range(na)), list(range(na, len(all_ids))))
        report.append({"event_id": ev["id"], "parent_id": ev["parent_id"],
                       "band": round(band, 4),
                       "would_pass": band >= cfg.min_split_band})
    return report
```

- [ ] **Step 4: Run tests (PASS), full suite** → all pass

- [ ] **Step 5: Commit**

```bash
git add persistence.py tests/test_persistence.py
git commit -m "feat(persistence): episode scores, generativity, retroactive conjunct audit"
```

---

### Task 6: guarded prune + protections

**Files:**
- Modify: `storage.py` (refactor), `persistence.py`
- Test: `tests/test_persistence_forgetting.py` (create)

Refactor first: extract the body of `prune_decayed` (storage.py:513–559) into
`prune_episode_ids(self, ids: list[str]) -> int` (the cold-move + delete + `cleanup_resonances` part, taking explicit ids and fetching their rows). `prune_decayed(threshold)` keeps its exact signature/behavior by selecting candidates as today and delegating. Existing tests must pass unchanged after the refactor — do the refactor as its own red/green step (run the full suite before and after).

Then the guarded path in persistence.py:

- **candidates**: same SELECT as `prune_decayed` (`decay_strength < threshold AND compressed = 1 AND core = 0 AND dormant = 0`).
- **evict** iff candidate AND `redundancy >= cfg.redundancy_floor`.
- **protections** (any blocks eviction): `uniqueness >= cfg.protect_threshold`; `cfg.generativity_threshold > 0 and generativity >= cfg.generativity_threshold`; episode id referenced by an active identity anchor's `expected` (mirror `get_active_anchors`'s active filter); episode missing from the score map (no vector → no evidence → no eviction).
- `evaluate_prune(storage, cfg, threshold=0.05) -> {"evict": [...], "protected": [{"id", "reasons": [...]}], "candidates": n}` — pure preview, works regardless of `enabled`, used by reflect and by `guarded_prune`.
- `guarded_prune(storage, cfg, threshold=0.05) -> int` — recomputes scores live (`compute_scores`), calls `evaluate_prune`, then `storage.prune_episode_ids(evict_ids)`. Any exception → log + return 0 (fail toward unchanged store; cold-db unavailability surfaces as an exception inside `prune_episode_ids` → no eviction).

- [ ] **Step 1: Write the failing tests**

```python
"""Forgetting surfaces: guarded prune, protections, decay modulation,
core-promotion gate."""

import numpy as np

import persistence
from config import PersistenceConfig


def _emb(axis, noise, seed):
    rng = np.random.default_rng(seed)
    v = np.zeros(768); v[axis] = 1.0
    v = v + noise * rng.standard_normal(768)
    return (v / np.linalg.norm(v)).tolist()


def _decayed_episode(tmp_db, eid, embedding, **kw):
    tmp_db.add_episode(id=eid, session_id="s", content=f"content {eid}",
                       embedding=embedding)
    tmp_db.conn.execute(
        "UPDATE episodes SET decay_strength = 0.01, compressed = 1 WHERE id = ?",
        (eid,))
    tmp_db.conn.commit()


class TestGuardedPrune:
    def test_redundant_decayed_evicts_unique_decayed_survives(self, tmp_db):
        # five near-duplicates (redundant) + one isolate (unique), all decayed
        for i in range(5):
            _decayed_episode(tmp_db, f"dup-{i}", _emb(0, 0.01, i))
        _decayed_episode(tmp_db, "iso", _emb(5, 0.0, 99))
        cfg = PersistenceConfig(enabled=True)
        n = persistence.guarded_prune(tmp_db, cfg)
        assert n >= 1
        remaining = {r[0] for r in tmp_db.conn.execute(
            "SELECT id FROM episodes").fetchall()}
        assert "iso" in remaining                      # unique protected
        assert any(f"dup-{i}" not in remaining for i in range(5))  # some evicted
        # carrier of the duplicate cluster survives (one copy always kept)
        assert any(f"dup-{i}" in remaining for i in range(5))
        # evicted went to cold, not destroyed
        cold = tmp_db._cold_storage()
        assert cold.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] >= 1

    def test_anchor_reference_protects(self, tmp_db):
        for i in range(5):
            _decayed_episode(tmp_db, f"dup-{i}", _emb(0, 0.01, i))
        tmp_db.add_anchor(type="identity", content="who am I",
                          expected="dup-0")
        cfg = PersistenceConfig(enabled=True)
        persistence.guarded_prune(tmp_db, cfg)
        remaining = {r[0] for r in tmp_db.conn.execute(
            "SELECT id FROM episodes").fetchall()}
        assert "dup-0" in remaining

    def test_generativity_protects_when_threshold_set(self, tmp_db):
        for i in range(5):
            _decayed_episode(tmp_db, f"dup-{i}", _emb(0, 0.01, i))
        tmp_db.conn.execute(
            "INSERT INTO resonances (id, memory_a, layer_a, memory_b, layer_b,"
            " similarity, weight, strength, co_occurrences, created_at, last_seen)"
            " VALUES ('r1', 'dup-1', 'episode', 'zzz', 'semantic', 0.1, 1.0,"
            " 0.5, 5, '2026-01-01', '2026-01-01')")
        tmp_db.conn.commit()
        cfg = PersistenceConfig(enabled=True, generativity_threshold=1.0)
        persistence.guarded_prune(tmp_db, cfg)
        remaining = {r[0] for r in tmp_db.conn.execute(
            "SELECT id FROM episodes").fetchall()}
        assert "dup-1" in remaining

    def test_preview_matches_action_and_reports_reasons(self, tmp_db):
        for i in range(5):
            _decayed_episode(tmp_db, f"dup-{i}", _emb(0, 0.01, i))
        _decayed_episode(tmp_db, "iso", _emb(5, 0.0, 99))
        cfg = PersistenceConfig(enabled=True)
        persistence.compute_scores(tmp_db, cfg)
        preview = persistence.evaluate_prune(tmp_db, cfg)
        protected_ids = {p["id"] for p in preview["protected"]}
        assert "iso" in protected_ids
        reasons = {p["id"]: p["reasons"] for p in preview["protected"]}
        assert "unique" in reasons["iso"]
```

- [ ] **Step 2: Run to verify failure** — no attribute `guarded_prune` / `evaluate_prune`

- [ ] **Step 3a: Refactor storage.prune_decayed → prune_episode_ids** (behavior-preserving; full suite must stay green)

```python
def prune_episode_ids(self, ids: list[str]) -> int:
    """Move the given episodes to cold storage (text+metadata preserved,
    vectors stripped). Extracted from prune_decayed so callers can supply
    their own eviction policy."""
    if not ids:
        return 0
    placeholders = ", ".join("?" * len(ids))
    rows = self.conn.execute(
        f"SELECT * FROM episodes WHERE id IN ({placeholders})", ids
    ).fetchall()
    episodes = [dict(r) for r in rows]
    # ... (move the existing cold-move + DELETE + cleanup_resonances +
    #      commit + logger body here verbatim, operating on `episodes`/`ids`)
    return len(ids)


def prune_decayed(self, threshold: float = 0.05) -> int:
    rows = self.conn.execute(
        "SELECT id FROM episodes "
        "WHERE decay_strength < ? AND compressed = 1 AND core = 0 AND dormant = 0",
        (threshold,),
    ).fetchall()
    return self.prune_episode_ids([r["id"] for r in rows])
```

- [ ] **Step 3b: Implement evaluate_prune + guarded_prune** (append to persistence.py)

```python
def _anchored_episode_ids(conn) -> set[str]:
    # identity anchors hold a memory id in `expected`; mirror the active
    # filter used by Storage.get_active_anchors (read it and match).
    rows = conn.execute(
        "SELECT expected FROM anchors WHERE type = 'identity'"
        " AND status = 'active'").fetchall()
    return {r["expected"] for r in rows if r["expected"]}


def evaluate_prune(storage, cfg, threshold: float = 0.05) -> dict:
    """Pure preview of the two-key prune rule. Reads the score cache —
    callers wanting live decisions refresh via compute_scores first."""
    scores = storage.get_persistence_scores()
    anchored = _anchored_episode_ids(storage.conn)
    rows = storage.conn.execute(
        "SELECT id FROM episodes WHERE decay_strength < ?"
        " AND compressed = 1 AND core = 0 AND dormant = 0",
        (threshold,)).fetchall()
    evict, protected = [], []
    for r in rows:
        eid = r["id"]
        s = scores.get(eid)
        reasons = []
        if s is None:
            reasons.append("no-vector-no-evidence")
        else:
            if s["uniqueness"] >= cfg.protect_threshold:
                reasons.append("unique")
            if (cfg.generativity_threshold > 0
                    and s["generativity"] >= cfg.generativity_threshold):
                reasons.append("generative")
            if s["redundancy"] < cfg.redundancy_floor:
                reasons.append("not-redundant-enough")
        if eid in anchored:
            reasons.append("anchored")
        if reasons:
            protected.append({"id": eid, "reasons": reasons})
        else:
            evict.append(eid)
    return {"evict": evict, "protected": protected,
            "candidates": len(rows)}


def guarded_prune(storage, cfg, threshold: float = 0.05) -> int:
    """The two-key rule, acting: decayed AND redundant AND unprotected ->
    cold storage. Fails toward leaving the store unchanged."""
    try:
        compute_scores(storage, cfg)   # decisions never trust a stale cache
        verdict = evaluate_prune(storage, cfg, threshold)
        return storage.prune_episode_ids(verdict["evict"])
    except Exception:
        logger.warning("guarded prune aborted — store unchanged", exc_info=True)
        return 0
```

(Note the verbatim-move instruction in 3a: the engineer moves the existing cold-move body, not rewrites it. The `add_anchor` accessor already exists on Storage — server.py:1719 wraps it.)

- [ ] **Step 4: Run new tests + full suite** → all pass

- [ ] **Step 5: Commit**

```bash
git add storage.py persistence.py tests/test_persistence_forgetting.py
git commit -m "feat(persistence): two-key guarded prune with unique/generative/anchor protections"
```

---

### Task 7: decay modulation

**Files:**
- Modify: `storage.py` (`apply_decay`)
- Test: `tests/test_persistence_forgetting.py` (append)

- [ ] **Step 1: Write the failing test**

```python
class TestDecayModulation:
    def test_multipliers_change_aging_rate(self, tmp_db):
        import datetime as dt
        old = (dt.datetime.now(dt.timezone.utc)
               - dt.timedelta(days=30)).isoformat()
        for eid in ("redundant-ep", "unique-ep"):
            tmp_db.add_episode(id=eid, session_id="s", content=eid)
            tmp_db.conn.execute(
                "UPDATE episodes SET created_at = ?, last_accessed = ?,"
                " decay_strength = 0.9 WHERE id = ?", (old, old, eid))
        tmp_db.conn.commit()
        tmp_db.apply_decay(min_interval_minutes=0, exponent_multipliers={
            "redundant-ep": 1.15, "unique-ep": 0.85})
        s = {r["id"]: r["decay_strength"] for r in tmp_db.conn.execute(
            "SELECT id, decay_strength FROM episodes").fetchall()}
        assert s["redundant-ep"] < s["unique-ep"]   # redundant ages faster

    def test_no_multipliers_is_todays_behavior(self, tmp_db):
        tmp_db.add_episode(id="e1", session_id="s", content="x")
        n = tmp_db.apply_decay(min_interval_minutes=0)
        assert isinstance(n, int)   # smoke: signature unchanged for old callers
```

- [ ] **Step 2: Run to verify failure** — `TypeError: unexpected keyword argument 'exponent_multipliers'`

- [ ] **Step 3: Implement** — in `apply_decay`, add keyword `exponent_multipliers: dict[str, float] | None = None`; inside the per-episode loop replace the activation line:

```python
        d_eff = decay_exponent * (
            (exponent_multipliers or {}).get(ep["id"], 1.0))
        activation = math.log(1 + n * t_hours ** (-d_eff))
```

(Everything else in the function unchanged. Multiplier mapping `1 + 0.15×(2×redundancy − 1)` is computed by the *caller* — Task 9's server wiring — from the score cache; the cache may be one sleep stale, which is acceptable for ±15% pressure and noted in a comment there.)

- [ ] **Step 4: Run tests + full suite** → all pass

- [ ] **Step 5: Commit**

```bash
git add storage.py tests/test_persistence_forgetting.py
git commit -m "feat(persistence): per-episode decay exponent multipliers"
```

---

### Task 8: core-promotion gate

**Files:**
- Modify: `persistence.py`, `compress.py` (the `mark_core(centroid_nearest)` site at ~502–507)
- Test: `tests/test_persistence_forgetting.py` (append)

Note (spec correction, record in the commit message): promotion is already centroid-nearest-only — the gate guards that single candidate, not "all sources."

- [ ] **Step 1: Write the failing tests**

```python
class TestCorePromotionGate:
    def _seed(self, tmp_db, candidate_emb):
        # an existing core occupying axis 0
        tmp_db.add_episode(id="core-1", session_id="s", content="existing core",
                           embedding=_emb(0, 0.01, 1))
        tmp_db.mark_core("core-1")
        tmp_db.add_episode(id="cand", session_id="s", content="candidate",
                           embedding=candidate_emb)

    def test_redundant_candidate_declined(self, tmp_db):
        self._seed(tmp_db, _emb(0, 0.01, 2))   # nearly identical to core-1
        cfg = PersistenceConfig(enabled=True)
        assert persistence.core_promotion_allowed(tmp_db, "cand", cfg) is False

    def test_novel_candidate_allowed(self, tmp_db):
        self._seed(tmp_db, _emb(5, 0.01, 3))   # different direction entirely
        cfg = PersistenceConfig(enabled=True)
        assert persistence.core_promotion_allowed(tmp_db, "cand", cfg) is True

    def test_disabled_always_allows(self, tmp_db):
        self._seed(tmp_db, _emb(0, 0.01, 4))
        cfg = PersistenceConfig(enabled=False)
        assert persistence.core_promotion_allowed(tmp_db, "cand", cfg) is True

    def test_empty_core_set_allows(self, tmp_db):
        tmp_db.add_episode(id="cand", session_id="s", content="c",
                           embedding=_emb(0, 0.01, 5))
        cfg = PersistenceConfig(enabled=True)
        assert persistence.core_promotion_allowed(tmp_db, "cand", cfg) is True
```

- [ ] **Step 2: Run to verify failure** — no attribute `core_promotion_allowed`

- [ ] **Step 3: Implement** (append to persistence.py)

```python
def core_promotion_allowed(storage, episode_id: str, cfg) -> bool:
    """Decline promotion when the candidate is redundant within the
    existing core set (adds no coverage). Permissive on any gap in
    evidence: disabled, no cores, or missing vectors -> allow."""
    if cfg is None or not getattr(cfg, "enabled", False):
        return True
    cand = storage.get_vector("episode", episode_id)
    if cand is None:
        return True
    rows = storage.conn.execute(
        "SELECT ev.embedding FROM episodes e"
        " JOIN episode_vectors ev ON ev.id = e.id"
        " WHERE e.core > 0 AND e.id != ?", (episode_id,)).fetchall()
    if not rows:
        return True
    C = np.stack([_unpack_embedding(r["embedding"]) for r in rows])
    C = C / (np.linalg.norm(C, axis=1, keepdims=True) + _EPS)
    v = np.asarray(cand, dtype=np.float64)
    v = v / (np.linalg.norm(v) + _EPS)
    redundancy_vs_cores = float(np.clip((C @ v).max(), 0.0, 1.0))
    return redundancy_vs_cores < cfg.redundancy_floor
```

In compress.py at the `mark_core` site (Compressor already has `self._persistence` from Task 4):

```python
            if centroid_nearest:
                from persistence import core_promotion_allowed
                if core_promotion_allowed(self._storage, centroid_nearest,
                                          self._persistence):
                    self._storage.mark_core(centroid_nearest)
                else:
                    logger.info("core promotion declined (redundant vs core"
                                " set): %s", centroid_nearest)
```

- [ ] **Step 4: Run tests + full suite** → all pass

- [ ] **Step 5: Commit**

```bash
git add persistence.py compress.py tests/test_persistence_forgetting.py
git commit -m "feat(persistence): core-promotion gate — decline redundant candidates (promotion was already centroid-nearest-only; spec assumption corrected)"
```

---

### Task 9: server wiring — sleep step, prune switch, decay modulation

**Files:**
- Modify: `server.py` (`_init` consolidation), `storage.py` only if a helper is missing
- Test: smoke via import + full suite (glue; the parts are unit-tested)

- [ ] **Step 1: Implement three wiring changes in `_init`:**

(a) **Decay modulation** — the decay step (~line 337) becomes:

```python
        try:
            multipliers = None
            if _config.persistence.enabled:
                # one-sleep-stale cache is fine for ±15% pressure
                cached = _storage.get_persistence_scores()
                multipliers = {eid: 1.0 + 0.15 * (2.0 * s["redundancy"] - 1.0)
                               for eid, s in cached.items()}
            _storage.apply_decay(decay_exponent=0.5,
                                 exponent_multipliers=multipliers)
        except Exception:
            logger.warning("decay failed", exc_info=True)
```

(Match the existing try/except idiom around the current call — adapt rather than duplicate guards.)

(b) **Prune switch** — the prune step (~line 342) becomes:

```python
        try:
            if _config.persistence.enabled:
                from persistence import guarded_prune
                pruned = guarded_prune(_storage, _config.persistence)
            else:
                pruned = _storage.prune_decayed(threshold=0.05)
        except Exception:
            logger.warning("prune failed", exc_info=True)
```

(c) **Score refresh step** — append after the cohesion sleep pass (~line 439):

```python
        # Persistence score refresh (spec: 2026-06-13-persistence-design.md)
        # Always-on observation: feeds reflect previews and next-boot decay
        # modulation; the cache is advisory, decisions recompute live.
        try:
            from persistence import compute_scores
            compute_scores(_storage, _config.persistence)
        except Exception:
            logger.warning("persistence score refresh failed", exc_info=True)
```

- [ ] **Step 2: Verify**

Run: `ENGRAM_PROJECT_ROOT=/Users/kairos/Projects/engram .venv/bin/python -c "import server; print('ok')"` → ok
Run: `.venv/bin/python -m pytest tests/ -q` → all pass

- [ ] **Step 3: Commit**

```bash
git add server.py
git commit -m "feat(persistence): wire score refresh, guarded prune, decay modulation into startup"
```

---

### Task 10: reflect(focus="persistence") + hub classification

**Files:**
- Modify: `persistence.py` (diagnostics helpers), `reflection.py`, `server.py` (Reflector construction)
- Test: `tests/test_persistence_surfaces.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
from reflection import Reflector


def _emb_list(axis, noise, seed):
    rng = np.random.default_rng(seed)
    v = np.zeros(768); v[axis] = 1.0
    v = v + noise * rng.standard_normal(768)
    return (v / np.linalg.norm(v)).tolist()


class TestReflectPersistence:
    def test_focus_returns_previews_and_classification(self, tmp_db):
        eps = []
        for i in range(8):
            eid = f"e{i}"
            tmp_db.add_episode(id=eid, session_id="s", content=f"ep {i}",
                               embedding=_emb_list(0 if i < 4 else 1, 0.03, i))
            eps.append(eid)
        tmp_db.add_semantic(id="hub-1", content="bimodal hub", kind="fact",
                            confidence=0.8, embedding=_emb_list(0, 0.3, 9),
                            source_episode_ids=eps)
        from config import PersistenceConfig
        r = Reflector(tmp_db, persistence_config=PersistenceConfig())
        out = r.reflect(focus="persistence")
        p = out["persistence"]
        assert "forgetting_preview" in p and "hubs" in p
        assert "conjunct_audit" in p and "flagged_cores" in p
        hub = [h for h in p["hubs"] if h["semantic_id"] == "hub-1"][0]
        assert hub["classification"] == "multi-modal"

    def test_empty_store(self, tmp_db):
        from config import PersistenceConfig
        out = Reflector(tmp_db,
                        persistence_config=PersistenceConfig()).reflect(
                            focus="persistence")
        assert out["persistence"]["hubs"] == []
```

- [ ] **Step 2: Run to verify failure** — unexpected kwarg `persistence_config` / focus falls through

- [ ] **Step 3: Implement.**

persistence.py diagnostics (append):

```python
def classify_hubs(storage, cfg, min_episodes: int = 10) -> list[dict]:
    """diffuse / multi-modal / looped, per provenance-heavy semantic.
    multi-modal: the best Fiedler split's band clears min_split_band.
    looped: persistent H1 exists (optional ripser; omitted otherwise)."""
    from sheaf import build_local_sheaf, cohesion_energy
    try:
        from ripser import ripser as _ripser
    except ImportError:
        _ripser = None
    sems = storage.conn.execute(
        "SELECT semantic_id, COUNT(*) AS n FROM semantic_sources"
        " GROUP BY semantic_id HAVING n >= ?", (min_episodes,)).fetchall()
    out = []
    for r in sems:
        rows = storage.conn.execute(
            "SELECT ss.episode_id, ev.embedding FROM semantic_sources ss"
            " JOIN episode_vectors ev ON ev.id = ss.episode_id"
            " WHERE ss.semantic_id = ?", (r["semantic_id"],)).fetchall()
        if len(rows) < min_episodes:
            continue
        ids = [x["episode_id"] for x in rows]
        X = np.stack([_unpack_embedding(x["embedding"]) for x in rows])
        ls = build_local_sheaf(r["semantic_id"], ids, X)
        res = cohesion_energy(ls)
        band = None
        if res["fiedler"]:
            f = np.array(res["fiedler"])
            a = [i for i, v in enumerate(f) if v > 0]
            b = [i for i, v in enumerate(f) if v <= 0]
            if len(a) >= 2 and len(b) >= 2:
                band = split_band(X, a, b)
        h1 = None
        if _ripser is not None:
            D = distance_matrix(X)
            dgm1 = _ripser(D, maxdim=1, distance_matrix=True)["dgms"][1]
            if len(dgm1):
                f_full = build_filtration(X)
                denom = max(f_full.max_height, _EPS)
                h1 = float(np.max(dgm1[:, 1] - dgm1[:, 0]) / denom)
        if band is not None and band >= cfg.min_split_band:
            cls = "multi-modal"
        elif h1 is not None and h1 >= 0.10:
            cls = "looped"
        else:
            cls = "diffuse"
        sem = storage.get_semantic(r["semantic_id"])
        out.append({"semantic_id": r["semantic_id"],
                    "content": (sem or {}).get("content", "")[:100],
                    "n": len(ids), "band": band,
                    "h1": h1 if _ripser is not None else "ripser-not-installed",
                    "classification": cls})
    return out


def flag_redundant_cores(storage, cfg) -> list[dict]:
    """Cores redundant within the core set — demotion candidates, review only."""
    rows = storage.conn.execute(
        "SELECT e.id, ev.embedding FROM episodes e"
        " JOIN episode_vectors ev ON ev.id = e.id WHERE e.core > 0").fetchall()
    if len(rows) < 2:
        return []
    ids = [r["id"] for r in rows]
    X = np.stack([_unpack_embedding(r["embedding"]) for r in rows])
    f = build_filtration(X)
    red = redundancy(f)
    flagged = []
    for i, eid in enumerate(ids):
        if red[i] >= cfg.redundancy_floor:
            ep = storage.get_episode(eid) or {}
            flagged.append({"id": eid, "redundancy": round(float(red[i]), 3),
                            "content": ep.get("content", "")[:100]})
    return sorted(flagged, key=lambda d: -d["redundancy"])
```

reflection.py — `Reflector.__init__` gains keyword `persistence_config=None` (stored); dispatch branch + method:

```python
    elif focus == "persistence":
        # Not in the no-focus default: filtrations per hub — heavier than other foci.
        return {"persistence": self.analyze_persistence()}
```

```python
    def analyze_persistence(self) -> dict:
        """Layer 4: forgetting preview, hub classification, core flags, audit."""
        from config import PersistenceConfig
        from persistence import (audit_unchecked_events, classify_hubs,
                                 compute_scores, evaluate_prune,
                                 flag_redundant_cores)
        cfg = self._persistence_config or PersistenceConfig()
        compute_scores(self._storage, cfg)
        return {
            "enabled": bool(getattr(cfg, "enabled", False)),
            "forgetting_preview": evaluate_prune(self._storage, cfg),
            "hubs": classify_hubs(self._storage, cfg),
            "flagged_cores": flag_redundant_cores(self._storage, cfg),
            "conjunct_audit": audit_unchecked_events(self._storage, cfg),
        }
```

server.py: add `persistence_config=_config.persistence if _config else None` to the Reflector construction (alongside `cohesion_config`).

- [ ] **Step 4: Run tests + full suite** → all pass

- [ ] **Step 5: Commit**

```bash
git add persistence.py reflection.py server.py tests/test_persistence_surfaces.py
git commit -m "feat(persistence): reflect(focus=persistence) — previews, hub classification, core flags"
```

---

### Task 11: daydream cold-uninvited

**Files:**
- Modify: `storage.py` (`sample_cold_random`), `server.py` (recall's uninvited block)
- Test: `tests/test_persistence_surfaces.py` (append; storage-level test real, server-level covered by existing recall tests staying green)

- [ ] **Step 1: Write the failing test**

```python
class TestColdUninvited:
    def test_sample_cold_random(self, tmp_db, fake_embedding):
        tmp_db.add_episode(id="e1", session_id="s", content="soon cold",
                           embedding=fake_embedding())
        tmp_db.conn.execute(
            "UPDATE episodes SET decay_strength = 0.01, compressed = 1"
            " WHERE id = 'e1'")
        tmp_db.conn.commit()
        tmp_db.prune_decayed()
        out = tmp_db.sample_cold_random(k=1)
        assert len(out) == 1 and out[0]["id"] == "e1"
        assert tmp_db.sample_cold_random(k=5)[0]["content"] == "soon cold"

    def test_empty_cold_returns_nothing(self, tmp_db):
        assert tmp_db.sample_cold_random(k=1) == []
```

- [ ] **Step 2: Run to verify failure** — no attribute `sample_cold_random`

- [ ] **Step 3: Implement.**

storage.py:

```python
def sample_cold_random(self, k: int = 1) -> list[dict]:
    """Unconditioned draw from cold storage — daydream material, never
    query-matched (a query-matched cold memory is retrieval pretending
    to be serendipity)."""
    try:
        cold = self._cold_storage()
        rows = cold.execute(
            "SELECT * FROM episodes ORDER BY RANDOM() LIMIT ?", (k,)
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        logger.warning("cold sample failed", exc_info=True)
        return []
```

server.py — inside the existing uninvited block (server.py:1096–1166), immediately after `matched_ids` is built, add (independent of `[persistence] enabled` by design — surfacing is observation):

```python
        import random as _random
        cold_p = getattr(getattr(_config, "persistence", None),
                         "cold_uninvited_p", 0.0)
        if uninvited > 0 and _random.random() < cold_p:
            cold_rows = _storage.sample_cold_random(k=1)
            if cold_rows:
                ep = cold_rows[0]
                results.append({
                    "id": ep["id"], "layer": "episode",
                    "content": ep.get("content", ""),
                    "lane": ep.get("lane") or "personal",
                    "uninvited": True, "cold": True, "origin": "cold",
                    "note": "daydream fragment from cold storage — revive(id) to bring it back",
                })
                result_ids.append(ep["id"])
                uninvited -= 1   # the cold draw takes one uninvited slot
```

- [ ] **Step 4: Run tests + full suite** → all pass (existing recall tests confirm the warm path is unchanged when the probability doesn't fire; the draw is probabilistic so server-level behavior is covered by the storage test + code review rather than a flaky test)

- [ ] **Step 5: Commit**

```bash
git add storage.py server.py tests/test_persistence_surfaces.py
git commit -m "feat(persistence): daydream cold-uninvited — unconditioned cold draws in recall"
```

---

### Task 12: calibration CLI, docs, final verification

**Files:**
- Modify: `persistence.py` (`__main__`), `CLAUDE.md`, spec (one correction)

- [ ] **Step 1: Add the read-only calibration entry point** (append to persistence.py)

```python
if __name__ == "__main__":
    # Read-only calibration: python persistence.py /path/to/copy-of-graph.db
    # Acceptance (spec): read the forgetting preview and hub classification
    # BEFORE setting [persistence] enabled = true. Pre-registered questions:
    # (1) does the recorded Prism verdict's band pass the conjunct?
    # (2) are the mega-hubs diffuse or looped?
    import sqlite3
    import sys

    import sqlite_vec

    from config import PersistenceConfig

    conn = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    class _RO:
        def __init__(self, conn):
            self.conn = conn

        def get_semantic(self, sid):
            row = self.conn.execute(
                "SELECT * FROM semantics WHERE id = ?", (sid,)).fetchone()
            return dict(row) if row else None

        def get_episode(self, eid):
            row = self.conn.execute(
                "SELECT * FROM episodes WHERE id = ?", (eid,)).fetchone()
            return dict(row) if row else None

        def get_persistence_scores(self):
            return {}

        def upsert_persistence_scores(self, scores):
            pass  # read-only: scores printed, not cached

    conn.row_factory = sqlite3.Row
    cfg = PersistenceConfig(enabled=True)  # evaluation only; nothing writes
    store = _RO(conn)

    print("== score distribution ==")
    gen = generativity_scores(conn)
    for lane in ("personal", "work"):
        ids, X = _episodes_with_vectors(conn, lane=lane)
        if not ids:
            continue
        f = build_filtration(X)
        red, uniq = redundancy(f), uniqueness(f)
        print(f"[{lane}] n={len(ids)} redundancy p50/p90:"
              f" {np.percentile(red, 50):.3f}/{np.percentile(red, 90):.3f}"
              f" uniqueness p50/p90:"
              f" {np.percentile(uniq, 50):.3f}/{np.percentile(uniq, 90):.3f}")
        prot = sum(1 for u in uniq if u >= cfg.protect_threshold)
        redd = sum(1 for x in red if x >= cfg.redundancy_floor)
        print(f"  would-protect(unique): {prot}  redundant-enough: {redd}"
              f"  generativity>0: {sum(1 for i in ids if gen.get(i, 0) > 0)}")

    print("\n== hub classification ==")
    for h in classify_hubs(store, cfg):
        print(f"  {h['classification']:>11}  n={h['n']:>4}"
              f" band={h['band'] if h['band'] is None else round(h['band'], 3)}"
              f" h1={h['h1']}  {h['content'][:60]}")

    print("\n== retroactive conjunct audit ==")
    for a in audit_unchecked_events(store, cfg):
        print(f"  {a}")
```

Verify against a TEST db you construct (a tmp Storage with a bimodal hub and some duplicates), exactly as the sheaf CLI was verified — and confirm a write attempt on the connection fails (mode=ro). Do NOT run against any real store copy — the controller does that personally.

- [ ] **Step 2: Update CLAUDE.md**

Key Files: add `| persistence.py | Layer 4 — H₀ filtrations, guarded forgetting, gate conjunct, daydream surfacing |`. Architecture: after the Sheaf cohesion paragraph add:

```markdown
**Persistence (Layer 4):** Single-linkage filtrations (exact, via MST) give
each episode a redundancy (nearest-neighbor coverage) and uniqueness
(survival across merge scales); resonance history adds generativity
(behaviorally close, geometrically far = keeps getting reframed). The
subdivision gate's middle conjunct is live: splits must hold a persistence
band ≥ `min_split_band`. Forgetting (gated by `[persistence] enabled`,
default false): prune requires decayed AND redundant; unique, generative,
anchor-referenced, and core episodes are never auto-evicted; eviction is
always a move to cold.db. Decay pressure modulates ±15% by redundancy. Core
promotion declines candidates redundant within the core set; demotion only
flags for review. Recall's uninvited slot occasionally daydreams a random
(never query-matched) cold episode back into view. Observe via
`reflect(focus="persistence")`; calibrate read-only via `python
persistence.py /path/to/copy-of-graph.db`.
Spec: docs/superpowers/specs/2026-06-13-persistence-design.md.
```

reflect() tools-table row: add `persistence` to the focus list. Update the test count to the real number (run the suite).

- [ ] **Step 3: Spec correction** — in `docs/superpowers/specs/2026-06-13-persistence-design.md` §Surface 2c, change "today *all* sources auto-promote" to note reality: promotion is already centroid-nearest-only (compress.py); the gate guards that single candidate.

- [ ] **Step 4: Full suite + final whole-feature review**

Run: `.venv/bin/python -m pytest tests/ -q` → all pass.
Then REQUIRED: dispatch the final whole-feature reviewer over the entire range (the assessment and sheaf builds both proved the final review finds what per-task reviews cannot). Hunt list for it: paths acting despite `enabled=false`; the prune refactor's behavior-parity; interactions between guarded prune and the cohesion sleep pass in the same startup; cold-uninvited's effect on dream-verify and lane filtering (cold results carry lane — confirm the lane filter handles them); `_reset_all` and `erase` against `persistence_scores`.

- [ ] **Step 5: Commit**

```bash
git add persistence.py CLAUDE.md docs/superpowers/specs/2026-06-13-persistence-design.md
git commit -m "feat(persistence): read-only calibration CLI + docs"
```

---

## Plan self-review notes

- **Spec coverage:** conjunct (T4), redundancy/uniqueness/generativity (T3, T5), prune gate + protections incl. anchors (T6), decay modulation with exact formula (T7, caller mapping in T9), core promotion/demotion-flags (T8, T10), diagnostics + hub classification + audit + previews (T5, T10), daydream cold-uninvited independent of enabled (T11), schema (T1), config (T2), CLI + acceptance posture (T12), error handling distributed per task (fail-toward-unchanged in T6/T9, ripser guard in T10, cold-db guard via prune_episode_ids exception path in T6).
- **Known deliberate lookups:** anchors' active-status filter (mirror `get_active_anchors`), the verbatim move of `prune_decayed`'s cold-move body, existing try/except idioms at the `_init` call sites. Each anchored to a named function.
- **Spec corrections recorded:** core promotion already centroid-nearest (T8/T12); anchor protection realized as identity-anchor `expected` references (T6) since anchors are not membership structures.
- **MCP server restart** required after implementation (migration 021 + new focus).
