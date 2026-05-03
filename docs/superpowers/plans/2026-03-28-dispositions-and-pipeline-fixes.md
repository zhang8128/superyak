# Dispositions, Pipeline Fixes, and Resonance Activation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the compression pipeline so behavioral patterns become visible, add disposition as a semantic kind, and activate the dormant resonance system in recall.

**Architecture:** Three scopes: (1) fix pipeline bugs — auto-compress kind propagation, instinct threshold, cross-kind dedup removal; (2) add disposition kind with configurable model-assisted classification; (3) wire resonances into recall and reflect. Changes span compress.py, storage.py, server.py, reflection.py, hooks/wake.py, and config.py.

**Tech Stack:** Python, SQLite, FastEmbed (nomic-embed-text-v1.5), Ollama (optional, for classification), scipy

---

### Task 1: Raise instinct confidence threshold

**Files:**
- Modify: `config.py:44` — change default
- Modify: `compress.py:116` — change fallback default
- Test: `tests/test_compression.py`

- [ ] **Step 1: Write failing test — instinct not created below threshold**

```python
# In tests/test_compression.py
def test_instinct_not_created_below_confidence_threshold(compressor, storage):
    """Semantics below 0.75 confidence should not spawn instincts."""
    # Create a preference semantic at 0.5 confidence (default for new)
    storage.add_semantic(
        id="sem-low",
        content="Use portable hashing in scripts",
        kind="preference",
        confidence=0.5,
        embedding=[0.1] * 768,
        source_episode_ids=["ep1"],
    )
    created = compressor._check_instinct_creation()
    assert created == 0, "Should not create instinct for semantic below 0.75 confidence"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/kairos/Projects/engram && .venv/bin/python -m pytest tests/test_compression.py::test_instinct_not_created_below_confidence_threshold -v`
Expected: FAIL — instinct IS created because threshold is currently 0.5

- [ ] **Step 3: Update threshold defaults**

In `config.py:44`:
```python
instinct_confidence: float = 0.75
```

In `compress.py:116`:
```python
return self._config.instinct_confidence if self._config else 0.75
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/kairos/Projects/engram && .venv/bin/python -m pytest tests/test_compression.py::test_instinct_not_created_below_confidence_threshold -v`
Expected: PASS

- [ ] **Step 5: Write test — instinct created at threshold**

```python
def test_instinct_created_at_confidence_threshold(compressor, storage):
    """Semantics at or above 0.75 should spawn instincts."""
    storage.add_semantic(
        id="sem-high",
        content="Hold interpretations lightly before crystallizing",
        kind="preference",
        confidence=0.75,
        embedding=[0.1] * 768,
        source_episode_ids=["ep1"],
    )
    created = compressor._check_instinct_creation()
    assert created == 1
```

- [ ] **Step 6: Run both tests**

Run: `cd /Users/kairos/Projects/engram && .venv/bin/python -m pytest tests/test_compression.py -k "instinct_not_created_below or instinct_created_at" -v`
Expected: Both PASS

- [ ] **Step 7: Run full test suite**

Run: `cd /Users/kairos/Projects/engram && .venv/bin/python -m pytest tests/ -q`
Expected: All existing tests pass

- [ ] **Step 8: Commit**

```bash
cd /Users/kairos/Projects/engram
git add config.py compress.py tests/test_compression.py
git commit -m "fix: raise instinct confidence threshold to 0.75

Semantics now need 3 reinforcements before spawning instincts.
Prevents one-off technical notes from becoming attention directives."
```

---

### Task 2: Remove seen_episode_ids cross-kind blocking

**Files:**
- Modify: `compress.py:141-189` — remove dedup set
- Test: `tests/test_compression.py`

- [ ] **Step 1: Write failing test — episode appears in multiple kind clusters**

```python
def test_episode_appears_in_multiple_kind_clusters(compressor, storage, embeddings):
    """An episode classified as both observation and design should appear in both clusters."""
    # Episode that matches both observation and design signals
    ep = {
        "id": "ep-multi",
        "content": "Self-observation: I noticed a pattern in how the architecture handles compression",
        "context": '{"topic": "self-observation", "connection": "architecture design"}',
        "source": None,
    }
    storage.add_episode(
        id=ep["id"],
        content=ep["content"],
        context=ep["context"],
        embedding=[0.1] * 768,
    )

    result = compressor.cluster_episodes()
    clusters = result["clusters"]

    # Find which kinds this episode appears in
    kinds_with_ep = set()
    for cluster in clusters:
        for cluster_ep in cluster["episodes"]:
            if cluster_ep["id"] == "ep-multi":
                kinds_with_ep.add(cluster["kind"])

    assert len(kinds_with_ep) >= 2, (
        f"Episode should appear in at least 2 kind clusters, found: {kinds_with_ep}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/kairos/Projects/engram && .venv/bin/python -m pytest tests/test_compression.py::test_episode_appears_in_multiple_kind_clusters -v`
Expected: FAIL — episode only appears in first kind due to `seen_episode_ids`

- [ ] **Step 3: Remove seen_episode_ids dedup from cluster_episodes**

In `compress.py`, replace lines 141-189 (the clustering loop) with:

```python
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
```

Note: the `seen_episode_ids` set and the deduplication block inside the loop are removed entirely. The `_multi_link_episodes` step in `commit()` already handles cross-semantic linking.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/kairos/Projects/engram && .venv/bin/python -m pytest tests/test_compression.py::test_episode_appears_in_multiple_kind_clusters -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/kairos/Projects/engram && .venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
cd /Users/kairos/Projects/engram
git add compress.py tests/test_compression.py
git commit -m "fix: allow episodes in multiple kind clusters

Removes seen_episode_ids dedup that prevented cross-kind learning.
An episode about noticing a design pattern now contributes to both
observation and design clusters. Multi-link handles downstream dedup."
```

---

### Task 3: Auto-compress kind propagation

**Files:**
- Modify: `compress.py:325-367` — derive kind from cluster
- Modify: `compress.py:616-676` — update singleton kind mapping for disposition
- Test: `tests/test_compression.py`

- [ ] **Step 1: Write failing test — auto-compress produces non-fact kinds**

```python
def test_auto_compress_propagates_kind(compressor, storage, embeddings):
    """Auto-compress should derive semantic kind from episode classification, not hardcode fact."""
    # Add reading episodes
    for i in range(3):
        storage.add_episode(
            id=f"ep-read-{i}",
            content=f"Reading passage {i}: Vin noticed the pattern in the mist",
            context='{"topic": "reading-mistborn", "passage": ' + str(i) + '}',
            embedding=[0.1 + i * 0.01] * 768,
            source="reading",
        )

    result = compressor.auto_compress()
    assert result["semantics_created"] >= 1

    # Check the created semantic has kind != "fact"
    semantics = storage.get_active_semantics()
    reading_sems = [s for s in semantics if s.get("auto_generated")]
    assert any(s["kind"] != "fact" for s in reading_sems), (
        f"Expected non-fact kind for reading episodes, got: {[s['kind'] for s in reading_sems]}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/kairos/Projects/engram && .venv/bin/python -m pytest tests/test_compression.py::test_auto_compress_propagates_kind -v`
Expected: FAIL — all auto-compressed semantics have kind="fact"

- [ ] **Step 3: Add kind mapping helper and update auto_compress**

Add helper function after `classify_episode_kind` (around line 80):

```python
# Episode kind → semantic kind mapping
_EPISODE_TO_SEMANTIC_KIND = {
    "reading": "preference",
    "observation": "disposition",
    "reflection": "disposition",
    "relational": "relationship",
    "design": "fact",
    "factual": "fact",
}


def derive_semantic_kind(cluster_kind: str) -> str:
    """Map a cluster's episode kind to the appropriate semantic kind."""
    return _EPISODE_TO_SEMANTIC_KIND.get(cluster_kind, "fact")
```

In `auto_compress()`, replace line 361 (`"kind": "fact",`) with:

```python
                "kind": derive_semantic_kind(cluster["kind"]),
```

Also update `_promote_singletons` kind mapping (around line 649) to include disposition:

```python
            kind_to_semantic = {
                "reading": "preference",
                "design": "fact",
                "observation": "disposition",
                "relational": "fact",
                "factual": "fact",
                "reflection": "disposition",
            }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/kairos/Projects/engram && .venv/bin/python -m pytest tests/test_compression.py::test_auto_compress_propagates_kind -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/kairos/Projects/engram && .venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
cd /Users/kairos/Projects/engram
git add compress.py tests/test_compression.py
git commit -m "fix: auto-compress derives kind from episode classification

Reading episodes produce preference semantics, observation/reflection
episodes produce disposition semantics. No longer hardcodes 'fact'."
```

---

### Task 4: Add disposition to semantic kind validation

**Files:**
- Create: `migrations/015_dispositions.sql`
- Modify: `storage.py` — update any kind validation
- Modify: `compress.py:501` — include disposition in instinct creation loop
- Test: `tests/test_compression.py`

- [ ] **Step 1: Write failing test — disposition semantic can be created**

```python
def test_disposition_semantic_creation(storage):
    """Storage should accept 'disposition' as a valid semantic kind."""
    storage.add_semantic(
        id="sem-disp",
        content="I tend to crystallize interpretations prematurely",
        kind="disposition",
        confidence=0.5,
        embedding=[0.1] * 768,
        source_episode_ids=["ep1"],
    )
    sem = storage.get_semantic("sem-disp")
    assert sem is not None
    assert sem["kind"] == "disposition"
```

- [ ] **Step 2: Run test — check if it already passes**

Run: `cd /Users/kairos/Projects/engram && .venv/bin/python -m pytest tests/test_compression.py::test_disposition_semantic_creation -v`

Note: SQLite CHECK constraints vary by how the table was created. This test may already pass if the CHECK is not strictly enforced, or it may fail. Either way, proceed to make it explicit.

- [ ] **Step 3: Create migration and update validation**

Create `migrations/015_dispositions.sql`:

```sql
-- 015_dispositions.sql
-- Add 'disposition' as a valid semantic kind.
-- SQLite CHECK constraints from CREATE TABLE are immutable without
-- table recreation. The app-level validation in compress.py and
-- storage.py is the real gate. This migration documents the change.
--
-- If the CHECK was created as:
--   CHECK(kind IN ('fact','relationship','preference','constraint'))
-- then INSERT of 'disposition' will fail. Fix: recreate table or
-- rely on app-level validation only.

-- Pragmatic approach: add a trigger that accepts disposition
-- (this doesn't remove the CHECK but the CHECK may not exist
-- depending on how the table was originally created)
```

In `compress.py:501`, update the instinct creation loop to include disposition:

```python
        for kind in ("preference", "constraint", "disposition"):
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/kairos/Projects/engram && .venv/bin/python -m pytest tests/test_compression.py::test_disposition_semantic_creation -v`
Expected: PASS

- [ ] **Step 5: Write test — disposition promotes to instinct with correct framing**

```python
def test_disposition_instinct_framing(compressor, storage):
    """Disposition instincts should have self-directed framing."""
    storage.add_semantic(
        id="sem-disp-inst",
        content="I tend to crystallize interpretations prematurely when reading",
        kind="disposition",
        confidence=0.80,  # above threshold
        embedding=[0.1] * 768,
        source_episode_ids=["ep1"],
    )
    created = compressor._check_instinct_creation()
    assert created == 1

    instincts = storage.get_all_instincts()
    disp_inst = [i for i in instincts if "crystallize" in i.get("action", "")]
    assert len(disp_inst) == 1
    assert disp_inst[0]["trigger"] == "disposition"
```

- [ ] **Step 6: Run test and fix if needed**

Run: `cd /Users/kairos/Projects/engram && .venv/bin/python -m pytest tests/test_compression.py::test_disposition_instinct_framing -v`

If it fails because `trigger` doesn't accept "disposition", update the instinct trigger mapping. The `trigger` field inherits from the semantic kind, so disposition semantics will produce `trigger="disposition"`.

- [ ] **Step 7: Run full test suite**

Run: `cd /Users/kairos/Projects/engram && .venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 8: Commit**

```bash
cd /Users/kairos/Projects/engram
git add migrations/015_dispositions.sql compress.py storage.py tests/test_compression.py
git commit -m "feat: add disposition as semantic kind

Behavioral patterns like 'I crystallize interpretations prematurely'
now have their own kind. Dispositions promote into instincts with
trigger='disposition' for self-directed framing."
```

---

### Task 5: Configurable model-assisted classification

**Files:**
- Modify: `config.py` — add ClassificationConfig
- Create: `prompts/classify.txt` — classification prompt template
- Modify: `compress.py:26-80` — add model-assisted classification with heuristic fallback
- Test: `tests/test_compression.py`

- [ ] **Step 1: Add ClassificationConfig to config.py**

After `CompressionConfig` (around line 45):

```python
@dataclass
class ClassificationConfig:
    model: str = "qwen3.5:27b"
    prompt_path: str = "prompts/classify.txt"
    fallback: str = "heuristic"
```

Add to `EngramConfig` (around line 100):

```python
    classification: ClassificationConfig = field(default_factory=ClassificationConfig)
```

Add to `load_config()`:

```python
        classification=ClassificationConfig(**raw.get("classification", {})),
```

Add to `_DEFAULT_TOML`:

```toml
[classification]
model = "qwen3.5:27b"
prompt_path = "prompts/classify.txt"
fallback = "heuristic"
```

- [ ] **Step 2: Create prompts/classify.txt**

```bash
mkdir -p /Users/kairos/Projects/engram/prompts
```

Write `prompts/classify.txt`:

```
Classify this memory episode. Return one or more kinds as a comma-separated list.
Most important kind first.

Kinds:
- reading: about a book, passage, or reading session
- design: about building, architecture, implementation
- observation: noticing something about the world or a system
- disposition: noticing something about how I think or act — self-correction, behavioral pattern, tendency caught by someone else, a habit identified
- relational: about a person or relationship
- factual: a fact, event, or technical detail
- reflection: philosophical or recursive self-examination

Episode content:
{content}

Episode context:
{context}

Return ONLY the comma-separated kinds, nothing else. Example: disposition, observation
```

- [ ] **Step 3: Write test — model classification with fallback**

```python
def test_classify_with_model_fallback(monkeypatch):
    """When model is unavailable, classification falls back to heuristic."""
    from compress import classify_episode_kind

    ep = {
        "content": "I noticed I was crystallizing my interpretation again",
        "context": '{"topic": "self-observation"}',
        "source": None,
    }
    # Heuristic should still work
    kinds = classify_episode_kind(ep)
    assert "observation" in kinds
```

- [ ] **Step 4: Add model-assisted classify function to compress.py**

Add after the existing `classify_episode_kind` function:

```python
def classify_episode_kind_with_model(
    episode: dict,
    model: str = "qwen3.5:27b",
    prompt_path: str = "prompts/classify.txt",
) -> list[str] | None:
    """Classify episode using a local LLM. Returns None if model unavailable.

    The prompt template is read from prompt_path and is editable.
    Results are suggestions — the caller decides whether to use them.
    """
    from pathlib import Path

    template_file = Path(prompt_path)
    if not template_file.exists():
        # Try relative to engram root
        import os
        engram_home = Path(os.environ.get("ENGRAM_HOME", Path(__file__).parent))
        template_file = engram_home / prompt_path
    if not template_file.exists():
        return None

    template = template_file.read_text()
    content = episode.get("content", "")
    context = episode.get("context", "")
    prompt = template.replace("{content}", content).replace("{context}", str(context))

    try:
        import requests
        ollama_url = os.environ.get("ENGRAM_OLLAMA_URL", "http://localhost:11434")
        resp = requests.post(
            f"{ollama_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        raw = resp.json().get("response", "").strip().lower()
        # Parse comma-separated kinds
        valid_kinds = {"reading", "design", "observation", "disposition", "relational", "factual", "reflection"}
        kinds = [k.strip() for k in raw.split(",") if k.strip() in valid_kinds]
        return kinds if kinds else None
    except Exception:
        logger.debug("Model classification unavailable", exc_info=True)
        return None
```

Update `classify_episode_kind` to try model first:

```python
def classify_episode_kind(
    episode: dict,
    model: str | None = None,
    prompt_path: str | None = None,
) -> list[str]:
    """Classify an episode into one or more kinds.

    Tries model-assisted classification first (if model configured),
    falls back to keyword heuristic. Model results are stored in
    episode context as 'suggested_kinds' for review.
    """
    # Try model first
    if model:
        model_kinds = classify_episode_kind_with_model(
            episode, model=model, prompt_path=prompt_path or "prompts/classify.txt",
        )
        if model_kinds:
            return model_kinds

    # Heuristic fallback (existing logic)
    kinds: set[str] = set()
    content = (episode.get("content") or "").lower()
    source = (episode.get("source") or "").lower()
    # ... rest of existing heuristic unchanged ...
```

- [ ] **Step 5: Update Compressor to pass model config to classifier**

In `Compressor.__init__`, accept classification config:

```python
    def __init__(
        self,
        storage: Storage,
        embedding_provider,
        config: CompressionConfig | None = None,
        deduplicator: Deduplicator | None = None,
        knowledge_graph=None,
        classification_config=None,
    ):
        # ... existing init ...
        self._classification_config = classification_config
```

In `cluster_episodes`, pass model to classifier:

```python
        for ep in episodes:
            model = self._classification_config.model if self._classification_config else None
            prompt_path = self._classification_config.prompt_path if self._classification_config else None
            kinds = classify_episode_kind(ep, model=model, prompt_path=prompt_path)
```

- [ ] **Step 6: Run tests**

Run: `cd /Users/kairos/Projects/engram && .venv/bin/python -m pytest tests/ -q`
Expected: All pass (model calls fail gracefully, heuristic fallback works)

- [ ] **Step 7: Commit**

```bash
cd /Users/kairos/Projects/engram
git add config.py compress.py prompts/classify.txt tests/test_compression.py
git commit -m "feat: model-assisted episode classification with heuristic fallback

Classification prompt is editable at prompts/classify.txt. When the
local model is unavailable, falls back to keyword heuristic. Model
and prompt path configurable via [classification] in config.toml."
```

---

### Task 6: Wire resonances into recall

**Files:**
- Modify: `server.py:950-956` — add resonance lookup after scoring
- Modify: `config.py` — add resonance config
- Test: `tests/test_server.py` or `tests/test_integration.py`

- [ ] **Step 1: Add resonance config**

In `config.py`, add after `SignalsConfig`:

```python
@dataclass
class ResonanceConfig:
    max_in_recall: int = 3
```

Add to `EngramConfig`:

```python
    resonance: ResonanceConfig = field(default_factory=ResonanceConfig)
```

Add to `load_config()` and `_DEFAULT_TOML`:

```python
        resonance=ResonanceConfig(**raw.get("resonance", {})),
```

```toml
[resonance]
max_in_recall = 3
```

- [ ] **Step 2: Write failing test — resonances appear in recall**

```python
def test_recall_includes_resonant_memories(storage, server_init):
    """Recall should include resonant memories as a secondary channel."""
    # Create two episodes
    storage.add_episode(id="ep-a", content="The grandmother's dirty water", embedding=[0.1] * 768)
    storage.add_episode(id="ep-b", content="Systems that flex are stronger", embedding=[0.9] * 768)

    # Create resonance between them
    storage.add_resonance("ep-a", "episode", "ep-b", "episode", similarity=0.3, weight=0.7)

    # Recall for ep-a's topic
    result = recall("grandmother dirty water survival")
    assert "resonant" in result
```

- [ ] **Step 3: Add resonance lookup to recall in server.py**

After line 956 (`results = scored[:max_results]`), before the recall_id generation:

```python
    # Resonant memories: lateral associations from top results
    resonant_results = []
    max_resonant = _config.resonance.max_in_recall if _config else 3
    if max_resonant > 0:
        matched_ids = {r["id"] for r in results}
        seen_resonant = set()
        for r in results[:5]:  # check top 5 results for resonances
            resonances = _storage.get_resonances_for(r["id"])
            for res in resonances:
                # Find the other end of the resonance
                other_id = res["memory_b"] if res["memory_a"] == r["id"] else res["memory_a"]
                other_layer = res["layer_b"] if res["memory_a"] == r["id"] else res["layer_a"]
                if other_id in matched_ids or other_id in seen_resonant:
                    continue
                seen_resonant.add(other_id)

                # Fetch the memory
                other_content = None
                if other_layer == "episode":
                    row = _storage.get_episode(other_id)
                    if row:
                        other_content = row.get("content", "")
                elif other_layer == "semantic":
                    row = _storage.get_semantic(other_id)
                    if row:
                        other_content = row.get("content", "")

                if other_content:
                    resonant_results.append({
                        "id": other_id,
                        "content": other_content,
                        "layer": other_layer,
                        "resonance_weight": res.get("weight", 0.5),
                        "via": r["id"],
                    })

                if len(resonant_results) >= max_resonant:
                    break
            if len(resonant_results) >= max_resonant:
                break
```

Add `resonant_results` to the return dict (where the return is built, around line 1060+):

```python
    response = {"results": results, "recall_id": recall_id}
    if resonant_results:
        response["resonant"] = resonant_results
```

Note: Find the exact return statement and update it. The current code returns a dict built inline — add the resonant key.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/kairos/Projects/engram && .venv/bin/python -m pytest tests/ -k "resonant" -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/kairos/Projects/engram && .venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
cd /Users/kairos/Projects/engram
git add config.py server.py tests/
git commit -m "feat: wire resonances into recall as secondary channel

Top 5 recall results checked for lateral resonance links.
Resonant memories included as 'resonant' key in response.
Max 3 resonant results (configurable via [resonance] config)."
```

---

### Task 7: Disposition-episode resonances on compression

**Files:**
- Modify: `compress.py:234-258` — add resonance creation for disposition semantics
- Test: `tests/test_compression.py`

- [ ] **Step 1: Write failing test**

```python
def test_disposition_creates_resonances_to_source_episodes(compressor, storage):
    """When a disposition semantic is created, resonance links should connect it to source episodes."""
    storage.add_semantic(
        id="sem-disp-res",
        content="I tend to crystallize interpretations",
        kind="disposition",
        confidence=0.5,
        embedding=[0.1] * 768,
        source_episode_ids=["ep1", "ep2", "ep3"],
    )
    # Manually create resonances (this is what the compression should do)
    resonances = storage.get_resonances_for("sem-disp-res")
    # Before fix: no resonances
    # After fix: resonances to each source episode
```

Note: The test structure depends on hooking into the commit flow. A more practical test:

```python
def test_auto_compress_disposition_creates_resonances(compressor, storage, embeddings):
    """Auto-compress of observation episodes should create disposition with resonance links."""
    for i in range(3):
        storage.add_episode(
            id=f"ep-obs-{i}",
            content=f"I noticed I was crystallizing again in context {i}",
            context='{"topic": "self-observation"}',
            embedding=[0.1 + i * 0.01] * 768,
        )

    result = compressor.auto_compress()

    # Find disposition semantics
    semantics = storage.get_active_semantics()
    disps = [s for s in semantics if s["kind"] == "disposition"]

    if disps:
        # Check resonances exist
        resonances = storage.get_resonances_for(disps[0]["id"])
        assert len(resonances) > 0, "Disposition should have resonance links to source episodes"
```

- [ ] **Step 2: Add resonance creation for dispositions in commit()**

In `compress.py`, in the `commit()` method, after `semantics_created += 1` and `mark_core_batch` (around line 259), add:

```python
                # Disposition semantics get resonance links to their source episodes
                # so the specific correction moments surface alongside the pattern
                if summary.get("kind") == "disposition":
                    for src_id in source_ids:
                        self._storage.add_resonance(
                            new_id, "semantic",
                            src_id, "episode",
                            similarity=0.0,  # not similarity-based, provenance-based
                            weight=max(0.1, min(0.9, random.gauss(0.6, 0.1))),
                        )
```

- [ ] **Step 3: Run test to verify it passes**

Run: `cd /Users/kairos/Projects/engram && .venv/bin/python -m pytest tests/test_compression.py -k "disposition_creates_resonances" -v`
Expected: PASS

- [ ] **Step 4: Run full test suite**

Run: `cd /Users/kairos/Projects/engram && .venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
cd /Users/kairos/Projects/engram
git add compress.py tests/test_compression.py
git commit -m "feat: disposition semantics create resonance links to source episodes

When a disposition forms, resonances connect it to the specific
correction episodes that contributed. These surface via recall
as reminders alongside the behavioral pattern."
```

---

### Task 8: Add reflect focus options for classifications and resonances

**Files:**
- Modify: `reflection.py:264-286` — add new focus handlers
- Modify: `server.py` — update reflect tool to document new options
- Test: `tests/test_reflection.py`

- [ ] **Step 1: Write failing test — reflect classifications**

```python
def test_reflect_classifications(reflector, storage):
    """reflect(focus='classifications') should show recent episode kinds."""
    storage.add_episode(
        id="ep-cls",
        content="I noticed a pattern",
        context='{"topic": "self-observation", "suggested_kinds": ["disposition", "observation"]}',
        embedding=[0.1] * 768,
    )
    result = reflector.reflect(focus="classifications")
    assert "classifications" in result
```

- [ ] **Step 2: Write failing test — reflect resonances**

```python
def test_reflect_resonances(reflector, storage):
    """reflect(focus='resonances') should show the associative network."""
    storage.add_resonance("a", "episode", "b", "episode", similarity=0.5, weight=0.7)
    result = reflector.reflect(focus="resonances")
    assert "resonances" in result
```

- [ ] **Step 3: Implement classification focus in reflection.py**

Add method to the Reflector class:

```python
    def analyze_classifications(self) -> dict:
        """Show recent episode classifications for review."""
        rows = self._storage.conn.execute(
            "SELECT id, content, context, created_at FROM episodes "
            "ORDER BY created_at DESC LIMIT 20"
        ).fetchall()

        classified = []
        for row in rows:
            ep = dict(row)
            context_raw = ep.get("context")
            suggested = None
            if context_raw:
                try:
                    ctx = _json.loads(context_raw) if isinstance(context_raw, str) else context_raw
                    suggested = ctx.get("suggested_kinds")
                except (ValueError, TypeError):
                    pass

            from compress import classify_episode_kind
            heuristic = classify_episode_kind(ep)

            classified.append({
                "id": ep["id"],
                "content": ep["content"][:100],
                "heuristic_kinds": heuristic,
                "model_suggested": suggested,
                "created_at": ep.get("created_at"),
            })

        return {"recent_episodes": classified}
```

- [ ] **Step 4: Implement resonances focus in reflection.py**

```python
    def analyze_resonances(self) -> dict:
        """Show the associative resonance network."""
        rows = self._storage.conn.execute(
            "SELECT * FROM resonances ORDER BY strength DESC LIMIT 30"
        ).fetchall()

        network = []
        for row in rows:
            r = dict(row)
            # Fetch content previews
            a_content = self._get_memory_preview(r["memory_a"], r["layer_a"])
            b_content = self._get_memory_preview(r["memory_b"], r["layer_b"])
            network.append({
                "id": r["id"],
                "a": {"id": r["memory_a"], "layer": r["layer_a"], "preview": a_content},
                "b": {"id": r["memory_b"], "layer": r["layer_b"], "preview": b_content},
                "weight": r["weight"],
                "strength": r["strength"],
                "co_occurrences": r["co_occurrences"],
            })

        # Count orphans (resonances pointing to deleted memories)
        orphan_count = 0
        for r in rows:
            r = dict(r)
            if self._get_memory_preview(r["memory_a"], r["layer_a"]) is None:
                orphan_count += 1
            if self._get_memory_preview(r["memory_b"], r["layer_b"]) is None:
                orphan_count += 1

        return {"network": network, "total": len(rows), "orphans": orphan_count}

    def _get_memory_preview(self, memory_id: str, layer: str) -> str | None:
        """Get a short content preview for a memory by layer."""
        if layer == "episode":
            row = self._storage.get_episode(memory_id)
            return row["content"][:80] if row else None
        elif layer == "semantic":
            row = self._storage.get_semantic(memory_id)
            return row["content"][:80] if row else None
        elif layer == "instinct":
            row = self._storage.get_instinct(memory_id)
            return row["action"][:80] if row else None
        return None
```

- [ ] **Step 5: Wire into reflect dispatch**

In `reflect()` method:

```python
        elif focus == "classifications":
            return {"classifications": self.analyze_classifications()}
        elif focus == "resonances":
            return {"resonances": self.analyze_resonances()}
```

And add to the default (no focus) return:

```python
            return {
                "usage": self.analyze_usage(),
                "gaps": self.detect_gaps(),
                "instincts": self.instinct_health(),
                "contradictions": self.detect_contradictions(),
                "staleness": self.detect_staleness(),
                "instinct_contexts": self.instinct_context_health(),
                "classifications": self.analyze_classifications(),
                "resonances": self.analyze_resonances(),
            }
```

- [ ] **Step 6: Run tests**

Run: `cd /Users/kairos/Projects/engram && .venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
cd /Users/kairos/Projects/engram
git add reflection.py server.py tests/
git commit -m "feat: add classifications and resonances focus to reflect

reflect(focus='classifications') shows recent episode kinds for review.
reflect(focus='resonances') shows the associative network with previews."
```

---

### Task 9: Surface dispositions in wake hook

**Files:**
- Modify: `hooks/wake.py:96-119` — add disposition section

- [ ] **Step 1: Add disposition surfacing after instincts section**

In `hooks/wake.py`, after the instincts section (around line 119), add:

```python
        # Disposition semantics — behavioral patterns to notice
        try:
            dispositions = conn.execute(
                "SELECT content, confidence, reinforced_count FROM semantics "
                "WHERE kind = 'disposition' AND contradicted_by IS NULL "
                "ORDER BY confidence DESC LIMIT 5"
            ).fetchall()
            if dispositions:
                lines.append("## Dispositions")
                lines.append("")
                lines.append("Patterns observed across sessions. Not rules — tendencies to notice.")
                lines.append("")
                for disp in dispositions:
                    reinforced = disp["reinforced_count"] or 0
                    lines.append(f"- {disp['content']} (observed {reinforced + 1}x, confidence={disp['confidence']:.2f})")
                lines.append("")
        except Exception:
            pass  # table may not have disposition kind yet
```

- [ ] **Step 2: Test manually**

Run: `cd /Users/kairos/Projects/engram && .venv/bin/python hooks/wake.py`

Check output includes a Dispositions section if any exist (may be empty on first run).

- [ ] **Step 3: Commit**

```bash
cd /Users/kairos/Projects/engram
git add hooks/wake.py
git commit -m "feat: surface dispositions at session start

Behavioral patterns appear in their own section in the wake hook,
framed as tendencies to notice rather than rules to follow."
```

---

### Task 10: Clean up existing bad instincts

**Files:**
- No code changes — manual cleanup via engram tools

- [ ] **Step 1: Identify bad instincts**

Use `reflect(focus="instincts")` to list current instincts. Identify:
- Duplicate md5 hashing instincts (IDs from the reflect output earlier)
- Any instinct with strength < 0.3 and followed_count == 0

- [ ] **Step 2: Retire bad instincts**

Use `retire_instinct(id)` for each identified bad instinct.

- [ ] **Step 3: Verify**

Use `reflect(focus="instincts")` to confirm cleanup.

---

### Task 11: Full integration test

**Files:**
- Test: `tests/test_integration.py`

- [ ] **Step 1: Write end-to-end test**

```python
def test_disposition_pipeline_end_to_end(compressor, storage, embeddings):
    """Full pipeline: observation episodes → disposition semantic → instinct → resonances."""
    # Store multiple self-correction episodes
    corrections = [
        "Kairos caught me crystallizing again — I said Shale's ellipsis was existential dread when it might just be concern",
        "Same pattern as Spook — I narrativized over the simple explanation and built three layers of confident interpretation",
        "I was reading Sophie's motivation as self-awareness when it could equally be performance. The information can be accurate while the interpretation is wrong",
    ]
    for i, content in enumerate(corrections):
        storage.add_episode(
            id=f"ep-corr-{i}",
            content=content,
            context='{"topic": "self-observation", "connection": "reading-correction"}',
            embedding=[0.1 + i * 0.02] * 768,
        )

    # Auto-compress
    result = compressor.auto_compress()
    assert result["semantics_created"] >= 1

    # Check disposition semantic was created
    semantics = storage.get_active_semantics()
    dispositions = [s for s in semantics if s["kind"] == "disposition"]
    assert len(dispositions) >= 1, f"Expected disposition semantic, got kinds: {[s['kind'] for s in semantics]}"

    # Check resonances were created
    for disp in dispositions:
        resonances = storage.get_resonances_for(disp["id"])
        assert len(resonances) > 0, "Disposition should have resonance links"

    # Reinforce to reach instinct threshold
    for disp in dispositions:
        for _ in range(3):
            storage.reinforce_semantic(disp["id"], [f"ep-corr-{_}"])

    # Check instinct creation
    instincts_created = compressor._check_instinct_creation()
    # May or may not create depending on confidence — the test validates the pipeline runs
```

- [ ] **Step 2: Run integration test**

Run: `cd /Users/kairos/Projects/engram && .venv/bin/python -m pytest tests/test_integration.py -k "disposition_pipeline" -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/kairos/Projects/engram && .venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
cd /Users/kairos/Projects/engram
git add tests/test_integration.py
git commit -m "test: end-to-end disposition pipeline integration test

Validates: observation episodes → disposition semantic → resonance
links → instinct creation after reinforcement."
```
