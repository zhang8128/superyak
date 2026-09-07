# Contextual Stochastic Recall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and falsify a bounded, replayable, shadow-mode joint context-memory filter that changes ambiguous recall by inferred context and restores an earlier trajectory when that context returns.

**Architecture:** Preserve existing vector/FTS recall as candidate generation. An isolated `context_memory.db` records immutable observations and derived sparse state nodes; a sticky Bayesian-style filter maintains context probabilities, and a bounded sparse Markov pass produces counterfactual rankings. Server integration records shadow results and explicit per-memory feedback but cannot alter live results.

**Tech Stack:** Python 3.12+, stdlib dataclasses/SQLite/JSON/hashlib/math/random, existing pytest and SciPy; no new runtime dependency.

## Global Constraints

- Execute in an isolated worktree created with `superpowers:using-git-worktrees`; the current checkout contains unrelated user changes.
- Never modify `graph.db`, `categories.db`, or `instinct_transitions.db` schemas for this feature.
- Use a separate `context_memory.db`; tests use temporary databases only.
- Physical memory content remains authoritative in the existing `Storage`; context state nodes store IDs and weights, never copied content.
- Defaults are `enabled = false`, `shadow = true`, `influence_recall = false`, `auto_create_context = false`, and `auto_consolidate = false`.
- Bound every inference to 8 posterior contexts plus `unknown`, 200 candidates, 32 expanded neighbors per candidate, 2 diffusion steps, 10,000 active state nodes, and 100 retained context proposals per session.
- A surfaced result is not positive evidence. Only explicit `used_memory_ids`, corrections, rejections, or explicit anchors may change learned memory paths.
- Context creation is asynchronous and gated by persistent `unknown` mass; recall never creates a context synchronously.
- Missing or failing shadow components must leave baseline recall byte-for-byte equivalent after removal of timestamps and generated IDs.
- Use TDD and commit only files named by each task.

---

### Task 1: Configuration and Immutable Context Event Store

**Files:**
- Create: `context_memory.py`
- Create: `tests/test_context_memory.py`
- Modify: `config.py:1-274`
- Modify: `tests/test_config.py:1-140`
- Modify: `pyproject.toml:28-75`

**Interfaces:**
- Produces: `ContextMemoryConfig`, `ContextEvent`, `ContextRecord`, `StateNode`, `ContextMemoryStore`
- Produces methods used later: `append_event`, `create_context`, `list_contexts`, `get_context`, `bind_memory`, `state_weight`, `observe_context_transition`, `observe_memory_transition`, `context_transition_counts`, `memory_transition_counts`, `save_activation`, `load_activation`, `save_shadow_recall`, `load_shadow_recall`

- [ ] **Step 1: Write failing configuration tests**

Add to `tests/test_config.py`:

```python
def test_context_memory_defaults_are_inert():
    cfg = EngramConfig().context_memory
    assert (cfg.enabled, cfg.shadow, cfg.influence_recall) == (False, True, False)
    assert (cfg.auto_create_context, cfg.auto_consolidate) == (False, False)
    assert cfg.max_posterior_contexts == 8
    assert cfg.max_candidates == 200
    assert cfg.max_neighbors == 32
    assert cfg.max_diffusion_steps == 2
    assert cfg.max_active_state_nodes == 10_000
    assert cfg.max_context_proposals_per_session == 100


def test_context_memory_config_loads_independent_gates(tmp_path):
    config_dir = tmp_path / ".engram"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        "[context_memory]\n"
        "enabled = true\nshadow = true\ninfluence_recall = false\n"
        "auto_create_context = false\nauto_consolidate = false\n"
        "max_candidates = 17\n"
    )
    cfg = load_config(tmp_path).context_memory
    assert cfg.enabled is True
    assert cfg.shadow is True
    assert cfg.influence_recall is False
    assert cfg.max_candidates == 17
```

- [ ] **Step 2: Verify the configuration tests fail**

Run: `.venv/bin/python -m pytest tests/test_config.py -q`

Expected: FAIL because `ContextMemoryConfig` and `EngramConfig.context_memory` do not exist.

- [ ] **Step 3: Add the exact configuration surface**

Add this dataclass, wire it into `EngramConfig`, `_DEFAULT_TOML`, and `load_config`:

```python
@dataclass
class ContextMemoryConfig:
    enabled: bool = False
    shadow: bool = True
    influence_recall: bool = False
    auto_create_context: bool = False
    auto_consolidate: bool = False
    db_path: str = ""
    max_posterior_contexts: int = 8
    max_candidates: int = 200
    max_neighbors: int = 32
    max_diffusion_steps: int = 2
    max_active_state_nodes: int = 10_000
    max_context_proposals_per_session: int = 100
    inference_wall_time_ms: int = 100
    self_transition_bias: float = 4.0
    unknown_prior: float = 0.10
    novelty_threshold: float = 0.55
    context_creation_confirmations: int = 3
    smoothing_alpha: float = 0.5
```

The TOML section must contain every field with the same values. Reject
non-positive budgets, probabilities outside `[0, 1]`, and
`influence_recall = true` when `shadow = true` in `ContextMemoryConfig.__post_init__`.

- [ ] **Step 4: Write failing store tests**

Create `tests/test_context_memory.py` with temporary-store fixtures and these
representative tests:

```python
def test_events_are_append_only_and_idempotent(store):
    event = ContextEvent(
        id="e1", kind="query", observed_at="2026-08-07T00:00:00+00:00",
        session_id="s1", payload={"query": "ambiguous cue"},
    )
    assert store.append_event(event) == "e1"
    assert store.append_event(event) == "e1"
    with pytest.raises(ValueError, match="event id collision"):
        store.append_event(replace(event, payload={"query": "different"}))
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute("UPDATE ctx_events SET kind='used' WHERE id='e1'")


def test_state_node_references_identity_without_copying_content(store):
    store.create_context(ContextRecord("c1", {"goal:debug": 1.0}, (1.0, 0.0)))
    store.append_event(ContextEvent(
        "e-bind", "used", "2026-08-07T00:00:00+00:00", "s1", {"memory_id": "memory-7"},
    ))
    node = store.bind_memory("c1", "memory-7", evidence_weight=0.75, event_id="e-bind")
    assert node == StateNode("c1", "memory-7", pytest.approx(0.75))
    columns = {r[1] for r in store.connection.execute("PRAGMA table_info(ctx_state_nodes)")}
    assert "content" not in columns


def test_failed_transition_write_is_atomic(store):
    store.create_context(ContextRecord("c1", {}, (1.0, 0.0)))
    with pytest.raises(ValueError, match="non-negative"):
        store.observe_context_transition("c1", "c1", -1.0, "e-bad")
    assert store.context_transition_counts() == {}
    assert store.connection.execute("SELECT COUNT(*) FROM ctx_events").fetchone()[0] == 0
```

Also test foreign keys, canonical JSON, dimension consistency for embeddings,
non-negative fractional counts, activation checkpoint replacement, immutable
shadow-recall inputs, nested transaction rollback, and close behavior.

- [ ] **Step 5: Verify store tests fail**

Run: `.venv/bin/python -m pytest tests/test_context_memory.py -q`

Expected: FAIL because `context_memory.py` does not exist.

- [ ] **Step 6: Implement the store and schema**

Define immutable dataclasses:

```python
@dataclass(frozen=True)
class ContextEvent:
    id: str
    kind: str
    observed_at: str
    session_id: str
    payload: Mapping[str, object]


@dataclass(frozen=True)
class ContextRecord:
    id: str
    features: Mapping[str, float]
    centroid: tuple[float, ...]
    created_event_id: str | None = None


@dataclass(frozen=True)
class StateNode:
    context_id: str
    memory_id: str
    evidence_weight: float
```

Create these tables exactly, with foreign keys enabled and immutable-table
`BEFORE UPDATE`/`BEFORE DELETE` triggers:

```sql
CREATE TABLE ctx_model_versions (
  id TEXT PRIMARY KEY, config_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE ctx_events (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, observed_at TEXT NOT NULL,
  session_id TEXT NOT NULL, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL
);
CREATE TABLE ctx_contexts (
  id TEXT PRIMARY KEY, features_json TEXT NOT NULL, centroid_json TEXT NOT NULL,
  dimension INTEGER NOT NULL CHECK (dimension >= 0),
  created_event_id TEXT REFERENCES ctx_events(id), created_at TEXT NOT NULL
);
CREATE TABLE ctx_state_nodes (
  context_id TEXT NOT NULL REFERENCES ctx_contexts(id), memory_id TEXT NOT NULL,
  created_event_id TEXT REFERENCES ctx_events(id),
  PRIMARY KEY (context_id, memory_id)
);
CREATE TABLE ctx_state_binding_observations (
  event_id TEXT NOT NULL REFERENCES ctx_events(id),
  context_id TEXT NOT NULL REFERENCES ctx_contexts(id), memory_id TEXT NOT NULL,
  evidence_weight REAL NOT NULL CHECK (evidence_weight BETWEEN 0 AND 1),
  signal TEXT NOT NULL,
  PRIMARY KEY (event_id, context_id, memory_id)
);
CREATE TABLE ctx_context_transition_observations (
  event_id TEXT NOT NULL REFERENCES ctx_events(id),
  from_context TEXT NOT NULL REFERENCES ctx_contexts(id),
  to_context TEXT NOT NULL REFERENCES ctx_contexts(id),
  responsibility REAL NOT NULL CHECK (responsibility >= 0),
  PRIMARY KEY (event_id, from_context, to_context)
);
CREATE TABLE ctx_memory_transition_observations (
  event_id TEXT NOT NULL REFERENCES ctx_events(id),
  from_context TEXT NOT NULL REFERENCES ctx_contexts(id),
  to_context TEXT NOT NULL REFERENCES ctx_contexts(id),
  from_memory TEXT NOT NULL, to_memory TEXT NOT NULL,
  responsibility REAL NOT NULL CHECK (responsibility >= 0), signal TEXT NOT NULL,
  PRIMARY KEY (event_id, from_context, to_context, from_memory, to_memory)
);
CREATE TABLE ctx_activation_checkpoints (
  session_id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES ctx_events(id),
  posterior_json TEXT NOT NULL, activation_json TEXT NOT NULL, model_version TEXT NOT NULL
);
CREATE TABLE ctx_shadow_recalls (
  recall_id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES ctx_events(id),
  model_version TEXT NOT NULL, baseline_json TEXT NOT NULL, shadow_json TEXT NOT NULL,
  posterior_before_json TEXT NOT NULL, posterior_after_json TEXT NOT NULL,
  trace_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE ctx_context_proposals (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL, first_event_id TEXT NOT NULL,
  last_event_id TEXT NOT NULL, fingerprint_hash TEXT NOT NULL,
  confirmations INTEGER NOT NULL CHECK (confirmations > 0),
  unknown_mass REAL NOT NULL CHECK (unknown_mass BETWEEN 0 AND 1),
  status TEXT NOT NULL CHECK (status IN ('observed','eligible','accepted','rejected'))
);
```

`ctx_events`, `ctx_model_versions`, state binding observations, context
transition observations, memory transition observations, and shadow recalls are
immutable. Contexts and state-node identities are insert-only. `bind_memory`
uses `INSERT OR IGNORE` for the identity and appends a binding observation;
`state_weight` returns the maximum observed evidence weight. Checkpoints and
proposals are derived materializations and may be replaced transactionally.
Canonical JSON is
`json.dumps(value, sort_keys=True, separators=(",", ":"))`; event ID reuse is
allowed only when its stored payload hash matches.

- [ ] **Step 7: Run focused verification**

Run:

```bash
.venv/bin/python -m pytest tests/test_config.py tests/test_context_memory.py -q
.venv/bin/python -m compileall -q context_memory.py config.py
```

Expected: all selected tests pass and compileall exits 0.

- [ ] **Step 8: Register the module and commit**

Add `context_memory` to `tool.setuptools.py-modules`, then commit:

```bash
git add config.py context_memory.py pyproject.toml tests/test_config.py tests/test_context_memory.py
git commit -m "feat: add contextual memory event store"
```

---

### Task 2: Sticky Context Inference and Novelty Proposals

**Files:**
- Create: `context_inference.py`
- Create: `tests/test_context_inference.py`
- Modify: `pyproject.toml:28-76`

**Interfaces:**
- Consumes: `ContextMemoryStore`, `ContextRecord`, `ContextMemoryConfig`
- Produces: `ContextEvidence`, `ContextPosterior`, `ContextProposalDecision`, `ContextFilter.filter`, `ContextFilter.observe_novelty`, `ContextProposalConsolidator.accept`

- [ ] **Step 1: Write failing pure-inference tests**

Create deterministic two-dimensional contexts and assert normalization,
stickiness, anchors, contradiction recovery, top-K truncation, and novelty:

```python
def test_sticky_filter_does_not_flicker_on_one_ambiguous_observation(filter_):
    prior = ContextPosterior({"work": 0.9, "personal": 0.05, "unknown": 0.05})
    evidence = ContextEvidence("e2", (0.70, 0.70), {}, None)
    result = filter_.filter(prior, evidence)
    assert result.probabilities["work"] > result.probabilities["personal"]
    assert sum(result.probabilities.values()) == pytest.approx(1.0)


def test_repeated_contradictory_evidence_recovers_from_prior_lock_in(filter_):
    posterior = ContextPosterior({"work": 0.99, "personal": 0.005, "unknown": 0.005})
    evidence = ContextEvidence("e", (0.0, 1.0), {"goal:rest": 1.0}, None)
    for _ in range(5):
        posterior = filter_.filter(posterior, evidence)
    assert posterior.probabilities["personal"] > posterior.probabilities["work"]


def test_explicit_anchor_is_strong_evidence_not_a_hard_assignment(filter_):
    result = filter_.filter(
        ContextPosterior({"work": 0.5, "personal": 0.4, "unknown": 0.1}),
        ContextEvidence("e", (1.0, 0.0), {}, "personal"),
    )
    assert 0.5 < result.probabilities["personal"] < 1.0


def test_eligible_context_requires_explicit_offline_acceptance(filter_, consolidator):
    decision = observe_three_novel_events(filter_)
    assert decision.eligible is True
    assert filter_.store.get_context(decision.proposal_id) is None
    created = consolidator.accept(decision.proposal_id, context_id="novel-c1")
    assert created.id == "novel-c1"
```

Add proposal tests showing that unknown mass above `0.55` becomes eligible only
after three matching observations, resets on a known-context fit, respects the
100-proposal session cap, and never calls `create_context` when
`auto_create_context` is false.

- [ ] **Step 2: Verify the inference tests fail**

Run: `.venv/bin/python -m pytest tests/test_context_inference.py -q`

Expected: FAIL because the inference module is absent.

- [ ] **Step 3: Implement exact evidence and posterior types**

```python
@dataclass(frozen=True)
class ContextEvidence:
    event_id: str
    embedding: tuple[float, ...]
    features: Mapping[str, float]
    explicit_anchor: str | None = None


@dataclass(frozen=True)
class ContextPosterior:
    probabilities: Mapping[str, float]

    def normalized(self) -> "ContextPosterior":
        values = {key: float(value) for key, value in self.probabilities.items()}
        if any(not math.isfinite(value) or value < 0.0 for value in values.values()):
            raise ValueError("posterior values must be finite and non-negative")
        total = sum(values.values())
        if total <= 0.0:
            raise ValueError("posterior must contain positive mass")
        return ContextPosterior({key: value / total for key, value in sorted(values.items())})


@dataclass(frozen=True)
class ContextProposalDecision:
    proposal_id: str | None
    confirmations: int
    eligible: bool
    unknown_mass: float
```

`normalized` rejects negative/non-finite values and zero total mass. Sort ties
by context ID before truncation so replay is deterministic.

- [ ] **Step 4: Implement the filter without learned neural components**

Use these exact likelihood components:

```python
embedding_fit = max(0.0, cosine(evidence.embedding, context.centroid))
feature_fit = weighted_jaccard(evidence.features, context.features)
likelihood = max(1e-6, 0.7 * embedding_fit + 0.3 * feature_fit)
if evidence.explicit_anchor == context.id:
    likelihood *= 4.0
```

Build `A(c | c')` from fractional counts plus `smoothing_alpha`; add
`self_transition_bias` to each diagonal count. Assign `unknown_prior` before
normalization and set unknown likelihood to
`max(1e-6, 1.0 - max_known_likelihood)`. Apply Bayes filtering, retain the top
8 known contexts, move discarded mass into `unknown`, and normalize again.

Proposal fingerprints hash rounded embedding components (two decimal places)
and sorted positive feature names. `observe_novelty` increments a proposal only
when unknown mass is at least `novelty_threshold`; otherwise it returns a
non-eligible decision and does not mutate proposals.

`ContextProposalConsolidator.accept(proposal_id, *, context_id)` is the only V1
path from proposal to context. It rejects non-eligible proposals. An explicit
offline call is authorized regardless of `auto_create_context`; the automatic
scheduler may call it only when that gate is true. It reads the proposal's
immutable events, computes their mean embedding and weighted feature mean,
calls `create_context` in one transaction, and marks the proposal accepted. It
is never called by `ContextFilter.filter`, `observe_novelty`, or server recall.

- [ ] **Step 5: Verify inference behavior and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_context_inference.py tests/test_context_memory.py -q
.venv/bin/python -m compileall -q context_inference.py
```

Expected: all selected tests pass.

Add `context_inference` to `pyproject.toml`, then:

```bash
git add context_inference.py pyproject.toml tests/test_context_inference.py
git commit -m "feat: infer sticky latent contexts"
```

---

### Task 3: Sparse Joint Context-Memory Activation

**Files:**
- Create: `context_recall.py`
- Create: `tests/test_context_recall.py`
- Modify: `pyproject.toml:28-77`

**Interfaces:**
- Consumes: `ContextMemoryStore`, `ContextFilter`, `ContextEvidence`, `ContextPosterior`, `ContextMemoryConfig`
- Produces: `RecallCandidate`, `ActivationTrace`, `ShadowRecallResult`, `ContextualRecallEngine.rank`, `ContextualRecallEngine.confirm`

Use these exact method signatures:

```python
def rank(
    self,
    recall_id: str,
    candidates: Sequence[RecallCandidate],
    evidence: ContextEvidence,
    previous_memory_id: str | None,
    neighbor_ids: Sequence[str] = (),
) -> ShadowRecallResult:

def confirm(
    self,
    result: ShadowRecallResult,
    signal: FeedbackSignal,
    memory_ids: Sequence[str],
) -> None:
```

- [ ] **Step 1: Write failing ranking tests**

```python
def test_same_ambiguous_candidates_reverse_order_by_context(engine, seeded_store):
    candidates = [RecallCandidate("bike-road", 0.7), RecallCandidate("bike-debug", 0.7)]
    work = engine.rank("r-work", candidates, evidence_for("work"), None)
    personal = engine.rank("r-personal", candidates, evidence_for("personal"), None)
    assert work.memory_scores["bike-debug"] > work.memory_scores["bike-road"]
    assert personal.memory_scores["bike-road"] > personal.memory_scores["bike-debug"]


def test_surfacing_does_not_learn_a_transition(engine, seeded_store):
    result = engine.rank("r1", [RecallCandidate("m1", 0.9)], evidence_for("work"), None)
    engine.confirm(result, signal="surfaced", memory_ids=("m1",))
    assert seeded_store.memory_transition_counts() == {}


def test_explicit_use_updates_with_fractional_context_responsibility(engine, seeded_store):
    result = engine.rank(
        "r1", [RecallCandidate("m1", 0.9), RecallCandidate("m2", 0.8)],
        evidence_for("ambiguous"), previous_memory_id="m0",
    )
    engine.confirm(result, signal="used", memory_ids=("m1",))
    counts = seeded_store.memory_transition_counts()
    assert sum(counts.values()) == pytest.approx(1.0)
    assert all(key[-1] == "m1" for key in counts)
```

Also test negative signals, no learning for unlisted candidates, inter-context
transport, deterministic ties, row normalization, maximum candidates, maximum
state nodes, maximum diffusion steps, wall-time termination, and exact baseline
order preservation outside the returned shadow object.

- [ ] **Step 2: Verify ranking tests fail**

Run: `.venv/bin/python -m pytest tests/test_context_recall.py -q`

Expected: FAIL because `context_recall.py` is absent.

- [ ] **Step 3: Define exact public types**

```python
FeedbackSignal = Literal[
    "surfaced", "attended", "used", "followed",
    "corrected", "rejected", "not_applicable", "explicit_anchor",
]


@dataclass(frozen=True)
class RecallCandidate:
    memory_id: str
    baseline_score: float


@dataclass(frozen=True)
class ActivationTrace:
    event_id: str
    posterior_before: Mapping[str, float]
    posterior_after: Mapping[str, float]
    seed_mass: Mapping[str, float]
    transition_mass: Mapping[str, float]
    steps: int
    stop_reason: str


@dataclass(frozen=True)
class ShadowRecallResult:
    recall_id: str
    baseline_ids: tuple[str, ...]
    shadow_ids: tuple[str, ...]
    memory_scores: Mapping[str, float]
    posterior: ContextPosterior
    activation: Mapping[tuple[str, str], float]
    trace: ActivationTrace
```

- [ ] **Step 4: Implement bounded joint activation**

Validate and sort candidates by `(-baseline_score, memory_id)`, then truncate at
200. For each candidate/context pair, compute:

```python
membership = store.state_weight(context_id, candidate.memory_id) or 0.05
seed[(context_id, candidate.memory_id)] = (
    posterior[context_id] * candidate.baseline_score * membership
)
```

Normalize seed mass. For each of at most two steps, visit only stored outgoing
transitions whose destination is a retained candidate or one of at most 32
explicitly supplied neighbor IDs. Accumulate:

```python
flow[(to_context, to_memory)] += (
    mass * context_kernel[from_context, to_context]
    * memory_kernel[from_context, to_context, from_memory, to_memory]
)
```

Mix `0.65 * seed + 0.35 * normalized_flow`, prune to the 10,000 highest masses
with lexical tie-breaking, and stop on step limit, wall time, empty flow, or
L1 change below `1e-6`. Marginalize over contexts for final memory scores.
The special `unknown` context uses membership `1.0`, contributes baseline seed
mass, and has no persisted state node or learned outgoing memory transition. If
the posterior contains only `unknown`, the shadow order therefore equals the
deterministic baseline order.

`confirm` writes an immutable feedback event. `surfaced` writes the event only;
`attended` binds state nodes at weight `0.1` but writes no transition;
`used|followed` bind at `1.0` and add positive fractional transition counts;
`corrected|rejected|not_applicable` append signal-tagged counter-observations
that the normalized kernel subtracts from positive count with a floor of zero.
Reject feedback IDs not present in `baseline_ids`.

- [ ] **Step 5: Verify the activation engine and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_context_recall.py tests/test_context_inference.py tests/test_context_memory.py -q
.venv/bin/python -m compileall -q context_recall.py
```

Expected: all selected tests pass.

Add `context_recall` to `pyproject.toml`, then:

```bash
git add context_recall.py pyproject.toml tests/test_context_recall.py
git commit -m "feat: rank sparse joint context memory states"
```

---

### Task 4: Reversible-Context Simulator and Ablation Harness

**Files:**
- Create: `context_eval.py`
- Create: `tests/test_context_eval.py`
- Modify: `pyproject.toml:28-78`

**Interfaces:**
- Consumes: `ContextualRecallEngine`, `ContextMemoryStore`, `ContextFilter`
- Produces: `Scenario`, `Trial`, `EvaluationReport`, `run_reversible_context_experiment`, CLI `context_eval.py reversible`

- [ ] **Step 1: Write failing metric and fixture tests**

```python
def test_rank_biased_overlap_identity_and_disjoint():
    assert rank_biased_overlap(["a", "b"], ["a", "b"], p=0.9) == pytest.approx(1.0)
    assert rank_biased_overlap(["a", "b"], ["x", "y"], p=0.9) == pytest.approx(0.0)


def test_scenario_generator_is_seeded_and_domain_neutral():
    left = generate_scenarios(seed=808, families=4, trials_per_family=12)
    right = generate_scenarios(seed=808, families=4, trials_per_family=12)
    assert left == right
    assert {s.family for s in left} == {"conversation", "coding", "reading", "planning"}


def test_full_model_restores_context_a_trajectory(tmp_path):
    report = run_reversible_context_experiment(tmp_path, seed=808, bootstrap_samples=200)
    assert report.metrics["return_a_rbo"].estimate >= 0.80
    assert report.metrics["context_macro_f1"].estimate >= 0.80
```

Also test multiclass Brier score, nDCG@10, empirical-frequency predictor,
bootstrap interval reproducibility, holdout separation, and JSON serialization.

- [ ] **Step 2: Verify evaluation tests fail**

Run: `.venv/bin/python -m pytest tests/test_context_eval.py -q`

Expected: FAIL because `context_eval.py` is absent.

- [ ] **Step 3: Implement fixed scenario generation and metrics**

Define:

```python
@dataclass(frozen=True)
class Trial:
    context_id: str
    query_embedding: tuple[float, ...]
    features: Mapping[str, float]
    candidates: tuple[RecallCandidate, ...]
    relevant_ids: frozenset[str]
    phase: Literal["A", "B", "return_A"]


@dataclass(frozen=True)
class Scenario:
    id: str
    family: str
    trials: tuple[Trial, ...]


@dataclass(frozen=True)
class MetricEstimate:
    estimate: float
    ci_low: float
    ci_high: float


@dataclass(frozen=True)
class EvaluationReport:
    seed: int
    train_ids: tuple[str, ...]
    holdout_ids: tuple[str, ...]
    metrics: Mapping[str, MetricEstimate]
    ablations: Mapping[str, Mapping[str, float]]
    passed: bool
```

Generate 48 scenarios: 12 per family, alternating A/B/return-A phases. Use 32
for training/calibration and seal 16 as holdout before any model execution.
Each trial has two equal-baseline ambiguous memories plus one unambiguous
control. Vocabulary changes by family; latent structure and random distributions
do not.

Implement exactly four runners: `static`, `context_score`,
`posterior_without_reinstatement`, and `joint`. Bootstrap scenario IDs with
replacement using `random.Random(seed + 1)`.

- [ ] **Step 4: Encode acceptance gates without tuning hooks**

`EvaluationReport.passed` is true only when all design gates hold:

```python
passed = (
    macro_f1.ci_low >= 0.80
    and brier.ci_high < frequency_brier.ci_low
    and joint_vs_static_ndcg.ci_low >= 0.15
    and joint_vs_posterior_ndcg.ci_low >= 0.05
    and return_a_rbo.ci_low >= 0.80
    and direct_recall_regression.ci_high <= 0.05
    and context_false_positive_rate.ci_high <= 0.05
    and resource_violation_count == 0
)
```

The CLI writes canonical JSON and exits 0 on pass, 1 on measured failure, and 2
on invalid input:

```bash
.venv/bin/python context_eval.py reversible --seed 808 --output /tmp/context-a.json
```

- [ ] **Step 5: Verify simulator and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_context_eval.py -q
.venv/bin/python context_eval.py reversible --seed 808 --output /tmp/context-a.json
```

Expected: tests pass; CLI writes a report. Record its actual pass/fail outcome
without changing thresholds.

Add `context_eval` to `pyproject.toml`, then:

```bash
git add context_eval.py pyproject.toml tests/test_context_eval.py
git commit -m "test: add reversible context experiment"
```

---

### Task 5: Historical Replay and Fail-Open Server Shadowing

**Files:**
- Create: `context_replay.py`
- Create: `tests/test_context_replay.py`
- Modify: `server.py:140-390,869-1450`
- Modify: `tests/test_server.py:35-110,130-940`
- Modify: `pyproject.toml:28-79`

**Interfaces:**
- Consumes: the Task 1–3 public interfaces and existing `memory_log`
- Produces: `replay_memory_log`, server `_context_store`, `_context_engine`, optional `recall(..., context_anchor=None)`, optional `log_outcome(..., used_memory_ids=None)`

- [ ] **Step 1: Write failing historical replay tests**

```python
def test_replay_treats_unscoped_used_recall_as_attended_only(graph_store, context_store):
    add_recall(graph_store, "r1", ["m1", "m2"], outcome="used")
    report = replay_memory_log(graph_store.conn, context_store, model_version="test-v1")
    assert report.attended == 2
    assert report.used == 0
    assert context_store.memory_transition_counts() == {}


def test_replay_uses_explicit_used_memory_ids(graph_store, context_store):
    add_recall(
        graph_store, "r2", ["m1", "m2"], outcome="used",
        context_extra={"used_memory_ids": ["m2"]},
    )
    report = replay_memory_log(graph_store.conn, context_store, model_version="test-v1")
    assert report.used == 1
```

Test chronological ordering, idempotent replay, malformed JSON isolation,
read-only opening of the source database, and source/target path refusal.

- [ ] **Step 2: Write failing server shadow tests**

Add a temporary `ContextMemoryStore` and deterministic `ContextualRecallEngine`
to `server_env`, then test:

```python
def test_shadow_failure_does_not_change_recall_response(server_env, monkeypatch):
    baseline = normalized(server.recall("Storage persistence", uninvited=0))
    monkeypatch.setattr(server, "_context_engine", ExplodingEngine())
    shadow_failure = normalized(server.recall("Storage persistence", uninvited=0))
    assert shadow_failure == baseline


def test_log_outcome_requires_explicit_memory_ids_for_positive_learning(server_env):
    recalled = server.recall("Storage persistence", uninvited=0)
    server.log_outcome(recalled["recall_id"], used=True)
    assert server._context_store.memory_transition_counts() == {}


def test_log_outcome_rejects_ids_not_returned(server_env):
    recalled = server.recall("Storage persistence", uninvited=0)
    result = server.log_outcome(
        recalled["recall_id"], used=True, used_memory_ids=["not-returned"],
    )
    assert "error" in result
```

Also prove `context_anchor` is logged as evidence, defaults preserve the current
MCP signature behavior, shadow results are absent from the user response, and
`influence_recall=true` cannot operate while `shadow=true`.

- [ ] **Step 3: Verify replay and server tests fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_context_replay.py -q
.venv/bin/python -m pytest tests/test_server.py -q -k 'shadow or context_anchor or explicit_memory_ids'
```

Expected: FAIL because replay and server shadow integration are absent.

- [ ] **Step 4: Implement conservative replay**

Define `ReplayReport(rows, queries, surfaced, attended, used, rejected, errors)`.
Open source SQLite with URI `mode=ro`, read `memory_log` ordered by
`timestamp, id`, and derive deterministic event IDs as
`sha256(f"memory-log:{row_id}:{signal}")`. A recall outcome beginning with
`used` and lacking `context.used_memory_ids` emits `attended`; it never emits
`used`. Explicit IDs must be a subset of `target_ids`. Replay writes only the
separate context database and is idempotent by event ID.

CLI:

```bash
.venv/bin/python context_replay.py --source /path/to/graph.db \
  --target /tmp/context_memory.db --model-version context-v1 --json
```

Resolve both paths and refuse equality. Exit 2 for malformed rows or invalid
paths; report errors without partially applying the bad row.

- [ ] **Step 5: Implement fail-open server shadowing**

Add `_context_store = None` and `_context_engine = None`. During `_init`, only
when `config.context_memory.enabled` is true, construct the store beside the
active instance database and the filter/engine inside one `try`; log and leave
both globals `None` on failure. Register a close callback.

Extend signatures compatibly:

```python
def recall(
    query: str,
    layer: str | None = None,
    max_results: int = 20,
    uninvited: int = 3,
    lane: str | None = None,
    context_anchor: str | None = None,
) -> dict:


def log_outcome(
    recall_id: str,
    used: bool,
    note: str | None = None,
    used_memory_ids: list[str] | None = None,
) -> dict:
```

After final lane filtering and before response construction, pass only returned
`results` as candidates to `rank`; never include unreturned pre-filter IDs.
Store the shadow result, catch `Exception`, and leave `results` untouched. Put
`used_memory_ids` in the existing memory-log context only after validating it
as a subset of the logged `target_ids`. Without explicit IDs, call `confirm`
with `attended`; with IDs call it with `used` or `rejected` according to
`used`. The legacy category application path may continue unchanged, but the
new transition store must obey explicit attribution.

- [ ] **Step 6: Run focused and full verification**

Run:

```bash
.venv/bin/python -m pytest tests/test_context_replay.py tests/test_server.py tests/test_context_recall.py -q
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q context_memory.py context_inference.py context_recall.py context_eval.py context_replay.py server.py
```

Expected: full suite passes. If the pre-existing dirty files produce unrelated
failures, record exact failing tests and verify the feature suite independently;
do not edit those files outside this task's named server overlap.

- [ ] **Step 7: Register the module and commit**

Add `context_replay` to `pyproject.toml`, then:

```bash
git add context_replay.py pyproject.toml server.py tests/test_context_replay.py tests/test_server.py
git commit -m "feat: observe contextual recall in shadow mode"
```

---

### Task 6: Read-Only Diagnostics and Experiment A Gate

**Files:**
- Modify: `context_memory.py`
- Modify: `context_eval.py`
- Create: `tests/test_context_diagnostics.py`
- Modify: `server.py:1680-1745`
- Modify: `tests/test_server.py`
- Create: `docs/contextual-memory-experiment-a.md`
- Create: `docs/contextual-memory-experiment-a.json`

**Interfaces:**
- Consumes: persisted contexts, events, shadow recalls, and Experiment A report
- Produces: `ContextMemoryStore.status`, MCP tool `context_memory_status`, committed Experiment A report

- [ ] **Step 1: Write failing status tests**

```python
def test_status_is_count_only_and_does_not_expose_payloads(store):
    status = store.status()
    assert set(status) == {
        "model_versions", "events", "contexts", "state_nodes",
        "state_binding_observations",
        "context_transition_observations", "memory_transition_observations",
        "shadow_recalls", "eligible_context_proposals",
    }
    assert all(isinstance(value, int) for value in status.values())


def test_server_status_is_read_only(server_env):
    before = server._context_store.status()
    result = server.context_memory_status()
    after = server._context_store.status()
    assert result == before
    assert after == before
```

- [ ] **Step 2: Verify status tests fail**

Run: `.venv/bin/python -m pytest tests/test_context_diagnostics.py -q`

Expected: FAIL because the APIs are absent.

- [ ] **Step 3: Implement count-only diagnostics**

`ContextMemoryStore.status` executes fixed `COUNT(*)` statements, never accepts
SQL fragments, and reports eligible proposals with a `WHERE status='eligible'`
count. `context_memory_status` returns `{"enabled": False}` when the observer is
unavailable; otherwise it returns the counts plus `enabled`, `shadow`, and
`influence_recall`. It must not return queries, features, embeddings, memory
IDs, event payloads, or file paths.

- [ ] **Step 4: Run the frozen Experiment A and record the result**

Run exactly:

```bash
.venv/bin/python context_eval.py reversible \
  --seed 808 --bootstrap-samples 2000 \
  --output docs/contextual-memory-experiment-a.json
```

Create `docs/contextual-memory-experiment-a.md` containing the command, commit
hash, model version, every estimate and confidence interval, each gate's
pass/fail state, and the overall exit code. Do not change model constants or
thresholds after reading the holdout.

- [ ] **Step 5: Run final core verification**

Run:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q .
uv lock --check
git diff --check
```

Expected: tests pass, compileall and lock check exit 0, and no whitespace errors.

- [ ] **Step 6: Commit the gate report**

```bash
git add context_memory.py context_eval.py server.py tests/test_context_diagnostics.py tests/test_server.py docs/contextual-memory-experiment-a.json docs/contextual-memory-experiment-a.md
git commit -m "test: gate contextual recall experiment"
```

Stop after this commit if Experiment A fails. Preserve the failed report and
return to design review; do not proceed to the durable-skill plan.
