# Generic Evolving-Category Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a shadow-mode, event-sourced weak 2-category that evolves through versioned rewrites, replays the legacy archive, detects generic context boundaries, and compiles a bounded working category without changing live recall by default.

**Architecture:** Preserve `CategoryStore` and `categories.db`; add an isolated `EvolvingCategoryStore` backed by `categories_v2.db`. Immutable cells, events, rewrites, epochs, contexts, and weight observations remain on disk. A compiler streams a small context-dependent view into RAM, and server integration is non-fatal behind independent observer, influence, and auto-commit gates.

**Tech Stack:** Python 3.12+, SQLite/JSON1, optional sqlite-vec, dataclasses, hashlib, pytest; no new runtime dependency.

## Global Constraints

- Execute in an isolated worktree; the current checkout has unrelated user changes in `dedup.py`, `framing.py`, `server.py`, tests, and research files.
- Never modify or delete legacy `categories.db`; v2 uses `categories_v2.db`.
- Production code contains no domain-specific branch for books, repositories, conversations, reading, or planning.
- Interpret dimensions 0–2; persist dimensions above 2 opaquely and exclude them from online traversal.
- Cells, events, contexts, weights, and rewrite dispositions are append-only.
- Token budgets are 36,000 normal, 40,000 forced rotation, and 65,536 absolute.
- Limits: traversal depth 4, neighbors 64, candidates 50,000, compile 500 ms, rewrites/pass 32, inputs or outputs/rewrite 32, active branches/locus 4.
- Archive quota is 3,000,000,000,000 bytes; derived writes stop at 90% and category writes fail closed at 100%.
- The existing 112 GB process governor remains authoritative.
- `enabled`, `shadow`, `influence_recall`, and `auto_commit` are independent; live influence and auto-commit ship false.
- An LLM may propose content but may not commit a rewrite.
- Acceptance gates are boundary F1 at least 0.80, cross-context MRR improvement at least 15%, direct-recall regression at most 5%, false-transfer rate at most 10%, three identical replay hashes, and less than 1 GiB incremental peak RSS for one million cells.
- Use TDD and commit only files named by each task.

---

### Task 1: Configuration and Safety Gates

**Files:**
- Modify: `config.py:123-274`
- Modify: `tests/test_config.py:56-139`

**Interfaces:**
- Consumes: `load_config(project_root: Path | None) -> EngramConfig`
- Produces: `CategoryEvolutionConfig`, `EngramConfig.category_evolution`

- [ ] **Step 1: Write failing tests**

Append:

```python
def test_category_evolution_config_defaults():
    cfg = EngramConfig().category_evolution
    assert (cfg.enabled, cfg.shadow, cfg.influence_recall, cfg.auto_commit) == (
        False, True, False, False,
    )
    assert cfg.archive_quota_bytes == 3_000_000_000_000
    assert cfg.archive_high_watermark_ratio == 0.90
    assert cfg.interpreted_max_dimension == 2
    assert cfg.max_traversal_depth == 4
    assert cfg.max_neighbors == 64
    assert cfg.max_candidates == 50_000
    assert cfg.compile_wall_time_ms == 500
    assert cfg.consolidation_event_interval == 250
    assert cfg.consolidation_rewrite_budget == 32
    assert cfg.max_rewrite_members == 32
    assert cfg.max_active_branches == 4
    assert cfg.soft_boundary_threshold == 0.35
    assert cfg.hard_boundary_threshold == 0.65
    assert cfg.hard_boundary_confirmations == 2


def test_category_evolution_config_loads_independent_gates(tmp_path):
    config_dir = tmp_path / ".engram"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        "[category_evolution]\n"
        "enabled = true\nshadow = true\n"
        "influence_recall = false\nauto_commit = false\n"
        "max_candidates = 1234\n"
    )
    cfg = load_config(tmp_path).category_evolution
    assert cfg.enabled is True
    assert cfg.influence_recall is False
    assert cfg.auto_commit is False
    assert cfg.max_candidates == 1234
```

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/python -m pytest tests/test_config.py -q`

Expected: FAIL because `category_evolution` is absent.

- [ ] **Step 3: Add the dataclass and loader**

```python
@dataclass
class CategoryEvolutionConfig:
    enabled: bool = False
    shadow: bool = True
    influence_recall: bool = False
    auto_commit: bool = False
    db_path: str = ""
    archive_quota_bytes: int = 3_000_000_000_000
    archive_high_watermark_ratio: float = 0.90
    interpreted_max_dimension: int = 2
    max_traversal_depth: int = 4
    max_neighbors: int = 64
    max_candidates: int = 50_000
    compile_wall_time_ms: int = 500
    consolidation_event_interval: int = 250
    consolidation_rewrite_budget: int = 32
    max_rewrite_members: int = 32
    max_active_branches: int = 4
    soft_boundary_threshold: float = 0.35
    hard_boundary_threshold: float = 0.65
    hard_boundary_confirmations: int = 2
```

Add it to `EngramConfig`, `_DEFAULT_TOML`, and `load_config` exactly as other sections are wired.

- [ ] **Step 4: Verify and commit**

Run: `.venv/bin/python -m pytest tests/test_config.py -q`

Expected: PASS.

```bash
git add config.py tests/test_config.py
git commit -m "feat: add evolving category safety gates"
```

---

### Task 2: Immutable V2 Store

**Files:**
- Modify: `categories.py:1-217`
- Create: `tests/test_categories_v2.py`

**Interfaces:**
- Produces: `Boundary`, `CellDraft`, `WeightVector`, `EvolvingCategoryStore`

```python
@dataclass(frozen=True)
class Boundary:
    side: Literal["source", "target"]
    position: int
    cell_id: str


@dataclass(frozen=True)
class CellDraft:
    id: str
    dimension: int
    content: str
    boundaries: tuple[Boundary, ...] = ()
    context_id: str | None = None
    payload: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WeightVector:
    relevance: float
    evidence: float
    recency: float
    affect: float
    adoption: float
    novelty: float
    cost: float
```

- [ ] **Step 1: Write failing storage tests**

Create fixtures with `sqlite3.connect(tmp_path / "categories_v2.db")` and test:

```python
def test_dimension_one_requires_zero_cell_boundaries(v2_store):
    v2_store.create_cell(CellDraft("a", 0, "a"))
    v2_store.create_cell(CellDraft("b", 0, "b"))
    arrow = CellDraft("f", 1, "a to b", (
        Boundary("source", 0, "a"), Boundary("target", 0, "b"),
    ))
    assert v2_store.create_cell(arrow) == "f"
    with pytest.raises(ValueError, match="dimension-1 cell requires"):
        v2_store.create_cell(CellDraft("broken", 1, "broken"))


def test_higher_cell_is_opaque(v2_store):
    v2_store.create_cell(CellDraft("higher", 5, "opaque", payload={"k": "v"}))
    assert v2_store.get_cell("higher")["payload"] == {"k": "v"}
    assert v2_store.is_interpretable("higher") is False


def test_cell_is_sql_immutable(v2_store):
    v2_store.create_cell(CellDraft("fixed", 0, "original"))
    with pytest.raises(sqlite3.IntegrityError):
        v2_store.connection.execute(
            "UPDATE cat_cells SET content='changed' WHERE id='fixed'"
        )
```

Also test schema table names, foreign keys, ordered boundaries, weight ranges, append-only observations, canonical content hashes, and context deduplication.

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/python -m pytest tests/test_categories_v2.py -q`

Expected: FAIL because v2 interfaces are absent.

- [ ] **Step 3: Add the schema below legacy `CategoryStore`**

Create prefixed tables: `cat_schema_version`, `cat_events`, `cat_contexts`, `cat_cells`, `cat_boundaries`, `cat_weight_observations`, `cat_rewrites`, `cat_rewrite_members`, `cat_epochs`, `cat_epoch_parents`, `cat_snapshots`, and optional sqlite-vec virtual table `cat_vectors`. Exact constraints:

```sql
CREATE TABLE cat_cells (
  id TEXT PRIMARY KEY,
  dimension INTEGER NOT NULL CHECK (dimension >= 0),
  content TEXT NOT NULL,
  context_id TEXT REFERENCES cat_contexts(id),
  payload_json TEXT NOT NULL DEFAULT '{}',
  content_hash TEXT NOT NULL,
  created_event_id TEXT REFERENCES cat_events(id),
  created_at TEXT NOT NULL
);
CREATE TABLE cat_boundaries (
  cell_id TEXT NOT NULL REFERENCES cat_cells(id),
  side TEXT NOT NULL CHECK (side IN ('source','target')),
  position INTEGER NOT NULL CHECK (position >= 0),
  boundary_id TEXT NOT NULL REFERENCES cat_cells(id),
  PRIMARY KEY (cell_id, side, position)
);
CREATE TABLE cat_weight_observations (
  id TEXT PRIMARY KEY,
  cell_id TEXT NOT NULL REFERENCES cat_cells(id),
  context_id TEXT REFERENCES cat_contexts(id),
  relevance REAL NOT NULL CHECK (relevance BETWEEN 0 AND 1),
  evidence REAL NOT NULL CHECK (evidence BETWEEN 0 AND 1),
  recency REAL NOT NULL CHECK (recency BETWEEN 0 AND 1),
  affect REAL NOT NULL CHECK (affect BETWEEN -1 AND 1),
  adoption REAL NOT NULL CHECK (adoption BETWEEN 0 AND 1),
  novelty REAL NOT NULL CHECK (novelty BETWEEN 0 AND 1),
  cost REAL NOT NULL CHECK (cost BETWEEN 0 AND 1),
  evidence_event_id TEXT REFERENCES cat_events(id),
  policy_version TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

`cat_rewrite_members.role` is constrained to `input|output|witness|evidence` and holds either `cell_id` or `external_id`, never both. Epochs have ordered parent rows. Snapshots store canonical sorted active-cell JSON and SHA-256. Enable foreign keys. Add triggers rejecting `UPDATE` and `DELETE` on every immutable table; snapshots are regenerable and replaceable.

- [ ] **Step 4: Implement the exact storage API**

Implement `connection -> sqlite3.Connection`, `transaction() -> ContextManager[sqlite3.Connection]`, `append_event(kind, payload, *, event_id=None) -> str`, `create_context(features, *, context_id=None) -> str`, `create_cell(draft, *, created_event_id=None) -> str`, `get_cell(cell_id) -> dict | None`, `get_boundaries(cell_id, side=None) -> list[Boundary]`, `is_interpretable(cell_id) -> bool`, `observe_weight(cell_id, context_id, weights, *, evidence_event_id=None, policy_version="v1") -> str`, `latest_weight(cell_id, context_id) -> WeightVector | None`, and `close() -> None`.

Canonical JSON uses `sort_keys=True, separators=(",", ":")`. Nested writes use SAVEPOINTs and never commit the caller's transaction. Validate dimensions 0 and 1 here; Task 5 adds dimension-2 path validation. Create `cat_vectors` only when sqlite-vec is loaded; missing sqlite-vec must leave exact traversal and non-vector tests operational.

- [ ] **Step 5: Verify v2 and legacy behavior**

Run:

```bash
.venv/bin/python -m pytest tests/test_categories_v2.py tests/test_server.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add categories.py tests/test_categories_v2.py
git commit -m "feat: add immutable evolving category store"
```

---

### Task 3: Deterministic Legacy Import

**Files:**
- Create: `category_evolution.py`
- Create: `tests/test_category_evolution.py`

**Interfaces:**
- Produces: `LegacyImportReport`, `import_legacy_category`, `canonical_snapshot_hash`

```python
@dataclass(frozen=True)
class LegacyImportReport:
    legacy_total: int
    proxy_zero_cells: int
    imported_one_cells: int
    imported_two_cells: int
    opaque_cells: int
    unexplained_loss: int
    root_epoch_id: str
    snapshot_hash: str
```

- [ ] **Step 1: Write failing import tests**

Create a legacy database with two level-1 cells pointing to external memory IDs and one level-2 transfer. Assert first and second imports both report 3 legacy cells, 2 proxy 0-cells, 2 one-cells, 1 two-cell, zero loss, the same snapshot hash, and exactly 5 v2 cells. Rebuild into three independent v2 databases and assert one hash. Test malformed references report loss rather than inventing targets.

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/python -m pytest tests/test_category_evolution.py -q -k legacy`

Expected: FAIL because importer is absent.

- [ ] **Step 3: Implement deterministic IDs and four-pass import**

```python
LEGACY_NAMESPACE = uuid.UUID("f4210ab5-b9e8-53ba-b3ca-261db44a9223")


def legacy_proxy_id(memory_id: str) -> str:
    return str(uuid.uuid5(LEGACY_NAMESPACE, f"memory:{memory_id}"))


def canonical_snapshot_hash(cell_ids: Iterable[str]) -> str:
    payload = json.dumps(sorted(set(cell_ids)), separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
```

Passes: validate rows; create proxy 0-cells; import level-1 cells; import level-2 and opaque cells. Preserve legacy IDs because the DB is isolated. Create a content-addressed root epoch and snapshot. Bootstrap is exempt from online rewrite member limits and emits one summary event.

- [ ] **Step 4: Add read-only replay CLI**

Support:

```bash
.venv/bin/python category_evolution.py replay \
  --legacy .engram/instances/engram/categories.db \
  --output /tmp/engram-categories-v2.db --json
```

Refuse identical resolved paths. Return exit 2 for unexplained loss. Open the legacy path read-only and never write to it.

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/python -m pytest tests/test_category_evolution.py -q -k 'legacy or replay'`

Expected: PASS.

```bash
git add category_evolution.py tests/test_category_evolution.py
git commit -m "feat: replay legacy category history"
```

---

### Task 4: Generic Context Boundaries

**Files:**
- Create: `category_context.py`
- Create: `tests/test_category_context.py`

**Interfaces:**
- Produces: `ContextObservation`, `BoundaryDecision`, `ContextTracker`

```python
@dataclass(frozen=True)
class ContextObservation:
    goal: Mapping[str, float] = field(default_factory=dict)
    entities: Mapping[str, float] = field(default_factory=dict)
    participants: Mapping[str, float] = field(default_factory=dict)
    tools: Mapping[str, float] = field(default_factory=dict)
    sources: Mapping[str, float] = field(default_factory=dict)
    attention: Mapping[str, float] = field(default_factory=dict)
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    explicit_boundary: bool = False


@dataclass(frozen=True)
class BoundaryDecision:
    kind: Literal["same", "soft", "hard"]
    score: float
    confirmations: int
    components: Mapping[str, float]
    context_id: str
```

- [ ] **Step 1: Write failing domain-neutral tests**

Parameterize abrupt goal changes using four vocabularies:

```python
@pytest.mark.parametrize("before,after", [
    ({"goal:understand": 1.0}, {"goal:decide": 1.0}),
    ({"goal:debug": 1.0}, {"goal:deploy": 1.0}),
    ({"goal:follow": 1.0}, {"goal:compare": 1.0}),
    ({"goal:collect": 1.0}, {"goal:schedule": 1.0}),
])
def test_one_algorithm_detects_goal_shift(before, after):
    tracker = ContextTracker(hard_confirmations=2)
    tracker.observe(ContextObservation(goal=before))
    assert tracker.observe(ContextObservation(goal=after)).kind == "soft"
    assert tracker.observe(ContextObservation(goal=after)).kind == "hard"
```

Also test explicit boundary, gradual drift, return to prior context, overlap, source-only change, goal-only change, time discontinuity, and stability.

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/python -m pytest tests/test_category_context.py -q`

Expected: FAIL because module is absent.

- [ ] **Step 3: Implement divergence and tracker**

Use weighted-Jaccard divergence for sparse maps and this exact score:

```python
score = (
    0.40 * goal_divergence
    + 0.20 * entity_turnover
    + 0.15 * max(participant_turnover, tool_turnover)
    + 0.15 * source_change
    + 0.10 * temporal_discontinuity
)
```

Explicit means hard/1.0. Hard requires two consecutive scores at least 0.65; 0.35 is soft. Below 0.35 clears confirmations. Keep 16 prior fingerprints so a return can reactivate its stable context ID.

- [ ] **Step 4: Verify and commit**

Run: `.venv/bin/python -m pytest tests/test_category_context.py -q`

Expected: PASS.

```bash
git add category_context.py tests/test_category_context.py
git commit -m "feat: detect generic context boundaries"
```

---

### Task 5: Structural Rewrites and Epochs

**Files:**
- Modify: `category_evolution.py`
- Modify: `categories.py`
- Modify: `tests/test_category_evolution.py`
- Modify: `tests/test_categories_v2.py`

**Interfaces:**
- Produces: `RewriteEvidence`, `RewriteProposal`, `EvolutionPolicy`, `EvolutionEngine`

```python
@dataclass(frozen=True)
class RewriteEvidence:
    evidence_event_ids: tuple[str, ...]
    cohesion_gain: float
    persistence_score: float
    complexity_cost: float
    explicit_correction: bool = False


@dataclass(frozen=True)
class RewriteProposal:
    id: str
    kind: Literal["create", "retire", "retype", "split", "merge"]
    locus_id: str
    context_id: str | None
    input_ids: tuple[str, ...]
    outputs: tuple[CellDraft, ...]
    witness_ids: tuple[str, ...]
    evidence: RewriteEvidence


@dataclass(frozen=True)
class EvolutionPolicy:
    min_persistence_score: float = 0.10
    rewrite_budget: int = 32
    max_members: int = 32
    max_active_branches: int = 4
```

- [ ] **Step 1: Write failing rewrite tests**

Test that proposal does not change active cells, supported split commits atomically, failed proposal preserves canonical state, one-off noise rejects, explicit correction is eligible, merge/retype/retire preserve lineage, consolidation stops at 32, members stop at 32, forks stop at 4, epoch parents stay acyclic, old epoch selection rolls back logically, replay hashes match, and a corrupt derived snapshot is discarded and rebuilt from immutable events.

- [ ] **Step 2: Write dimension-2 path tests**

Create `A -> B -> C`, non-composable `A -> B, C -> A`, and a 2-cell relating two `A -> C` paths. Only composable equal-endpoint paths may be interpreted.

- [ ] **Step 3: Verify failure**

Run: `.venv/bin/python -m pytest tests/test_category_evolution.py tests/test_categories_v2.py -q -k 'proposal or commit or epoch or dimension_two'`

Expected: FAIL.

- [ ] **Step 4: Implement validation and append-only dispositions**

`validate_path` requires dimension-1 members and adjacent target/source equality. Dimension-2 source and target paths must be nonempty and share endpoints. Do not add mutable status: append `rewrite_proposed`, `rewrite_committed`, `rewrite_rejected`, or `rewrite_superseded` events and derive the latest disposition.

Eligibility is exact:

```python
def is_eligible(evidence: RewriteEvidence, policy: EvolutionPolicy) -> bool:
    if evidence.explicit_correction:
        return True
    return (
        evidence.cohesion_gain > evidence.complexity_cost
        and evidence.persistence_score >= policy.min_persistence_score
    )
```

- [ ] **Step 5: Implement atomic proposal, commit, and consolidation**

Proposal creates inactive outputs, rewrite members, and event in one transaction. Commit validates evidence, parents, limits, lineage, and branch count; appends disposition, creates epoch, derives active set from parent snapshots, and writes canonical snapshot in one transaction. Rejected output cells remain archived but inactive. Consolidation orders by explicit correction descending, net gain descending, creation time ascending, ID ascending, and commits at most 32.

- [ ] **Step 6: Verify and commit**

Run: `.venv/bin/python -m pytest tests/test_category_evolution.py tests/test_categories_v2.py -q`

Expected: PASS.

```bash
git add categories.py category_evolution.py tests/test_categories_v2.py tests/test_category_evolution.py
git commit -m "feat: evolve category structure through rewrites"
```

---

### Task 6: Bounded Working-Category Compiler

**Files:**
- Create: `category_compile.py`
- Create: `tests/test_category_compile.py`

**Interfaces:**
- Consumes: store, epoch ID, context ID, seed cell IDs, base tokens
- Produces: `CompileBudget`, `CompiledCell`, `CompiledCategory`, `CategoryCompiler`

```python
@dataclass(frozen=True)
class CompileBudget:
    normal_target: int = 36_000
    rotation_watermark: int = 40_000
    hard_ceiling: int = 65_536
    base_tokens: int = 0
    max_depth: int = 4
    max_neighbors: int = 64
    max_candidates: int = 50_000
    wall_time_ms: int = 500


@dataclass(frozen=True)
class CompiledCell:
    id: str
    content: str
    dimension: int
    score: float
    contributions: Mapping[str, float]
    hops: int
    token_count: int


@dataclass(frozen=True)
class CompiledCategory:
    epoch_id: str
    context_id: str | None
    cells: tuple[CompiledCell, ...]
    token_count: int
    candidate_count: int
    truncated: bool
    rotation_required: bool
    policy_version: str = "v1"
```

- [ ] **Step 1: Write failing valuation tests**

```python
def test_weight_channels_remain_separate():
    weights = WeightVector(0.8, 0.9, 0.5, -0.7, 0.2, 0.6, 0.4)
    score, parts = valuation_v1(weights)
    assert parts == {
        "relevance": 0.24,
        "evidence": 0.18,
        "recency": 0.05,
        "affect_salience": 0.07,
        "adoption": 0.02,
        "novelty": 0.09,
        "cost": -0.02,
    }
    assert score == pytest.approx(sum(parts.values()))
    assert weights.affect == -0.7
```

Coefficients are `0.30, 0.20, 0.10, 0.10*abs(affect), 0.10, 0.15, -0.05`. Also prove evidence cannot masquerade as relevance, affect does not alter evidence, and adoption remains scoped.

- [ ] **Step 2: Write failing traversal and budget tests**

Build a temporary epoch containing direct cells, a dense hub, a distant useful relation, a rewritten historical cell, and an opaque 3-cell. Assert depth 4, neighbors 64, candidates 50,000, active-descendant translation, deterministic ID ties, diversity retains the distant cell, `base + selected <= 65_536`, base 40,000 requires rotation, base 65,536 returns no cells, and dimension 3 is excluded.

- [ ] **Step 3: Verify failure**

Run: `.venv/bin/python -m pytest tests/test_category_compile.py -q`

Expected: FAIL because compiler is absent.

- [ ] **Step 4: Implement streaming traversal and valuation**

Query adjacency and lineage with indexed SQL. Hold only a deque, visited set, and bounded candidate heap. Check `time.monotonic_ns()` every expansion batch. The token estimator is:

```python
def estimate_tokens(text: str) -> int:
    return max(1, (len(text.encode("utf-8")) + 3) // 4)
```

- [ ] **Step 5: Implement deterministic diversity and packing**

Use greedy MMR with lambda 0.75. Similarity is cosine when both embeddings exist; otherwise weighted-Jaccard over lowercase word tokens. Break ties by cell ID. Pack to `min(normal_target - base_tokens, hard_ceiling - base_tokens)`. Preserve signed affect in metadata while using its magnitude for salience. Mark truncation for any time, depth, neighbor, candidate, or token stop.

- [ ] **Step 6: Verify and commit**

Run: `.venv/bin/python -m pytest tests/test_category_compile.py tests/test_category_evolution.py -q`

Expected: PASS.

```bash
git add category_compile.py tests/test_category_compile.py
git commit -m "feat: compile bounded working categories"
```

---

### Task 7: Archive Quota and Degraded Mode

**Files:**
- Modify: `categories.py`
- Modify: `tests/test_categories_v2.py`

**Interfaces:**
- Produces: `ArchivePressure`, `CategoryQuotaExceeded`, `EvolvingCategoryStore.pressure`

- [ ] **Step 1: Write failing quota tests with an injected size provider**

```python
def test_archive_pressure_stages(tmp_path):
    size = {"value": 0}
    store = make_v2_store(
        tmp_path / "v2.db", quota_bytes=1_000,
        high_watermark_ratio=0.90,
        size_provider=lambda _path: size["value"],
    )
    size["value"] = 899
    assert store.pressure().state == "normal"
    size["value"] = 900
    assert store.pressure().state == "derived_blocked"
    size["value"] = 1_000
    assert store.pressure().state == "writes_blocked"


def test_hard_quota_blocks_write_but_not_read(store_at_quota):
    with pytest.raises(CategoryQuotaExceeded):
        store_at_quota.create_cell(CellDraft("new", 0, "new"))
    assert store_at_quota.get_cell("existing")["content"] == "existing"
```

Test snapshots/vector duplicates stop at 90%, immutable writes continue until 100%, and failed writes leave no partial rows.

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/python -m pytest tests/test_categories_v2.py -q -k quota`

Expected: FAIL.

- [ ] **Step 3: Implement pressure states**

```python
@dataclass(frozen=True)
class ArchivePressure:
    state: Literal["normal", "derived_blocked", "writes_blocked"]
    used_bytes: int
    quota_bytes: int


class CategoryQuotaExceeded(RuntimeError):
    pass
```

Default size provider sums the DB, `-wal`, and `-shm` files. Check before write transactions. Derived operations return a skipped result at high water; immutable writes raise only at hard quota. Never delete immutable rows.

- [ ] **Step 4: Verify and commit**

Run: `.venv/bin/python -m pytest tests/test_categories_v2.py -q`

Expected: PASS.

```bash
git add categories.py tests/test_categories_v2.py
git commit -m "feat: bound evolving category archive writes"
```

---

### Task 8: Shadow Integration and Reflection

**Files:**
- Modify: `server.py:150-168,273-386,1368-1495,2126-2133`
- Modify: `reflection.py:52-64,675-740`
- Modify: `tests/test_server.py:47-89`
- Modify: `tests/test_reflection.py:86-94`
- Create: `tests/test_category_server.py`

**Interfaces:**
- Produces: `CategoryObserver`, `_category_observer`, `Reflector.analyze_category_evolution`

`CategoryObserver` exposes `observe_recall(query, result_ids, *, source, observed_at) -> None`, `observe_outcome(recall_id, used, note) -> None`, `compile_for_recall(seed_ids, base_tokens=0) -> CompiledCategory`, `adjust_results(results, compiled, influence=0.10) -> list[dict]`, `report() -> dict`, and `close() -> None`.

- [ ] **Step 1: Write failing isolation tests**

Test that enabling observer with `shadow=True, influence_recall=False` leaves result IDs and scores identical and adds no response field. Force `observe_recall` to raise `sqlite3.DatabaseError` and assert recall still returns results. Assert shadow writes v2 events, `auto_commit=False` creates no new committed epoch, and explicit `shadow=False, influence_recall=True` adjusts existing results by exactly 10% without injecting a new result or commentary.

- [ ] **Step 2: Write failing reflection tests**

Pass a report provider to `Reflector`; `reflect(focus="category_evolution")` must return flags, counts by dimension, proposal dispositions, current epoch, recent boundaries, compiler truncations, quota pressure, and last error. Keep it out of no-focus reflection.

- [ ] **Step 3: Verify failure**

Run: `.venv/bin/python -m pytest tests/test_category_server.py tests/test_reflection.py -q -k category`

Expected: FAIL.

- [ ] **Step 4: Implement `CategoryObserver`**

Build sparse context features from normalized query terms, cwd source, and timestamp. Record recall and boundary events plus proxy links for result IDs. Never consolidate in recall or outcome. `adjust_results` uses `0.90 * baseline_score + 0.10 * category_score`, reorders deterministically, and never creates results.

- [ ] **Step 5: Wire independent gates non-fatally**

Add `_category_observer = None`. Initialize only when `enabled`; empty `db_path` resolves beside active `graph.db` as `categories_v2.db`. Catch init/observe/compile failures, log, and continue. Preserve legacy `_category_store` and visible transfers unchanged. Shadow compiles only diagnostics. Startup consolidation runs only when `enabled and auto_commit`; recall never runs it.

- [ ] **Step 6: Add reflection provider**

Extend `Reflector.__init__` with keyword-only `category_reporter: Callable[[], dict] | None = None`. Return `{"available": False}` when absent and `{"available": False, "error": type(exc).__name__}` on failure. Add only explicit focus dispatch.

- [ ] **Step 7: Verify and commit**

Run: `.venv/bin/python -m pytest tests/test_category_server.py tests/test_reflection.py tests/test_server.py -q`

Expected: PASS.

```bash
git add server.py reflection.py category_evolution.py tests/test_category_server.py tests/test_reflection.py tests/test_server.py
git commit -m "feat: observe evolving categories in shadow mode"
```

---

### Task 9: Falsifiable Evaluation and Resource Harness

**Files:**
- Create: `experiments/category_evolution/__init__.py`
- Create: `experiments/category_evolution/metrics.py`
- Create: `experiments/category_evolution/fixtures.py`
- Create: `experiments/category_evolution/runner.py`
- Create: `experiments/category_evolution/benchmark.py`
- Create: `tests/test_category_evaluation.py`

**Interfaces:**
- Produces: boundary precision/recall/F1, MRR, false-transfer rate, JSON report

- [ ] **Step 1: Write failing metric tests**

```python
def test_boundary_metrics_by_kind():
    rows = [
        ("explicit", True, True), ("abrupt", True, True),
        ("gradual", True, False), ("gradual", False, False),
    ]
    result = boundary_metrics(rows)
    assert result["overall"]["precision"] == 1.0
    assert result["overall"]["recall"] == pytest.approx(2 / 3)
    assert set(result) == {"overall", "explicit", "abrupt", "gradual"}


def test_ranking_metrics():
    rankings = [(["a", "b"], {"b"}), (["c", "d"], {"c"})]
    assert mean_reciprocal_rank(rankings) == 0.75
    assert false_transfer_rate([True, False, False, True]) == 0.5
```

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/python -m pytest tests/test_category_evaluation.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement metrics and fixed fixtures**

Create development and holdout fixtures for conversation, coding, reading/media, and planning with equivalent structure and distinct vocabulary. Hash canonical fixture serialization. The runner refuses tuning options for holdout.

- [ ] **Step 4: Implement evaluation runner**

```bash
.venv/bin/python -m experiments.category_evolution.runner \
  --legacy .engram/instances/engram/categories.db \
  --work-dir /tmp/engram-category-eval \
  --cohort development --seed 20260807
```

JSON includes fixture hash, seed, import report, boundary metrics by kind, baseline/shadow MRR, relative improvement, direct-recall regression, false-transfer rate, compiler limits, configuration, and each acceptance gate. The legacy database is opened read-only.

- [ ] **Step 5: Implement resource benchmark**

Stream generated cells in batches of 10,000, record incremental peak RSS with `resource.getrusage`, compile once, and report the 1 GiB gate. Require explicit `--cells 1000000`; unit tests use 1,000 and validate shape.

- [ ] **Step 6: Verify tests and run disposable development evaluation**

Run: `.venv/bin/python -m pytest tests/test_category_evaluation.py -q`

Then:

```bash
eval_dir=$(mktemp -d)
.venv/bin/python -m experiments.category_evolution.runner \
  --legacy .engram/instances/engram/categories.db \
  --work-dir "$eval_dir" --cohort development --seed 20260807
```

Expected: report completes; failed gates remain reported rather than triggering hidden tuning. Delete only the resolved temporary directory after retaining command output.

- [ ] **Step 7: Commit**

```bash
git add experiments/category_evolution tests/test_category_evaluation.py
git commit -m "test: add evolving category acceptance harness"
```

---

### Task 10: Packaging, Documentation, and Full Verification

**Files:**
- Modify: `pyproject.toml:31-70`
- Modify: `CLAUDE.md:1-170`
- Modify: `docs/superpowers/specs/2026-08-07-evolving-category-memory-design.md:1-478`
- Modify: `tests/test_packaging.py`

**Interfaces:**
- Produces: installable modules and documented shadow runtime

- [ ] **Step 1: Write failing packaging assertions**

Parse `pyproject.toml` and assert `category_context`, `category_evolution`, and `category_compile` occur in `tool.setuptools.py-modules`.

- [ ] **Step 2: Verify failure**

Run: `.venv/bin/python -m pytest tests/test_packaging.py -q`

Expected: FAIL because modules are absent from packaging.

- [ ] **Step 3: Package and document**

Add modules alphabetically. Document legacy/v2 separation, generic boundaries, immutable epochs, interpreted dimensions, gates, token and archive limits, degraded behavior, reflection focus, replay/evaluation/benchmark commands. Change spec status to `Implemented in shadow mode; acceptance pending`; do not claim gates passed without a report.

- [ ] **Step 4: Run focused tests**

```bash
.venv/bin/python -m pytest \
  tests/test_categories_v2.py tests/test_category_context.py \
  tests/test_category_evolution.py tests/test_category_compile.py \
  tests/test_category_server.py tests/test_category_evaluation.py -q
```

Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`

Expected: PASS. Reproduce unrelated failures on untouched base before attributing them to this branch.

- [ ] **Step 6: Verify disabled-by-default behavior**

A fresh config must not create `categories_v2.db`. Enabling only observer in a temporary project must create it while recall output remains unchanged and no epoch is auto-committed.

- [ ] **Step 7: Verify scope**

```bash
git diff --check
git status --short
git diff --stat a1e161c..HEAD
```

Expected: only planned modules, tests, documentation, and packaging changes in the implementation worktree.

- [ ] **Step 8: Commit and request review**

```bash
git add pyproject.toml CLAUDE.md \
  docs/superpowers/specs/2026-08-07-evolving-category-memory-design.md \
  tests/test_packaging.py
git commit -m "docs: document evolving category shadow runtime"
```

Use `superpowers:requesting-code-review` on the complete branch. Keep observer, recall influence, and auto-commit disabled until review and development evaluation are complete. Holdout evaluation and live enablement are separate explicit decisions.
