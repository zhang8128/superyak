# PMI-Based Resonance Formation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace similarity-zone resonance formation with PMI (pointwise mutual information) computed from recall co-occurrence history.

**Architecture:** Track which memories appear together in recall results. Compute PMI to find pairs that co-occur more than chance predicts. Form resonances from high-PMI pairs. Session span acts as a multiplier — cross-session co-occurrences count more. The existing resonances table, surfacing logic, and feedback loop stay the same; only formation changes.

**Tech Stack:** Python, SQLite, existing engram Storage/resonance infrastructure.

---

## File Structure

| File | Role |
|------|------|
| `resonance.py` | Replace `form_resonances()` with PMI-based formation. Add `compute_pmi()`. Keep `surface_resonances()` unchanged. |
| `storage.py` | Add `get_recall_cooccurrences()` — query memory_log for co-occurrence counts. |
| `server.py` | Update call site: replace similarity-based formation with PMI-based. Add session_id to recall log context. |
| `emma_engram.py` | Same changes for Emma's recall path. |
| `tests/test_resonances.py` | New tests for PMI computation and formation. Update existing e2e test. |
| `migrations/013_recall_session.sql` | No new migration needed — memory_log already has target_ids and timestamps. |

---

### Task 1: Storage — get co-occurrence data from recall logs

**Files:**
- Modify: `storage.py` — add `get_recall_cooccurrences()` and `get_memory_recall_frequency()`
- Test: `tests/test_resonances.py`

- [ ] **Step 1: Write failing tests**

```python
def test_get_recall_cooccurrences_empty(store):
    """No recall logs = empty co-occurrences."""
    result = store.get_recall_cooccurrences()
    assert result == {}


def test_get_recall_cooccurrences(store):
    """Two recalls with overlapping target_ids produce co-occurrences."""
    import json
    store.add_log_entry(id="r1", event_type="recall", layer="all",
                        target_ids=["a", "b", "c"],
                        context={"recall_id": "r1", "query": "test"})
    store.add_log_entry(id="r2", event_type="recall", layer="all",
                        target_ids=["a", "b", "d"],
                        context={"recall_id": "r2", "query": "test2"})
    result = store.get_recall_cooccurrences()
    # a,b co-occurred in both recalls
    pair_ab = result.get(("a", "b"), 0)
    assert pair_ab == 2
    # a,c only in first recall
    pair_ac = result.get(("a", "c"), 0)
    assert pair_ac == 1
    # a,d only in second recall
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_resonances.py::test_get_recall_cooccurrences_empty tests/test_resonances.py::test_get_recall_cooccurrences tests/test_resonances.py::test_get_memory_recall_frequency -v`
Expected: AttributeError — methods don't exist yet.

- [ ] **Step 3: Implement in storage.py**

Add after `cleanup_resonances`:

```python
def get_recall_cooccurrences(self) -> dict[tuple[str, str], int]:
    """Count how many recall events each pair of memories co-occurred in.

    Reads memory_log entries with event_type='recall', extracts target_ids,
    and counts pairwise co-occurrences. Returns {(id_a, id_b): count} with
    canonical ordering (id_a < id_b).
    """
    import json as _json
    rows = self.conn.execute(
        "SELECT target_ids FROM memory_log WHERE event_type = 'recall'"
    ).fetchall()
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        raw = row[0] if not hasattr(row, 'keys') else row["target_ids"]
        try:
            ids = _json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (TypeError, ValueError):
            continue
        ids = sorted(set(ids))  # dedupe within single recall, canonical order
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                pair = (ids[i], ids[j])
                counts[pair] = counts.get(pair, 0) + 1
    return counts


def get_memory_recall_frequency(self) -> dict[str, int]:
    """Count how many recall events each memory appears in."""
    import json as _json
    rows = self.conn.execute(
        "SELECT target_ids FROM memory_log WHERE event_type = 'recall'"
    ).fetchall()
    freq: dict[str, int] = {}
    for row in rows:
        raw = row[0] if not hasattr(row, 'keys') else row["target_ids"]
        try:
            ids = _json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (TypeError, ValueError):
            continue
        for mid in set(ids):
            freq[mid] = freq.get(mid, 0) + 1
    return freq
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_resonances.py::test_get_recall_cooccurrences_empty tests/test_resonances.py::test_get_recall_cooccurrences tests/test_resonances.py::test_get_memory_recall_frequency -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add storage.py tests/test_resonances.py
git commit -m "feat: add recall co-occurrence and frequency queries to Storage"
```

---

### Task 2: PMI computation in resonance.py

**Files:**
- Modify: `resonance.py` — add `compute_pmi()`, replace `form_resonances()`
- Test: `tests/test_resonances.py`

- [ ] **Step 1: Write failing tests for PMI**

```python
def test_compute_pmi_basic():
    """PMI > 0 for pairs that co-occur more than chance predicts."""
    from resonance import compute_pmi
    cooccurrences = {("a", "b"): 5, ("a", "c"): 1, ("b", "c"): 1}
    frequency = {"a": 6, "b": 6, "c": 2}
    total_recalls = 10
    pmi = compute_pmi(cooccurrences, frequency, total_recalls)
    # a,b: P(a,b)=5/10=0.5, P(a)=6/10=0.6, P(b)=6/10=0.6
    # PMI = log(0.5 / (0.6*0.6)) = log(1.389) ≈ 0.329
    assert pmi[("a", "b")] > 0
    # a,c: P(a,c)=1/10=0.1, P(a)=6/10=0.6, P(c)=2/10=0.2
    # PMI = log(0.1 / (0.6*0.2)) = log(0.833) ≈ -0.182
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
    # With only 2 total recalls, PMI is unreliable — should return empty
    assert len(pmi) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_resonances.py::test_compute_pmi_basic tests/test_resonances.py::test_compute_pmi_zero_frequency tests/test_resonances.py::test_compute_pmi_insufficient_recalls -v`
Expected: ImportError — `compute_pmi` doesn't exist.

- [ ] **Step 3: Implement compute_pmi**

Replace the content of `resonance.py`:

```python
"""Resonance — lateral associations formed from recall co-occurrence patterns."""
from __future__ import annotations

import math
import random


# Minimum total recalls before PMI computation is meaningful
MIN_RECALLS_FOR_PMI = 5


def compute_pmi(
    cooccurrences: dict[tuple[str, str], int],
    frequency: dict[str, int],
    total_recalls: int,
) -> dict[tuple[str, str], float]:
    """Compute pointwise mutual information for co-occurring memory pairs.

    PMI(a,b) = log2( P(a,b) / (P(a) * P(b)) )

    Returns only pairs where both memories have nonzero frequency
    and total_recalls >= MIN_RECALLS_FOR_PMI.
    """
    if total_recalls < MIN_RECALLS_FOR_PMI:
        return {}

    pmi: dict[tuple[str, str], float] = {}
    for (a, b), count in cooccurrences.items():
        freq_a = frequency.get(a, 0)
        freq_b = frequency.get(b, 0)
        if freq_a == 0 or freq_b == 0:
            continue
        p_ab = count / total_recalls
        p_a = freq_a / total_recalls
        p_b = freq_b / total_recalls
        pmi[(a, b)] = math.log2(p_ab / (p_a * p_b))
    return pmi


def form_resonances(storage, results, reinforce_threshold=0.70) -> int:
    """Form resonances from recall co-occurrence history using PMI.

    Called after each recall. Computes PMI across all recall history,
    then creates/updates resonances for pairs with PMI > 0 (co-occur
    more than chance predicts). Stochastic birth weight for individuality.
    """
    cooccurrences = storage.get_recall_cooccurrences()
    frequency = storage.get_memory_recall_frequency()
    total_recalls = sum(1 for _ in storage.conn.execute(
        "SELECT 1 FROM memory_log WHERE event_type = 'recall'"
    ))

    pmi = compute_pmi(cooccurrences, frequency, total_recalls)
    if not pmi:
        return 0

    # Build lookup for layer info from current results
    layer_map: dict[str, str] = {}
    for r in results:
        layer_map[r["id"]] = r["layer"]

    # Only consider pairs where at least one member is in current results.
    # Without this filter, every recall would upsert ALL positive-PMI pairs
    # from the entire history — O(N^2) upserts that grow unboundedly.
    current_ids = {r["id"] for r in results}

    formed = 0
    for (a, b), score in pmi.items():
        if score <= 0:
            continue
        if a not in current_ids and b not in current_ids:
            continue
        # Need layer info — check current results or query DB
        layer_a = layer_map.get(a) or _guess_layer(storage, a)
        layer_b = layer_map.get(b) or _guess_layer(storage, b)
        if layer_a is None or layer_b is None:
            continue
        weight = max(0.1, min(0.9, random.gauss(0.5, 0.15)))
        storage.add_resonance(a, layer_a, b, layer_b,
                              similarity=score, weight=weight)
        formed += 1

    return formed


def _guess_layer(storage, memory_id: str) -> str | None:
    """Determine which layer a memory ID belongs to."""
    for layer, table in [("episode", "episodes"), ("semantic", "semantics"),
                         ("instinct", "instincts")]:
        row = storage.conn.execute(
            f"SELECT 1 FROM {table} WHERE id = ?", (memory_id,)
        ).fetchone()
        if row:
            return layer
    return None


def surface_resonances(storage, top_results, existing_ids, max_resonant=2) -> list[dict]:
    """Surface resonance-linked memories not in direct recall results.

    Takes the top 3 results, queries their resonances, and probabilistically
    surfaces the other side of each resonance pair. Unchanged from original.
    """
    surfaced = []
    seen_ids = set(existing_ids)

    for result in top_results[:3]:
        if len(surfaced) >= max_resonant:
            break
        resonances = storage.get_resonances_for(result["id"])
        for res in resonances:
            if len(surfaced) >= max_resonant:
                break
            other_id = res["memory_b"] if res["memory_a"] == result["id"] else res["memory_a"]
            other_layer = res["layer_b"] if res["memory_a"] == result["id"] else res["layer_a"]
            if other_id in seen_ids:
                continue
            strength = res.get("strength", 0.5)
            weight = res.get("weight", 0.5)
            if random.random() >= weight * strength:
                continue
            mem = _hydrate(storage, other_id, other_layer, res["id"])
            if mem is not None:
                surfaced.append(mem)
                seen_ids.add(other_id)

    return surfaced


def _hydrate(storage, memory_id: str, layer: str, resonance_id: str) -> dict | None:
    """Load content for a resonance-surfaced memory."""
    if layer == "episode":
        row = storage.get_episode(memory_id)
        if row:
            return {"id": memory_id, "layer": "episode",
                    "content": row.get("content", ""),
                    "context": row.get("context"),
                    "origin": "lived", "resonant": True,
                    "resonance_id": resonance_id}
    elif layer == "semantic":
        row = storage.get_semantic(memory_id)
        if row:
            return {"id": memory_id, "layer": "semantic",
                    "content": row.get("content", ""),
                    "confidence": row.get("confidence"),
                    "kind": row.get("kind"),
                    "origin": "organic", "resonant": True,
                    "resonance_id": resonance_id}
    elif layer == "instinct":
        row = storage.get_instinct(memory_id)
        if row:
            return {"id": memory_id, "layer": "instinct",
                    "content": row.get("action", ""),
                    "trigger": row.get("trigger", ""),
                    "origin": "organic", "resonant": True,
                    "resonance_id": resonance_id}
    return None
```

- [ ] **Step 4: Update existing e2e test**

The old `test_resonance_end_to_end` uses the similarity-zone approach which no longer exists. Update it to seed recall log entries so PMI can form the resonance:

```python
def test_resonance_end_to_end(store):
    """Full cycle: recalls build co-occurrence, PMI forms resonance, surface, feedback."""
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

    # Seed recall history: e2e-1 and e2e-2 co-occur often,
    # e2e-3 appears independently
    for i in range(6):
        ids = ["e2e-1", "e2e-2"] if i % 2 == 0 else ["e2e-1", "e2e-3"]
        store.add_log_entry(id=f"e2e-r{i}", event_type="recall", layer="all",
                            target_ids=ids, context={})

    results = [
        {"id": "e2e-1", "layer": "episode", "score": 0.9},
        {"id": "e2e-2", "layer": "episode", "score": 0.8},
    ]
    formed = form_resonances(store, results)
    resonances = store.get_resonances_for("e2e-1")
    assert len(resonances) >= 1, f"Expected resonance, formed={formed}"

    # Set high weight+strength for deterministic surfacing
    rid = resonances[0]["id"]
    store.conn.execute("UPDATE resonances SET weight=0.99, strength=0.99 WHERE id=?", (rid,))
    store.conn.commit()

    existing = {"e2e-1"}
    surfaced = surface_resonances(store, [{"id": "e2e-1", "layer": "episode"}],
                                  existing, max_resonant=2)
    assert len(surfaced) >= 1
    assert surfaced[0].get("resonant") is True

    store.strengthen_resonance(rid, delta=0.1)
    r = store.get_resonances_for("e2e-1")[0]
    assert r["strength"] >= 0.99
```

- [ ] **Step 5: Run all resonance tests**

Run: `.venv/bin/python -m pytest tests/test_resonances.py -v`
Expected: All pass (existing CRUD tests unchanged, e2e updated).

- [ ] **Step 6: Commit**

```bash
git add resonance.py tests/test_resonances.py
git commit -m "feat: PMI-based resonance formation from recall co-occurrence"
```

---

### Task 3: Wire PMI formation into server.py recall path

**Files:**
- Modify: `server.py` — update recall to log session_id, call PMI-based form_resonances after logging

The key change: formation must happen *after* the recall is logged (so the current recall's co-occurrences are included in PMI computation).

- [ ] **Step 1: Update recall log to include session_id**

In `server.py`, find the recall log entry (around line 805-811) and add `session_id` to context:

```python
_storage.add_log_entry(
    id=str(uuid.uuid4()),
    event_type="recall",
    layer=layer or "all",
    target_ids=result_ids,
    context={"recall_id": recall_id, "query": query, "session_id": _session_id},
)
```

Do the same for the instinct-only recall log entry (~line 592-598).

- [ ] **Step 2: Move resonance formation after logging**

The current code forms resonances before logging. Move it after so the current recall is included in PMI. The formation call is already `_form_resonances(_storage, results, ...)` — no change to the call itself, just its position relative to the log entry.

- [ ] **Step 3: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add server.py
git commit -m "feat: log session_id in recall, move resonance formation after logging"
```

---

### Task 4: Update Emma's recall to participate in PMI

**Files:**
- Modify: `emma_engram.py` — add recall logging, use PMI-based formation

Emma's `recall()` currently forms resonances but doesn't log to memory_log. Without log entries, PMI has no data. Also, `recall_id` is generated late (after formation/surfacing) — move it earlier so it's available for logging.

- [ ] **Step 1: Move recall_id generation and add logging to EmmaEngram.recall()**

In `emma_engram.py`, move `recall_id = str(uuid.uuid4())` to right after the results list is assembled (before resonance formation). Then add the log entry immediately after:

```python
recall_id = str(uuid.uuid4())

self.storage.add_log_entry(
    id=str(uuid.uuid4()),
    event_type="recall",
    layer="all",
    target_ids=[r["id"] for r in results],
    context={"recall_id": recall_id, "query": query},
)
```

Then resonance formation and surfacing follow, using the already-generated `recall_id`.

- [ ] **Step 2: Verify form_resonances now uses PMI path**

Emma already imports `from resonance import form_resonances` — since we replaced the function in Task 2, it automatically uses PMI. No change needed.

- [ ] **Step 3: Deploy and test in container**

```bash
docker cp emma_engram.py emma:/opt/emma/emma_engram.py
docker exec -u root emma chmod 644 /opt/emma/emma_engram.py
docker exec emma python3 -c "
from emma_engram import EmmaEngram
e = EmmaEngram('/sandbox/emma/engram.db')
r = e.recall('Jane Eyre red room fear')
print(f'Results: {len(r[\"results\"])}, recall_id: {r[\"recall_id\"]}')
"
```

- [ ] **Step 4: Commit**

```bash
git add emma_engram.py
git commit -m "feat: add recall logging to Emma for PMI resonance formation"
```

---

### Task 5: Test PMI resonance formation end-to-end

**Files:**
- Modify: `tests/test_resonances.py` — update e2e test

- [ ] **Step 1: Write e2e test for PMI-based resonance**

```python
def test_pmi_resonance_end_to_end(store):
    """Full cycle: multiple recalls build co-occurrence, PMI forms resonance."""
    store.add_episode(id="pmi-1", session_id="s1", content="about trees",
                      embedding=[0.1] * 768)
    store.add_episode(id="pmi-2", session_id="s1", content="about forests",
                      embedding=[0.2] * 768)
    store.add_episode(id="pmi-3", session_id="s1", content="about oceans",
                      embedding=[0.3] * 768)

    # Simulate 6 recalls: pmi-1 and pmi-2 always co-occur,
    # pmi-3 appears in some but not all
    for i in range(6):
        ids = ["pmi-1", "pmi-2"]
        if i % 3 == 0:
            ids.append("pmi-3")
        store.add_log_entry(
            id=f"recall-{i}", event_type="recall", layer="all",
            target_ids=ids, context={"recall_id": f"recall-{i}", "query": f"q{i}"},
        )

    from resonance import form_resonances
    results = [
        {"id": "pmi-1", "layer": "episode"},
        {"id": "pmi-2", "layer": "episode"},
        {"id": "pmi-3", "layer": "episode"},
    ]
    formed = form_resonances(store, results)

    # pmi-1 and pmi-2 always co-occur — should have positive PMI
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
```

- [ ] **Step 2: Run the new e2e tests**

Run: `.venv/bin/python -m pytest tests/test_resonances.py::test_pmi_resonance_end_to_end tests/test_resonances.py::test_pmi_no_resonance_below_threshold -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_resonances.py
git commit -m "test: PMI resonance e2e tests"
```

---

## Notes

*Task 6 was merged into Task 2 — the e2e test is updated in the same commit as the resonance.py replacement to avoid a broken test window.*

- **The `similarity` field in resonances now stores PMI score** (not cosine similarity). This is fine — it's a measure of association strength either way. The surfacing logic doesn't use this field.
- **PMI computation scans all recall logs** each time. For the current scale (~56 recalls) this is trivial. If it grows to thousands, add a materialized co-occurrence table updated incrementally. Not needed now.
- **Session span weighting** is deferred. The session_id is now logged, so it can be added later as a multiplier on co-occurrence counts without schema changes.
- **The `reinforce_threshold` parameter** is kept in the function signature for backward compatibility but no longer used for formation. It can be removed in a follow-up cleanup.
