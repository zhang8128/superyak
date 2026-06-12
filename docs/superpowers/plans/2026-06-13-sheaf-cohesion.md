# Cellular-Sheaf Cohesion Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Energy-gated subdivision of conflated semantics — local sheaves over provenance neighborhoods, with the gate acting at compression time and sleep time.

**Architecture:** New `sheaf.py` module computes a per-semantic cohesion energy (normalized-Laplacian spectral gap over the episode similarity graph, in the semantic's PCA subspace — "its terms"). A `subdivision_test` verdict gates splits by description-length cost, with a stubbed persistence conjunct for Layer 4. An atomic executor mints peers under the surviving hub (map home in `semantic_peers`), wired into `compress.cluster_episodes` (pre-partition) and a budgeted sleep pass in `server._init`.

**Tech Stack:** Python, numpy (eigh/SVD), SQLite + sqlite-vec, Ollama (peer content distillation), pytest.

**Spec:** `docs/superpowers/specs/2026-06-13-sheaf-cohesion-design.md`

---

## File structure

| File | Responsibility |
|---|---|
| `migrations/020_sheaf_cohesion.sql` (create) | `subdivision_events`, `semantic_peers`, `subdivision_queue` tables |
| `storage.py` (modify) | Accessors for the three tables; peer edges in `get_neighbors` |
| `config.py` (modify) | `CohesionConfig` dataclass + `[cohesion]` TOML section |
| `sheaf.py` (create) | All sheaf math, gate, executor, distiller, sleep pass, calibration CLI |
| `compress.py` (modify) | Compression-time gate: cluster pre-partition + sibling resonance |
| `server.py` (modify) | Sleep-pass wiring in `_init` consolidation |
| `reflection.py` (modify) | `reflect(focus="cohesion")` |
| `tests/test_sheaf.py` (create) | Math + gate unit tests (synthetic embeddings) |
| `tests/test_sheaf_apply.py` (create) | Migration, storage accessors, atomic executor |
| `tests/test_sheaf_sleep.py` (create) | Sleep pass: budget, rate limit, queue, narration |
| `tests/test_sheaf_compress.py` (create) | Compression gate + sibling resonance |
| `tests/test_sheaf_reflect.py` (create) | reflect focus + peer neighbors |

Conventions to follow (verified in repo): migrations are `NNN_name.sql` applied by `storage._run_migrations`; `tests/conftest.py` provides `tmp_db` (Storage on tmp path with migrations) and `fake_embedding` (factory); embeddings packed via `storage._pack_embedding` (little-endian f32); resonance columns are `(id, memory_a, layer_a, memory_b, layer_b, similarity, weight, strength, co_occurrences, created_at, last_seen)` with `memory_a < memory_b`.

---

### Task 1: Migration 020 + storage accessors

**Files:**
- Create: `migrations/020_sheaf_cohesion.sql`
- Modify: `storage.py` (new methods at end of Storage class)
- Test: `tests/test_sheaf_apply.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for sheaf-cohesion storage: migration 020 + accessors."""

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_sheaf_apply.py -v`
Expected: FAIL — tables missing / `AttributeError: log_subdivision_event`

- [ ] **Step 3: Write the migration**

```sql
-- 020: sheaf cohesion — subdivision audit trail, map home, and LLM-wait queue.
-- Spec: docs/superpowers/specs/2026-06-13-sheaf-cohesion-design.md
CREATE TABLE IF NOT EXISTS subdivision_events (
    id TEXT PRIMARY KEY,
    parent_id TEXT NOT NULL,
    peer_ids TEXT NOT NULL,
    energy_before REAL NOT NULL,
    energy_after REAL NOT NULL,
    dl_cost REAL NOT NULL,
    persistence_checked INTEGER NOT NULL DEFAULT 0,
    site TEXT NOT NULL CHECK (site IN ('sleep', 'compress')),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_subdivision_events_parent
    ON subdivision_events(parent_id);

CREATE TABLE IF NOT EXISTS semantic_peers (
    peer_id TEXT NOT NULL,
    parent_id TEXT NOT NULL,
    residual_energy REAL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (peer_id, parent_id)
);
CREATE INDEX IF NOT EXISTS idx_semantic_peers_parent
    ON semantic_peers(parent_id);

CREATE TABLE IF NOT EXISTS subdivision_queue (
    parent_id TEXT PRIMARY KEY,
    verdict TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

- [ ] **Step 4: Add the storage methods** (end of `Storage` class; follow the existing `datetime.now(timezone.utc).isoformat()` timestamp idiom used elsewhere in the file)

```python
# --- Sheaf cohesion (migration 020) -------------------------------------

def log_subdivision_event(self, id: str, parent_id: str, peer_ids: list[str],
                          energy_before: float, energy_after: float,
                          dl_cost: float, persistence_checked: bool,
                          site: str) -> None:
    self.conn.execute(
        "INSERT INTO subdivision_events (id, parent_id, peer_ids, energy_before,"
        " energy_after, dl_cost, persistence_checked, site, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (id, parent_id, json.dumps(peer_ids), energy_before, energy_after,
         dl_cost, int(persistence_checked), site,
         datetime.now(timezone.utc).isoformat()),
    )
    self.conn.commit()

def get_subdivision_events(self, limit: int = 20) -> list[dict]:
    rows = self.conn.execute(
        "SELECT * FROM subdivision_events ORDER BY created_at DESC LIMIT ?",
        (limit,)).fetchall()
    return [dict(r) for r in rows]

def add_semantic_peer(self, peer_id: str, parent_id: str,
                      residual_energy: float | None = None) -> None:
    self.conn.execute(
        "INSERT OR REPLACE INTO semantic_peers"
        " (peer_id, parent_id, residual_energy, created_at) VALUES (?, ?, ?, ?)",
        (peer_id, parent_id, residual_energy,
         datetime.now(timezone.utc).isoformat()),
    )
    self.conn.commit()

def get_semantic_peers(self, parent_id: str) -> list[dict]:
    rows = self.conn.execute(
        "SELECT * FROM semantic_peers WHERE parent_id = ?", (parent_id,)).fetchall()
    return [dict(r) for r in rows]

def queue_subdivision(self, parent_id: str, verdict: dict) -> None:
    self.conn.execute(
        "INSERT OR REPLACE INTO subdivision_queue (parent_id, verdict, created_at)"
        " VALUES (?, ?, ?)",
        (parent_id, json.dumps(verdict), datetime.now(timezone.utc).isoformat()),
    )
    self.conn.commit()

def get_queued_subdivisions(self) -> list[dict]:
    rows = self.conn.execute(
        "SELECT * FROM subdivision_queue ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]

def dequeue_subdivision(self, parent_id: str) -> None:
    self.conn.execute(
        "DELETE FROM subdivision_queue WHERE parent_id = ?", (parent_id,))
    self.conn.commit()
```

(`json`, `datetime`, `timezone` are already imported in storage.py — verify at top of file.)

- [ ] **Step 5: Run tests to verify they pass, then full suite**

Run: `.venv/bin/python -m pytest tests/test_sheaf_apply.py -v` → PASS
Run: `.venv/bin/python -m pytest tests/ -q` → all pass

- [ ] **Step 6: Commit**

```bash
git add migrations/020_sheaf_cohesion.sql storage.py tests/test_sheaf_apply.py
git commit -m "feat(sheaf): migration 020 — subdivision events, semantic peers, queue"
```

---

### Task 2: CohesionConfig

**Files:**
- Modify: `config.py` (dataclass, `EngramConfig` field, `_DEFAULT_TOML`, `load_config`)
- Test: `tests/test_sheaf.py` (start the file)

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the sheaf cohesion layer — config, math, gate."""

from config import load_config


class TestCohesionConfig:
    def test_defaults(self, tmp_path):
        cfg = load_config(tmp_path)
        assert cfg.cohesion.dl_cost == 0.15
        assert cfg.cohesion.variance_threshold == 0.90
        assert cfg.cohesion.max_subspace_dim == 8
        assert cfg.cohesion.min_episodes == 3
        assert cfg.cohesion.sleep_budget == 3

    def test_toml_override(self, tmp_path):
        (tmp_path / ".engram").mkdir()
        (tmp_path / ".engram" / "config.toml").write_text(
            "[cohesion]\ndl_cost = 0.3\nsleep_budget = 1\n")
        cfg = load_config(tmp_path)
        assert cfg.cohesion.dl_cost == 0.3
        assert cfg.cohesion.sleep_budget == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_sheaf.py -v`
Expected: FAIL — `AttributeError: 'EngramConfig' object has no attribute 'cohesion'`

- [ ] **Step 3: Implement** (match the existing pattern exactly — dataclass near `ReflectionConfig`, field in `EngramConfig`, section in `_DEFAULT_TOML`, line in `load_config`)

```python
@dataclass
class CohesionConfig:
    dl_cost: float = 0.15
    variance_threshold: float = 0.90
    max_subspace_dim: int = 8
    min_episodes: int = 3
    sleep_budget: int = 3
```

In `EngramConfig`: `cohesion: CohesionConfig = field(default_factory=CohesionConfig)`
In `load_config`: `cohesion=CohesionConfig(**raw.get("cohesion", {})),`
In `_DEFAULT_TOML` append:

```toml
[cohesion]
dl_cost = 0.15
variance_threshold = 0.90
max_subspace_dim = 8
min_episodes = 3
sleep_budget = 3
```

- [ ] **Step 4: Run to verify pass, then full suite**

Run: `.venv/bin/python -m pytest tests/test_sheaf.py tests/test_config.py -v` (if `tests/test_config.py` exists; else just the former) → PASS

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_sheaf.py
git commit -m "feat(sheaf): [cohesion] config section"
```

---

### Task 3: sheaf.py — local sheaf and cohesion energy

**Files:**
- Create: `sheaf.py`
- Test: `tests/test_sheaf.py` (append)

The math, so the engineer needn't reverse-engineer it from code:
1. **Subspace ("S's terms"):** L2-normalize episode embeddings, mean-center, SVD; keep k components reaching `variance_threshold` of variance, clamped to [2, `max_subspace_dim`]. Project to get n×k coordinates.
2. **Energy:** build the full similarity graph on projected coordinates, `W_ij = max(0, cos(y_i, y_j))`; normalized Laplacian `L = I − D^{-1/2} W D^{-1/2}`; `λ₂` = second-smallest eigenvalue. A coherent blob has λ₂ ≈ 1 (complete-graph limit); two separated groups have λ₂ ≈ 0. **energy = clamp(1 − λ₂, 0, 1)**.
3. **Localization:** Fiedler vector `f = D^{-1/2} v₂` — per-edge residual `r_ij = W_ij (f_i − f_j)²` names the breaking edges; the sign of `f` is the candidate partition.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_sheaf.py`)

```python
import numpy as np

import sheaf


def _cluster(center: np.ndarray, n: int, noise: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    pts = center + noise * rng.standard_normal((n, center.shape[0]))
    return pts


def _two_orthogonal(n_per: int = 10, noise: float = 0.05):
    a = np.zeros(768); a[0] = 1.0
    b = np.zeros(768); b[1] = 1.0
    X = np.vstack([_cluster(a, n_per, noise, 1), _cluster(b, n_per, noise, 2)])
    ids = [f"e{i}" for i in range(2 * n_per)]
    return ids, X


class TestLocalSheaf:
    def test_subspace_dimension_bounded(self):
        ids, X = _two_orthogonal()
        ls = sheaf.build_local_sheaf("s1", ids, X, variance_threshold=0.90, max_dim=8)
        assert 2 <= ls.k <= 8
        assert ls.coords.shape == (len(ids), ls.k)


class TestCohesionEnergy:
    def test_conflated_semantic_is_hot(self):
        ids, X = _two_orthogonal()
        ls = sheaf.build_local_sheaf("s1", ids, X)
        res = sheaf.cohesion_energy(ls)
        assert res["energy"] > 0.8

    def test_tight_cluster_is_cool(self):
        a = np.zeros(768); a[0] = 1.0
        X = _cluster(a, 12, 0.05, 3)
        ids = [f"e{i}" for i in range(12)]
        res = sheaf.cohesion_energy(sheaf.build_local_sheaf("s1", ids, X))
        assert res["energy"] < 0.3

    def test_diverse_but_coherent_is_cool_despite_spread(self):
        a = np.zeros(768); a[0] = 1.0
        X = _cluster(a, 30, 0.35, 4)  # high degree, high spread, one mode
        ids = [f"e{i}" for i in range(30)]
        res = sheaf.cohesion_energy(sheaf.build_local_sheaf("s1", ids, X))
        assert res["energy"] < 0.5

    def test_too_few_episodes_trivial(self):
        a = np.zeros(768); a[0] = 1.0
        X = _cluster(a, 2, 0.05, 5)
        res = sheaf.cohesion_energy(sheaf.build_local_sheaf("s1", ["e0", "e1"], X))
        assert res["energy"] == 0.0

    def test_worst_edges_cross_the_conflation(self):
        ids, X = _two_orthogonal()
        res = sheaf.cohesion_energy(sheaf.build_local_sheaf("s1", ids, X))
        # localization: the hottest edges connect the two groups
        for ea, eb, _r in res["worst_edges"][:3]:
            ia, ib = int(ea[1:]), int(eb[1:])
            assert (ia < 10) != (ib < 10)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_sheaf.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sheaf'`

- [ ] **Step 3: Implement `sheaf.py`**

```python
"""Cellular-sheaf cohesion — local sheaves over semantic provenance neighborhoods.

A semantic's source episodes are translated into "its terms" (a low-dim PCA
subspace = the restriction maps); the cohesion energy is the spectral gap of
the similarity graph in those terms. The harmonic (Fiedler) part localizes
which edges fail to glue and proposes the partition.

Spec: docs/superpowers/specs/2026-06-13-sheaf-cohesion-design.md
"""

import json
import logging
import struct
import uuid
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

_EPS = 1e-12


def _unpack_embedding(blob: bytes) -> np.ndarray:
    return np.array(struct.unpack(f"<{len(blob) // 4}f", blob), dtype=np.float64)


@dataclass
class LocalSheaf:
    semantic_id: str
    episode_ids: list[str]
    coords: np.ndarray  # n×k coordinates in the semantic's subspace
    k: int


def build_local_sheaf(semantic_id: str, episode_ids: list[str], X: np.ndarray,
                      variance_threshold: float = 0.90, max_dim: int = 8) -> LocalSheaf:
    n = len(episode_ids)
    if n == 0:
        return LocalSheaf(semantic_id, [], np.zeros((0, 2)), 2)
    Xn = X / (np.linalg.norm(X, axis=1, keepdims=True) + _EPS)
    C = Xn - Xn.mean(axis=0)
    _, s, Vt = np.linalg.svd(C, full_matrices=False)
    var = (s ** 2) / max(float((s ** 2).sum()), _EPS)
    k = int(np.searchsorted(np.cumsum(var), variance_threshold)) + 1
    k = max(2, min(k, max_dim, len(s)))
    coords = C @ Vt[:k].T
    return LocalSheaf(semantic_id, episode_ids, coords, k)


def cohesion_energy(sheaf: LocalSheaf) -> dict:
    """Energy in [0,1]: 0 = globally consistent, 1 = provably conflated."""
    n = len(sheaf.episode_ids)
    trivial = {"energy": 0.0, "lambda2": None, "fiedler": [], "worst_edges": [], "n": n}
    if n < 3:
        return trivial
    Y = sheaf.coords / (np.linalg.norm(sheaf.coords, axis=1, keepdims=True) + _EPS)
    W = np.clip(Y @ Y.T, 0.0, None)
    np.fill_diagonal(W, 0.0)
    d = W.sum(axis=1)
    if (d <= _EPS).any():
        # an isolated episode is already a disconnection — maximally incoherent
        fiedler = [1.0 if dd <= _EPS else -1.0 for dd in d]
        return {"energy": 1.0, "lambda2": 0.0, "fiedler": fiedler,
                "worst_edges": [], "n": n}
    d_isqrt = 1.0 / np.sqrt(d)
    L = np.eye(n) - (W * d_isqrt[:, None]) * d_isqrt[None, :]
    evals, evecs = np.linalg.eigh(L)
    lam2 = float(evals[1])
    fiedler = (d_isqrt * evecs[:, 1])
    residuals = W * (fiedler[:, None] - fiedler[None, :]) ** 2
    iu = np.triu_indices(n, k=1)
    order = np.argsort(residuals[iu])[::-1][:10]
    worst = [(sheaf.episode_ids[iu[0][o]], sheaf.episode_ids[iu[1][o]],
              float(residuals[iu][o])) for o in order]
    return {"energy": float(np.clip(1.0 - lam2, 0.0, 1.0)), "lambda2": lam2,
            "fiedler": fiedler.tolist(), "worst_edges": worst, "n": n}
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_sheaf.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add sheaf.py tests/test_sheaf.py
git commit -m "feat(sheaf): local sheaf construction and cohesion energy"
```

---

### Task 4: subdivision_test — the gate

**Files:**
- Modify: `sheaf.py`
- Test: `tests/test_sheaf.py` (append)

Gate rule (spec §Gate rule): binary Fiedler partition; ambiguous episodes (|f| < 0.1·max|f|) excluded from parts; split iff `gain = energy_before − Σ (n_p/n_assigned)·energy(part_p) > dl_cost × (n_parts − 1)` AND `persistence_check(parts)` (stub: True, recorded as unchecked). Splits cascade across passes, not within one — no recursion here.

- [ ] **Step 1: Write the failing tests**

```python
class TestSubdivisionGate:
    def test_conflated_splits(self):
        ids, X = _two_orthogonal()
        v = sheaf.subdivision_test("s1", ids, X, dl_cost=0.15)
        assert v.split is True
        assert len(v.parts) == 2
        groups = [{int(e[1:]) < 10 for e in part} for part in v.parts]
        assert groups[0] != groups[1] and all(len(g) == 1 for g in groups)
        assert v.persistence_checked is False
        assert v.gain > 0.15

    def test_tight_cluster_does_not_split(self):
        a = np.zeros(768); a[0] = 1.0
        X = _cluster(a, 12, 0.05, 6)
        v = sheaf.subdivision_test("s1", [f"e{i}" for i in range(12)], X, dl_cost=0.15)
        assert v.split is False

    def test_noise_perturbation_never_splits(self):
        # the messageboard test: same data, jittered — verdict stays no-split
        a = np.zeros(768); a[0] = 1.0
        for seed in range(5):
            X = _cluster(a, 12, 0.08, 100 + seed)
            v = sheaf.subdivision_test("s1", [f"e{i}" for i in range(12)], X, dl_cost=0.15)
            assert v.split is False

    def test_dl_cost_blocks_marginal_split(self):
        ids, X = _two_orthogonal()
        v = sheaf.subdivision_test("s1", ids, X, dl_cost=10.0)  # absurd price
        assert v.split is False

    def test_too_small_parts_block_split(self):
        a = np.zeros(768); a[0] = 1.0
        b = np.zeros(768); b[1] = 1.0
        X = np.vstack([_cluster(a, 10, 0.05, 7), _cluster(b, 1, 0.05, 8)])
        v = sheaf.subdivision_test("s1", [f"e{i}" for i in range(11)], X, dl_cost=0.15)
        assert v.split is False  # a 1-episode peer is not a peer
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_sheaf.py::TestSubdivisionGate -v`
Expected: FAIL — `AttributeError: module 'sheaf' has no attribute 'subdivision_test'`

- [ ] **Step 3: Implement** (append to `sheaf.py`)

```python
@dataclass
class Verdict:
    semantic_id: str
    split: bool
    parts: list[list[str]]
    ambiguous: list[str]
    energy_before: float
    part_energies: list[float]
    gain: float
    dl_cost: float
    persistence_checked: bool
    worst_edges: list

    def to_dict(self) -> dict:
        return {
            "semantic_id": self.semantic_id, "split": self.split,
            "parts": self.parts, "ambiguous": self.ambiguous,
            "energy_before": self.energy_before,
            "part_energies": self.part_energies, "gain": self.gain,
            "dl_cost": self.dl_cost,
            "persistence_checked": self.persistence_checked,
        }


def persistence_check(parts: list[list[str]]) -> bool:
    """Layer 4 slot — persistence regularization (survives-across-scales).

    Returns True until persistent homology lands; every event records
    persistence_checked=False so Layer 4 can audit what it would have blocked.
    """
    return True


def subdivision_test(semantic_id: str, episode_ids: list[str], X: np.ndarray,
                     dl_cost: float = 0.15, variance_threshold: float = 0.90,
                     max_dim: int = 8, min_part: int = 2) -> Verdict:
    ls = build_local_sheaf(semantic_id, episode_ids, X, variance_threshold, max_dim)
    res = cohesion_energy(ls)
    no_split = Verdict(semantic_id, False, [], [], res["energy"], [], 0.0,
                       dl_cost, False, res["worst_edges"])
    if res["energy"] == 0.0 or not res["fiedler"]:
        return no_split
    f = np.array(res["fiedler"])
    eps = 0.1 * float(np.abs(f).max())
    idx = {"a": [], "b": [], "amb": []}
    for i, fi in enumerate(f):
        key = "amb" if abs(fi) < eps else ("a" if fi > 0 else "b")
        idx[key].append(i)
    if len(idx["a"]) < min_part or len(idx["b"]) < min_part:
        return no_split
    parts_idx = [idx["a"], idx["b"]]
    part_energies = []
    for pi in parts_idx:
        sub = build_local_sheaf(semantic_id, [episode_ids[i] for i in pi],
                                X[pi], variance_threshold, max_dim)
        part_energies.append(cohesion_energy(sub)["energy"])
    n_assigned = sum(len(pi) for pi in parts_idx)
    weighted_after = sum((len(pi) / n_assigned) * e
                         for pi, e in zip(parts_idx, part_energies))
    gain = res["energy"] - weighted_after
    split = gain > dl_cost * (len(parts_idx) - 1) and persistence_check(
        [[episode_ids[i] for i in pi] for pi in parts_idx])
    return Verdict(
        semantic_id, split,
        [[episode_ids[i] for i in pi] for pi in parts_idx],
        [episode_ids[i] for i in idx["amb"]],
        res["energy"], part_energies, gain, dl_cost,
        False,  # persistence slot not yet built — recorded on every event
        res["worst_edges"],
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_sheaf.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add sheaf.py tests/test_sheaf.py
git commit -m "feat(sheaf): subdivision gate — DL-priced split with persistence slot"
```

---

### Task 5: apply_subdivision — atomic executor

**Files:**
- Modify: `sheaf.py`
- Test: `tests/test_sheaf_apply.py` (append)

Hub survives as common ground; peers minted per part inheriting kind/lane/confidence; provenance moves; ambiguous episodes stay on the hub; peer edges + event logged — **all in one transaction** (spec: partial splits cannot exist). Hub content rewritten only if episodes remain on it AND a hub_content was provided.

- [ ] **Step 1: Write the failing tests** (append; uses `tmp_db`, `fake_embedding` from conftest)

```python
import uuid as _uuid

import numpy as np
import pytest

import sheaf


def _seed_semantic(tmp_db, fake_embedding, n_eps=6):
    eps = []
    for i in range(n_eps):
        eid = f"ep-{i}"
        tmp_db.add_episode(id=eid, session_id="s", content=f"episode {i}",
                           embedding=fake_embedding())
        eps.append(eid)
    tmp_db.add_semantic(id="sem-1", content="conflated hub", kind="fact",
                        confidence=0.8, embedding=fake_embedding(),
                        source_episode_ids=eps, lane="personal")
    return eps


def _verdict(eps):
    return sheaf.Verdict(
        semantic_id="sem-1", split=True,
        parts=[eps[:3], eps[3:5]], ambiguous=[eps[5]],
        energy_before=0.9, part_energies=[0.1, 0.1], gain=0.7,
        dl_cost=0.15, persistence_checked=False, worst_edges=[],
    )


class TestApplySubdivision:
    def test_full_split(self, tmp_db, fake_embedding):
        eps = _seed_semantic(tmp_db, fake_embedding)
        result = sheaf.apply_subdivision(
            tmp_db, _verdict(eps),
            peer_contents=["peer one", "peer two"],
            hub_content="the shared residue",
            embed_fn=lambda text: fake_embedding(), site="sleep",
        )
        assert len(result["peer_ids"]) == 2
        p1 = tmp_db.get_semantic(result["peer_ids"][0])
        assert p1["content"] == "peer one"
        assert p1["kind"] == "fact" and p1["lane"] == "personal"
        assert set(p1["source_episode_ids"]) == set(eps[:3])
        hub = tmp_db.get_semantic("sem-1")
        assert hub["content"] == "the shared residue"     # episodes remained
        assert hub["source_episode_ids"] == [eps[5]]      # only the ambiguous one
        assert {p["peer_id"] for p in tmp_db.get_semantic_peers("sem-1")} \
            == set(result["peer_ids"])
        events = tmp_db.get_subdivision_events()
        assert events[0]["parent_id"] == "sem-1" and events[0]["site"] == "sleep"
        # peers are recallable: vectors exist
        for pid in result["peer_ids"]:
            row = tmp_db.conn.execute(
                "SELECT 1 FROM semantic_vectors WHERE id = ?", (pid,)).fetchone()
            assert row is not None

    def test_hub_content_kept_when_emptied(self, tmp_db, fake_embedding):
        eps = _seed_semantic(tmp_db, fake_embedding)
        v = _verdict(eps)
        v.parts = [eps[:3], eps[3:]]   # nothing ambiguous, hub empties
        v.ambiguous = []
        sheaf.apply_subdivision(tmp_db, v, ["peer one", "peer two"],
                                hub_content="ignored",
                                embed_fn=lambda t: fake_embedding(), site="sleep")
        hub = tmp_db.get_semantic("sem-1")
        assert hub["content"] == "conflated hub"   # left as-is per spec
        assert hub["source_episode_ids"] == []

    def test_atomicity_on_failure(self, tmp_db, fake_embedding):
        eps = _seed_semantic(tmp_db, fake_embedding)

        def exploding_embed(text):
            raise RuntimeError("embedder died mid-split")

        with pytest.raises(RuntimeError):
            sheaf.apply_subdivision(tmp_db, _verdict(eps), ["a", "b"],
                                    hub_content=None,
                                    embed_fn=exploding_embed, site="sleep")
        # store unchanged: no peers, provenance intact, no events
        assert tmp_db.get_semantic_peers("sem-1") == []
        assert set(tmp_db.get_semantic("sem-1")["source_episode_ids"]) == set(eps)
        assert tmp_db.get_subdivision_events() == []

    def test_peer_count_mismatch_rejected(self, tmp_db, fake_embedding):
        eps = _seed_semantic(tmp_db, fake_embedding)
        with pytest.raises(ValueError):
            sheaf.apply_subdivision(tmp_db, _verdict(eps), ["only one"],
                                    hub_content=None,
                                    embed_fn=lambda t: fake_embedding(), site="sleep")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_sheaf_apply.py -v`
Expected: new tests FAIL — `AttributeError: module 'sheaf' has no attribute 'apply_subdivision'`

- [ ] **Step 3: Implement** (append to `sheaf.py`; import `hashlib`, `datetime`/`timezone` at top)

```python
def apply_subdivision(storage, verdict: Verdict, peer_contents: list[str],
                      hub_content: str | None, embed_fn, site: str) -> dict:
    """Mint peers under the surviving hub. One transaction; partial splits
    cannot exist. embed_fn: str -> list[float] (the recall-side embedding
    used for new semantics — wire to the same call compress.commit uses)."""
    if len(peer_contents) != len(verdict.parts):
        raise ValueError(
            f"{len(verdict.parts)} parts but {len(peer_contents)} peer contents")
    parent = storage.get_semantic(verdict.semantic_id)
    if parent is None:
        raise ValueError(f"unknown semantic {verdict.semantic_id}")
    now = datetime.now(timezone.utc).isoformat()
    conn = storage.conn
    peer_ids = [str(uuid.uuid4()) for _ in verdict.parts]
    # Embed outside any partial writes so an embedder failure aborts cleanly
    peer_vecs = [embed_fn(c) for c in peer_contents]
    try:
        for pid, content, vec, part, p_energy in zip(
                peer_ids, peer_contents, peer_vecs, verdict.parts,
                verdict.part_energies):
            conn.execute(
                "INSERT INTO semantics (id, content, content_hash, kind,"
                " confidence, created_at, lane, auto_generated)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                (pid, content, hashlib.sha256(content.encode()).hexdigest(),
                 parent["kind"], parent["confidence"], now, parent["lane"]),
            )
            conn.execute(
                "INSERT INTO semantic_vectors (id, embedding) VALUES (?, ?)",
                (pid, struct.pack(f"<{len(vec)}f", *vec)),
            )
            for eid in part:
                conn.execute(
                    "DELETE FROM semantic_sources WHERE semantic_id = ?"
                    " AND episode_id = ?", (verdict.semantic_id, eid))
                conn.execute(
                    "INSERT INTO semantic_sources (semantic_id, episode_id)"
                    " VALUES (?, ?)", (pid, eid))
            conn.execute(
                "INSERT INTO semantic_peers (peer_id, parent_id,"
                " residual_energy, created_at) VALUES (?, ?, ?, ?)",
                (pid, verdict.semantic_id, p_energy, now))
        if verdict.ambiguous and hub_content:
            conn.execute(
                "UPDATE semantics SET content = ?, content_hash = ? WHERE id = ?",
                (hub_content, hashlib.sha256(hub_content.encode()).hexdigest(),
                 verdict.semantic_id))
        conn.execute(
            "INSERT INTO subdivision_events (id, parent_id, peer_ids,"
            " energy_before, energy_after, dl_cost, persistence_checked,"
            " site, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), verdict.semantic_id, json.dumps(peer_ids),
             verdict.energy_before,
             sum(verdict.part_energies) / max(len(verdict.part_energies), 1),
             verdict.dl_cost, int(verdict.persistence_checked), site, now))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"peer_ids": peer_ids, "parent_id": verdict.semantic_id}
```

Note (corrected during review): when `UPDATE semantics` rewrites hub content, the executor also DELETEs the hub's `semantic_vectors` row in the same transaction — the orphan-vector backfill keys on *missing* rows only, so deletion is what makes it re-embed the new content next startup. FTS stays correct via the update trigger meanwhile.
**Check during implementation:** the live `semantics` table may have NOT NULL columns beyond these (inspect `migrations/002_v3_layers.sql` and later). If so, extend the INSERT with their defaults — the test on `tmp_db` will catch any violation.

- [ ] **Step 4: Run to verify pass, then full suite**

Run: `.venv/bin/python -m pytest tests/test_sheaf_apply.py -v` → PASS
Run: `.venv/bin/python -m pytest tests/ -q` → all pass

- [ ] **Step 5: Commit**

```bash
git add sheaf.py tests/test_sheaf_apply.py
git commit -m "feat(sheaf): atomic subdivision executor — hub survives as common ground"
```

---

### Task 6: distill_subdivision — peer content via Ollama

**Files:**
- Modify: `sheaf.py`
- Test: `tests/test_sheaf_sleep.py` (start the file)

Same transport pattern as `framing.py` (`urllib`, temperature 0, JSON body to `http://localhost:11434/api/generate`, model from the framing config). Returns `(peer_contents, hub_content)` or `None` when Ollama is unavailable/unparseable — the caller queues.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for sheaf sleep pass and content distillation."""

import json

import sheaf


class TestDistillSubdivision:
    def test_parses_valid_response(self, monkeypatch):
        reply = json.dumps({"peers": ["About Mistborn.", "About Perfect State."],
                            "hub": "Reading sessions in general."})
        monkeypatch.setattr(sheaf, "_ollama_generate", lambda prompt, cfg: reply)
        out = sheaf.distill_subdivision(
            parent_content="Reading sessions: Mistborn and Perfect State",
            part_episode_contents=[["read mistborn ch1"], ["read perfect state"]],
            has_ambiguous=True, framing_cfg=None)
        assert out == (["About Mistborn.", "About Perfect State."],
                       "Reading sessions in general.")

    def test_none_on_transport_failure(self, monkeypatch):
        monkeypatch.setattr(sheaf, "_ollama_generate", lambda prompt, cfg: None)
        assert sheaf.distill_subdivision("x", [["a"], ["b"]], False, None) is None

    def test_none_on_wrong_peer_count(self, monkeypatch):
        reply = json.dumps({"peers": ["only one"], "hub": None})
        monkeypatch.setattr(sheaf, "_ollama_generate", lambda prompt, cfg: reply)
        assert sheaf.distill_subdivision("x", [["a"], ["b"]], False, None) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_sheaf_sleep.py -v`
Expected: FAIL — no attribute `distill_subdivision`

- [ ] **Step 3: Implement** (append to `sheaf.py`; `import urllib.request` at top)

```python
def _ollama_generate(prompt: str, framing_cfg) -> str | None:
    """Same transport as framing.py — model/url/timeout from FramingConfig."""
    import urllib.request
    model = getattr(framing_cfg, "model", "gemma4:31b")
    url = getattr(framing_cfg, "ollama_url", "http://localhost:11434/api/generate")
    timeout = getattr(framing_cfg, "timeout", 60)
    body = {"model": model, "prompt": prompt, "stream": False,
            "options": {"temperature": 0.0, "num_predict": 400}}
    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read()).get("response", "")
    except Exception:
        logger.warning("subdivision distill LLM call failed", exc_info=True)
        return None


def distill_subdivision(parent_content: str,
                        part_episode_contents: list[list[str]],
                        has_ambiguous: bool, framing_cfg) -> tuple | None:
    """Write peer contents (one per part) and optionally the hub residue.
    Returns (peer_contents, hub_content_or_None) or None on failure."""
    sections = []
    for i, part in enumerate(part_episode_contents):
        sample = "\n".join(f"  - {c[:200]}" for c in part[:8])
        sections.append(f"PART {i + 1}:\n{sample}")
    hub_clause = (
        '"hub": a 1-2 sentence summary of only what ALL parts genuinely share'
        if has_ambiguous else '"hub": null')
    prompt = (
        "A memory summary conflates distinct groups of experiences.\n"
        f"CURRENT SUMMARY: {parent_content[:400]}\n\n"
        + "\n\n".join(sections)
        + "\n\nReply with ONLY a JSON object: {\"peers\": [one 1-3 sentence"
        " summary per PART, in order], " + hub_clause + "}."
    )
    raw = _ollama_generate(prompt, framing_cfg)
    if not raw:
        return None
    try:
        start, end = raw.index("{"), raw.rindex("}") + 1
        data = json.loads(raw[start:end])
        peers = data.get("peers")
        if (not isinstance(peers, list)
                or len(peers) != len(part_episode_contents)
                or not all(isinstance(p, str) and p.strip() for p in peers)):
            return None
        hub = data.get("hub")
        return ([p.strip() for p in peers],
                hub.strip() if isinstance(hub, str) and hub.strip() else None)
    except (ValueError, json.JSONDecodeError):
        logger.warning("subdivision distill returned unparseable output")
        return None
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_sheaf_sleep.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add sheaf.py tests/test_sheaf_sleep.py
git commit -m "feat(sheaf): peer-content distillation via Ollama, None on failure"
```

---

### Task 7: run_sleep_pass — budgeted, rate-limited, queueing

**Files:**
- Modify: `sheaf.py`
- Test: `tests/test_sheaf_sleep.py` (append)

Flow: rate-limit (30 min via `memory_log`, mirroring `apply_decay` — read its exact column names at storage.py:439–471 and match them) → measure energy for every semantic with ≥ `min_episodes` provenance (both lanes) → rank desc → for the hottest, run `subdivision_test`; apply at most `sleep_budget` passing verdicts. Distill failure → queue verdict, no split. Each applied split also `add_episode`s a narration. Returns a report dict. Never raises (catches everything, logs, returns partial report).

- [ ] **Step 1: Write the failing tests** (append; build a store with one conflated + one tight semantic using deterministic embeddings, monkeypatch `distill_subdivision`)

```python
import numpy as np


def _emb(axis: int, noise: float, seed: int) -> list[float]:
    rng = np.random.default_rng(seed)
    v = np.zeros(768); v[axis] = 1.0
    v = v + noise * rng.standard_normal(768)
    return (v / np.linalg.norm(v)).tolist()


def _seed_store(tmp_db):
    """sem-hot conflates axes 0 and 1; sem-cool is tight on axis 2."""
    hot_eps, cool_eps = [], []
    for i in range(10):
        eid = f"hot-{i}"
        tmp_db.add_episode(id=eid, session_id="s", content=f"hot episode {i}",
                           embedding=_emb(0 if i < 5 else 1, 0.05, i))
        hot_eps.append(eid)
    for i in range(6):
        eid = f"cool-{i}"
        tmp_db.add_episode(id=eid, session_id="s", content=f"cool episode {i}",
                           embedding=_emb(2, 0.05, 50 + i))
        cool_eps.append(eid)
    tmp_db.add_semantic(id="sem-hot", content="conflated", kind="fact",
                        confidence=0.8, embedding=_emb(0, 0.3, 99),
                        source_episode_ids=hot_eps)
    tmp_db.add_semantic(id="sem-cool", content="coherent", kind="fact",
                        confidence=0.8, embedding=_emb(2, 0.05, 98),
                        source_episode_ids=cool_eps)


class TestSleepPass:
    def _run(self, tmp_db, monkeypatch, **kw):
        monkeypatch.setattr(
            sheaf, "distill_subdivision",
            lambda parent, parts, amb, cfg: ([f"peer {i}" for i in range(len(parts))],
                                             "shared" if amb else None))
        from config import CohesionConfig
        return sheaf.run_sleep_pass(
            tmp_db, embed_fn=lambda t: _emb(5, 0.1, hash(t) % 1000),
            framing_cfg=None, cfg=CohesionConfig(), **kw)

    def test_splits_hot_not_cool(self, tmp_db, monkeypatch):
        _seed_store(tmp_db)
        report = self._run(tmp_db, monkeypatch)
        assert "sem-hot" in [s["parent_id"] for s in report["subdivided"]]
        assert tmp_db.get_semantic_peers("sem-hot") != []
        assert tmp_db.get_semantic_peers("sem-cool") == []

    def test_narration_episode_written(self, tmp_db, monkeypatch):
        _seed_store(tmp_db)
        self._run(tmp_db, monkeypatch)
        row = tmp_db.conn.execute(
            "SELECT content FROM episodes WHERE content LIKE"
            " 'Sleep-time subdivision:%'").fetchone()
        assert row is not None

    def test_budget_respected(self, tmp_db, monkeypatch):
        _seed_store(tmp_db)
        from config import CohesionConfig
        monkeypatch.setattr(
            sheaf, "distill_subdivision",
            lambda parent, parts, amb, cfg: ([f"p{i}" for i in range(len(parts))], None))
        report = sheaf.run_sleep_pass(
            tmp_db, embed_fn=lambda t: _emb(5, 0.1, 1),
            framing_cfg=None, cfg=CohesionConfig(sleep_budget=0))
        assert report["subdivided"] == []

    def test_distill_failure_queues(self, tmp_db, monkeypatch):
        _seed_store(tmp_db)
        monkeypatch.setattr(sheaf, "distill_subdivision",
                            lambda parent, parts, amb, cfg: None)
        from config import CohesionConfig
        report = sheaf.run_sleep_pass(
            tmp_db, embed_fn=lambda t: _emb(5, 0.1, 1),
            framing_cfg=None, cfg=CohesionConfig())
        assert report["subdivided"] == []
        assert "sem-hot" in [q["parent_id"] for q in tmp_db.get_queued_subdivisions()]
        assert tmp_db.get_semantic_peers("sem-hot") == []

    def test_rate_limited_second_run_skips(self, tmp_db, monkeypatch):
        _seed_store(tmp_db)
        self._run(tmp_db, monkeypatch)
        report2 = self._run(tmp_db, monkeypatch)
        assert report2.get("skipped") == "rate_limited"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_sheaf_sleep.py -v`
Expected: new tests FAIL — no attribute `run_sleep_pass`

- [ ] **Step 3: Implement** (append to `sheaf.py`)

```python
def _episode_matrix(conn, semantic_id: str):
    rows = conn.execute(
        "SELECT ss.episode_id, ev.embedding FROM semantic_sources ss"
        " JOIN episode_vectors ev ON ev.id = ss.episode_id"
        " WHERE ss.semantic_id = ?", (semantic_id,)).fetchall()
    if not rows:
        return [], None
    ids = [r[0] for r in rows]
    X = np.stack([_unpack_embedding(r[1]) for r in rows])
    return ids, X


def measure_all(storage, cfg) -> list[dict]:
    """Energy for every semantic with enough provenance. Read-only."""
    sem_rows = storage.conn.execute(
        "SELECT semantic_id, COUNT(*) AS n FROM semantic_sources"
        " GROUP BY semantic_id HAVING n >= ?", (cfg.min_episodes,)).fetchall()
    out = []
    for r in sem_rows:
        ids, X = _episode_matrix(storage.conn, r[0])
        if len(ids) < cfg.min_episodes:
            continue  # episodes lacking vectors shrink the neighborhood
        ls = build_local_sheaf(r[0], ids, X, cfg.variance_threshold,
                               cfg.max_subspace_dim)
        res = cohesion_energy(ls)
        out.append({"semantic_id": r[0], "energy": res["energy"], "n": len(ids),
                    "worst_edges": res["worst_edges"][:3]})
    out.sort(key=lambda d: d["energy"], reverse=True)
    return out


def _rate_limited(conn, minutes: int = 30) -> bool:
    # Mirror apply_decay's memory_log mechanism (storage.py:439-471) —
    # match its exact column names when implementing.
    try:
        row = conn.execute(
            "SELECT timestamp FROM memory_log WHERE event_type = 'cohesion_pass'"
            " ORDER BY timestamp DESC LIMIT 1").fetchone()
        if row is None:
            return False
        from datetime import datetime, timedelta
        last = datetime.fromisoformat(row[0])
        return datetime.now(timezone.utc) - last < timedelta(minutes=minutes)
    except Exception:
        return False


def run_sleep_pass(storage, embed_fn, framing_cfg, cfg) -> dict:
    """Budgeted sleep-time subdivision. Fails toward leaving the store unchanged."""
    report = {"measured": [], "subdivided": [], "queued": []}
    try:
        if _rate_limited(storage.conn):
            return {"skipped": "rate_limited"}
        ranked = measure_all(storage, cfg)
        report["measured"] = ranked[:10]
        applied = 0
        for entry in ranked:
            if applied >= cfg.sleep_budget:
                break
            sid = entry["semantic_id"]
            ids, X = _episode_matrix(storage.conn, sid)
            verdict = subdivision_test(sid, ids, X, cfg.dl_cost,
                                       cfg.variance_threshold, cfg.max_subspace_dim)
            if not verdict.split:
                continue
            parent = storage.get_semantic(sid)
            part_contents = []
            for part in verdict.parts:
                rows = storage.conn.execute(
                    "SELECT content FROM episodes WHERE id IN (%s)"
                    % ",".join("?" * len(part)), part).fetchall()
                part_contents.append([r[0] for r in rows])
            distilled = distill_subdivision(parent["content"], part_contents,
                                            bool(verdict.ambiguous), framing_cfg)
            if distilled is None:
                storage.queue_subdivision(sid, verdict.to_dict())
                report["queued"].append(sid)
                continue
            peer_contents, hub_content = distilled
            result = apply_subdivision(storage, verdict, peer_contents,
                                       hub_content, embed_fn, site="sleep")
            storage.dequeue_subdivision(sid)
            storage.add_episode(
                id=str(uuid.uuid4()), session_id=None,
                content=(f"Sleep-time subdivision: '{parent['content'][:80]}'"
                         f" split into {len(peer_contents)} peers"
                         f" (energy {verdict.energy_before:.2f} ->"
                         f" {sum(verdict.part_energies) / len(verdict.part_energies):.2f},"
                         f" gain {verdict.gain:.2f}, persistence unchecked)."),
                context={"topic": "sheaf-subdivision", "parent_id": sid,
                         "peer_ids": result["peer_ids"]})
            report["subdivided"].append({"parent_id": sid, **result})
            applied += 1
        storage.conn.execute(
            "INSERT INTO memory_log (event_type, timestamp) VALUES (?, ?)",
            ("cohesion_pass", datetime.now(timezone.utc).isoformat()))
        storage.conn.commit()
    except Exception:
        logger.warning("cohesion sleep pass aborted", exc_info=True)
    return report
```

(Narration episode has no embedding — the existing orphan-vector backfill embeds it next startup. The `memory_log` INSERT must match the table's real columns; check how `apply_decay` writes/reads it and adjust both here and in `_rate_limited`.)

- [ ] **Step 4: Run to verify pass, then full suite**

Run: `.venv/bin/python -m pytest tests/test_sheaf_sleep.py -v` → PASS
Run: `.venv/bin/python -m pytest tests/ -q` → all pass

- [ ] **Step 5: Commit**

```bash
git add sheaf.py tests/test_sheaf_sleep.py
git commit -m "feat(sheaf): budgeted rate-limited sleep pass with LLM-wait queue"
```

---

### Task 8: server wiring

**Files:**
- Modify: `server.py` (consolidation sequence in `_init`, after the coherence check ~line 412)

- [ ] **Step 1: Add the consolidation step** (no new unit test — the pass itself is fully tested; this is glue, covered by the existing server import smoke test)

```python
# Sheaf cohesion sleep pass (spec: 2026-06-13-sheaf-cohesion-design.md)
try:
    from sheaf import run_sleep_pass
    _cohesion_report = run_sleep_pass(
        _storage,
        embed_fn=lambda text: <same embedding call compress.commit uses for new semantics — read compress.py commit() and reuse it verbatim>,
        framing_cfg=getattr(_compressor, "_framer", None) and _compressor._framer._config or None,
        cfg=_config.cohesion,
    )
    if _cohesion_report.get("subdivided"):
        logger.info("cohesion pass subdivided: %s",
                    [s["parent_id"] for s in _cohesion_report["subdivided"]])
except Exception:
    logger.warning("cohesion sleep pass failed", exc_info=True)
```

**Resolve the two placeholders while implementing** (they are deliberate, single-line lookups): (a) `embed_fn` — open `compress.py` `commit()` and copy the exact embedding invocation used when storing a `new` semantic; (b) the framing config attribute — open `server.py` `_init` to see how the `Compressor`'s `framer` is constructed and pass that object's config (or `None` if no framer).

- [ ] **Step 2: Verify**

Run: `.venv/bin/python -c "import server; print('imports ok')"` (with `ENGRAM_PROJECT_ROOT=/Users/kairos/Projects/engram`) → no errors
Run: `.venv/bin/python -m pytest tests/ -q` → all pass

- [ ] **Step 3: Commit**

```bash
git add server.py
git commit -m "feat(sheaf): wire sleep pass into startup consolidation"
```

---

### Task 9: compression-time gate

**Files:**
- Modify: `compress.py` (`Compressor.__init__`, `cluster_episodes`, `commit`)
- Modify: `server.py` (pass `cohesion_config=_config.cohesion` where `Compressor(...)` is constructed)
- Test: `tests/test_sheaf_compress.py`

Behavior: after clusters form, any cluster with ≥ `min_episodes` episodes is gate-tested on its episode embeddings. A splitting cluster is **replaced by one preview cluster per part** (so `commit`'s positional summary mapping is untouched), each annotated with `split_group` (shared uuid) and `cohesion` evidence; ambiguous episodes join the part whose centroid is nearer (no hub exists yet — spec). At `commit`, after semantics are created, every `split_group` with ≥2 new semantics gets sibling resonance edges.

- [ ] **Step 1: Write the failing tests**

```python
"""Compression-time sheaf gate tests."""

import numpy as np
import pytest

from compress import Compressor
from config import CohesionConfig, CompressionConfig


def _emb(axis, noise, seed):
    rng = np.random.default_rng(seed)
    v = np.zeros(768); v[axis] = 1.0
    v = v + noise * rng.standard_normal(768)
    return (v / np.linalg.norm(v)).tolist()


class FakeEmbedder:
    """Returns the episode's stored embedding at cluster time; deterministic
    vector for new summary content. Match the provider interface compress.py
    actually calls — read cluster_episodes/commit and adapt method names."""
    def __init__(self, table):
        self._table = table

    def embed(self, texts, prefix=None):
        return [self._table.get(t, _emb(5, 0.1, abs(hash(t)) % 1000))
                for t in texts]


@pytest.fixture
def conflated_compressor(tmp_db):
    table = {}
    for i in range(10):
        content = f"episode about topic {'A' if i < 5 else 'B'} number {i}"
        table[content] = _emb(0 if i < 5 else 1, 0.05, i)
        tmp_db.add_episode(id=f"ep-{i}", session_id="s", content=content,
                           embedding=table[content])
    comp = Compressor(tmp_db, FakeEmbedder(table), config=CompressionConfig(),
                      cohesion_config=CohesionConfig())
    return comp, tmp_db


class TestCompressionGate:
    def test_conflated_cluster_is_pre_partitioned(self, conflated_compressor):
        comp, _db = conflated_compressor
        preview = comp.cluster_episodes()
        split = [c for c in preview["clusters"] if c.get("split_group")]
        # if clustering merged A+B into one cluster, the gate must split it
        if split:
            groups = {}
            for c in split:
                groups.setdefault(c["split_group"], []).append(c)
            assert any(len(v) >= 2 for v in groups.values())
            assert all("cohesion" in c for c in split)

    def test_sibling_resonance_after_commit(self, conflated_compressor):
        comp, db = conflated_compressor
        preview = comp.cluster_episodes()
        split = [c for c in preview["clusters"] if c.get("split_group")]
        if not split:
            pytest.skip("clustering separated the topics on its own")
        summaries = []
        for c in preview["clusters"]:
            summaries.append({"content": f"summary of {len(c['episodes'])} eps",
                              "kind": "fact", "action": "new"})
        result = comp.commit(preview["compress_id"], summaries)
        assert result["semantics_created"] >= 2
        row = db.conn.execute(
            "SELECT COUNT(*) FROM resonances WHERE layer_a = 'semantic'"
            " AND layer_b = 'semantic'").fetchone()
        assert row[0] >= 1
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_sheaf_compress.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'cohesion_config'`

- [ ] **Step 3: Implement in compress.py**

`__init__`: add `cohesion_config=None` parameter, store as `self._cohesion`.

In `cluster_episodes`, after the clusters list is built and before returning (the cluster dicts and the episode-embedding arrays are both in scope there — reuse the same vectors that went into `fclusterdata`):

```python
if self._cohesion is not None:
    from sheaf import subdivision_test
    gated = []
    for cluster in clusters:
        eps = cluster["episodes"]
        if len(eps) < self._cohesion.min_episodes:
            gated.append(cluster)
            continue
        ids = [e["id"] for e in eps]
        X = np.stack([emb_by_id[i] for i in ids])  # reuse clustering vectors
        verdict = subdivision_test(ids=ids, X=X, semantic_id="(cluster)",
                                   dl_cost=self._cohesion.dl_cost,
                                   variance_threshold=self._cohesion.variance_threshold,
                                   max_dim=self._cohesion.max_subspace_dim)
        if not verdict.split:
            gated.append(cluster)
            continue
        group = str(uuid.uuid4())
        parts = [list(p) for p in verdict.parts]
        # no hub at compression time: ambiguous episodes join the nearer part
        for amb in verdict.ambiguous:
            cents = [np.mean([emb_by_id[i] for i in p], axis=0) for p in parts]
            v = np.array(emb_by_id[amb])
            parts[int(np.argmax([c @ v for c in cents]))].append(amb)
        by_id = {e["id"]: e for e in eps}
        for part, p_energy in zip(parts, verdict.part_energies):
            sub = dict(cluster)
            sub["episodes"] = [by_id[i] for i in part]
            sub["centroid"] = np.mean([emb_by_id[i] for i in part], axis=0).tolist()
            sub["split_group"] = group
            sub["cohesion"] = {"energy_before": verdict.energy_before,
                               "gain": verdict.gain, "part_energy": p_energy}
            gated.append(sub)
    clusters = gated
```

(`emb_by_id` stands for whatever mapping episode-id → clustering vector exists at that point in the function — bind to the actual local variable name when implementing.)

In `commit`, after new semantics are created (track `created_by_group: dict[str, list[tuple[id, centroid]]]` while iterating clusters that carry `split_group`):

```python
for group, members in created_by_group.items():
    if len(members) < 2:
        continue
    now = datetime.now(timezone.utc).isoformat()
    for (id_a, cen_a), (id_b, cen_b) in itertools.combinations(members, 2):
        a, b = sorted((id_a, id_b))
        sim = float(np.dot(cen_a, cen_b) /
                    (np.linalg.norm(cen_a) * np.linalg.norm(cen_b) + 1e-12))
        self._storage.conn.execute(
            "INSERT OR IGNORE INTO resonances (id, memory_a, layer_a, memory_b,"
            " layer_b, similarity, weight, strength, co_occurrences,"
            " created_at, last_seen) VALUES (?, ?, 'semantic', ?, 'semantic',"
            " ?, 1.0, 0.5, 1, ?, ?)",
            (str(uuid.uuid4()), a, b, sim, now, now))
    self._storage.conn.commit()
```

Also log the split in the audit trail (same loop): `self._storage.log_subdivision_event(id=str(uuid.uuid4()), parent_id=f"cluster:{group}", peer_ids=[m[0] for m in members], energy_before=<from the first member cluster's cohesion dict>, energy_after=<mean part_energy>, dl_cost=self._cohesion.dl_cost, persistence_checked=False, site="compress")` — thread the `cohesion` dict through to commit alongside `split_group`.

In `server.py`, add `cohesion_config=_config.cohesion` to the `Compressor(...)` construction in `_init`.

- [ ] **Step 4: Run to verify pass, then full suite**

Run: `.venv/bin/python -m pytest tests/test_sheaf_compress.py tests/ -q` → all pass

- [ ] **Step 5: Commit**

```bash
git add compress.py server.py tests/test_sheaf_compress.py
git commit -m "feat(sheaf): compression-time gate — pre-partitioned clusters, sibling resonance"
```

---

### Task 10: reflect(focus="cohesion") + peer edges in get_neighbors

**Files:**
- Modify: `reflection.py`, `storage.py` (`get_neighbors`)
- Test: `tests/test_sheaf_reflect.py`

- [ ] **Step 1: Write the failing tests**

```python
"""reflect(focus='cohesion') and peer-edge neighbor tests."""

import numpy as np

from reflection import Reflector


def _emb(axis, noise, seed):
    rng = np.random.default_rng(seed)
    v = np.zeros(768); v[axis] = 1.0
    v = v + noise * rng.standard_normal(768)
    return (v / np.linalg.norm(v)).tolist()


class TestReflectCohesion:
    def test_focus_returns_ranked_energies(self, tmp_db):
        eps = []
        for i in range(8):
            eid = f"e{i}"
            tmp_db.add_episode(id=eid, session_id="s", content=f"ep {i}",
                               embedding=_emb(0 if i < 4 else 1, 0.05, i))
            eps.append(eid)
        tmp_db.add_semantic(id="sem-1", content="conflated", kind="fact",
                            confidence=0.8, embedding=_emb(0, 0.3, 9),
                            source_episode_ids=eps)
        r = Reflector(tmp_db)
        out = r.reflect(focus="cohesion")
        coh = out["cohesion"]
        assert coh["semantics_measured"] == 1
        assert coh["hottest"][0]["semantic_id"] == "sem-1"
        assert coh["hottest"][0]["energy"] > 0.8
        assert "recent_events" in coh and "queued" in coh

    def test_empty_store(self, tmp_db):
        out = Reflector(tmp_db).reflect(focus="cohesion")
        assert out["cohesion"]["semantics_measured"] == 0


class TestPeerNeighbors:
    def test_peer_edge_appears(self, tmp_db):
        for sid in ("sem-1", "peer-1"):
            tmp_db.add_semantic(id=sid, content=f"content {sid}", kind="fact",
                                confidence=0.8, embedding=_emb(0, 0.1, 1),
                                source_episode_ids=[])
        tmp_db.add_semantic_peer(peer_id="peer-1", parent_id="sem-1",
                                 residual_energy=0.1)
        neighbors = tmp_db.get_neighbors("sem-1")
        peer = [n for n in neighbors if n["connection_type"] == "peer"]
        assert peer and peer[0]["id"] == "peer-1"
        # and symmetric from the peer side
        back = [n for n in tmp_db.get_neighbors("peer-1")
                if n["connection_type"] == "peer"]
        assert back and back[0]["id"] == "sem-1"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_sheaf_reflect.py -v`
Expected: FAIL — `reflect(focus="cohesion")` falls through to the default multi-key dict (no `"cohesion"` key) / no peer connection_type

- [ ] **Step 3: Implement**

`reflection.py` — add the method and a dispatch branch (`elif focus == "cohesion": return {"cohesion": self.analyze_cohesion()}`); do NOT add it to the no-focus default (it is O(semantics × eigh) — heavier than the other foci):

```python
def analyze_cohesion(self) -> dict:
    """Sheaf cohesion: global energy picture, hottest semantics, audit trail."""
    from config import CohesionConfig
    from sheaf import measure_all
    measured = measure_all(self._storage, CohesionConfig())
    hottest = []
    for entry in measured[:5]:
        sem = self._storage.get_semantic(entry["semantic_id"])
        edges = []
        for ea, eb, r in entry["worst_edges"]:
            rows = self._storage.conn.execute(
                "SELECT id, substr(content, 1, 80) FROM episodes"
                " WHERE id IN (?, ?)", (ea, eb)).fetchall()
            edges.append({"residual": round(r, 4),
                          "episodes": {row[0]: row[1] for row in rows}})
        hottest.append({"semantic_id": entry["semantic_id"],
                        "content": (sem or {}).get("content", "")[:120],
                        "energy": round(entry["energy"], 3),
                        "episodes": entry["n"], "worst_edges": edges})
    return {
        "semantics_measured": len(measured),
        "mean_energy": (round(sum(m["energy"] for m in measured)
                              / len(measured), 3) if measured else None),
        "hottest": hottest,
        "recent_events": self._storage.get_subdivision_events(limit=10),
        "queued": self._storage.get_queued_subdivisions(),
    }
```

`storage.py` — inside `get_neighbors`, alongside the resonance/provenance sections:

```python
peer_rows = self.conn.execute(
    "SELECT parent_id AS other, residual_energy FROM semantic_peers"
    " WHERE peer_id = ?"
    " UNION SELECT peer_id AS other, residual_energy FROM semantic_peers"
    " WHERE parent_id = ?", (memory_id, memory_id)).fetchall()
for r in peer_rows:
    sem = self.get_semantic(r["other"])
    if sem:
        neighbors.append({
            "id": r["other"], "content": sem["content"][:300],
            "layer": "semantic", "connection_type": "peer",
            "connection_strength": 1.0 - (r["residual_energy"] or 0.0),
        })
```

(Bind to the actual accumulator variable name in `get_neighbors` — verify it's `neighbors` when implementing.)

- [ ] **Step 4: Run to verify pass, then full suite**

Run: `.venv/bin/python -m pytest tests/test_sheaf_reflect.py tests/ -q` → all pass

- [ ] **Step 5: Commit**

```bash
git add reflection.py storage.py tests/test_sheaf_reflect.py
git commit -m "feat(sheaf): reflect(focus=cohesion) and peer edges in graph neighbors"
```

---

### Task 11: calibration CLI, docs, final verification

**Files:**
- Modify: `sheaf.py` (`__main__` block), `CLAUDE.md`

- [ ] **Step 1: Add the read-only calibration entry point** (append to `sheaf.py`)

```python
if __name__ == "__main__":
    # Read-only calibration: python sheaf.py /path/to/graph.db
    # The spec's acceptance gate: run against a COPY of the live store and
    # check that known-conflated semantics measure hot and known-coherent cool.
    import sqlite3
    import sys

    import sqlite_vec

    from config import CohesionConfig

    db = sys.argv[1]
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    cfg = CohesionConfig()

    class _RO:  # minimal storage shim for measure_all
        def __init__(self, conn):
            self.conn = conn

    ranked = measure_all(_RO(conn), cfg)
    print(f"{'energy':>7}  {'n':>4}  semantic")
    for m in ranked:
        row = conn.execute("SELECT substr(content, 1, 70) FROM semantics"
                           " WHERE id = ?", (m["semantic_id"],)).fetchone()
        print(f"{m['energy']:7.3f}  {m['n']:4d}  {row[0] if row else m['semantic_id']}")
```

- [ ] **Step 2: Run calibration against a copy of the live store**

```bash
cp /Users/kairos/Projects/engram/.engram/instances/engram/graph.db /tmp/engram-calib.db
.venv/bin/python sheaf.py /tmp/engram-calib.db
```

Expected (spec acceptance): "Mistborn + Perfect State" (149 eps) measures hot (top quartile); the Prism semantic (85 eps, one topic) measures cool (bottom half). **If not, tune `[cohesion]` defaults and re-run — do not proceed to live operation with an uncalibrated gate; report the table to Kairos either way.**

- [ ] **Step 3: Update CLAUDE.md**

Add `sheaf.py` to the Key Files table: `| sheaf.py | Cellular-sheaf cohesion — energy metric, subdivision gate, sleep pass |`. Add an architecture paragraph after "Memory lanes" summarizing: cohesion energy (spectral, in the semantic's subspace), gate rule (DL-priced, persistence slot stubbed), hub-as-common-ground, two gate sites, `reflect(focus="cohesion")`, calibration CLI. Update the test count in the Testing section to the new total.

- [ ] **Step 4: Full suite + final review**

Run: `.venv/bin/python -m pytest tests/ -q` → all pass
Then: REQUIRED SUB-SKILL `superpowers:requesting-code-review` for the whole feature (the assessment build's lesson: the final whole-feature review finds what per-task reviews structurally cannot).

- [ ] **Step 5: Commit**

```bash
git add sheaf.py CLAUDE.md
git commit -m "feat(sheaf): read-only calibration CLI + docs"
```

---

## Plan self-review notes

- **Spec coverage:** mechanism (T3), gate rule + persistence slot (T4), map home/hub survival/ambiguous-stay (T5), Ollama distillation + fail-toward-unchanged (T6), budget/rate-limit/queue/narration (T7), server wiring (T8), compression site + sibling resonance + lane purity via lane-pure clustering (T9), reflect + graph surfaces (T10), config knobs (T2), calibration acceptance (T11). Spec's `graph_view` annotation is realized through `get_neighbors` peer edges (which both `wander` and `graph_view` consume).
- **Known deliberate lookups for the implementer:** `memory_log` column names (mirror `apply_decay`), embedding call for new semantics (mirror `compress.commit`), local variable names in `cluster_episodes`/`get_neighbors`, NOT NULL columns on `semantics`. Each is anchored to a specific file/function to read.
- **MCP server restart** is required after implementation for live tools to see migration 020 (the standing instinct about server code changes applies).
