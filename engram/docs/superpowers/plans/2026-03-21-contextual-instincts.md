# Contextual Perceptual Instincts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform instincts from static behavioral rules (trigger/action) into context-sensitive perceptual attention directives (notice/implication) with dual-vector search and contextual feedback.

**Architecture:** Instincts gain two new fields (`notice`, `implication`) replacing the semantics of `trigger`/`action`. Each instinct gets two embeddings: a content vector (what it's about, for cross-layer recall) and a context vector (when it applies, for contextual activation). Feedback becomes context-aware — followed/overridden per-situation rather than globally. The existing `trigger`/`action` columns are preserved for backward compatibility but the system reads `notice`/`implication` when present.

**Tech Stack:** SQLite + vec0, FastEmbed (nomic-embed-text-v1.5, 768-dim), Python 3.12, pytest

---

### Task 1: Migration — Add instinct context fields and context feedback table

**Files:**
- Create: `migrations/008_contextual_instincts.sql`
- Modify: `storage.py` — add context feedback methods

- [ ] **Step 1: Write the migration SQL**

```sql
-- Contextual instincts: perceptual attention directives with dual vectors and context feedback.

-- New fields on instincts for perceptual framing
ALTER TABLE instincts ADD COLUMN notice TEXT;
ALTER TABLE instincts ADD COLUMN implication TEXT;

-- Context vector table (separate from content vectors in instinct_vectors)
CREATE VIRTUAL TABLE IF NOT EXISTS instinct_context_vectors USING vec0(
    id TEXT PRIMARY KEY,
    embedding float[768]
);

-- Context feedback: per-situation follow/override tracking
CREATE TABLE IF NOT EXISTS instinct_context_feedback (
    id TEXT PRIMARY KEY,
    instinct_id TEXT NOT NULL REFERENCES instincts(id) ON DELETE CASCADE,
    context_text TEXT NOT NULL,
    context_embedding BLOB,
    followed BOOLEAN NOT NULL,
    timestamp TEXT NOT NULL
);
```

- [ ] **Step 2: Verify migration applies cleanly**

Run: `.venv/bin/python -c "from storage import Storage; s = Storage('/tmp/test_mig.db'); print('OK'); s.close()"`
Expected: OK (migrations auto-run on Storage init)

- [ ] **Step 3: Commit**

```bash
git add migrations/008_contextual_instincts.sql
git commit -m "migration 008: contextual instincts schema — notice/implication, context vectors, feedback table"
```

---

### Task 2: Storage — Context feedback and dual-vector methods

**Files:**
- Modify: `storage.py` — add instinct context feedback CRUD, context vector search
- Test: `tests/test_storage.py` — new tests for context feedback

- [ ] **Step 1: Write failing tests for context feedback storage**

```python
def test_add_instinct_context_feedback(tmp_db, fake_embedding):
    """Store context feedback for an instinct."""
    emb = fake_embedding()
    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(id=sem_id, content="test", kind="preference",
                        confidence=0.5, embedding=emb, source_episode_ids=[])
    inst_id = tmp_db.add_instinct(
        id=str(uuid.uuid4()), trigger="preference", action="be terse",
        source_semantic_ids=[sem_id], embedding=emb,
    )
    from storage import _pack_embedding
    tmp_db.add_instinct_context_feedback(
        instinct_id=inst_id, context_text="building code",
        context_embedding=_pack_embedding(emb), followed=True,
    )
    feedback = tmp_db.get_instinct_context_feedback(inst_id)
    assert len(feedback) == 1
    assert feedback[0]["followed"] == 1
    assert feedback[0]["context_text"] == "building code"


def test_instinct_contextual_strength(tmp_db, fake_embedding):
    """Contextual strength should reflect follow/override ratio in similar contexts."""
    emb = fake_embedding()
    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(id=sem_id, content="test", kind="preference",
                        confidence=0.5, embedding=emb, source_episode_ids=[])
    inst_id = tmp_db.add_instinct(
        id=str(uuid.uuid4()), trigger="preference", action="be terse",
        source_semantic_ids=[sem_id], embedding=emb,
    )
    from storage import _pack_embedding
    packed = _pack_embedding(emb)
    # 3 follows, 1 override in this context
    for _ in range(3):
        tmp_db.add_instinct_context_feedback(
            instinct_id=inst_id, context_text="building",
            context_embedding=packed, followed=True,
        )
    tmp_db.add_instinct_context_feedback(
        instinct_id=inst_id, context_text="building",
        context_embedding=packed, followed=False,
    )
    ratio = tmp_db.get_context_follow_ratio(inst_id, context_text="building")
    assert ratio == pytest.approx(0.75)


def test_add_instinct_with_notice_implication(tmp_db, fake_embedding):
    """Instincts can be created with notice and implication fields."""
    emb = fake_embedding()
    inst_id = tmp_db.add_instinct(
        id=str(uuid.uuid4()), trigger="preference", action="be terse",
        source_semantic_ids=[],
        notice="when the conversation shifts from building to reflecting",
        implication="communication style should match the mode",
        embedding=emb,
    )
    inst = tmp_db.get_instinct(inst_id)
    assert inst["notice"] == "when the conversation shifts from building to reflecting"
    assert inst["implication"] == "communication style should match the mode"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_storage.py -k "context_feedback or notice_implication" -v`
Expected: FAIL

- [ ] **Step 3: Implement storage methods**

In `storage.py`, add to the `Storage` class:

1. Update `add_instinct()` to accept optional `notice` and `implication` parameters, storing them in the new columns.
2. Add `add_instinct_context_feedback(instinct_id, context_text, context_embedding, followed)` — inserts into `instinct_context_feedback`.
3. Add `get_instinct_context_feedback(instinct_id)` — returns all feedback rows for an instinct.
4. Add `get_context_follow_ratio(instinct_id, context_text)` — returns followed/total ratio for feedback matching that context.
5. Add `add_instinct_context_vector(id, embedding)` — inserts into `instinct_context_vectors`.
6. Register `"instinct_context"` in `_VECTOR_TABLES` so `search_vectors("instinct_context", ...)` works.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_storage.py -k "context_feedback or notice_implication" -v`
Expected: PASS

- [ ] **Step 5: Run full test suite for regressions**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add storage.py tests/test_storage.py
git commit -m "feat(storage): context feedback CRUD, notice/implication on instincts, dual vector support"
```

---

### Task 3: Contextual instinct recall in server

**Files:**
- Modify: `server.py` — change instinct recall to use context-vector search, update `instinct_feedback()` to store context
- Test: `tests/test_server.py` — update instinct recall tests

- [ ] **Step 1: Write failing test for contextual instinct recall**

```python
def test_recall_instincts_filtered_by_context(self, server_env):
    """Instinct recall should return instincts relevant to the query context, not all."""
    srv = server_env["server"]
    storage = server_env["storage"]
    embeddings = server_env["embeddings"]
    # Create two instincts with different context vectors
    emb_build = embeddings.embed(["building code and implementing features"])[0]
    emb_reflect = embeddings.embed(["reflecting on design and philosophy"])[0]
    sem_id1 = str(uuid.uuid4())
    sem_id2 = str(uuid.uuid4())
    storage.add_semantic(id=sem_id1, content="s1", kind="preference",
                         confidence=0.5, embedding=emb_build, source_episode_ids=[])
    storage.add_semantic(id=sem_id2, content="s2", kind="preference",
                         confidence=0.5, embedding=emb_reflect, source_episode_ids=[])
    storage.add_instinct(
        id="inst-build", trigger="preference", action="be terse",
        source_semantic_ids=[sem_id1], embedding=emb_build,
        notice="when building code", implication="keep communication terse",
    )
    storage.add_instinct(
        id="inst-reflect", trigger="preference", action="explore deeply",
        source_semantic_ids=[sem_id2], embedding=emb_reflect,
        notice="when reflecting on design", implication="expand on reasoning",
    )
    # Add context vectors for both
    from storage import _pack_embedding
    storage.add_instinct_context_vector("inst-build", emb_build)
    storage.add_instinct_context_vector("inst-reflect", emb_reflect)

    # Query in a building context — should rank build instinct higher
    result = srv.recall(query="implementing a new feature", layer="instinct")
    assert len(result["results"]) >= 1
    # The build instinct should score higher than the reflect one
    ids = [r["id"] for r in result["results"]]
    if "inst-build" in ids and "inst-reflect" in ids:
        build_score = next(r["score"] for r in result["results"] if r["id"] == "inst-build")
        reflect_score = next(r["score"] for r in result["results"] if r["id"] == "inst-reflect")
        assert build_score > reflect_score
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_server.py -k "filtered_by_context" -v`
Expected: FAIL

- [ ] **Step 3: Modify instinct recall in `server.py`**

Change the `layer == "instinct"` special case in `recall()` (lines 291-313) to use context-vector search instead of `get_all_instincts()`:

1. Embed the query
2. Search `instinct_context_vectors` for nearest matches
3. Fall back to `instinct_vectors` (content vectors) if no context vectors exist
4. Score as: `context_similarity * 0.5 + content_similarity * 0.2 + strength * 0.3`
5. Return sorted results with `notice` and `implication` fields when present

- [ ] **Step 4: Update `instinct_feedback()` to accept optional context**

Add `context: str | None = None` parameter. When provided, embed the context and store in `instinct_context_feedback` alongside the global strength update. This preserves backward compatibility — existing feedback still works globally.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_server.py -k "instinct" -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat(server): contextual instinct recall with dual-vector search, context-aware feedback"
```

---

### Task 4: Instinct creation as perceptual reframing

**Files:**
- Modify: `compress.py` — `_check_instinct_creation()` generates notice/implication from semantic content
- Test: `tests/test_compression.py` — update instinct creation tests

- [ ] **Step 1: Write failing test for perceptual instinct creation**

```python
def test_instinct_created_with_notice_implication(tmp_db, compressor, embedder):
    """High-confidence preference semantic should create instinct with notice/implication."""
    text = "always use type hints in function signatures"
    emb = embedder.embed([text])[0]
    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sem_id, content=text, kind="preference",
        confidence=0.85, embedding=emb, source_episode_ids=[],
    )
    _add_episode(tmp_db, "filler", embedder.embed(["filler"])[0])
    result = compressor.cluster_episodes()
    summaries = [{"content": "filler", "kind": "fact", "action": "new"}]
    stats = compressor.commit(result["compress_id"], summaries)

    assert stats["instincts_created"] == 1
    instincts = tmp_db.get_all_instincts()
    inst = instincts[0]
    # Should have notice and implication fields populated
    assert inst["notice"] is not None
    assert inst["implication"] is not None
    # Notice should be about what to attend to, not a behavioral rule
    assert inst["notice"] != inst["action"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_compression.py -k "notice_implication" -v`
Expected: FAIL

- [ ] **Step 3: Implement perceptual reframing in `_check_instinct_creation()`**

In `compress.py`, modify `_check_instinct_creation()`:

1. When creating an instinct from a semantic, generate `notice` and `implication` from the semantic content and kind:
   - For `kind="preference"`: `notice` = "when making choices about: {topic}" / `implication` = semantic content
   - For `kind="constraint"`: `notice` = "when: {condition applies}" / `implication` = semantic content
2. The heuristic extraction parses the semantic content to separate the situational trigger from the behavioral content. This is a simple rule-based approach — no LLM needed.
3. Embed the `notice` text as the context vector, store in `instinct_context_vectors`.
4. The existing `action` embedding goes into `instinct_vectors` (content vector) as before.

Heuristic for notice generation from semantic text:
- If text starts with "always/never/prefer/avoid" → strip the directive word, the rest describes what to attend to
- If text contains "when" → split on "when", before is implication, after is notice
- Fallback: `notice` = f"when making decisions about: {kind}" / `implication` = full text

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_compression.py -v`
Expected: All pass (including existing tests — backward compatible)

- [ ] **Step 5: Commit**

```bash
git add compress.py tests/test_compression.py
git commit -m "feat(compress): generate perceptual instincts with notice/implication during promotion"
```

---

### Task 5: Wake hook — contextual instinct loading

**Files:**
- Modify: `hooks/wake.py` — use context vector search when session_context is set, display notice/implication
- Test: `tests/test_wake.py` — update wake tests

- [ ] **Step 1: Write failing test for contextual wake**

```python
def test_wake_displays_notice_implication(self, tmp_path):
    """Wake output should show notice/implication when present on instincts."""
    db_path = tmp_path / ".engram" / "graph.db"
    db_path.parent.mkdir(parents=True)
    store = Storage(str(db_path))
    sem_id = str(uuid.uuid4())
    store.add_semantic(id=sem_id, content="test", kind="preference",
                       confidence=0.5, embedding=None, source_episode_ids=[])
    store.add_instinct(
        id="inst-1", trigger="preference", action="be terse",
        source_semantic_ids=[sem_id],
        notice="when building code and implementing features",
        implication="keep communication focused and direct",
    )
    store.close()

    import hooks.wake as wake_module
    wake_module.DB_PATH = db_path
    # Capture output
    import io, json
    captured = io.StringIO()
    import sys
    old_stdout = sys.stdout
    sys.stdout = captured
    wake_module.wake()
    sys.stdout = old_stdout

    output = json.loads(captured.getvalue())
    msg = output["systemMessage"]
    assert "attend to" in msg.lower() or "notice" in msg.lower() or "when building" in msg.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_wake.py -k "notice_implication" -v`
Expected: FAIL

- [ ] **Step 3: Update wake.py**

1. When instincts have `notice` and `implication` fields, display them in the orientation message as:
   ```
   - **Attend to:** {notice}
     *{implication}*
     (strength=0.60)
   ```
   Fall back to the existing `[trigger] action` format when notice/implication are NULL.

2. When `session_context` is set in config, use it as a context hint: query the `instinct_context_vectors` table to find relevant instincts rather than loading all of them. This requires loading vec0, so wrap in a try/except and fall back to loading all instincts if vec0 search fails.

- [ ] **Step 4: Run wake tests**

Run: `.venv/bin/python -m pytest tests/test_wake.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add hooks/wake.py tests/test_wake.py
git commit -m "feat(wake): display perceptual instincts, context-filtered loading"
```

---

### Task 6: Reflection — per-context instinct health

**Files:**
- Modify: `reflection.py` — add `instinct_context_health()` method
- Modify: `server.py` — add `reflect(focus="instinct_contexts")` dispatch
- Test: `tests/test_reflection.py` — new tests

- [ ] **Step 1: Write failing test for per-context instinct health**

```python
def test_instinct_context_health(tmp_db):
    """Per-context health should show follow/override ratio per context."""
    sem_id = str(uuid.uuid4())
    emb = [0.1] * 768
    tmp_db.add_semantic(id=sem_id, content="test", kind="preference",
                        confidence=0.5, embedding=emb, source_episode_ids=[])
    tmp_db.add_instinct(
        id="inst-ctx", trigger="preference", action="be terse",
        source_semantic_ids=[sem_id],
    )
    # Add context feedback
    from storage import _pack_embedding
    packed = _pack_embedding(emb)
    for _ in range(3):
        tmp_db.add_instinct_context_feedback(
            instinct_id="inst-ctx", context_text="building",
            context_embedding=packed, followed=True,
        )
    tmp_db.add_instinct_context_feedback(
        instinct_id="inst-ctx", context_text="reflecting",
        context_embedding=packed, followed=False,
    )

    from reflection import Reflector
    reflector = Reflector(tmp_db)
    health = reflector.instinct_context_health()
    assert len(health) >= 1
    inst_health = health[0]
    assert "contexts" in inst_health
    assert any(c["context"] == "building" and c["follow_ratio"] == 1.0
               for c in inst_health["contexts"])
    assert any(c["context"] == "reflecting" and c["follow_ratio"] == 0.0
               for c in inst_health["contexts"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reflection.py -k "context_health" -v`
Expected: FAIL

- [ ] **Step 3: Implement `instinct_context_health()` in Reflector**

1. Query `instinct_context_feedback` grouped by `(instinct_id, context_text)`
2. Compute follow ratio per context per instinct
3. Return list of `{id, action, notice, implication, contexts: [{context, follow_ratio, count}]}`

- [ ] **Step 4: Add dispatch in `reflection.py`**

In `reflection.py`, add dispatch for `focus="instinct_contexts"` in the `reflect()` method.

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_reflection.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add reflection.py server.py tests/test_reflection.py
git commit -m "feat(reflection): per-context instinct health analysis"
```

---

### Task 7: Backfill existing instincts

**Files:**
- Modify: `server.py` — add backfill step in `_init()` for existing instincts without notice/implication

- [ ] **Step 1: Write failing test for backfill**

```python
def test_backfill_instinct_notice_implication(tmp_db, embedder):
    """Existing instincts without notice/implication should get backfilled."""
    from compress import Compressor
    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(id=sem_id, content="test", kind="preference",
                        confidence=0.5, embedding=embedder.embed(["test"])[0],
                        source_episode_ids=[])
    tmp_db.add_instinct(
        id="old-inst", trigger="preference",
        action="Prefer terse, direct communication.",
        source_semantic_ids=[sem_id],
        embedding=embedder.embed(["Prefer terse, direct communication."])[0],
    )
    # Verify no notice/implication yet
    inst = tmp_db.get_instinct("old-inst")
    assert inst["notice"] is None

    # Backfill function should populate notice/implication
    from server import _backfill_instinct_perceptual
    _backfill_instinct_perceptual(tmp_db, embedder)

    inst = tmp_db.get_instinct("old-inst")
    assert inst["notice"] is not None
    assert inst["implication"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_server.py -k "backfill_instinct" -v`
Expected: FAIL

- [ ] **Step 3: Implement backfill function**

Add `_backfill_instinct_perceptual(storage, embeddings)` to `server.py`:
1. Find all instincts where `notice IS NULL`
2. Apply the same heuristic from Task 4 to generate notice/implication from action text
3. Update the instinct rows
4. Embed notice text and store in `instinct_context_vectors`

Call this from `_init()` after the existing instinct vector backfill step.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat(server): backfill existing instincts with notice/implication on init"
```

---

### Task 8: Instinct dedup update — check notice + implication pair

**Files:**
- Modify: `compress.py` — update `_instinct_already_exists()` to consider notice/implication
- Test: `tests/test_compression.py`

- [ ] **Step 1: Write failing test**

```python
def test_dedup_considers_notice_not_just_action(tmp_db, embedder):
    """Two instincts with same implication but different notice should NOT be deduped."""
    dedup = FakeDeduplicator()  # No equivalences — tests embedding path
    compressor = Compressor(tmp_db, embedder, config=None, deduplicator=dedup)

    sem_id1 = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sem_id1, content="keep communication focused", kind="preference",
        confidence=0.85, embedding=embedder.embed(["keep communication focused"])[0],
        source_episode_ids=[],
    )
    tmp_db.add_instinct(
        id="inst-comm", trigger="preference",
        action="keep communication focused",
        source_semantic_ids=[sem_id1],
        notice="when building code",
        implication="keep communication focused",
        embedding=embedder.embed(["keep communication focused"])[0],
    )

    # Different semantic, same general topic but different context
    sem_id2 = str(uuid.uuid4())
    tmp_db.add_semantic(
        id=sem_id2, content="keep error messages focused", kind="preference",
        confidence=0.85, embedding=embedder.embed(["keep error messages focused"])[0],
        source_episode_ids=[],
    )

    _add_episode(tmp_db, "filler", embedder.embed(["filler"])[0])
    result = compressor.cluster_episodes()
    summaries = [{"content": "filler", "kind": "fact", "action": "new"}]
    stats = compressor.commit(result["compress_id"], summaries)

    # Should create the second instinct (different topic despite similar action)
    assert stats["instincts_created"] == 1
```

- [ ] **Step 2: Run test, verify failure**

Run: `.venv/bin/python -m pytest tests/test_compression.py -k "notice_not_just" -v`
Expected: FAIL

- [ ] **Step 3: Update `_instinct_already_exists()` in compress.py**

When checking dedup, compare the notice/implication pair, not just the action text. Two instincts are duplicates only when both their perceptual target (notice) and their implication are equivalent.

- [ ] **Step 4: Run all compression tests**

Run: `.venv/bin/python -m pytest tests/test_compression.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add compress.py tests/test_compression.py
git commit -m "feat(compress): dedup checks notice+implication pair, not just action text"
```

---

### Task 9: Cleanup — vec0 orphan prevention in reset and prune

**Files:**
- Modify: `storage.py` — update `prune_weak_instincts()` to delete from `instinct_context_vectors`
- Modify: `compress.py` — update `_reset_all()` to delete from `instinct_context_vectors` and `instinct_context_feedback`
- Test: `tests/test_storage.py`, `tests/test_compression.py`

vec0 virtual tables don't support FK CASCADE, so instinct deletion leaves orphaned context vectors. Both `prune_weak_instincts()` and `_reset_all()` need explicit cleanup.

- [ ] **Step 1: Write failing test for prune cleanup**

```python
def test_prune_weak_instincts_cleans_context_vectors(tmp_db, fake_embedding):
    """Pruning weak instincts should also remove their context vectors and feedback."""
    emb = fake_embedding()
    sem_id = str(uuid.uuid4())
    tmp_db.add_semantic(id=sem_id, content="test", kind="preference",
                        confidence=0.5, embedding=emb, source_episode_ids=[])
    inst_id = str(uuid.uuid4())
    tmp_db.add_instinct(
        id=inst_id, trigger="preference", action="weak instinct",
        source_semantic_ids=[sem_id], strength=0.05, embedding=emb,
    )
    tmp_db.add_instinct_context_vector(inst_id, emb)
    from storage import _pack_embedding
    tmp_db.add_instinct_context_feedback(
        instinct_id=inst_id, context_text="test",
        context_embedding=_pack_embedding(emb), followed=False,
    )

    pruned = tmp_db.prune_weak_instincts(strength_threshold=0.1)
    assert pruned == 1

    # Context vectors and feedback should be gone too
    ctx_vec = tmp_db.conn.execute(
        "SELECT COUNT(*) FROM instinct_context_vectors WHERE id = ?", (inst_id,)
    ).fetchone()[0]
    assert ctx_vec == 0
    feedback = tmp_db.get_instinct_context_feedback(inst_id)
    assert len(feedback) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_storage.py -k "prune_weak_instincts_cleans" -v`
Expected: FAIL

- [ ] **Step 3: Update `prune_weak_instincts()` in storage.py**

Add cleanup of `instinct_context_vectors` (explicit DELETE for each pruned id) before deleting from `instincts`. The `instinct_context_feedback` FK CASCADE handles feedback rows.

- [ ] **Step 4: Update `_reset_all()` in compress.py**

Add:
```python
self._storage.conn.execute("DELETE FROM instinct_context_vectors")
self._storage.conn.execute("DELETE FROM instinct_context_feedback")
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add storage.py compress.py tests/test_storage.py tests/test_compression.py
git commit -m "fix: clean up instinct_context_vectors on prune and reset (vec0 has no FK CASCADE)"
```

---

### Task 10: Integration test — full lifecycle

**Files:**
- Modify: `tests/test_integration.py` — add contextual instinct lifecycle test

- [ ] **Step 1: Write integration test**

```python
def test_contextual_instinct_lifecycle(storage, embeddings, compressor):
    """Full lifecycle: create semantic → instinct with notice/implication →
    contextual recall → context feedback → reflection shows per-context health."""
    # Create high-confidence semantic
    sem_id = str(uuid.uuid4())
    storage.add_semantic(
        id=sem_id, content="prefer concise output when coding",
        kind="preference", confidence=0.85,
        embedding=embeddings.embed(["prefer concise output when coding"])[0],
        source_episode_ids=[],
    )
    # Trigger instinct creation
    ep_id = str(uuid.uuid4())
    storage.add_episode(id=ep_id, session_id="test",
                        content="filler",
                        embedding=embeddings.embed(["filler"])[0])
    result = compressor.cluster_episodes()
    stats = compressor.commit(result["compress_id"],
                              [{"content": "filler", "kind": "fact", "action": "new"}])
    assert stats["instincts_created"] == 1

    # Verify instinct has notice/implication
    instincts = storage.get_all_instincts()
    inst = instincts[0]
    assert inst["notice"] is not None

    # Store context feedback
    from storage import _pack_embedding
    build_emb = embeddings.embed(["building code"])[0]
    storage.add_instinct_context_feedback(
        instinct_id=inst["id"], context_text="building",
        context_embedding=_pack_embedding(build_emb), followed=True,
    )
    storage.add_instinct_context_feedback(
        instinct_id=inst["id"], context_text="reflecting",
        context_embedding=_pack_embedding(build_emb), followed=False,
    )

    # Per-context health
    from reflection import Reflector
    reflector = Reflector(storage)
    health = reflector.instinct_context_health()
    assert len(health) == 1
    contexts = {c["context"]: c["follow_ratio"] for c in health[0]["contexts"]}
    assert contexts["building"] == 1.0
    assert contexts["reflecting"] == 0.0
```

- [ ] **Step 2: Run integration test**

Run: `.venv/bin/python -m pytest tests/test_integration.py -k "contextual_instinct" -v`
Expected: PASS (all components from Tasks 1-8 working together)

- [ ] **Step 3: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All pass, no regressions

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: contextual instinct lifecycle integration test"
```

---

### Task 11: Update CLAUDE.md and engram skill

**Files:**
- Modify: `CLAUDE.md` — update instinct documentation
- Modify: Engram skill — update instinct usage guidance

- [ ] **Step 1: Update CLAUDE.md**

Update the Architecture table to mention notice/implication. Update the MCP Tools table to note the `context` parameter on `instinct_feedback`. Add a brief note under Architecture about contextual instincts.

- [ ] **Step 2: Update engram skill**

Update the skill to explain the perceptual framing: instincts as attention directives, using context parameter on feedback, what notice/implication mean.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update instinct documentation for perceptual contextual model"
```
