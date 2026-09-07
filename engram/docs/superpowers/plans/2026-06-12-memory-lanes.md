# Memory Lanes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `lane` field ('personal' | 'work') to episodes and semantics so work reference material never compresses into identity layers (core episodes, instincts).

**Architecture:** Single store, lane column on episodes/semantics. Lane is set at write time via `remember(work=True)`, correctable at compression via a summary `lane` override. Clustering partitions by lane; the work lane is gated out of core promotion, instinct formation, and cross-lane reinforcement. Recall spans both lanes with labels.

**Tech Stack:** Python 3.14, SQLite + sqlite-vec, pytest. Spec: `docs/superpowers/specs/2026-06-12-memory-lanes-design.md`.

**Conventions:** Run tests with `.venv/bin/python -m pytest` from `/Users/kairos/Projects/engram`. Existing fixtures: `tmp_db` (Storage with migrations, from `tests/conftest.py`), `embedder`/`compressor` (in `tests/test_compression.py`), `server_env` (in `tests/test_server.py`). The live MCP server needs a restart after these changes — note this at the end.

---

### Task 1: Schema migration + storage lane support

**Files:**
- Create: `migrations/018_memory_lanes.sql`
- Modify: `storage.py` (`add_episode` ~line 354, `add_semantic` ~line 776, new `set_episode_lanes` after `mark_episodes_compressed` ~line 385)
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_storage.py`:

```python
def test_episode_lane_defaults_personal(tmp_db):
    eid = str(uuid.uuid4())
    tmp_db.add_episode(id=eid, session_id="s", content="a plain memory")
    row = tmp_db.conn.execute("SELECT lane FROM episodes WHERE id = ?", (eid,)).fetchone()
    assert row["lane"] == "personal"


def test_episode_lane_work_round_trip(tmp_db):
    eid = str(uuid.uuid4())
    tmp_db.add_episode(id=eid, session_id="s", content="CommonWell uses OTP login", lane="work")
    row = tmp_db.conn.execute("SELECT lane FROM episodes WHERE id = ?", (eid,)).fetchone()
    assert row["lane"] == "work"


def test_semantic_lane_round_trip(tmp_db):
    sid = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sid, content="pagination is cursor-based", kind="fact",
        confidence=0.5, embedding=[0.1] * 768, source_episode_ids=[], lane="work",
    )
    sem = tmp_db.get_semantic(sid)
    assert sem["lane"] == "work"


def test_set_episode_lanes_batch(tmp_db):
    ids = []
    for i in range(3):
        eid = str(uuid.uuid4())
        tmp_db.add_episode(id=eid, session_id="s", content=f"episode {i}")
        ids.append(eid)
    changed = tmp_db.set_episode_lanes(ids[:2], "work")
    assert changed == 2
    lanes = [r["lane"] for r in tmp_db.conn.execute(
        "SELECT lane FROM episodes ORDER BY created_at").fetchall()]
    assert lanes.count("work") == 2 and lanes.count("personal") == 1
```

(`uuid` is already imported in `tests/test_storage.py`; verify, add `import uuid` if not.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_storage.py -q -k lane`
Expected: 4 failures — `no such column: lane` / `unexpected keyword argument 'lane'`

- [ ] **Step 3: Create the migration**

Create `migrations/018_memory_lanes.sql`:

```sql
-- 018: memory lanes — separate work (reference) from personal (identity) content.
-- Work-lane memories decay and recall normally but never become core episodes,
-- instincts, or reinforcement for personal semantics.
ALTER TABLE episodes ADD COLUMN lane TEXT NOT NULL DEFAULT 'personal';
ALTER TABLE semantics ADD COLUMN lane TEXT NOT NULL DEFAULT 'personal';
CREATE INDEX IF NOT EXISTS idx_episodes_lane ON episodes(lane);
CREATE INDEX IF NOT EXISTS idx_semantics_lane ON semantics(lane);
```

- [ ] **Step 4: Add lane to `add_episode`**

In `storage.py`, change the `add_episode` signature and INSERT:

```python
    def add_episode(
        self,
        id: str,
        session_id: str | None,
        content: str,
        episode_type: str | None = None,
        embedding: list[float] | None = None,
        entity_ids: list[str] | None = None,
        context: dict | None = None,
        lane: str = "personal",
    ) -> str:
        now = _now_iso()
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        self.conn.execute(
            "INSERT INTO episodes (id, session_id, content, episode_type, context, created_at, content_hash, lane) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (id, session_id, content, episode_type, json.dumps(context) if context is not None else None, now, content_hash, lane),
        )
```

(rest of the method unchanged)

- [ ] **Step 5: Add lane to `add_semantic`**

```python
    def add_semantic(
        self,
        id: str,
        content: str,
        kind: str,
        confidence: float,
        embedding: list[float],
        source_episode_ids: list[str],
        auto_generated: bool = False,
        lane: str = "personal",
    ) -> str:
        now = _now_iso()
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        self.conn.execute(
            "INSERT INTO semantics (id, content, kind, confidence, created_at, auto_generated, content_hash, lane) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (id, content, kind, confidence, now, 1 if auto_generated else 0, content_hash, lane),
        )
```

(rest unchanged)

- [ ] **Step 6: Add `set_episode_lanes`**

After `mark_episodes_compressed` in `storage.py`:

```python
    def set_episode_lanes(self, ids: list[str], lane: str) -> int:
        """Re-lane episodes (e.g. when compression review reveals work content)."""
        if not ids:
            return 0
        placeholders = ", ".join("?" * len(ids))
        cur = self.conn.execute(
            f"UPDATE episodes SET lane = ? WHERE id IN ({placeholders})",
            [lane, *ids],
        )
        self.conn.commit()
        return cur.rowcount
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_storage.py -q`
Expected: all pass (existing + 4 new)

- [ ] **Step 8: Commit**

```bash
git add migrations/018_memory_lanes.sql storage.py tests/test_storage.py
git commit -m "feat(lanes): lane column on episodes/semantics with storage support"
```

---

### Task 2: `remember(work=...)`

**Files:**
- Modify: `server.py` (`remember` ~line 583)
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_server.py`, inside the existing test class that uses `server_env` (next to `test_remember_stores_episode`):

```python
    def test_remember_work_flag_sets_lane(self, server_env):
        import server
        result = server.remember("CommonWell portal serves the login form on GET", work=True)
        row = server._storage.conn.execute(
            "SELECT lane FROM episodes WHERE id = ?", (result["episode_id"],)
        ).fetchone()
        assert row["lane"] == "work"

    def test_remember_defaults_personal_lane(self, server_env):
        import server
        result = server.remember("a quiet realization about reading")
        row = server._storage.conn.execute(
            "SELECT lane FROM episodes WHERE id = ?", (result["episode_id"],)
        ).fetchone()
        assert row["lane"] == "personal"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_server.py -q -k lane`
Expected: FAIL — `unexpected keyword argument 'work'`

- [ ] **Step 3: Implement**

In `server.py`, `remember`: add the parameter and pass it through. Signature becomes:

```python
def remember(
    content: str,
    context: dict | None = None,
    core: bool = False,
    genome: bool = False,
    source: str | None = None,
    work: bool = False,
) -> dict:
```

Extend the docstring Args with:

```python
        work: If True, this is work-lane reference material — it decays and
            recalls normally but never becomes core, instincts, or identity
            semantics.
```

In the `_storage.add_episode(...)` call inside `remember`, add `lane="work" if work else "personal",` as a keyword argument. After the result dict is built (`result = {"episode_id": episode_id, "layer": "episode"}` ~line 657), add:

```python
    if work:
        result["lane"] = "work"
```

Guard the conflict: `core=True`/`genome=True` with `work=True` makes no sense (work can't be core). Immediately after the length validation in `remember`, add:

```python
    if work and (core or genome):
        return {"error": "work-lane memories cannot be core or genome", "layer": "rejected"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_server.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat(lanes): remember(work=True) stores work-lane episodes"
```

---

### Task 3: Lane-pure clustering

**Files:**
- Modify: `compress.py` (`cluster_episodes` ~lines 218-275)
- Test: `tests/test_compression.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_compression.py` (after the discard tests):

```python
def test_clusters_are_lane_pure(tmp_db, compressor, embedder):
    """Episodes with identical embeddings but different lanes form separate clusters."""
    shared = embedder.embed(["shared topic"])[0]
    texts = ["personal note one", "personal note two", "work note one", "work note two"]
    for t in texts:
        embedder.override_map[t] = shared
    for t in texts[:2]:
        tmp_db.add_episode(id=str(uuid.uuid4()), session_id="t", content=t, embedding=shared)
    for t in texts[2:]:
        tmp_db.add_episode(id=str(uuid.uuid4()), session_id="t", content=t,
                           embedding=shared, lane="work")

    result = compressor.cluster_episodes()

    assert len(result["clusters"]) == 2
    for cluster in result["clusters"]:
        lanes = {ep.get("lane", "personal") for ep in cluster["episodes"]}
        assert len(lanes) == 1, f"mixed-lane cluster: {lanes}"
        assert cluster["lane"] in ("personal", "work")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_compression.py::test_clusters_are_lane_pure -q`
Expected: FAIL — one mixed cluster (`assert 1 == 2`) or missing `lane` key

- [ ] **Step 3: Implement lane partitioning**

In `compress.py` `cluster_episodes`, Step 1 (typed grouping, ~line 219) — group by `(kind, lane)`:

```python
        typed_groups: dict[tuple[str, str], list[dict]] = {}
        for ep in episodes:
            model = self._classification_config.model if self._classification_config else None
            prompt_path = self._classification_config.prompt_path if self._classification_config else None
            kinds = classify_episode_kind(ep, model=model, prompt_path=prompt_path)
            ep_lane = ep.get("lane") or "personal"
            for kind in kinds:
                typed_groups.setdefault((kind, ep_lane), []).append(ep)
```

And the loop header (~line 230):

```python
        for (kind, lane), kind_episodes in typed_groups.items():
```

Where the cluster dict is appended (~line 267-275, the dict with `episodes`/`centroid`/`match`/`action`/`near_miss`), add the lane key:

```python
                all_clusters.append({
                    "episodes": cluster_eps,
                    "centroid": centroid,
                    "action": action,
                    "match": match,
                    "near_miss": near_miss,
                    "lane": lane,
                })
```

(Match the existing dict construction exactly — only add `"lane": lane`. If the dict is built in more than one place in this function, add the key in each.)

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_compression.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add compress.py tests/test_compression.py
git commit -m "feat(lanes): clustering partitions episodes by lane"
```

---

### Task 4: Commit gating — work semantics, no core, lane override

**Files:**
- Modify: `compress.py` (`commit` ~lines 282-400)
- Test: `tests/test_compression.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_work_cluster_creates_work_semantic_without_core(tmp_db, compressor, embedder):
    """A work cluster compresses to a work semantic; no episode becomes core."""
    emb = embedder.embed(["bedrock requires inference profiles"])[0]
    tmp_db.add_episode(id=str(uuid.uuid4()), session_id="t",
                       content="bedrock requires inference profiles",
                       embedding=emb, lane="work")
    result = compressor.cluster_episodes()
    stats = compressor.commit(result["compress_id"],
                              [{"content": "Bedrock needs inference profile IDs",
                                "kind": "fact", "action": "new"}])

    assert stats["semantics_created"] == 1
    sem_lane = tmp_db.conn.execute("SELECT lane FROM semantics").fetchone()["lane"]
    assert sem_lane == "work"
    core_count = tmp_db.conn.execute(
        "SELECT COUNT(*) FROM episodes WHERE core >= 1").fetchone()[0]
    assert core_count == 0


def test_summary_lane_override_relanes_sources(tmp_db, compressor, embedder):
    """A summary carrying lane='work' re-lanes the cluster's source episodes."""
    emb = embedder.embed(["auto captured work chatter"])[0]
    eid = str(uuid.uuid4())
    tmp_db.add_episode(id=eid, session_id="t", content="auto captured work chatter",
                       embedding=emb)  # defaults personal
    result = compressor.cluster_episodes()
    stats = compressor.commit(result["compress_id"],
                              [{"content": "deploy pipeline uses blue-green",
                                "kind": "fact", "action": "new", "lane": "work"}])

    assert stats["semantics_created"] == 1
    ep_lane = tmp_db.conn.execute(
        "SELECT lane FROM episodes WHERE id = ?", (eid,)).fetchone()["lane"]
    assert ep_lane == "work"
    sem_lane = tmp_db.conn.execute("SELECT lane FROM semantics").fetchone()["lane"]
    assert sem_lane == "work"
    core_count = tmp_db.conn.execute(
        "SELECT COUNT(*) FROM episodes WHERE core >= 1").fetchone()[0]
    assert core_count == 0


def test_personal_cluster_still_promotes_core(tmp_db, compressor, embedder):
    """Personal lane keeps today's behavior: centroid episode becomes core."""
    emb = embedder.embed(["a formative correction"])[0]
    tmp_db.add_episode(id=str(uuid.uuid4()), session_id="t",
                       content="a formative correction", embedding=emb)
    result = compressor.cluster_episodes()
    compressor.commit(result["compress_id"],
                      [{"content": "corrections change how I read",
                        "kind": "preference", "action": "new"}])
    core_count = tmp_db.conn.execute(
        "SELECT COUNT(*) FROM episodes WHERE core >= 1").fetchone()[0]
    assert core_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_compression.py -q -k "lane or core_count or promotes_core"`
Expected: first two FAIL (`sem_lane == 'personal'`, `core_count == 1`); third should PASS already (guards against regression)

- [ ] **Step 3: Implement**

In `compress.py` `commit`, inside the per-cluster loop after `action = summary.get("action", cluster["action"])` (and after the existing `discard` block), resolve the lane:

```python
            lane = summary.get("lane") or cluster.get("lane") or "personal"
            if summary.get("lane") and summary["lane"] != cluster.get("lane", "personal"):
                # Compression review corrected the lane — re-lane the evidence too
                self._storage.set_episode_lanes(all_episode_ids, summary["lane"])
```

Pass lane into `add_semantic` (the call ~line 333):

```python
                self._storage.add_semantic(
                    id=new_id,
                    content=semantic_content,
                    kind=summary.get("kind", "fact"),
                    confidence=confidence,
                    embedding=semantic_embedding if semantic_embedding is not None else centroid,
                    source_episode_ids=source_ids,
                    auto_generated=bool(summary.get("auto_generated", False)),
                    lane=lane,
                )
```

Gate core promotion (the `mark_core` block ~line 343):

```python
                if lane != "work" and centroid is not None and source_ids:
                    centroid_nearest = self._find_centroid_nearest_id(
                        cluster["episodes"], centroid, source_ids,
                    )
                    if centroid_nearest:
                        self._storage.mark_core(centroid_nearest)
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_compression.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add compress.py tests/test_compression.py
git commit -m "feat(lanes): work clusters skip core promotion; summary lane override"
```

---

### Task 5: Cross-lane reinforcement guard

**Files:**
- Modify: `compress.py` (`_find_semantic_match` ~line 958, call site ~line 267)
- Test: `tests/test_compression.py`

- [ ] **Step 1: Write the failing test**

```python
def test_work_episode_does_not_reinforce_personal_semantic(tmp_db, compressor, embedder):
    """A work cluster matching a personal semantic gets action='new', not 'reinforce'."""
    text = "always check the page's own classification first"
    emb = embedder.embed([text])[0]
    tmp_db.add_semantic(
        id=str(uuid.uuid4()), content=text, kind="fact",
        confidence=0.8, embedding=emb, source_episode_ids=[],
    )  # personal lane
    embedder.override_map["work version of the same idea"] = emb
    tmp_db.add_episode(id=str(uuid.uuid4()), session_id="t",
                       content="work version of the same idea",
                       embedding=emb, lane="work")

    result = compressor.cluster_episodes()

    assert len(result["clusters"]) == 1
    assert result["clusters"][0]["action"] == "new"
    assert result["clusters"][0]["match"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_compression.py::test_work_episode_does_not_reinforce_personal_semantic -q`
Expected: FAIL — `action == 'reinforce'`

- [ ] **Step 3: Implement**

Change `_find_semantic_match` to be lane-aware — search wider, take the first same-lane hit:

```python
    def _find_semantic_match(self, centroid: list[float], lane: str = "personal") -> tuple[str, dict | None, dict | None]:
        """Search for an existing same-lane semantic matching this centroid.

        Returns (action, match_info, near_miss) where:
        - action is 'reinforce' or 'new'
        - match_info is populated when action == 'reinforce'
        - near_miss is populated when similarity is in [0.50, reinforce_threshold)

        Cross-lane matches are skipped entirely: a work episode must not
        reinforce a personal semantic (or vice versa).
        """
        try:
            results = self._storage.search_vectors("semantic", centroid, k=5)
            for sem_id, distance in results:
                sem = self._storage.get_semantic(sem_id)
                if not sem or (sem.get("lane") or "personal") != lane:
                    continue
                similarity = vec0_distance_to_similarity(distance)
                if similarity >= self._reinforce_threshold:
                    return "reinforce", {"id": sem_id, "similarity": similarity, "content": sem["content"]}, None
                elif similarity >= 0.50:
                    return "new", None, {"id": sem_id, "similarity": similarity}
                break  # best same-lane hit below near-miss range — stop
        except Exception:
            logger.debug("Semantic vector search failed (table may be empty)")

        return "new", None, None
```

At the call site in `cluster_episodes` (~line 267), pass the group's lane:

```python
                action, match, near_miss = self._find_semantic_match(centroid, lane=lane)
```

(`lane` is in scope from the Task 3 loop header.)

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_compression.py -q`
Expected: all pass — including existing reinforce tests (they use personal-lane episodes and semantics, unaffected)

- [ ] **Step 5: Commit**

```bash
git add compress.py tests/test_compression.py
git commit -m "feat(lanes): reinforcement matching is lane-scoped"
```

---

### Task 6: Instinct formation gate

**Files:**
- Modify: `compress.py` (`_check_instinct_creation` ~line 690)
- Test: `tests/test_compression.py`

- [ ] **Step 1: Write the failing test**

```python
def test_work_semantic_never_becomes_instinct(tmp_db, compressor, embedder):
    """A high-confidence work-lane preference is skipped by instinct creation."""
    text = "prefer cursor-based pagination for the portal scraper"
    tmp_db.add_semantic(
        id=str(uuid.uuid4()), content=text, kind="preference",
        confidence=0.85, embedding=embedder.embed([text])[0],
        source_episode_ids=[], lane="work",
    )
    _add_episode(tmp_db, "instinct gate filler", embedder.embed(["instinct gate filler"])[0])
    result = compressor.cluster_episodes()
    stats = compressor.commit(result["compress_id"],
                              [{"content": "filler", "kind": "fact", "action": "new"}])

    assert stats["instincts_created"] == 0
    assert tmp_db.get_all_instincts() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_compression.py::test_work_semantic_never_becomes_instinct -q`
Expected: FAIL — `instincts_created == 1`

- [ ] **Step 3: Implement**

In `_check_instinct_creation`, inside the `for sem in semantics:` loop, immediately after the confidence check (`if sem["confidence"] < self._instinct_confidence: continue`):

```python
                if (sem.get("lane") or "personal") == "work":
                    continue  # work lane never forms instincts
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_compression.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add compress.py tests/test_compression.py
git commit -m "feat(lanes): work semantics are gated out of instinct formation"
```

---

### Task 7: Recall lane labels and filter

**Files:**
- Modify: `server.py` (`recall` — episode results ~lines 840-852, semantic results ~lines 865-877, signature)
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing tests**

In the `server_env` test class:

```python
    def test_recall_labels_lanes(self, server_env):
        import server
        server.remember("the portal login serves the form on GET", work=True)
        server.remember("a memory about reading with someone")
        result = server.recall("portal login form")
        episode_lanes = {r["content"]: r.get("lane") for r in result["results"]
                         if r.get("layer") == "episode"}
        assert episode_lanes["the portal login serves the form on GET"] == "work"
        assert episode_lanes["a memory about reading with someone"] == "personal"

    def test_recall_lane_filter(self, server_env):
        import server
        server.remember("kubernetes ingress needs the rewrite annotation", work=True)
        server.remember("a conversation that changed my reading")
        result = server.recall("anything at all", lane="work", uninvited=0)
        for r in result["results"]:
            assert r.get("lane") == "work"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_server.py -q -k "recall_labels or recall_lane"`
Expected: FAIL — `lane` missing / unexpected keyword `lane`

- [ ] **Step 3: Implement**

In `server.py` `recall`: add `lane: str | None = None` to the signature and document it ("Filter to a lane: 'personal' or 'work'. Default spans both."). In each episode result dict (both ~line 840 and the uninvited one ~line 852) add:

```python
                    "lane": ep.get("lane") or "personal",
```

In each semantic result dict (~lines 865 and 877) add:

```python
                    "lane": sem.get("lane") or "personal",
```

(`ep`/`sem` — match the local variable names used at each site; they are dicts from storage rows, which include `lane` after migration 018.)

Just before the `response = {"results": results, "recall_id": recall_id}` line, apply the filter — instincts and other lane-less layers count as personal:

```python
    if lane is not None:
        results = [r for r in results if (r.get("lane") or "personal") == lane]
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_server.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat(lanes): recall labels lanes and accepts a lane filter"
```

---

### Task 8: Per-lane reflection

**Files:**
- Modify: `reflection.py` (`vital_signs` ~line 130)
- Test: `tests/test_reflection.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_reflection.py` (use that file's existing fixture for a `Reflector` with storage — match its naming; the test below assumes a `tmp_db` Storage fixture and constructs the Reflector the same way neighboring tests do):

```python
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
    assert vs["episode_count"] == 2          # personal only
    assert vs["core_fraction"] == 0.5        # 1 of 2 personal
    assert vs["lanes"] == {"episodes": {"personal": 2, "work": 2},
                           "semantics": {"personal": 0, "work": 0}}
```

(Check the `Reflector` constructor signature used by neighboring tests in `tests/test_reflection.py` and match it — it takes storage and `staleness_days`, plus optional genome/signals paths.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reflection.py -q -k personal_lane`
Expected: FAIL — `episode_count == 4`, no `lanes` key

- [ ] **Step 3: Implement**

In `reflection.py` `vital_signs`, replace the episode/core counting block:

```python
        episode_count = self._storage.conn.execute(
            "SELECT COUNT(*) FROM episodes WHERE COALESCE(lane, 'personal') = 'personal'"
        ).fetchone()[0]
        core_count = self._storage.conn.execute(
            "SELECT COUNT(*) FROM episodes WHERE core >= 1 AND COALESCE(lane, 'personal') = 'personal'"
        ).fetchone()[0]
```

Before the return statement, gather lane counts:

```python
        lane_counts = {"episodes": {"personal": 0, "work": 0},
                       "semantics": {"personal": 0, "work": 0}}
        for table in ("episodes", "semantics"):
            rows = self._storage.conn.execute(
                f"SELECT COALESCE(lane, 'personal') AS lane, COUNT(*) FROM {table} GROUP BY 1"
            ).fetchall()
            for lane_name, count in rows:
                lane_counts[table][lane_name] = count
```

And add to the returned dict: `"lanes": lane_counts,`.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_reflection.py -q`
Expected: all pass. If an existing vital_signs test asserts on total `episode_count`, update it to reflect personal-lane counting (that change is intended behavior per the spec).

- [ ] **Step 5: Commit**

```bash
git add reflection.py tests/test_reflection.py
git commit -m "feat(lanes): vital_signs computes core health over the personal lane"
```

---

### Task 9: Full suite + docs

**Files:**
- Modify: `CLAUDE.md` (MCP tools table, architecture section)

- [ ] **Step 1: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all pass (475+ tests)

- [ ] **Step 2: Update CLAUDE.md**

In the MCP tools table, update the `remember` row:

```markdown
| `remember(content, core?, source?, work?)` | Store an episode. `core=True` for formative memories, `source` for provenance, `work=True` for work-lane reference material. |
```

Update the `recall` row:

```markdown
| `recall(query, lane?)` | Search across all layers. Returns `recall_id` for feedback. `lane="work"|"personal"` to filter. Scores hidden when dreaming. |
```

In the Architecture section, after the **Task contexts** paragraph, add:

```markdown
**Memory lanes:** Episodes and semantics carry a `lane` ('personal' | 'work').
The work lane is reference material: it decays and recalls normally but never
becomes core episodes, instincts, or reinforcement for personal semantics.
Lane is set at write time (`remember(work=True)`) and correctable during
compression review (summary `lane` override re-lanes source episodes).
Clustering is lane-pure. Spec: docs/superpowers/specs/2026-06-12-memory-lanes-design.md.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(lanes): document memory lanes in CLAUDE.md"
```

---

### Task 10: Data migration — re-lane existing work content

This is a judgment task performed against the live store at
`.engram/instances/engram/graph.db` (the MCP server should be restarted after
the code tasks, before or after this — the SQL here goes direct, same as the
core triage did).

- [ ] **Step 1: Generate candidates**

```bash
cd /Users/kairos/Projects/engram/.engram/instances/engram && sqlite3 -separator ' | ' graph.db "
SELECT 'episode', id, substr(replace(content, char(10),' '), 1, 120) FROM episodes
WHERE COALESCE(lane,'personal') = 'personal' AND (
  content LIKE '%LF52%' OR content LIKE '%WA30%' OR content LIKE '%ARC-AGI%'
  OR content LIKE '%CommonWell%' OR content LIKE '%lkopera%' OR content LIKE '%Bedrock%'
  OR content LIKE '%BG3%' OR content LIKE '%CDP%' OR content LIKE '%zsh%'
  OR content LIKE '%universal_note%' OR content LIKE '%codex-pair%'
  OR content LIKE '%asyncio%' OR content LIKE '%md5%' OR content LIKE '%graphiti_core%')
UNION ALL
SELECT 'semantic', id, substr(replace(content, char(10),' '), 1, 120) FROM semantics
WHERE COALESCE(lane,'personal') = 'personal' AND contradicted_by IS NULL AND (
  content LIKE '%LF52%' OR content LIKE '%WA30%' OR content LIKE '%ARC-AGI%'
  OR content LIKE '%CommonWell%' OR content LIKE '%lkopera%' OR content LIKE '%Bedrock%'
  OR content LIKE '%BG3%' OR content LIKE '%CDP%' OR content LIKE '%zsh%'
  OR content LIKE '%universal_note%' OR content LIKE '%codex-pair%'
  OR content LIKE '%asyncio%' OR content LIKE '%md5%' OR content LIKE '%graphiti_core%');"
```

- [ ] **Step 2: Review the candidate list**

Read every candidate. The keyword list over-matches on purpose — exclude
anything where the work reference is incidental to a personal memory (e.g. an
identity episode that *mentions* LF52 while recording a cognitive
self-observation stays personal; kept-core episodes from the 2026-06-10 triage
stay personal by definition). Produce the final ID list.

- [ ] **Step 3: Apply and save the artifact**

For the reviewed IDs (episodes and semantics separately):

```bash
sqlite3 graph.db "UPDATE episodes  SET lane='work' WHERE id IN (<reviewed episode ids>);
UPDATE semantics SET lane='work' WHERE id IN (<reviewed semantic ids>);"
```

Save the re-laned IDs with one-line reasons to
`.engram/lane_triage_2026-06-12.json` (same convention as
`core_triage_2026-06-10_pass2.json`).

- [ ] **Step 4: Verify**

```bash
sqlite3 graph.db "SELECT COALESCE(lane,'personal'), COUNT(*) FROM episodes GROUP BY 1;
SELECT COALESCE(lane,'personal'), COUNT(*) FROM semantics GROUP BY 1;"
```

Expected: a work lane exists; no core episode is in it:

```bash
sqlite3 graph.db "SELECT COUNT(*) FROM episodes WHERE lane='work' AND core >= 1;"
```

Expected: `0`

---

## Self-Review Checklist (run after writing)

- Spec coverage: §1 lane field → Task 1; §2 write path → Tasks 2, 4; §3 gating → Tasks 4, 5, 6; §4 recall → Task 7; §5 reflection → Task 8; §6 migration → Task 10. Docs → Task 9.
- Reminder for the executor: the live MCP server must be restarted to pick up these changes.
