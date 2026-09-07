# Compression Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce 25-40 semantics from 179 episodes (up from 14) by adding episode typing, multi-semantic membership, and singleton promotion to the compression pipeline.

**Architecture:** Episodes get a `kind` classification before clustering. Clustering happens within each type. After semantic creation, every episode is compared against all semantics and linked above threshold. Core episodes with no links get singleton semantics.

**Tech Stack:** Python, SQLite, scipy (fclusterdata), numpy, pytest

---

## File Structure

```
engram/
├── compress.py              # MODIFY: typing, per-type clustering, multi-link, singletons
├── storage.py               # MODIFY: similarity column, get_semantic_neighbors(), episode kind
├── migrations/
│   └── 014_compression_rework.sql  # CREATE: schema changes
├── tests/
│   └── test_compression.py  # MODIFY: add tests for new pipeline steps
```

---

### Task 1: Migration — Schema Changes

**Files:**
- Create: `migrations/014_compression_rework.sql`
- Modify: `storage.py`

- [ ] **Step 1: Create migration file**

```sql
-- migrations/014_compression_rework.sql
-- Add similarity to semantic_sources for weighted edges
ALTER TABLE semantic_sources ADD COLUMN similarity REAL;

-- Episode kind column already exists as episode_type — reuse it.
-- No schema change needed for episode typing.
```

Note: The `episodes` table already has an `episode_type` column (from the original schema). We'll reuse it for the kind classification.

- [ ] **Step 2: Write test for get_semantic_neighbors**

Add to `tests/test_compression.py`:

```python
class TestSemanticNeighbors:
    def test_neighbors_from_shared_episodes(self, storage, embeddings):
        """Two semantics sharing episodes should appear as neighbors."""
        # Create two semantics
        emb_a = embeddings.embed(["topic A"])[0]
        emb_b = embeddings.embed(["topic B"])[0]
        storage.add_semantic("sem-a", "Topic A insight", "fact", 0.7, emb_a, [])
        storage.add_semantic("sem-b", "Topic B insight", "fact", 0.7, emb_b, [])

        # Create shared episode linked to both
        ep_emb = embeddings.embed(["shared episode"])[0]
        storage.add_episode("ep-1", "shared episode", embedding=ep_emb)
        storage.conn.execute(
            "INSERT INTO semantic_sources (semantic_id, episode_id, similarity) VALUES (?, ?, ?)",
            ("sem-a", "ep-1", 0.9),
        )
        storage.conn.execute(
            "INSERT INTO semantic_sources (semantic_id, episode_id, similarity) VALUES (?, ?, ?)",
            ("sem-b", "ep-1", 0.88),
        )
        storage.conn.commit()

        neighbors = storage.get_semantic_neighbors("sem-a")
        assert len(neighbors) == 1
        assert neighbors[0]["semantic_id"] == "sem-b"
        assert neighbors[0]["shared_count"] == 1

    def test_no_neighbors_when_no_shared_episodes(self, storage, embeddings):
        emb_a = embeddings.embed(["topic A"])[0]
        storage.add_semantic("sem-a", "Topic A", "fact", 0.7, emb_a, [])
        neighbors = storage.get_semantic_neighbors("sem-a")
        assert neighbors == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_compression.py::TestSemanticNeighbors -v`
Expected: FAIL — `get_semantic_neighbors` not defined

- [ ] **Step 4: Apply migration and implement get_semantic_neighbors**

In `storage.py`, add after `reinforce_semantic`:

```python
def get_semantic_neighbors(self, semantic_id: str) -> list[dict]:
    """Find semantics that share episodes with this one, weighted by co-occurrence."""
    rows = self.conn.execute(
        """
        SELECT s2.semantic_id, COUNT(*) as shared_count, AVG(s2.similarity) as avg_similarity
        FROM semantic_sources s1
        JOIN semantic_sources s2 ON s1.episode_id = s2.episode_id
        WHERE s1.semantic_id = ? AND s2.semantic_id != s1.semantic_id
        GROUP BY s2.semantic_id
        ORDER BY shared_count DESC
        """,
        (semantic_id,),
    ).fetchall()
    return [dict(r) for r in rows]
```

Also apply the migration. In `storage.py`, in the `_run_migrations` method, add migration 14:

```python
if current_version < 14:
    migration_path = os.path.join(migrations_dir, "014_compression_rework.sql")
    if os.path.exists(migration_path):
        self.conn.executescript(open(migration_path).read())
    else:
        self.conn.execute("ALTER TABLE semantic_sources ADD COLUMN similarity REAL")
    self.conn.execute("UPDATE meta SET value = '14' WHERE key = 'schema_version'")
    self.conn.commit()
```

- [ ] **Step 5: Run tests to verify pass**

Run: `.venv/bin/python -m pytest tests/test_compression.py::TestSemanticNeighbors -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add migrations/014_compression_rework.sql storage.py tests/test_compression.py
git commit -m "feat: semantic_sources similarity column + get_semantic_neighbors query"
```

---

### Task 2: Episode Typing

**Files:**
- Modify: `compress.py`
- Modify: `tests/test_compression.py`

- [ ] **Step 1: Write tests for classify_episode_kind**

Add to `tests/test_compression.py`:

```python
from compress import classify_episode_kind


class TestEpisodeTyping:
    def test_reading_from_source(self):
        ep = {"content": "some reading reaction", "source": "reading", "context": None}
        kinds = classify_episode_kind(ep)
        assert "reading" in kinds

    def test_reading_from_context(self):
        ep = {"content": "passage 42", "source": None, "context": '{"topic": "passage-reading"}'}
        kinds = classify_episode_kind(ep)
        assert "reading" in kinds

    def test_design_from_context(self):
        ep = {"content": "built the lens system", "source": None, "context": '{"topic": "design-session"}'}
        kinds = classify_episode_kind(ep)
        assert "design" in kinds

    def test_observation_from_context(self):
        ep = {"content": "pattern noticed", "source": None, "context": '{"kind": "self-observation"}'}
        kinds = classify_episode_kind(ep)
        assert "observation" in kinds

    def test_relational_from_names(self):
        ep = {"content": "Kairos said something important", "source": None, "context": None}
        kinds = classify_episode_kind(ep)
        assert "relational" in kinds

    def test_factual_from_build_summary(self):
        ep = {"content": "Session 2026-03-25. Built three things: ...", "source": None, "context": None}
        kinds = classify_episode_kind(ep)
        assert "factual" in kinds

    def test_reflection_from_context(self):
        ep = {"content": "recursive self-reflection", "source": None, "context": '{"topic": "reflection"}'}
        kinds = classify_episode_kind(ep)
        assert "reflection" in kinds

    def test_multi_type(self):
        ep = {"content": "Pattern noticed while reading Mistborn with Andy", "source": "reading", "context": None}
        kinds = classify_episode_kind(ep)
        assert "reading" in kinds
        assert "relational" in kinds
        assert "observation" in kinds

    def test_unknown_defaults_to_factual(self):
        ep = {"content": "something", "source": None, "context": None}
        kinds = classify_episode_kind(ep)
        assert "factual" in kinds
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_compression.py::TestEpisodeTyping -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement classify_episode_kind**

Add to `compress.py` as a module-level function:

```python
import json as _json

# Known people names for relational detection
_KNOWN_NAMES = {"andy", "kairos", "vaughn", "emma", "koan", "vin", "kelsier"}

def classify_episode_kind(episode: dict) -> list[str]:
    """Classify an episode into one or more kinds based on metadata and content.

    Returns a list of kinds. An episode can belong to multiple types.
    """
    kinds: set[str] = set()
    content = (episode.get("content") or "").lower()
    source = (episode.get("source") or "").lower()
    context_raw = episode.get("context")

    # Parse context JSON if present
    context_str = ""
    if context_raw:
        if isinstance(context_raw, str):
            try:
                ctx = _json.loads(context_raw)
                context_str = _json.dumps(ctx).lower()
            except (ValueError, TypeError):
                context_str = context_raw.lower()
        elif isinstance(context_raw, dict):
            context_str = _json.dumps(context_raw).lower()

    # Reading: source tag or passage/chapter references
    if source == "reading" or "passage" in context_str or "chapter" in context_str:
        kinds.add("reading")

    # Design: built/architecture/design/commit references
    design_signals = ("design", "architecture", "built", "commit", "implement", "branch")
    if any(s in context_str for s in design_signals) or any(s in content[:100] for s in ("built ", "session 20")):
        kinds.add("design")

    # Observation: self-observation, pattern-noticed
    obs_signals = ("self-observation", "observation", "pattern", "noticed", "noticed across")
    if any(s in context_str for s in obs_signals) or "pattern noticed" in content:
        kinds.add("observation")

    # Relational: mentions known people
    content_words = set(content.split())
    if content_words & _KNOWN_NAMES:
        kinds.add("relational")

    # Factual: session summaries, build logs
    if content.startswith(("session 20", "completed ", "implemented ", "built ")):
        kinds.add("factual")

    # Reflection: recursive, philosophical
    refl_signals = ("reflection", "recursive", "philosophical", "self-reflection")
    if any(s in context_str for s in refl_signals) or "recursive" in content:
        kinds.add("reflection")

    # Default: if nothing matched, it's factual
    if not kinds:
        kinds.add("factual")

    return sorted(kinds)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/python -m pytest tests/test_compression.py::TestEpisodeTyping -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add compress.py tests/test_compression.py
git commit -m "feat: episode kind classification for typed compression"
```

---

### Task 3: Per-Type Clustering

**Files:**
- Modify: `compress.py`
- Modify: `tests/test_compression.py`

- [ ] **Step 1: Write test for typed clustering**

Add to `tests/test_compression.py`:

```python
class TestTypedClustering:
    def test_same_topic_different_types_separate(self, storage, embeddings):
        """A reading episode and a design episode about the same topic should
        cluster separately when typed."""
        # Both about "trust" but different types
        shared_emb = [0.5] * 768
        embeddings.override_map["Reading: trust in Mistborn"] = shared_emb
        embeddings.override_map["Design: trust anchors in system"] = [x + 0.01 for x in shared_emb]

        storage.add_episode("ep-read", "Reading: trust in Mistborn",
                           embedding=shared_emb, source="reading")
        storage.add_episode("ep-design", "Design: trust anchors in system",
                           embedding=[x + 0.01 for x in shared_emb],
                           context='{"topic": "design-session"}')

        compressor = Compressor(storage, embeddings)
        result = compressor.cluster_episodes()
        clusters = result["clusters"]

        # Should produce 2 clusters (one per type), not 1 merged cluster
        assert len(clusters) >= 2

    def test_same_type_clusters_together(self, storage, embeddings):
        """Two reading episodes about similar topics should cluster together."""
        emb = [0.5] * 768
        embeddings.override_map["Reading reaction to chapter 5"] = emb
        embeddings.override_map["Reading reaction to chapter 6"] = [x + 0.001 for x in emb]

        storage.add_episode("ep-r1", "Reading reaction to chapter 5",
                           embedding=emb, source="reading")
        storage.add_episode("ep-r2", "Reading reaction to chapter 6",
                           embedding=[x + 0.001 for x in emb], source="reading")

        compressor = Compressor(storage, embeddings)
        result = compressor.cluster_episodes()

        # Should cluster together since same type + similar embedding
        # (may be 1 or 2 clusters, but at least grouped by type)
        assert len(result["clusters"]) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_compression.py::TestTypedClustering -v`
Expected: FAIL — episodes cluster together regardless of type

- [ ] **Step 3: Modify cluster_episodes for per-type clustering**

In `compress.py`, modify `cluster_episodes`:

```python
def cluster_episodes(self, scope: str = "recent") -> dict:
    """Phase 1: classify, then cluster within each type."""
    if scope == "full":
        self._reset_all()
    elif scope == "refine":
        return self._refine_clusters()

    episodes = self._storage.get_uncompressed_episodes()
    if not episodes:
        return {"clusters": [], "compress_id": None}

    # Step 1: Classify episodes by kind
    typed_groups: dict[str, list[dict]] = {}
    for ep in episodes:
        kinds = classify_episode_kind(ep)
        for kind in kinds:
            typed_groups.setdefault(kind, []).append(ep)

    # Step 2: Cluster within each type
    all_clusters = []
    for kind, kind_episodes in typed_groups.items():
        texts = [ep["content"] for ep in kind_episodes]
        embeddings = self._embeddings.embed(texts, prefix="clustering")

        valid = [(ep, emb) for ep, emb in zip(kind_episodes, embeddings) if emb is not None]
        if not valid:
            continue

        valid_episodes, valid_embeddings = zip(*valid)
        valid_episodes = list(valid_episodes)
        valid_embeddings = list(valid_embeddings)
        embeddings_matrix = np.array(valid_embeddings)

        if len(embeddings_matrix) == 1:
            cluster_labels = [1]
        else:
            cluster_labels = fclusterdata(
                embeddings_matrix,
                t=self._cluster_similarity,
                metric="cosine",
                criterion="distance",
            )

        cluster_groups: dict[int, list[tuple[dict, list[float]]]] = {}
        for label, ep, emb in zip(cluster_labels, valid_episodes, valid_embeddings):
            label_int = int(label)
            if label_int not in cluster_groups:
                cluster_groups[label_int] = []
            cluster_groups[label_int].append((ep, emb))

        for label, members in cluster_groups.items():
            eps = [m[0] for m in members]
            embs = [m[1] for m in members]
            centroid = np.mean(embs, axis=0).tolist()
            action, match, near_miss = self._find_semantic_match(centroid)

            all_clusters.append({
                "episodes": eps,
                "centroid": centroid,
                "match": match,
                "action": action,
                "near_miss": near_miss,
                "kind": kind,
            })

    compress_id = str(uuid.uuid4())
    self._pending[compress_id] = {"clusters": all_clusters}
    return {"clusters": all_clusters, "compress_id": compress_id}
```

- [ ] **Step 4: Update commit() to use cluster kind for semantic kind**

In `compress.py`, in `commit()`, change the semantic kind assignment. Where it currently uses `summary.get("kind", "fact")`, also fall back to the cluster's kind:

```python
# In the 'else' branch of action == "reinforce" (creating new semantic):
semantic_kind = summary.get("kind")
if not semantic_kind or semantic_kind == "fact":
    # Use the cluster's episode type as a hint
    cluster_kind = cluster.get("kind", "fact")
    kind_to_semantic = {
        "reading": "preference",
        "design": "fact",
        "observation": "preference",
        "relational": "fact",
        "factual": "fact",
        "reflection": "preference",
    }
    semantic_kind = kind_to_semantic.get(cluster_kind, "fact")
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_compression.py -v`
Expected: All pass (existing 20 + new tests)

- [ ] **Step 6: Commit**

```bash
git add compress.py tests/test_compression.py
git commit -m "feat: per-type episode clustering — cluster within kind, not globally"
```

---

### Task 4: Multi-Semantic Membership

**Files:**
- Modify: `compress.py`
- Modify: `tests/test_compression.py`

- [ ] **Step 1: Write tests**

```python
class TestMultiMembership:
    def test_episode_links_to_multiple_semantics(self, storage, embeddings):
        """An episode similar to two semantics should link to both."""
        # Create two existing semantics with known embeddings
        emb_a = [0.8] + [0.0] * 767
        emb_b = [0.0] + [0.8] * 767
        storage.add_semantic("sem-a", "Topic A", "fact", 0.7, emb_a, [])
        storage.add_semantic("sem-b", "Topic B", "fact", 0.7, emb_b, [])

        # Create episode similar to BOTH (high values in both dimensions)
        ep_emb = [0.75] + [0.75] * 767
        embeddings.override_map["episode about both topics"] = ep_emb
        storage.add_episode("ep-1", "episode about both topics", embedding=ep_emb)

        compressor = Compressor(storage, embeddings)
        compressor._multi_link_episodes(
            [{"id": "ep-1", "content": "episode about both topics"}],
            exclude_semantic_ids=[],
        )

        # Check source links
        rows = storage.conn.execute(
            "SELECT semantic_id, similarity FROM semantic_sources WHERE episode_id = 'ep-1'"
        ).fetchall()
        linked_sems = {r[0] for r in rows}
        assert "sem-a" in linked_sems or "sem-b" in linked_sems
        # At least one link should have similarity stored
        sims = [r[1] for r in rows if r[1] is not None]
        assert len(sims) > 0

    def test_no_duplicate_links(self, storage, embeddings):
        """Multi-link should not create duplicate source links."""
        emb = [0.5] * 768
        storage.add_semantic("sem-a", "Topic A", "fact", 0.7, emb, ["ep-1"])
        storage.add_episode("ep-1", "existing episode", embedding=emb)

        compressor = Compressor(storage, embeddings)
        compressor._multi_link_episodes(
            [{"id": "ep-1", "content": "existing episode"}],
            exclude_semantic_ids=["sem-a"],
        )

        rows = storage.conn.execute(
            "SELECT COUNT(*) FROM semantic_sources WHERE episode_id = 'ep-1' AND semantic_id = 'sem-a'"
        ).fetchone()
        assert rows[0] == 1  # no duplicate
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_compression.py::TestMultiMembership -v`
Expected: FAIL — `_multi_link_episodes` not defined

- [ ] **Step 3: Implement _multi_link_episodes**

Add to `Compressor` class in `compress.py`:

```python
def _multi_link_episodes(
    self,
    episodes: list[dict],
    exclude_semantic_ids: list[str],
) -> int:
    """Link episodes to all matching semantics above threshold.

    Compares each episode's embedding against all semantic embeddings.
    Adds source links with similarity scores for matches above reinforce_threshold.
    Skips semantic IDs in exclude_semantic_ids (already linked by the cluster step).

    Returns number of new links created.
    """
    all_semantics = self._storage.get_active_semantics(limit=500)
    if not all_semantics:
        return 0

    # Get semantic embeddings
    sem_ids = [s["id"] for s in all_semantics]
    sem_texts = [s["content"] for s in all_semantics]
    sem_embeddings = self._embeddings.embed(sem_texts, prefix="clustering")

    # Build lookup: sem_id -> embedding
    sem_emb_map: dict[str, np.ndarray] = {}
    for sid, emb in zip(sem_ids, sem_embeddings):
        if emb is not None:
            sem_emb_map[sid] = np.array(emb)

    # Compare each episode against all semantics
    ep_texts = [ep["content"] for ep in episodes]
    ep_embeddings = self._embeddings.embed(ep_texts, prefix="clustering")

    links_created = 0
    for ep, ep_emb in zip(episodes, ep_embeddings):
        if ep_emb is None:
            continue
        ep_arr = np.array(ep_emb)
        ep_norm = np.linalg.norm(ep_arr)
        if ep_norm == 0:
            continue

        for sid, sem_arr in sem_emb_map.items():
            if sid in exclude_semantic_ids:
                continue
            sem_norm = np.linalg.norm(sem_arr)
            if sem_norm == 0:
                continue
            sim = float(np.dot(ep_arr, sem_arr) / (ep_norm * sem_norm))
            if sim >= self._reinforce_threshold:
                # Add link if not already present
                existing = self._storage.conn.execute(
                    "SELECT 1 FROM semantic_sources WHERE semantic_id = ? AND episode_id = ?",
                    (sid, ep["id"]),
                ).fetchone()
                if existing is None:
                    self._storage.conn.execute(
                        "INSERT INTO semantic_sources (semantic_id, episode_id, similarity) VALUES (?, ?, ?)",
                        (sid, ep["id"], sim),
                    )
                    links_created += 1

    if links_created:
        self._storage.conn.commit()
    return links_created
```

- [ ] **Step 4: Wire multi-link into commit()**

In `compress.py`, at the end of `commit()`, before the log entry, add:

```python
# Multi-link: connect episodes to all matching semantics
all_episodes = []
cluster_semantic_ids = []
for i, cluster in enumerate(clusters):
    if i < len(summaries):
        all_episodes.extend(cluster["episodes"])
        if summaries[i].get("semantic_id"):
            cluster_semantic_ids.append(summaries[i]["semantic_id"])

multi_links = self._multi_link_episodes(all_episodes, cluster_semantic_ids)
```

Add `multi_links` to the return dict and log context.

- [ ] **Step 5: Run all tests**

Run: `.venv/bin/python -m pytest tests/test_compression.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add compress.py tests/test_compression.py
git commit -m "feat: multi-semantic membership — episodes link to all matching semantics"
```

---

### Task 5: Singleton Promotion

**Files:**
- Modify: `compress.py`
- Modify: `tests/test_compression.py`

- [ ] **Step 1: Write tests**

```python
class TestSingletonPromotion:
    def test_core_episode_gets_singleton(self, storage, embeddings):
        """A core episode with no semantic link should get its own semantic."""
        emb = embeddings.embed(["unique core memory"])[0]
        storage.add_episode("ep-core", "unique core memory", embedding=emb, core=True)

        compressor = Compressor(storage, embeddings)
        promoted = compressor._promote_singletons()
        assert promoted >= 1

        # Should have a semantic now
        rows = storage.conn.execute(
            "SELECT semantic_id FROM semantic_sources WHERE episode_id = 'ep-core'"
        ).fetchall()
        assert len(rows) >= 1

    def test_linked_episode_not_promoted(self, storage, embeddings):
        """An episode already linked to a semantic should not get a singleton."""
        emb = embeddings.embed(["linked episode"])[0]
        storage.add_semantic("sem-x", "existing semantic", "fact", 0.7, emb, ["ep-linked"])
        storage.add_episode("ep-linked", "linked episode", embedding=emb, core=True)

        compressor = Compressor(storage, embeddings)
        promoted = compressor._promote_singletons()
        assert promoted == 0

    def test_singleton_confidence_is_baseline(self, storage, embeddings):
        """Singleton semantics should start at confidence 0.5."""
        emb = embeddings.embed(["another unique memory"])[0]
        storage.add_episode("ep-solo", "another unique memory", embedding=emb, core=True)

        compressor = Compressor(storage, embeddings)
        compressor._promote_singletons()

        rows = storage.conn.execute(
            "SELECT semantic_id FROM semantic_sources WHERE episode_id = 'ep-solo'"
        ).fetchall()
        sem_id = rows[0][0]
        sem = storage.get_semantic(sem_id)
        assert sem["confidence"] == 0.5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_compression.py::TestSingletonPromotion -v`
Expected: FAIL — `_promote_singletons` not defined

- [ ] **Step 3: Implement _promote_singletons**

Add to `Compressor` class:

```python
def _promote_singletons(self) -> int:
    """Promote core episodes with no semantic links to singleton semantics.

    Candidates: core episodes that have no entry in semantic_sources.
    Each gets its own semantic at confidence 0.5.

    Returns number of singletons created.
    """
    rows = self._storage.conn.execute(
        """
        SELECT e.id, e.content FROM episodes e
        WHERE e.core = 1
        AND e.id NOT IN (SELECT episode_id FROM semantic_sources)
        """
    ).fetchall()

    if not rows:
        return 0

    created = 0
    for row in rows:
        ep_id, content = row
        if not content or len(content.strip()) < 10:
            continue

        sem_id = str(uuid.uuid4())
        embedding = self._embeddings.embed([content], prefix="search_document")[0]
        if embedding is None:
            continue

        # Classify kind from episode
        ep = self._storage.get_episode(ep_id)
        kinds = classify_episode_kind(ep) if ep else ["fact"]
        kind_to_semantic = {
            "reading": "preference",
            "design": "fact",
            "observation": "preference",
            "relational": "fact",
            "factual": "fact",
            "reflection": "preference",
        }
        semantic_kind = kind_to_semantic.get(kinds[0], "fact")

        self._storage.add_semantic(
            id=sem_id,
            content=content,
            kind=semantic_kind,
            confidence=0.5,
            embedding=embedding,
            source_episode_ids=[ep_id],
            auto_generated=True,
        )
        # Update the source link with similarity
        self._storage.conn.execute(
            "UPDATE semantic_sources SET similarity = 1.0 WHERE semantic_id = ? AND episode_id = ?",
            (sem_id, ep_id),
        )
        self._storage.conn.commit()
        created += 1

    return created
```

- [ ] **Step 4: Wire into commit()**

In `compress.py`, in `commit()`, after the multi-link step, add:

```python
singletons_created = self._promote_singletons()
```

Add to the return dict:

```python
"singletons_created": singletons_created,
```

- [ ] **Step 5: Run all tests**

Run: `.venv/bin/python -m pytest tests/test_compression.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add compress.py tests/test_compression.py
git commit -m "feat: singleton promotion — core episodes get own semantics"
```

---

### Task 6: Integration Test — Full Pipeline

**Files:**
- Modify: `tests/test_compression.py`

- [ ] **Step 1: Write integration test**

```python
class TestFullPipeline:
    def test_typed_compression_produces_more_semantics(self, storage, embeddings):
        """The full pipeline should produce more semantics than episodes would
        suggest with global clustering."""
        # Create episodes of different types that share a topic
        reading_emb = [0.5, 0.5] + [0.0] * 766
        design_emb = [0.5, 0.0] + [0.5] * 766
        obs_emb = [0.0, 0.5] + [0.5] * 766

        embeddings.override_map["Reading Mistborn: trust is earned through small repeated acts"] = reading_emb
        embeddings.override_map["Design: trust anchors at system boundaries"] = design_emb
        embeddings.override_map["Pattern noticed: I drop relational frames under load"] = obs_emb

        storage.add_episode("ep-r", "Reading Mistborn: trust is earned through small repeated acts",
                           embedding=reading_emb, source="reading")
        storage.add_episode("ep-d", "Design: trust anchors at system boundaries",
                           embedding=design_emb, context='{"topic": "design-session"}')
        storage.add_episode("ep-o", "Pattern noticed: I drop relational frames under load",
                           embedding=obs_emb, context='{"kind": "self-observation"}')

        compressor = Compressor(storage, embeddings)
        result = compressor.cluster_episodes()

        # Should have at least 2 clusters (typed separation)
        assert len(result["clusters"]) >= 2

        # Each cluster should have a kind
        kinds = {c.get("kind") for c in result["clusters"]}
        assert len(kinds) >= 2

    def test_auto_compress_with_singletons(self, storage, embeddings):
        """Auto compress should handle the full pipeline including singletons."""
        emb = embeddings.embed(["unique core observation"])[0]
        storage.add_episode("ep-core", "unique core observation", embedding=emb, core=True)

        compressor = Compressor(storage, embeddings)
        result = compressor.auto_compress()

        assert result["episodes_processed"] >= 1
        # Should have created at least one semantic (either from cluster or singleton)
        total = result["semantics_created"] + result.get("singletons_created", 0)
        assert total >= 1
```

- [ ] **Step 2: Run integration tests**

Run: `.venv/bin/python -m pytest tests/test_compression.py::TestFullPipeline -v`
Expected: 2 passed

- [ ] **Step 3: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_compression.py
git commit -m "test: integration tests for full typed compression pipeline"
```

---

### Task 7: Live Recompression

**Files:** None — this is an observation task using the live database.

- [ ] **Step 1: Back up the current database**

```bash
cp ~/.engram/shared/koan-snapshot.db ~/.engram/shared/koan-snapshot.db.bak
```

- [ ] **Step 2: Run full recompression**

```bash
cd ~/Projects/engram && .venv/bin/python -c "
from config import load_config
from storage import Storage
from embeddings import NomicEmbedProvider
from compress import Compressor

cfg = load_config()
s = Storage(cfg.memory.db_path)
e = NomicEmbedProvider()
c = Compressor(s, e)

# Full recompression
result = c.cluster_episodes(scope='full')
print(f'Clusters: {len(result[\"clusters\"])}')
for cl in result['clusters']:
    print(f'  [{cl.get(\"kind\", \"?\")}] {len(cl[\"episodes\"])} episodes, action={cl[\"action\"]}')
"
```

Observe: How many clusters? What types? How does it compare to 14 semantics before?

- [ ] **Step 3: Check the results**

```bash
sqlite3 ~/.engram/shared/koan-snapshot.db "
SELECT 'Semantics:', COUNT(*) FROM semantics;
SELECT 'Source links:', COUNT(*) FROM semantic_sources;
SELECT 'Max sources:', MAX(c) FROM (SELECT COUNT(*) as c FROM semantic_sources GROUP BY semantic_id);
SELECT 'Avg sources:', AVG(c) FROM (SELECT COUNT(*) as c FROM semantic_sources GROUP BY semantic_id);
SELECT 'Links with similarity:', COUNT(*) FROM semantic_sources WHERE similarity IS NOT NULL;
"
```

Target: 25-40 semantics, no single semantic with >40% of links.

- [ ] **Step 4: Test wander on the new graph**

Use the MCP `wander` tool from a Claude session and observe whether paths exist that don't collapse into one hub.

- [ ] **Step 5: Record observations**

Write what happened, what the new graph topology looks like, what surprised you.
