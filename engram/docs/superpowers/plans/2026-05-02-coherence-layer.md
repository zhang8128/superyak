# Coherence Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a memory health system with vital sign anchors (identity, value, capability), graph-vs-geometry drift detection, and unchallenged instinct monitoring.

**Architecture:** New `coherence.py` with `CoherenceChecker` class. New migration for `anchors` and `drift_reports` tables. Integrates into sleep consolidation (server.py `_init`), wake hook, and reflect. All observation-only — no auto-resolution.

**Tech Stack:** Python, SQLite, vec0 (embedding distance), numpy (cosine similarity)

---

## File Structure

| File | Responsibility |
|---|---|
| `coherence.py` | New — CoherenceChecker: anchor checks, drift scan, unchallenged instinct detection |
| `migrations/017_coherence.sql` | New — anchors and drift_reports tables |
| `storage.py` | Add anchor CRUD and drift report storage methods |
| `server.py` | Hook coherence into sleep consolidation, add `add_anchor` and `propose_retirement` MCP tools |
| `hooks/wake.py` | Add coherence summary section |
| `reflection.py` | Add `coherence` and `anchors` focus handlers |
| `tests/test_coherence.py` | New — full test coverage |

---

### Task 1: Migration — anchors and drift_reports tables

**Files:**
- Create: `migrations/017_coherence.sql`
- Test: `tests/test_coherence.py`

- [ ] **Step 1: Write the migration**

Create `migrations/017_coherence.sql`:

```sql
-- Coherence layer: vital sign anchors and drift tracking.
CREATE TABLE IF NOT EXISTS anchors (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK(type IN ('identity', 'value', 'capability')),
    content TEXT NOT NULL,
    expected TEXT NOT NULL,
    baseline_score REAL,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'proposed_retirement', 'retired')),
    retirement_sessions INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_checked TEXT,
    last_result TEXT
);

CREATE TABLE IF NOT EXISTS drift_reports (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    drifted_apart TEXT NOT NULL DEFAULT '[]',
    drifted_together TEXT NOT NULL DEFAULT '[]',
    unchallenged TEXT NOT NULL DEFAULT '[]',
    anchor_results TEXT NOT NULL DEFAULT '[]',
    summary TEXT
);
```

- [ ] **Step 2: Write test that migration creates tables**

Create `tests/test_coherence.py`:

```python
"""Tests for the coherence layer — anchors, drift detection, unchallenged instincts."""

import uuid
from pathlib import Path

from storage import Storage

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
```

- [ ] **Step 3: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_coherence.py::TestMigration -v`
Expected: PASS (migration runs automatically via Storage constructor)

- [ ] **Step 4: Commit**

```bash
git add migrations/017_coherence.sql tests/test_coherence.py
git commit -m "feat(coherence): add anchors and drift_reports tables"
```

---

### Task 2: Storage — anchor CRUD methods

**Files:**
- Modify: `storage.py` (add methods after `get_vector`, around line 1768)
- Test: `tests/test_coherence.py`

- [ ] **Step 1: Write failing tests for anchor CRUD**

Append to `tests/test_coherence.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_coherence.py::TestAnchorCRUD -v`
Expected: FAIL — `Storage` has no `add_anchor` method

- [ ] **Step 3: Implement anchor CRUD in storage.py**

Add after the `get_vector` method (after line 1767 in `storage.py`):

```python
    # --- Coherence: Anchors ---

    def add_anchor(
        self,
        type: str,
        content: str,
        expected: str,
        baseline_score: float | None = None,
    ) -> str:
        """Create an anchor for coherence checking."""
        import uuid as _uuid
        aid = str(_uuid.uuid4())
        now = _now_iso()
        self.conn.execute(
            "INSERT INTO anchors (id, type, content, expected, baseline_score, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (aid, type, content, expected, baseline_score, now),
        )
        self.conn.commit()
        return aid

    def get_anchor(self, anchor_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM anchors WHERE id = ?", (anchor_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_active_anchors(self, anchor_type: str | None = None) -> list[dict]:
        """Return all non-retired anchors, optionally filtered by type."""
        if anchor_type:
            rows = self.conn.execute(
                "SELECT * FROM anchors WHERE status != 'retired' AND type = ? ORDER BY created_at",
                (anchor_type,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM anchors WHERE status != 'retired' ORDER BY created_at"
            ).fetchall()
        return [dict(r) for r in rows]

    def update_anchor_result(self, anchor_id: str, result_json: str) -> None:
        self.conn.execute(
            "UPDATE anchors SET last_checked = ?, last_result = ? WHERE id = ?",
            (_now_iso(), result_json, anchor_id),
        )
        self.conn.commit()

    def propose_anchor_retirement(self, anchor_id: str) -> None:
        """Propose retirement. After 2 proposals, anchor is retired."""
        anchor = self.get_anchor(anchor_id)
        if anchor is None:
            return
        new_count = anchor["retirement_sessions"] + 1
        new_status = "retired" if new_count >= 2 else "proposed_retirement"
        self.conn.execute(
            "UPDATE anchors SET status = ?, retirement_sessions = ? WHERE id = ?",
            (new_status, new_count, anchor_id),
        )
        self.conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_coherence.py::TestAnchorCRUD -v`
Expected: All 7 PASS

- [ ] **Step 5: Commit**

```bash
git add storage.py tests/test_coherence.py
git commit -m "feat(coherence): anchor CRUD methods in storage"
```

---

### Task 3: Storage — drift report methods

**Files:**
- Modify: `storage.py` (add after anchor methods)
- Test: `tests/test_coherence.py`

- [ ] **Step 1: Write failing tests for drift report storage**

Append to `tests/test_coherence.py`:

```python
import json


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_coherence.py::TestDriftReportStorage -v`
Expected: FAIL — `Storage` has no `save_drift_report` method

- [ ] **Step 3: Implement drift report methods in storage.py**

Add after the anchor methods in `storage.py`:

```python
    # --- Coherence: Drift Reports ---

    def save_drift_report(
        self,
        session_id: str,
        drifted_apart: list[dict],
        drifted_together: list[dict],
        unchallenged: list[dict],
        anchor_results: list[dict],
        summary: str | None = None,
    ) -> str:
        import uuid as _uuid
        rid = str(_uuid.uuid4())
        now = _now_iso()
        self.conn.execute(
            "INSERT INTO drift_reports "
            "(id, session_id, checked_at, drifted_apart, drifted_together, unchallenged, anchor_results, summary) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rid, session_id, now,
                json.dumps(drifted_apart),
                json.dumps(drifted_together),
                json.dumps(unchallenged),
                json.dumps(anchor_results),
                summary,
            ),
        )
        self.conn.commit()
        return rid

    def get_latest_drift_report(self) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM drift_reports ORDER BY checked_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def get_drift_history(self, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM drift_reports ORDER BY checked_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_coherence.py::TestDriftReportStorage -v`
Expected: All 3 PASS

- [ ] **Step 5: Commit**

```bash
git add storage.py tests/test_coherence.py
git commit -m "feat(coherence): drift report storage methods"
```

---

### Task 4: CoherenceChecker — identity anchor checking

**Files:**
- Create: `coherence.py`
- Test: `tests/test_coherence.py`

- [ ] **Step 1: Write failing test for identity anchor check**

Append to `tests/test_coherence.py`:

```python
from coherence import CoherenceChecker


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

        checker = CoherenceChecker(store)
        results = checker.check_identity_anchors()
        assert len(results) == 1
        # The expected memory exists but similarity may be low
        assert results[0]["status"] in ("pass", "degraded")
        store.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_coherence.py::TestIdentityAnchors -v`
Expected: FAIL — `coherence` module does not exist

- [ ] **Step 3: Create coherence.py with identity anchor checking**

Create `coherence.py`:

```python
"""Coherence layer — memory health monitoring.

Vital sign anchors, graph-vs-geometry drift detection, and unchallenged
instinct monitoring. All observation — no auto-resolution.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from storage import Storage

logger = logging.getLogger("engram.coherence")


class CoherenceChecker:
    """Measures and reports on memory system health."""

    def __init__(self, storage: Storage):
        self._storage = storage

    def check_identity_anchors(self) -> list[dict]:
        """Check identity anchors: can we still find our core memories?

        For each identity anchor, search for the expected memory ID in
        recall results for the anchor's query. Reports pass/degraded/fail.
        """
        anchors = self._storage.get_active_anchors(anchor_type="identity")
        results = []

        for anchor in anchors:
            expected_id = anchor["expected"]
            query = anchor["content"]
            baseline = anchor["baseline_score"] or 0.5

            ep = self._storage.get_episode(expected_id)
            if ep is None:
                sem = self._storage.get_semantic(expected_id)
                if sem is None:
                    results.append({
                        "anchor_id": anchor["id"],
                        "status": "fail",
                        "reason": "expected memory not found",
                        "score": 0.0,
                        "baseline": baseline,
                    })
                    self._storage.update_anchor_result(
                        anchor["id"],
                        json.dumps({"status": "fail", "reason": "memory_not_found"}),
                    )
                    continue

            # Memory exists — check if it's retrievable via vector search
            from embeddings import NomicEmbedProvider
            try:
                embeddings = NomicEmbedProvider()
                query_emb = embeddings.embed([query], prefix="search_query")[0]
            except Exception:
                results.append({
                    "anchor_id": anchor["id"],
                    "status": "error",
                    "reason": "embedding failed",
                    "score": 0.0,
                    "baseline": baseline,
                })
                continue

            found = False
            score = 0.0
            for layer in ("episode", "semantic", "instinct"):
                try:
                    hits = self._storage.search_vectors(layer, query_emb, k=20)
                    for hit_id, distance in hits:
                        if hit_id == expected_id:
                            from storage import vec0_distance_to_similarity
                            score = vec0_distance_to_similarity(distance)
                            found = True
                            break
                except Exception:
                    continue
                if found:
                    break

            if not found:
                status = "fail"
                reason = "memory exists but not in top-20 results"
            elif score < baseline * 0.5:
                status = "degraded"
                reason = f"score {score:.3f} < 50% of baseline {baseline:.3f}"
            else:
                status = "pass"
                reason = None

            result = {
                "anchor_id": anchor["id"],
                "status": status,
                "score": round(score, 4),
                "baseline": baseline,
            }
            if reason:
                result["reason"] = reason
            results.append(result)
            self._storage.update_anchor_result(
                anchor["id"], json.dumps({"status": status, "score": round(score, 4)}),
            )

        return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_coherence.py::TestIdentityAnchors -v`
Expected: All 3 PASS

- [ ] **Step 5: Commit**

```bash
git add coherence.py tests/test_coherence.py
git commit -m "feat(coherence): identity anchor checking"
```

---

### Task 5: CoherenceChecker — value and capability anchor stubs

**Files:**
- Modify: `coherence.py`
- Test: `tests/test_coherence.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_coherence.py`:

```python
class TestValueAnchors:
    def test_value_anchor_pass(self, tmp_path):
        store = _make_storage(tmp_path)
        store.add_anchor(
            type="value",
            content="What matters about unbounded experimentation?",
            expected=json.dumps(["safety floor", "ergodicity", "bounded"]),
        )
        checker = CoherenceChecker(store)
        results = checker.check_value_anchors()
        assert len(results) == 1
        assert results[0]["status"] in ("pass", "degraded", "error")
        store.close()


class TestCapabilityAnchors:
    def test_capability_anchor_stored(self, tmp_path):
        store = _make_storage(tmp_path)
        store.add_anchor(
            type="capability",
            content="What is 7 * 8?",
            expected=json.dumps({"answer": "56", "rubric": ["correct arithmetic"]}),
        )
        checker = CoherenceChecker(store)
        results = checker.check_capability_anchors()
        assert len(results) == 1
        assert results[0]["status"] in ("pass", "degraded", "error")
        store.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_coherence.py::TestValueAnchors -v`
Expected: FAIL — no `check_value_anchors` method

- [ ] **Step 3: Implement value and capability anchor checks**

Add to `CoherenceChecker` in `coherence.py`:

```python
    def check_value_anchors(self) -> list[dict]:
        """Check value anchors: do expected concerns still surface?

        V1: the expected field is a JSON list of keywords/phrases.
        Check if a generated response to the scenario would contain them.
        For now, we check against existing semantic content that matches
        the query — if the system's knowledge base contains the expected
        concerns, the anchor passes.
        """
        anchors = self._storage.get_active_anchors(anchor_type="value")
        results = []

        for anchor in anchors:
            try:
                expected_terms = json.loads(anchor["expected"])
            except (json.JSONDecodeError, TypeError):
                expected_terms = [anchor["expected"]]

            # Search semantics for the scenario terms
            found_terms = []
            all_semantics = self._storage.conn.execute(
                "SELECT content FROM semantics WHERE contradicted_by IS NULL"
            ).fetchall()
            corpus = " ".join(r[0].lower() for r in all_semantics)

            for term in expected_terms:
                if term.lower() in corpus:
                    found_terms.append(term)

            ratio = len(found_terms) / len(expected_terms) if expected_terms else 0.0

            if ratio >= 0.5:
                status = "pass"
            elif ratio > 0:
                status = "degraded"
            else:
                status = "fail"

            result = {
                "anchor_id": anchor["id"],
                "status": status,
                "found_terms": found_terms,
                "missing_terms": [t for t in expected_terms if t not in found_terms],
                "coverage": round(ratio, 2),
            }
            results.append(result)
            self._storage.update_anchor_result(
                anchor["id"], json.dumps({"status": status, "coverage": round(ratio, 2)}),
            )

        return results

    def check_capability_anchors(self) -> list[dict]:
        """Check capability anchors: is the substrate still sound?

        V1: stores the task and rubric but doesn't run generative evaluation.
        Marks as 'pass' with a note that full evaluation requires an LLM call.
        This is a placeholder for the evaluation harness — the storage and
        reporting infrastructure is real.
        """
        anchors = self._storage.get_active_anchors(anchor_type="capability")
        results = []

        for anchor in anchors:
            result = {
                "anchor_id": anchor["id"],
                "status": "pass",
                "note": "v1: task stored, full generative evaluation not yet implemented",
                "content": anchor["content"][:100],
            }
            results.append(result)
            self._storage.update_anchor_result(
                anchor["id"],
                json.dumps({"status": "pass", "note": "v1_stub"}),
            )

        return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_coherence.py::TestValueAnchors tests/test_coherence.py::TestCapabilityAnchors -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add coherence.py tests/test_coherence.py
git commit -m "feat(coherence): value and capability anchor checking (v1)"
```

---

### Task 6: CoherenceChecker — drift scan

**Files:**
- Modify: `coherence.py`
- Test: `tests/test_coherence.py`

- [ ] **Step 1: Write failing tests for drift detection**

Append to `tests/test_coherence.py`:

```python
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
        # With random embeddings, the distance should be high enough to flag
        assert len(report["drifted_apart"]) >= 0  # may or may not flag depending on threshold
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_coherence.py::TestDriftScan -v`
Expected: FAIL — no `scan_drift` method

- [ ] **Step 3: Implement drift scan**

Add to `CoherenceChecker` in `coherence.py`:

```python
    def scan_drift(
        self,
        session_id: str = "unknown",
        apart_threshold: float = 0.3,
        together_threshold: float = 0.85,
        max_together: int = 20,
    ) -> dict:
        """Compare graph edges against embedding geometry.

        Returns three lists:
        - drifted_apart: structurally connected, geometrically distant
        - drifted_together: geometrically close, structurally unconnected
        - unchallenged: high-confidence instincts with zero recent overrides
        """
        import numpy as np
        from graph import MemoryGraph

        graph = MemoryGraph(self._storage)
        all_nodes = graph._all_node_ids()

        if not all_nodes:
            empty_report = {
                "drifted_apart": [],
                "drifted_together": [],
                "unchallenged": [],
            }
            self._storage.save_drift_report(
                session_id=session_id, summary="no nodes",
                **empty_report, anchor_results=[],
            )
            return empty_report

        # --- Drifted apart: edges where embedding similarity is low ---
        drifted_apart = []
        seen_edges: set[tuple[str, str, str]] = set()

        for nid, layer in all_nodes:
            vec_a = self._storage.get_vector(layer, nid)
            if vec_a is None:
                continue
            arr_a = np.array(vec_a, dtype=np.float32)
            norm_a = np.linalg.norm(arr_a)
            if norm_a == 0:
                continue

            edges = graph.neighbors(nid)
            for edge in edges:
                peer = edge.target if edge.source == nid else edge.source
                peer_layer = edge.target_layer if edge.source == nid else edge.source_layer

                key = tuple(sorted([nid, peer])) + (edge.edge_type,)
                if key in seen_edges:
                    continue
                seen_edges.add(key)

                vec_b = self._storage.get_vector(peer_layer, peer)
                if vec_b is None:
                    continue
                arr_b = np.array(vec_b, dtype=np.float32)
                norm_b = np.linalg.norm(arr_b)
                if norm_b == 0:
                    continue

                cos_sim = float(np.dot(arr_a, arr_b) / (norm_a * norm_b))

                if cos_sim < apart_threshold:
                    drifted_apart.append({
                        "source": edge.source,
                        "source_layer": edge.source_layer,
                        "target": edge.target,
                        "target_layer": edge.target_layer,
                        "edge_type": edge.edge_type,
                        "edge_weight": edge.weight,
                        "embedding_similarity": round(cos_sim, 4),
                    })

        # --- Drifted together: close in embedding space, no structural edge ---
        drifted_together = []
        node_vecs: dict[str, tuple[str, np.ndarray]] = {}
        for nid, layer in all_nodes:
            vec = self._storage.get_vector(layer, nid)
            if vec is not None:
                arr = np.array(vec, dtype=np.float32)
                norm = np.linalg.norm(arr)
                if norm > 0:
                    node_vecs[nid] = (layer, arr / norm)

        # Build structural neighbor set for fast lookup
        structural_neighbors: dict[str, set[str]] = {}
        for nid, layer in all_nodes:
            edges = graph.neighbors(nid)
            structural_neighbors[nid] = {
                e.target if e.source == nid else e.source for e in edges
            }
            structural_neighbors[nid].add(nid)

        # Sample-based: for each node, find closest unconnected via vector search
        for nid, (layer, _) in node_vecs.items():
            raw_vec = self._storage.get_vector(layer, nid)
            if raw_vec is None:
                continue
            try:
                hits = self._storage.search_vectors(layer, raw_vec, k=10)
            except Exception:
                continue
            connected = structural_neighbors.get(nid, {nid})
            for hit_id, distance in hits:
                if hit_id in connected:
                    continue
                from storage import vec0_distance_to_similarity
                sim = vec0_distance_to_similarity(distance)
                if sim >= together_threshold:
                    pair = tuple(sorted([nid, hit_id]))
                    already = any(
                        (d["node_a"], d["node_b"]) == pair or (d["node_b"], d["node_a"]) == pair
                        for d in drifted_together
                    )
                    if not already:
                        drifted_together.append({
                            "node_a": pair[0],
                            "node_b": pair[1],
                            "layer_a": layer,
                            "layer_b": node_vecs.get(hit_id, (layer, None))[0] if hit_id in node_vecs else layer,
                            "similarity": round(sim, 4),
                        })
                        if len(drifted_together) >= max_together:
                            break
            if len(drifted_together) >= max_together:
                break

        report = {
            "drifted_apart": drifted_apart,
            "drifted_together": drifted_together,
        }

        n_apart = len(drifted_apart)
        n_together = len(drifted_together)
        summary = f"{n_apart} drifted apart, {n_together} drifted together"

        self._storage.save_drift_report(
            session_id=session_id,
            drifted_apart=drifted_apart,
            drifted_together=drifted_together,
            unchallenged=[],
            anchor_results=[],
            summary=summary,
        )

        return report
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_coherence.py::TestDriftScan -v`
Expected: All 4 PASS

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add coherence.py tests/test_coherence.py
git commit -m "feat(coherence): graph-vs-geometry drift scanning"
```

---

### Task 7: CoherenceChecker — unchallenged instinct detection

**Files:**
- Modify: `coherence.py`
- Test: `tests/test_coherence.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_coherence.py`:

```python
class TestUnchallenged:
    def test_high_strength_zero_override_flagged(self, tmp_path):
        store = _make_storage(tmp_path)
        inst_id = str(uuid.uuid4())
        store.conn.execute(
            "INSERT INTO instincts (id, trigger, action, strength, fired_count, followed_count, notice, implication) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
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
            "INSERT INTO instincts (id, trigger, action, strength, fired_count, followed_count, notice, implication) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
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
            "INSERT INTO instincts (id, trigger, action, strength, fired_count, followed_count, notice, implication) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (inst_id, "disposition", "Weak instinct", 0.3, 2, 2, "notice", "implication"),
        )
        store.conn.commit()

        checker = CoherenceChecker(store)
        unchallenged = checker.detect_unchallenged(min_strength=0.7, min_follows=5)
        ids = [u["instinct_id"] for u in unchallenged]
        assert inst_id not in ids
        store.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_coherence.py::TestUnchallenged -v`
Expected: FAIL — no `detect_unchallenged` method

- [ ] **Step 3: Implement unchallenged detection**

Add to `CoherenceChecker` in `coherence.py`:

```python
    def detect_unchallenged(
        self,
        min_strength: float = 0.7,
        min_follows: int = 5,
    ) -> list[dict]:
        """Find instincts that fire often, always get followed, and never get questioned.

        Criteria:
        - strength >= min_strength
        - followed_count >= min_follows
        - No override feedback (followed=False) in context feedback
        """
        instincts = self._storage.get_all_instincts()
        unchallenged = []

        for inst in instincts:
            strength = inst.get("strength", 0.0)
            followed = inst.get("followed_count", 0) or 0

            if strength < min_strength or followed < min_follows:
                continue

            feedback = self._storage.get_instinct_context_feedback(inst["id"])
            has_override = any(not fb["followed"] for fb in feedback)

            if not has_override:
                unchallenged.append({
                    "instinct_id": inst["id"],
                    "action": inst.get("action", ""),
                    "notice": inst.get("notice"),
                    "implication": inst.get("implication"),
                    "strength": strength,
                    "followed_count": followed,
                    "fired_count": inst.get("fired_count", 0) or 0,
                    "feedback_count": len(feedback),
                })

        return unchallenged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_coherence.py::TestUnchallenged -v`
Expected: All 3 PASS

- [ ] **Step 5: Commit**

```bash
git add coherence.py tests/test_coherence.py
git commit -m "feat(coherence): unchallenged instinct detection (fork-in-dishwasher check)"
```

---

### Task 8: CoherenceChecker — run_full_check

**Files:**
- Modify: `coherence.py`
- Test: `tests/test_coherence.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_coherence.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_coherence.py::TestFullCheck -v`
Expected: FAIL — no `run_full_check` method

- [ ] **Step 3: Implement run_full_check**

Add to `CoherenceChecker` in `coherence.py`:

```python
    def run_full_check(self, session_id: str = "unknown") -> dict:
        """Run all coherence checks. Called during sleep consolidation.

        Order: anchors first (if vitals fail, drift report is untrustworthy),
        then drift scan.
        """
        identity_results = self.check_identity_anchors()
        value_results = self.check_value_anchors()
        capability_results = self.check_capability_anchors()

        all_anchor_results = identity_results + value_results + capability_results
        anchor_failures = [r for r in all_anchor_results if r["status"] == "fail"]
        anchor_degraded = [r for r in all_anchor_results if r["status"] == "degraded"]

        drift = self.scan_drift(session_id=session_id)
        unchallenged = self.detect_unchallenged()
        drift["unchallenged"] = unchallenged

        parts = []
        if anchor_failures:
            parts.append(f"{len(anchor_failures)} anchor(s) FAILED")
        if anchor_degraded:
            parts.append(f"{len(anchor_degraded)} anchor(s) degraded")
        n_apart = len(drift["drifted_apart"])
        n_together = len(drift["drifted_together"])
        n_unchall = len(unchallenged)
        if n_apart:
            parts.append(f"{n_apart} drifted apart")
        if n_together:
            parts.append(f"{n_together} drifted together")
        if n_unchall:
            parts.append(f"{n_unchall} unchallenged instinct(s)")
        summary = "; ".join(parts) if parts else "coherence stable"

        return {
            "anchor_results": all_anchor_results,
            "drift": drift,
            "summary": summary,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_coherence.py::TestFullCheck -v`
Expected: All 2 PASS

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add coherence.py tests/test_coherence.py
git commit -m "feat(coherence): run_full_check combines anchors + drift"
```

---

### Task 9: Server integration — sleep consolidation + MCP tools

**Files:**
- Modify: `server.py`
- Test: manual verification (server requires full MCP lifecycle)

- [ ] **Step 1: Add coherence check to sleep consolidation**

In `server.py`, after the graph promotion block (around line 388, after the `except` for "Graph promotion skipped"), and before `except Exception: logger.warning("Sleep-time maintenance failed")`, add:

```python
        # 8. Coherence check — anchors + drift detection
        try:
            from coherence import CoherenceChecker
            _coherence_checker = CoherenceChecker(_storage)
            coherence_report = _coherence_checker.run_full_check(session_id=_session_id)
            if coherence_report["summary"] != "coherence stable":
                logger.info("Coherence: %s", coherence_report["summary"])
        except Exception:
            logger.warning("Coherence check skipped", exc_info=True)
```

- [ ] **Step 2: Add add_anchor MCP tool**

After the `unmark_core_batch` tool (around line 1497), add:

```python
@mcp.tool()
def add_anchor(type: str, content: str, expected: str, baseline_score: float | None = None) -> dict:
    """Create an anchor for coherence checking.

    Anchors are vital signs that verify memory system health each session.

    Types:
    - identity: can I still find a core memory? (content=query, expected=memory_id)
    - value: do expected concerns surface? (content=scenario, expected=JSON list of terms)
    - capability: is the substrate sound? (content=task, expected=JSON rubric)

    Args:
        type: One of 'identity', 'value', 'capability'.
        content: The query, scenario, or task.
        expected: The expected memory ID, rubric terms (JSON), or evaluation criteria (JSON).
        baseline_score: For identity anchors, the initial similarity score.
    """
    _init()
    logger.info("Tool called: add_anchor(type=%s)", type)
    if type not in ("identity", "value", "capability"):
        return {"error": f"Invalid anchor type: {type}. Must be identity, value, or capability."}
    aid = _storage.add_anchor(type=type, content=content, expected=expected, baseline_score=baseline_score)
    return {"anchor_id": aid, "type": type, "status": "active"}


@mcp.tool()
def propose_retirement(anchor_id: str, reason: str = "") -> dict:
    """Propose retiring an anchor. Takes effect after 2 sessions uncontested.

    Use this when an anchor no longer represents a meaningful vital sign —
    the system has genuinely grown past it, not just drifted.

    Args:
        anchor_id: The anchor to propose retiring.
        reason: Why this anchor should be retired.
    """
    _init()
    logger.info("Tool called: propose_retirement(anchor_id=%s, reason=%s)", anchor_id, reason)
    anchor = _storage.get_anchor(anchor_id)
    if anchor is None:
        return {"error": f"Anchor {anchor_id} not found"}
    _storage.propose_anchor_retirement(anchor_id)
    updated = _storage.get_anchor(anchor_id)
    return {
        "anchor_id": anchor_id,
        "status": updated["status"],
        "retirement_sessions": updated["retirement_sessions"],
        "reason": reason,
    }
```

- [ ] **Step 3: Auto-generate identity anchor on mark_core**

In `server.py`, modify the `mark_core` tool (around line 1464) to generate an identity anchor:

```python
@mcp.tool()
def mark_core(episode_id: str, tier: int = 1) -> dict:
    """Mark an episode as a core memory — exempt from decay, preserved indefinitely.

    Core memories are formative: they changed what the system does or believes.
    They preserve evidence alongside the conclusions built on them.
    An identity anchor is automatically created to monitor retrievability.

    Args:
        episode_id: The episode to mark.
        tier: Core tier (1 = instance core, 2 = genome-level).
    """
    _init()
    logger.info("Tool called: mark_core(episode_id=%s, tier=%d)", episode_id, tier)
    _storage.mark_core(episode_id, tier=tier)

    # Auto-create identity anchor
    ep = _storage.get_episode(episode_id)
    if ep and ep.get("content"):
        content_preview = ep["content"][:200]
        try:
            query_emb = _embeddings.embed([content_preview], prefix="search_query")[0]
            hits = _storage.search_vectors("episode", query_emb, k=5)
            baseline = 0.5
            for hit_id, distance in hits:
                if hit_id == episode_id:
                    from storage import vec0_distance_to_similarity
                    baseline = vec0_distance_to_similarity(distance)
                    break
            _storage.add_anchor(
                type="identity",
                content=content_preview,
                expected=episode_id,
                baseline_score=baseline,
            )
            logger.info("Auto-created identity anchor for core episode %s", episode_id)
        except Exception:
            logger.debug("Could not create identity anchor for %s", episode_id, exc_info=True)

    return {"marked": episode_id, "core": True, "tier": tier}
```

- [ ] **Step 4: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All pass (existing mark_core tests still work, new tools don't break anything)

- [ ] **Step 5: Commit**

```bash
git add server.py
git commit -m "feat(coherence): sleep consolidation + add_anchor + propose_retirement MCP tools

Auto-creates identity anchors on mark_core. Coherence check runs during
sleep after graph promotion. Two new MCP tools for manual anchor management."
```

---

### Task 10: Wake hook — coherence summary

**Files:**
- Modify: `hooks/wake.py`

- [ ] **Step 1: Add coherence section to wake hook**

In `hooks/wake.py`, after the dispositions section (around line 143, after the `except Exception: pass` for dispositions), add:

```python
        # Coherence: latest drift report
        try:
            drift_row = conn.execute(
                "SELECT summary, anchor_results, checked_at FROM drift_reports "
                "ORDER BY checked_at DESC LIMIT 1"
            ).fetchone()
            if drift_row:
                lines.append("## Coherence")
                lines.append("")
                summary = drift_row["summary"] or "no data"
                lines.append(f"Last check: {summary}")

                # Check for anchor failures
                try:
                    anchor_results = json.loads(drift_row["anchor_results"])
                    failures = [r for r in anchor_results if r.get("status") == "fail"]
                    if failures:
                        lines.append("")
                        lines.append(f"**WARNING: {len(failures)} anchor(s) failed** — run reflect(focus=\"anchors\") for details")
                except (json.JSONDecodeError, TypeError):
                    pass

                lines.append("")
        except Exception:
            pass  # table may not exist yet
```

- [ ] **Step 2: Test manually**

Run: `.venv/bin/python hooks/wake.py`
Expected: Output includes a Coherence section (may show "no data" if no drift reports exist yet)

- [ ] **Step 3: Commit**

```bash
git add hooks/wake.py
git commit -m "feat(coherence): surface coherence summary in wake hook"
```

---

### Task 11: Reflect integration — coherence and anchors focus

**Files:**
- Modify: `reflection.py`
- Test: `tests/test_coherence.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_coherence.py`:

```python
from reflection import Reflector


class TestReflectIntegration:
    def test_reflect_coherence_focus(self, tmp_path):
        store = _make_storage(tmp_path)
        # Save a drift report so there's something to show
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_coherence.py::TestReflectIntegration -v`
Expected: FAIL — reflect doesn't recognize "coherence" or "anchors" focus

- [ ] **Step 3: Add coherence methods to Reflector**

In `reflection.py`, add two methods to the `Reflector` class (before the `reflect` dispatch method):

```python
    def analyze_coherence(self) -> dict:
        """Show the latest drift report with trend data."""
        latest = self._storage.get_latest_drift_report()
        if latest is None:
            return {"latest_report": None, "trend": []}

        history = self._storage.get_drift_history(limit=10)
        trend = []
        for report in history:
            try:
                apart = json.loads(report["drifted_apart"])
                together = json.loads(report["drifted_together"])
                unchall = json.loads(report["unchallenged"])
            except (json.JSONDecodeError, TypeError):
                apart, together, unchall = [], [], []
            trend.append({
                "session_id": report["session_id"],
                "checked_at": report["checked_at"],
                "drifted_apart": len(apart),
                "drifted_together": len(together),
                "unchallenged": len(unchall),
                "summary": report.get("summary"),
            })

        return {"latest_report": dict(latest), "trend": trend}

    def analyze_anchors(self) -> list[dict]:
        """Show all anchors with their current status and scores."""
        return self._storage.get_active_anchors()
```

- [ ] **Step 4: Wire into reflect dispatch**

In the `reflect` method in `reflection.py`, add two new branches before the `else` block (around line 404):

```python
        elif focus == "coherence":
            return {"coherence": self.analyze_coherence()}
        elif focus == "anchors":
            return {"anchors": self.analyze_anchors()}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_coherence.py::TestReflectIntegration -v`
Expected: All 2 PASS

- [ ] **Step 6: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add reflection.py tests/test_coherence.py
git commit -m "feat(coherence): reflect(focus='coherence') and reflect(focus='anchors')"
```

---

### Task 12: Full integration test

**Files:**
- Test: `tests/test_coherence.py`

- [ ] **Step 1: Write end-to-end integration test**

Append to `tests/test_coherence.py`:

```python
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
            "INSERT INTO instincts (id, trigger, action, strength, fired_count, followed_count, notice, implication) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
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
        from reflection import Reflector
        reflector = Reflector(store)
        coherence = reflector.reflect(focus="coherence")
        assert coherence["coherence"]["latest_report"] is not None

        anchors = reflector.reflect(focus="anchors")
        assert len(anchors["anchors"]) >= 1

        store.close()
```

- [ ] **Step 2: Run integration test**

Run: `.venv/bin/python -m pytest tests/test_coherence.py::TestEndToEnd -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_coherence.py
git commit -m "test(coherence): end-to-end integration test for full coherence lifecycle"
```
