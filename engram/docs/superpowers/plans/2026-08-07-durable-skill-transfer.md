# Durable Skill Transfer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add replayable durable skill cores, context transport, fast local residuals, and guarded consolidation, then prove that dormant skills adapt faster than cold start without corrupting their source context.

**Architecture:** Extend the isolated contextual-memory database after the Contextual Stochastic Recall plan passes Experiment A. Skills are versioned stochastic options over abstract phases; a context transport selects a compatible core, while a fast residual learns local transition corrections. Only offline consolidation can create a new core version, and replayable 2-cell witnesses compare source and adapted paths.

**Tech Stack:** Python 3.12+, stdlib dataclasses/SQLite/JSON/hashlib/math/random, existing NumPy/SciPy transitively available through project dependencies, pytest; no new runtime dependency.

## Global Constraints

- Do not begin until `docs/contextual-memory-experiment-a.json` exists and reports `passed: true`.
- Execute in the same isolated worktree used for the contextual-recall plan.
- Use the existing `context_memory.db`; never add skill columns or tables to `graph.db`, `categories.db`, or `instinct_transitions.db`.
- A skill core is a temporally extended stochastic option with phases, initiation conditions, and termination conditions; a single edge is not a skill.
- Long inactivity changes accessibility only; it cannot mutate or weaken a durable core.
- Online outcomes update context-local residuals according to context posterior responsibility.
- Core versions are append-only and change only through offline consolidation.
- Consolidation requires separated successful evidence, multi-context support or explicit correction, held-out loss improvement, total-variation core drift at most `0.02`, and complete lineage.
- Interpret category dimensions 0–2 only. A 2-cell must compare replayable composed paths; no opaque higher-cell generation is authorized.
- Keep `auto_consolidate = false` and live behavior unchanged throughout V1.
- Use TDD and commit only files named by each task.

---

### Task 1: Versioned Skill Core, Transport, and Residual Store

**Files:**
- Create: `skill_memory.py`
- Create: `tests/test_skill_memory.py`
- Modify: `context_memory.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `ContextMemoryStore.connection`, canonical JSON helpers, context IDs
- Produces: `SkillPhase`, `SkillCore`, `SkillTransport`, `SkillResidual`, `SkillMemoryStore`
- Produces methods used later: `create_core`, `get_core`, `latest_core`, `create_transport`, `get_transport`, `put_residual`, `get_residual`, `append_outcome`, `list_outcomes`, `set_accessibility`, `status`

- [ ] **Step 1: Write failing immutable-store tests**

```python
def test_skill_core_is_a_normalized_temporally_extended_option(skill_store):
    core = make_core(
        skill_id="ride-bike", version=1,
        phases=("balance", "propel", "steer"),
        kernel={
            "balance": {"balance": 0.2, "propel": 0.8},
            "propel": {"propel": 0.3, "steer": 0.7},
            "steer": {"steer": 1.0},
        },
    )
    skill_store.create_core(core)
    assert skill_store.latest_core("ride-bike") == core
    with pytest.raises(sqlite3.IntegrityError):
        skill_store.connection.execute(
            "UPDATE ctx_skill_cores SET version=2 WHERE skill_id='ride-bike'"
        )


def test_inactivity_changes_accessibility_not_core(skill_store):
    core = make_core(skill_id="ride-bike", version=1)
    skill_store.create_core(core)
    before = skill_store.get_core("ride-bike", 1)
    skill_store.set_accessibility("ride-bike", "new-body", 0.1, "e-decay")
    assert skill_store.get_core("ride-bike", 1) == before
    assert skill_store.get_residual("ride-bike", "new-body").accessibility == 0.1


def test_transport_and_residual_retain_core_lineage(skill_store):
    skill_store.create_core(make_core(skill_id="ride-bike", version=1))
    skill_store.create_transport(make_transport("ride-bike", 1, "old", "new"))
    skill_store.put_residual(make_residual("ride-bike", 1, "new"), event_id="e1")
    residual = skill_store.get_residual("ride-bike", "new")
    assert residual.core_version == 1
```

Also test phase uniqueness, at least two phases, stochastic rows, valid
initiation/termination phases, transport source/target context foreign keys,
residual phase compatibility, append-only outcomes, version monotonicity,
canonical serialization, and transaction rollback.

- [ ] **Step 2: Verify store tests fail**

Run: `.venv/bin/python -m pytest tests/test_skill_memory.py -q`

Expected: FAIL because `skill_memory.py` is absent.

- [ ] **Step 3: Define exact immutable types**

```python
@dataclass(frozen=True)
class SkillPhase:
    id: str
    features: Mapping[str, float]


@dataclass(frozen=True)
class SkillCore:
    skill_id: str
    version: int
    phases: tuple[SkillPhase, ...]
    kernel: Mapping[str, Mapping[str, float]]
    initiation: frozenset[str]
    termination: frozenset[str]
    evidence_event_ids: tuple[str, ...]
    parent_version: int | None


@dataclass(frozen=True)
class SkillTransport:
    id: str
    skill_id: str
    core_version: int
    source_context_id: str
    target_context_id: str
    phase_map: Mapping[str, str]
    confidence: float
    evidence_event_ids: tuple[str, ...]


@dataclass(frozen=True)
class SkillResidual:
    skill_id: str
    core_version: int
    context_id: str
    deltas: Mapping[str, Mapping[str, float]]
    accessibility: float
    updated_event_id: str
```

- [ ] **Step 4: Add the exact skill schema to store initialization**

```sql
CREATE TABLE ctx_skill_cores (
  skill_id TEXT NOT NULL, version INTEGER NOT NULL CHECK (version > 0),
  phases_json TEXT NOT NULL, kernel_json TEXT NOT NULL,
  initiation_json TEXT NOT NULL, termination_json TEXT NOT NULL,
  evidence_json TEXT NOT NULL, parent_version INTEGER,
  created_at TEXT NOT NULL, PRIMARY KEY (skill_id, version),
  FOREIGN KEY (skill_id, parent_version) REFERENCES ctx_skill_cores(skill_id, version)
);
CREATE TABLE ctx_skill_transports (
  id TEXT PRIMARY KEY, skill_id TEXT NOT NULL, core_version INTEGER NOT NULL,
  source_context_id TEXT NOT NULL REFERENCES ctx_contexts(id),
  target_context_id TEXT NOT NULL REFERENCES ctx_contexts(id),
  phase_map_json TEXT NOT NULL, confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  evidence_json TEXT NOT NULL, created_at TEXT NOT NULL,
  FOREIGN KEY (skill_id, core_version) REFERENCES ctx_skill_cores(skill_id, version)
);
CREATE TABLE ctx_skill_residual_events (
  event_id TEXT PRIMARY KEY REFERENCES ctx_events(id), skill_id TEXT NOT NULL,
  core_version INTEGER NOT NULL, context_id TEXT NOT NULL REFERENCES ctx_contexts(id),
  deltas_json TEXT NOT NULL, accessibility REAL NOT NULL CHECK (accessibility BETWEEN 0 AND 1),
  FOREIGN KEY (skill_id, core_version) REFERENCES ctx_skill_cores(skill_id, version)
);
CREATE TABLE ctx_skill_outcomes (
  event_id TEXT PRIMARY KEY REFERENCES ctx_events(id), skill_id TEXT NOT NULL,
  core_version INTEGER NOT NULL, context_id TEXT NOT NULL REFERENCES ctx_contexts(id),
  posterior_weight REAL NOT NULL CHECK (posterior_weight BETWEEN 0 AND 1),
  phase_from TEXT NOT NULL, phase_to TEXT NOT NULL,
  reward REAL NOT NULL CHECK (reward BETWEEN -1 AND 1), success INTEGER NOT NULL CHECK (success IN (0,1)),
  observed_at TEXT NOT NULL,
  FOREIGN KEY (skill_id, core_version) REFERENCES ctx_skill_cores(skill_id, version)
);
CREATE TABLE ctx_skill_accessibility (
  skill_id TEXT NOT NULL, context_id TEXT NOT NULL REFERENCES ctx_contexts(id),
  accessibility REAL NOT NULL CHECK (accessibility BETWEEN 0 AND 1),
  event_id TEXT NOT NULL REFERENCES ctx_events(id),
  PRIMARY KEY (skill_id, context_id)
);
```

Core, transport, residual-event, and outcome rows are immutable. Accessibility
is a replaceable materialization. Each residual event stores the complete
cumulative residual snapshot after that observation; `get_residual` returns the
latest snapshot in event-observation order and applies the latest accessibility
row. `put_residual` and `set_accessibility` append their referenced
`ctx_events` rows atomically when those event IDs do not already exist.

- [ ] **Step 5: Implement validation and persistence**

Reject a core unless it has at least two unique phases, every kernel source and
destination is a declared phase, every row is finite/non-negative and sums to
one within `1e-9`, and initiation/termination are non-empty phase subsets.
Require version 1 to have no parent and version N to name existing parent N-1.
Require transport maps to cover every source phase exactly once. Residual
deltas may be signed but each realized row must remain non-negative after
application and normalization. Verify every core and transport evidence event
ID against `ctx_events` before insert.

- [ ] **Step 6: Verify and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_skill_memory.py tests/test_context_memory.py -q
.venv/bin/python -m compileall -q skill_memory.py context_memory.py
```

Expected: all selected tests pass.

Add `skill_memory` to `pyproject.toml`, then:

```bash
git add context_memory.py skill_memory.py pyproject.toml tests/test_skill_memory.py
git commit -m "feat: store durable skills and local residuals"
```

---

### Task 2: Context Transport and Fast Residual Adaptation

**Files:**
- Create: `skill_adaptation.py`
- Create: `tests/test_skill_adaptation.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `SkillMemoryStore`, `SkillCore`, `SkillTransport`, `SkillResidual`, `ContextPosterior`
- Produces: `SkillRealization`, `SkillOutcome`, `SkillAdapter.realize`, `SkillAdapter.observe`

- [ ] **Step 1: Write failing realization and learning tests**

```python
def test_realization_starts_from_transported_core_not_zero(adapter, seeded_skills):
    posterior = ContextPosterior({"new-body": 1.0})
    realized = adapter.realize("ride-bike", posterior)
    assert realized.kernel["balance"]["propel"] > 0.0
    assert realized.sources == (("old-body", "new-body", pytest.approx(0.8)),)


def test_success_updates_residuals_in_proportion_to_context_responsibility(adapter, seeded_skills):
    posterior = ContextPosterior({"new-body": 0.8, "old-body": 0.2})
    before_old = adapter.store.get_residual("ride-bike", "old-body")
    adapter.observe(SkillOutcome(
        event_id="o1", skill_id="ride-bike", core_version=1,
        posterior=posterior, phase_from="balance", phase_to="propel",
        reward=1.0, success=True, observed_at="2026-08-07T00:00:00+00:00",
    ))
    new_delta = adapter.store.get_residual("ride-bike", "new-body").deltas
    old_delta = adapter.store.get_residual("ride-bike", "old-body").deltas
    assert new_delta["balance"]["propel"] > old_delta["balance"]["propel"]
    assert old_delta != before_old.deltas


def test_accessibility_decay_does_not_change_realized_structure(adapter, seeded_skills):
    before = adapter.realize("ride-bike", ContextPosterior({"new-body": 1.0}))
    adapter.decay_accessibility("ride-bike", "new-body", rate=0.1, event_id="d1")
    after = adapter.realize("ride-bike", ContextPosterior({"new-body": 1.0}))
    assert after.kernel == before.kernel
    assert after.accessibility < before.accessibility
```

Also test failure updates, posterior weights summing below one, context without a
transport, incompatible phase map rejection, deterministic source choice,
residual clipping, and zero mutation of the core.

- [ ] **Step 2: Verify adaptation tests fail**

Run: `.venv/bin/python -m pytest tests/test_skill_adaptation.py -q`

Expected: FAIL because `skill_adaptation.py` is absent.

- [ ] **Step 3: Define runtime types**

```python
@dataclass(frozen=True)
class SkillRealization:
    skill_id: str
    core_version: int
    context_weights: Mapping[str, float]
    kernel: Mapping[str, Mapping[str, float]]
    accessibility: float
    sources: tuple[tuple[str, str, float], ...]


@dataclass(frozen=True)
class SkillOutcome:
    event_id: str
    skill_id: str
    core_version: int
    posterior: ContextPosterior
    phase_from: str
    phase_to: str
    reward: float
    success: bool
    observed_at: str
```

- [ ] **Step 4: Implement transport and realization**

For each posterior context, use its existing residual if present. Otherwise
select the highest-confidence transport targeting that context, breaking ties
by transport ID. The transport maps target-observation phase labels back to
canonical core phase IDs; the realized kernel remains keyed by canonical phases.
Add the residual delta, clip negatives to zero, and normalize each row. Mix
realized kernels by posterior context weight and normalize again. Accessibility
is the posterior-weighted mean of context accessibility; it scales selection
confidence but not transition probabilities. A context with neither a residual
nor a transport is excluded; if no posterior context is realizable, raise
`LookupError("no transport or residual for active contexts")` rather than
inventing transfer.

- [ ] **Step 5: Implement fast residual observations**

Use learning rate `0.25`. For each context with posterior mass `q > 0`, let
`current_probability` be the realized probability of the observed transition
and append:

```python
target = 1.0 if outcome.success else 0.0
delta = 0.25 * q * (target - current_probability)
```

Add `delta` to the observed `phase_from -> phase_to` entry and subtract it
uniformly from the other destinations in that row before clipping and
renormalizing. Append one outcome per responsible context with its posterior
weight. `decay_accessibility` multiplies accessibility by the supplied rate and
rejects rates outside `[0, 1]`; it never appends a residual delta or core row.

- [ ] **Step 6: Verify and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_skill_adaptation.py tests/test_skill_memory.py -q
.venv/bin/python -m compileall -q skill_adaptation.py
```

Expected: all selected tests pass.

Add `skill_adaptation` to `pyproject.toml`, then:

```bash
git add skill_adaptation.py pyproject.toml tests/test_skill_adaptation.py
git commit -m "feat: adapt durable skills with context residuals"
```

---

### Task 3: Guarded Core Consolidation

**Files:**
- Create: `skill_consolidation.py`
- Create: `tests/test_skill_consolidation.py`
- Modify: `context_memory.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `SkillMemoryStore`, `SkillAdapter`, stored outcomes and residuals
- Produces: `ConsolidationPolicy`, `ConsolidationDecision`, `SkillConsolidator.evaluate`, `SkillConsolidator.commit`

- [ ] **Step 1: Write failing gate tests**

```python
@pytest.mark.parametrize("case,reason", [
    ("one_off", "insufficient separated evidence"),
    ("one_context", "insufficient context support"),
    ("unsuccessful", "insufficient successful evidence"),
    ("no_holdout_gain", "held-out loss did not improve"),
    ("too_much_drift", "core drift exceeds 0.02"),
])
def test_consolidation_rejects_unsafe_promotions(consolidator, cases, case, reason):
    decision = consolidator.evaluate(cases[case])
    assert decision.eligible is False
    assert reason in decision.reasons


def test_commit_creates_versioned_core_with_lineage(consolidator, eligible_case):
    decision = consolidator.evaluate(eligible_case)
    assert decision.eligible is True
    new_core = consolidator.commit(decision)
    assert new_core.version == 2
    assert new_core.parent_version == 1
    assert set(new_core.evidence_event_ids) == set(decision.evidence_event_ids)
```

Test that evaluate is read-only, commit refuses stale decisions, repeated commit
is idempotent, `auto_consolidate=false` prevents scheduled commit, explicit
correction may satisfy multi-context support but not integrity/held-out/drift
gates, and a failed transaction leaves version 1 current.

- [ ] **Step 2: Verify consolidation tests fail**

Run: `.venv/bin/python -m pytest tests/test_skill_consolidation.py -q`

Expected: FAIL because the module is absent.

- [ ] **Step 3: Define exact policy and decision types**

```python
@dataclass(frozen=True)
class ConsolidationPolicy:
    min_separated_observations: int = 6
    min_contexts: int = 2
    min_success_rate: float = 0.70
    min_holdout_loss_improvement: float = 0.01
    max_core_tv_drift: float = 0.02
    separation_seconds: int = 3_600


@dataclass(frozen=True)
class ConsolidationDecision:
    id: str
    skill_id: str
    parent_version: int
    eligible: bool
    proposed_kernel: Mapping[str, Mapping[str, float]]
    evidence_event_ids: tuple[str, ...]
    training_event_ids: tuple[str, ...]
    holdout_event_ids: tuple[str, ...]
    old_holdout_loss: float
    new_holdout_loss: float
    core_tv_drift: float
    reasons: tuple[str, ...]
    input_hash: str
```

- [ ] **Step 4: Implement deterministic evaluation**

Sort outcomes by `(observed_at, event_id)`. Greedily select observations at least
3,600 seconds apart. Use every fifth selected event as holdout and the rest as
training. Require six selected observations, two contexts unless an explicit
correction event is present, and weighted training success rate at least 0.70.

Propose each core row as `0.9 * old_row + 0.1 * weighted_mean_residual_row`, then
normalize. Evaluate negative log likelihood of observed holdout transitions
with floor probability `1e-9`. Compute total-variation drift as the maximum over
rows of `0.5 * sum(abs(old_p - new_p))`. Derive `input_hash` from canonical
parent core, policy, and evidence IDs.

- [ ] **Step 5: Implement atomic commit records**

Add an immutable `ctx_consolidations` table:

```sql
CREATE TABLE ctx_consolidations (
  id TEXT PRIMARY KEY, skill_id TEXT NOT NULL, parent_version INTEGER NOT NULL,
  new_version INTEGER, eligible INTEGER NOT NULL CHECK (eligible IN (0,1)),
  input_hash TEXT NOT NULL, decision_json TEXT NOT NULL, committed_at TEXT,
  FOREIGN KEY (skill_id, parent_version) REFERENCES ctx_skill_cores(skill_id, version)
);
```

`commit` rereads current core and evidence, recomputes `input_hash`, rejects a
stale decision, and inserts the decision record and new core in one transaction.
If configuration does not have `auto_consolidate`, the scheduler records an
eligible decision but does not call `commit`; direct test/API calls may commit.

- [ ] **Step 6: Verify and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_skill_consolidation.py tests/test_skill_adaptation.py tests/test_skill_memory.py -q
.venv/bin/python -m compileall -q skill_consolidation.py
```

Expected: all selected tests pass.

Add `skill_consolidation` to `pyproject.toml`, then:

```bash
git add context_memory.py skill_consolidation.py pyproject.toml tests/test_skill_consolidation.py
git commit -m "feat: gate durable skill consolidation"
```

---

### Task 4: Markov Composition and Replayable 2-Cell Witnesses

**Files:**
- Create: `category_semantics.py`
- Create: `tests/test_category_semantics.py`
- Modify: `context_memory.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: normalized kernels, skill transports, outcomes, context event IDs
- Produces: `StochasticKernel`, `Path`, `PathWitness`, `identity_kernel`, `compose_kernels`, `compare_paths`, `WitnessStore`

- [ ] **Step 1: Write failing categorical-law tests**

```python
def assert_kernel_close(actual, expected, *, abs=1e-12):
    assert actual.sources == expected.sources
    assert actual.targets == expected.targets
    for actual_row, expected_row in zip(actual.matrix, expected.matrix, strict=True):
        assert actual_row == pytest.approx(expected_row, abs=abs)


def test_identity_and_associativity_for_finite_kernels():
    f, g, h = finite_test_kernels()
    assert_kernel_close(compose_kernels(identity_kernel(f.sources), f), f)
    assert_kernel_close(compose_kernels(f, identity_kernel(f.targets)), f)
    left = compose_kernels(compose_kernels(f, g), h)
    right = compose_kernels(f, compose_kernels(g, h))
    assert_kernel_close(left, right)


def test_witness_compares_replayable_equal_endpoint_paths(witness_store):
    source, adapted = comparable_paths()
    witness = compare_paths(source, adapted, evidence_event_ids=("e1", "e2"))
    witness_store.append(witness)
    replayed = witness_store.replay(witness.id)
    assert replayed.source_path.source_endpoint == replayed.adapted_path.source_endpoint
    assert replayed.source_path.target_endpoint == replayed.adapted_path.target_endpoint
    assert replayed.evidence_event_ids == ("e1", "e2")


def test_witness_rejects_mismatched_endpoints():
    with pytest.raises(ValueError, match="same endpoints"):
        compare_paths(*mismatched_paths(), evidence_event_ids=("e1",))
```

Also test stochastic validation, dimension mismatch, lexical state ordering,
empty evidence rejection, deterministic witness hashes, conflicting paths, and
SQL immutability.

- [ ] **Step 2: Verify categorical tests fail**

Run: `.venv/bin/python -m pytest tests/test_category_semantics.py -q`

Expected: FAIL because `category_semantics.py` is absent.

- [ ] **Step 3: Implement finite stochastic kernels and composition**

```python
@dataclass(frozen=True)
class StochasticKernel:
    id: str
    sources: tuple[str, ...]
    targets: tuple[str, ...]
    matrix: tuple[tuple[float, ...], ...]


@dataclass(frozen=True)
class Path:
    id: str
    kernels: tuple[StochasticKernel, ...]
    source_endpoint: str
    target_endpoint: str


@dataclass(frozen=True)
class PathWitness:
    id: str
    source_path: Path
    adapted_path: Path
    relation: Literal["equivalent", "compatible", "conflicting"]
    max_total_variation: float
    evidence_event_ids: tuple[str, ...]
```

Validate shapes and stochastic rows at construction. `compose_kernels(f, g)`
requires `f.targets == g.sources` and computes row-vector composition `f @ g`
with deterministic tuple output. `compare_paths` composes both paths, requires
equal source/target endpoints, computes maximum row total variation, and assigns
`equivalent <= 0.02`, `compatible <= 0.20`, otherwise `conflicting`.

- [ ] **Step 4: Persist only replayable 2-cell witnesses**

Add:

```sql
CREATE TABLE ctx_path_witnesses (
  id TEXT PRIMARY KEY, relation TEXT NOT NULL CHECK (relation IN ('equivalent','compatible','conflicting')),
  source_path_json TEXT NOT NULL, adapted_path_json TEXT NOT NULL,
  max_total_variation REAL NOT NULL CHECK (max_total_variation BETWEEN 0 AND 1),
  evidence_json TEXT NOT NULL, created_at TEXT NOT NULL
);
```

`WitnessStore.append` verifies that every evidence event exists, recomputes the
witness ID from canonical content, and inserts immutably. `replay` reconstructs
both paths, recomposes them, and rejects stored data whose relation or distance
does not match. No schema or API for dimensions above 2 is added.

- [ ] **Step 5: Verify and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_category_semantics.py -q
.venv/bin/python -m compileall -q category_semantics.py
```

Expected: all selected tests pass.

Add `category_semantics` to `pyproject.toml`, then:

```bash
git add category_semantics.py context_memory.py pyproject.toml tests/test_category_semantics.py
git commit -m "feat: compose stochastic paths with transfer witnesses"
```

---

### Task 5: Dormant-Skill Simulator and Frozen Ablations

**Files:**
- Create: `skill_eval.py`
- Create: `tests/test_skill_eval.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `SkillAdapter`, `SkillConsolidator`, `SkillMemoryStore`, path witnesses
- Produces: `SkillScenario`, `SkillEvaluationReport`, `run_dormant_skill_experiment`, CLI `skill_eval.py dormant`

- [ ] **Step 1: Write failing metric and experiment tests**

```python
def test_time_to_competence_requires_sustained_window():
    rewards = [0.2, 0.8, 0.2, 0.8, 0.8, 0.8]
    assert time_to_competence(rewards, threshold=0.75, window=3) == 6


def test_dormant_skill_experiment_is_reproducible(tmp_path):
    left = run_dormant_skill_experiment(tmp_path / "a", seed=809, bootstrap_samples=200)
    right = run_dormant_skill_experiment(tmp_path / "b", seed=809, bootstrap_samples=200)
    assert left.to_dict() == right.to_dict()


def test_core_plus_residual_retains_source_context(tmp_path):
    report = run_dormant_skill_experiment(tmp_path, seed=809, bootstrap_samples=200)
    assert report.metrics["source_context_regression"].estimate <= 0.05
    assert report.metrics["preconsolidation_core_tv"].estimate <= 0.02
```

Also test bootstrap interval determinism, accessibility decay, second
reactivation, rejected one-off promotion, unrelated-skill controls, and canonical
JSON serialization.

- [ ] **Step 2: Verify evaluation tests fail**

Run: `.venv/bin/python -m pytest tests/test_skill_eval.py -q`

Expected: FAIL because `skill_eval.py` is absent.

- [ ] **Step 3: Implement fixed skill scenarios and four ablations**

Define 48 seeded scenarios across four vocabularies. Each has a three-to-six
phase source skill, two source contexts, 1,000 inactivity ticks that reduce
accessibility to `0.1`, a target context with a bounded transition perturbation,
an unrelated skill, and two reactivation blocks. Split 32 training/calibration
and 16 sealed holdout scenarios before execution.

Implement exactly:

1. `cold_start`: uniform phase rows learned only in the target context;
2. `global_fast_slow`: one global kernel with learning rates 0.25 and 0.02;
3. `local_no_transport`: an independent uniform target residual;
4. `core_transport_residual`: the Task 2 adapter with the fixed transport.

Use normalized per-step reward `1.0` for the scenario's correct next phase and
`0.0` otherwise. Competence is rolling mean `>= 0.80` for 10 steps. Compute
source regression against the pre-target source reward and unrelated regression
against the unrelated skill's pre-target reward.

- [ ] **Step 4: Encode Experiment B gates**

```python
passed = (
    first_block_vs_cold.ci_low >= 0.20
    and time_to_competence_ratio.ci_high <= 0.60
    and source_context_regression.ci_high <= 0.05
    and preconsolidation_core_tv.ci_high <= 0.02
    and unrelated_skill_regression.ci_high <= 0.02
    and second_reactivation_vs_cold.ci_low > 0.0
    and unsafe_promotion_acceptance_count == 0
)
```

The CLI writes canonical JSON and exits 0 on pass, 1 on measured failure, and 2
on invalid input:

```bash
.venv/bin/python skill_eval.py dormant --seed 809 --output /tmp/context-b.json
```

- [ ] **Step 5: Verify simulator and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_skill_eval.py -q
.venv/bin/python skill_eval.py dormant --seed 809 --output /tmp/context-b.json
```

Expected: tests pass; CLI writes a report. Preserve the actual experimental
outcome without changing thresholds.

Add `skill_eval` to `pyproject.toml`, then:

```bash
git add skill_eval.py pyproject.toml tests/test_skill_eval.py
git commit -m "test: add dormant skill experiment"
```

---

### Task 6: Shadow Outcome Ingestion, Diagnostics, and Experiment B Gate

**Files:**
- Create: `skill_observer.py`
- Create: `tests/test_skill_observer.py`
- Modify: `server.py:140-390,1400-1580,1680-1745`
- Modify: `tests/test_server.py`
- Modify: `context_memory.py`
- Modify: `pyproject.toml`
- Create: `docs/contextual-memory-experiment-b.md`
- Create: `docs/contextual-memory-experiment-b.json`

**Interfaces:**
- Consumes: explicit `used_memory_ids`, context posterior checkpoints, skill cores created through internal APIs
- Produces: `SkillTrajectoryObserver.observe_recall`, count-only skill status, committed Experiment B report

- [ ] **Step 1: Write failing observer tests**

```python
def test_observer_ignores_recall_without_explicit_memory_attribution(observer):
    observer.observe_recall("r1", used=True, used_memory_ids=None)
    assert observer.store.list_outcomes("workflow-skill") == []


def test_observer_maps_confirmed_sequence_to_existing_skill_phases(observer):
    observer.observe_recall("r1", used=True, used_memory_ids=["phase-balance"])
    observer.observe_recall("r2", used=True, used_memory_ids=["phase-propel"])
    outcomes = observer.store.list_outcomes("workflow-skill")
    assert [(o.phase_from, o.phase_to) for o in outcomes] == [("balance", "propel")]


def test_observer_never_creates_or_consolidates_a_core(observer):
    for index in range(20):
        observer.observe_recall(f"r{index}", used=True, used_memory_ids=["phase-balance"])
    assert observer.store.latest_core("unregistered") is None
    assert observer.consolidator.commit_calls == 0
```

Also test session boundaries, posterior responsibility, negative feedback,
unknown IDs, fail-open server behavior, and count-only diagnostics.

- [ ] **Step 2: Verify observer tests fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_skill_observer.py -q
.venv/bin/python -m pytest tests/test_server.py -q -k skill
```

Expected: FAIL because observer integration is absent.

- [ ] **Step 3: Implement explicit, registered-skill observation**

`SkillTrajectoryObserver` receives a mapping from physical memory ID to
`(skill_id, core_version, phase_id)`. It maintains the last confirmed phase per
`(session_id, skill_id)` only. A transition is recorded when consecutive
explicitly attributed IDs map to the same registered skill and core version.
The context posterior comes from the matching shadow recall checkpoint.
Unregistered IDs, recall-level `used` without IDs, and `surfaced` events do not
create skill rows. The observer has no method that creates cores or calls
`SkillConsolidator.commit`.

- [ ] **Step 4: Wire observer after explicit context confirmation**

Construct `_skill_store`, `_skill_adapter`, and `_skill_observer` only when the
context observer initialized successfully. In `log_outcome`, invoke the skill
observer after context `confirm` and inside an independent `try/except`; never
change the tool response on observer failure. Add count-only fields to
`context_memory_status`: `skill_cores`, `skill_transports`, `skill_residual_events`,
`skill_outcomes`, `consolidation_decisions`, and `path_witnesses`. Do not return
phase maps, kernels, evidence, memory IDs, or contexts.

- [ ] **Step 5: Run frozen Experiment B and document it**

Run exactly:

```bash
.venv/bin/python skill_eval.py dormant \
  --seed 809 --bootstrap-samples 2000 \
  --output docs/contextual-memory-experiment-b.json
```

Create `docs/contextual-memory-experiment-b.md` containing the command, commit
hash, model version, every estimate and confidence interval, each gate's
pass/fail state, and the overall exit code. Do not alter constants or thresholds
after reading the sealed holdout.

- [ ] **Step 6: Run final verification**

Run:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q .
uv lock --check
git diff --check
```

Expected: tests pass, compileall and lock check exit 0, and no whitespace errors.
If Experiment B fails, the implementation remains an inert research artifact;
do not enable ranking influence, residual learning in production, or core
consolidation.

- [ ] **Step 7: Register and commit**

Add `skill_observer` to `pyproject.toml`, then:

```bash
git add skill_observer.py context_memory.py pyproject.toml server.py tests/test_skill_observer.py tests/test_server.py docs/contextual-memory-experiment-b.json docs/contextual-memory-experiment-b.md
git commit -m "test: gate dormant skill transfer experiment"
```
