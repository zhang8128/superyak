# Contextual Stochastic Memory — Design Specification

**Date:** 2026-08-07

**Status:** Approved 2026-08-07; implementation remains experiment-gated

**Scope:** First falsifiable, shadow-mode implementation in `engram`

## Revision Note

This document supersedes the pre-research design committed at `a1e161c`.
That design treated context as an input to a bounded category compiler. The
research review exposed a missing feedback loop: context must change recall,
and recalled or successfully used memories must in turn update the inferred
context. A context-weighted static graph cannot provide that behavior.

The revised design is a **contextual-inference sparse multilayer Markov
memory**. Category theory specifies composition and transport laws; it is not
an excuse to store arbitrary higher cells. V1 interprets only dimensions 0–2.

## Purpose

Make memory expression depend on a continuously inferred context without
duplicating memories or corrupting durable knowledge. The same cue may follow
different recall trajectories in different situations, and returning to a
prior situation should restore its trajectory without relearning it.

Skills must retain durable structure through long inactivity while adapting
quickly to a changed body, tool, environment, or goal. A changed agent is not a
cold-start agent.

V1 must prove two behaviors before influencing live recall:

1. **Reversible contextual recall:** switching context changes an ambiguous
   recall trajectory; switching back restores the earlier trajectory.
2. **Dormant skill reactivation:** an old skill transfers into a changed
   context, adapts faster than cold start, and does not corrupt the old skill.

## Research Basis

The design combines mechanisms that are separately well supported:

- Context Maintenance and Retrieval (CMR): memory search is driven by an
  internally maintained context, and a retrieved item reinstates context that
  biases the next retrieval.
- Contextual Inference (COIN): latent-context inference jointly controls memory
  creation, updating, and expression; apparent learning can be a change in
  which preserved memory is expressed.
- Sparse memory and multilayer networks: distinguish a physical node from the
  context-specific state nodes through which flow visits it.
- Fast/slow adaptation and complementary learning systems: fast local learning
  coexists with slow, well-retained structure.
- Context-dependent gating: sparse activation protects unrelated knowledge
  from interference.
- Successor features and temporally extended options: reusable dynamics and
  skill structure should be separated from current valuation, while recognizing
  that changed dynamics require adaptation rather than zero-shot reuse.
- Markov categories and categorical Bayes filtering: stochastic kernels and
  their composition have a legitimate categorical semantics without requiring
  an unbounded higher-category runtime.

Primary references:

- Polyn, Norman, and Kahana, *A Context Maintenance and Retrieval Model*:
  https://pubmed.ncbi.nlm.nih.gov/19159151/
- Heald, Lengyel, and Wolpert, *Contextual inference underlies the learning of
  sensorimotor repertoires*: https://www.nature.com/articles/s41586-021-04129-3
- Edler, Bohlin, and Rosvall, *Mapping higher-order network flows*:
  https://arxiv.org/abs/1706.04792
- Smith, Ghazizadeh, and Shadmehr, *Interacting Adaptive Processes with
  Different Timescales*: https://doi.org/10.1371/journal.pbio.0040179
- Fritz, *A synthetic approach to Markov kernels*:
  https://arxiv.org/abs/1908.07021
- Fritz et al., *Hidden Markov Models and the Bayes Filter in Categorical
  Probability*: https://arxiv.org/abs/2401.14669
- Barreto et al., *Successor Features for Transfer in Reinforcement Learning*:
  https://arxiv.org/abs/1606.05312

## Existing System and Baseline

Engram currently has three relevant but disconnected mechanisms:

- `server.recall` generates candidates with vector/FTS search and scores most
  memories with static similarity and recency. Dream and session state can bias
  the query, but no persistent posterior over latent contexts drives the search.
- `categories.py` stores nominal higher cells. `compose` merely sets the result
  level to `max(input levels) + 1`; it does not implement categorical
  composition, coherence laws, or stochastic transport.
- `transitions.py` stores context-isolated weighted edges. It is a useful
  Markov-chain primitive, but currently serves instinct sequences and treats
  context as an exact string rather than an uncertain inferred state.

The existing category, transition, unified-graph, sheaf, persistence, and
recall systems remain untouched during shadow evaluation. The new model is an
overlay and uses their identifiers; it does not become another source of truth
for memory content.

## Design Decision

Implement a **sparse joint context-memory state model** in an isolated database.

- A physical memory has one durable identity in the existing store.
- A context-state node `(context_id, memory_id)` exists only after evidence that
  the memory participates in that context.
- A sticky hidden-state filter maintains a probability distribution over
  contexts rather than selecting a single label.
- Context-conditioned stochastic kernels model likely memory transitions.
- The active state is a sparse joint belief over context-state nodes.
- Recall evidence and confirmed memory use update the context posterior.
- Skills have a durable core and fast context-local residuals.
- Slow consolidation, not online recall, may promote repeated residual structure
  into a durable core.
- All behavior remains shadow-only until preregistered acceptance gates pass.

Do not implement a full hierarchical Dirichlet process in V1. Use a finite,
online set of context prototypes with explicit novelty and persistence gates.
The nonparametric model is a research reference, not required machinery.

## Conceptual Model

### Physical nodes and state nodes

Let `m` identify an existing episode, semantic, instinct, category cell, or
skill. Let `c` identify an inferred context.

```text
physical memory m
    ├── state node (c_work, m)
    ├── state node (c_personal, m)
    └── state node (c_research, m)
```

State nodes contain activation and learned transition statistics, not copied
memory content. Deleting a derived state node never deletes the physical
memory. One context may contain several overlapping subcontexts, and one memory
may participate in several contexts.

### Context posterior

At observation `t`, the model receives generic evidence `x_t`:

- query or situation embedding;
- active goal and entities;
- participant, tool, source, and lane features;
- temporal continuity;
- optional explicit context anchors;
- prior recalls that were actually used, followed, corrected, or rejected.

For known contexts, filtering computes:

```text
q_prior(c) = sum_c' q_(t-1)(c') * A(c | c')
q_t(c)     ∝ q_prior(c) * likelihood(x_t | c)
```

`A` is a learned context transition matrix with a configurable self-transition
bias. Explicit anchors contribute likelihood evidence; they do not bypass the
posterior. The posterior is normalized, calibrated, and retained as a sparse
top-K distribution plus an `unknown` mass.

Context must not flicker on ambiguous observations. A new context may be
proposed only when:

1. the `unknown` posterior mass exceeds the novelty threshold;
2. poor fit to every known context persists for multiple observations;
3. the observations are not adequately explained by a short transition;
4. the per-session and global context budgets permit it.

A proposal is shadow evidence. Consolidation creates the context; recall never
creates one synchronously.

### Joint activation and recall

Let `b_t(c,m)` be active probability mass on state node `(c,m)`. Its prediction
uses both context transitions and memory transitions:

```text
b_pred(c,m) = sum_(c',m') b_(t-1)(c',m')
              * A(c | c') * K_(c',c)(m | m')
```

Candidate evidence then filters and normalizes that prediction:

```text
b_t(c,m) ∝ b_pred(c,m) * E(x_t, c, m)
R_t(m)    = sum_c b_t(c,m)
```

`E` combines the existing candidate score with context compatibility and
explicit evidence. `K_(c,c)` is the within-context memory kernel;
`K_(c',c)` for `c' != c` is an inter-context transport kernel. The
implementation uses sparse top-K beams and bounded diffusion, never a dense
Cartesian product of all contexts and memories.

Baseline vector/FTS retrieval remains candidate generation. The shadow model
reranks only those candidates plus a bounded set of graph neighbors. It records
what it would have returned but cannot change the live response in V1.

### Bidirectional context reinstatement

Surfacing a memory is not proof that it belongs in the current context; using
it may be. Context observations distinguish:

- `surfaced`: no positive learning signal;
- `attended`: weak evidence;
- `used` or `followed`: positive evidence;
- `corrected`, `rejected`, or `not_applicable`: negative evidence;
- `explicit_anchor`: strong but scoped context evidence.

After a confirmed event, the associated memory features update the next context
posterior. This closes the CMR-style loop:

```text
context -> recall -> confirmed memory -> updated context -> next recall
```

Learning from `surfaced` results would amplify the model's own guesses and is
forbidden.

### Soft transition learning

Context and memory transitions update with fractional responsibility rather
than hard assignments:

```text
count_A(c',c)       += q_(t-1)(c') * q_t(c)
count_K(c,m',m)     += q_t(c) * responsibility(m',m)
```

Rows are converted to stochastic kernels with smoothing. Negative feedback
reduces the responsible edge through an append-only counter-observation; it
does not erase history. Decay applies to accessibility statistics, not durable
memory content or proven skill competence.

## Durable Skills

A skill is a temporally extended option or attractor, not a one-step recall
edge. Its context-specific realization is:

```text
skill(s,c) = transport(core_s, c) + residual_(s,c)
```

The three pieces have different roles:

1. **Durable core `core_s`:** reusable topology, ordered phases, invariants,
   termination conditions, and evidence-backed competence. It has a low learning
   rate and high retention.
2. **Transport map:** maps the durable structure into the features and controls
   available in a related context. It records its source, target, confidence,
   and evidence.
3. **Fast residual `residual_(s,c)`:** local corrections for the current body,
   tool, environment, or goal. It learns quickly and its accessibility may
   decay quickly.

Long inactivity lowers activation and confidence that a context is current. It
does not decay the durable core merely because the skill was not observed.

Online success updates residuals according to context responsibility. A slow
consolidation may alter the core only when a pattern:

- recurs across separated observations;
- succeeds rather than merely fires;
- persists across more than one context, or has explicit correction evidence;
- improves predictive loss on held-out history;
- stays within a bounded core-drift budget;
- preserves lineage to the previous core version.

Failure in a new context updates its residual or transport map first. It cannot
immediately overwrite the durable skill.

## Categorical Semantics

The categorical layer describes the stochastic system; it is not a parallel
ontology database.

- **0-cells:** state spaces such as contexts, physical memories, skills, and
  observations.
- **1-cells:** stochastic kernels for context transition, recall, feedback,
  skill execution, and transport.
- **Composition:** ordinary kernel composition (matrix multiplication or its
  sparse equivalent), with identity kernels and normalized rows.
- **2-cells:** explicit, evidence-linked witnesses that two composed paths are
  equivalent, compatible, conflicting, or successful transfers.

For example, a transfer witness may compare:

```text
old context -> old skill -> outcome
old context -> new context -> adapted skill -> outcome
```

A 2-cell is retained only if the comparison and evidence can be replayed. V1
does not create or interpret dimensions above 2. If later experiments reveal a
behavior that requires higher coherence data, the disk format may be extended
then. The system does not claim to implement an infinity-category.

Conceptually, contexts form a base graph, each context has a sparse memory
fiber, and transport connects fibers. Operationally, this is stored as a sparse
multilayer graph over `(context_id, memory_id)` state nodes.

## Storage and Replay

Use a separate `context_memory.db`. Never modify `categories.db`, the instinct
transition database, or physical memory rows during shadow evaluation.

Suggested tables:

- `ctx_model_versions`
- `ctx_events`
- `ctx_contexts`
- `ctx_context_observations`
- `ctx_context_transition_counts`
- `ctx_state_nodes`
- `ctx_memory_transition_counts`
- `ctx_activation_events`
- `ctx_context_proposals`
- `ctx_skill_cores`
- `ctx_skill_residuals`
- `ctx_transport_maps`
- `ctx_consolidations`
- `ctx_path_witnesses`

Raw observations, feedback, model versions, consolidation decisions, and core
versions are append-only. Counts, normalized kernels, posterior checkpoints,
and indexes are rebuildable materializations. Every shadow result records:

- model and valuation version;
- input event IDs;
- context posterior before and after filtering;
- candidate and state-node contributions;
- diffusion budget and stopping reason;
- the live baseline order and shadow order.

Replaying the same canonical event sequence with the same model version must
produce the same contexts, kernels, posterior checkpoints, and rankings.

## Bounds and Safety Invariants

Initial limits are calibration hypotheses and live in configuration:

- at most 8 posterior contexts plus `unknown` per observation;
- at most 200 baseline candidates;
- at most 32 graph neighbors expanded per candidate;
- at most 2 diffusion steps;
- at most 10,000 active state nodes in one inference;
- at most 100 context proposals retained per session;
- no synchronous context creation or core consolidation;
- no live recall influence by default;
- no automatic mutation of physical memories.

Required invariants:

- every state node references an existing physical memory and context;
- memory content exists in exactly one authoritative store;
- context posteriors are non-negative and sum to one within tolerance;
- materialized kernel rows are non-negative and sum to one within tolerance;
- an unconfirmed surfaced result cannot strengthen its own path;
- failed shadow inference leaves baseline recall unchanged;
- a failed transaction leaves no partial event or materialization;
- durable skill cores change only through versioned consolidation;
- every residual and transport map retains lineage to its core and evidence;
- accessibility decay cannot delete or weaken durable competence by itself;
- all inference obeys candidate, neighbor, state, step, and wall-time budgets.

## Components

The implementation plan may adjust file boundaries after code-level planning,
but responsibilities must remain separated:

| Component | Responsibility |
|---|---|
| `context_memory.py` | Immutable events, contexts, state nodes, transition statistics, replay |
| `context_inference.py` | Sticky posterior, novelty mass, proposal gating, calibration |
| `context_recall.py` | Candidate seeding, sparse joint activation, bounded diffusion, explanations |
| `skill_memory.py` | Durable options, transports, residuals, promotion and drift checks |
| `category_semantics.py` | Kernel composition and replayable 2-cell/path witnesses |
| `config.py` | Independent observer, influence, learning, and consolidation gates and budgets |
| `server.py` | Fail-open shadow observation and read-only diagnostics |

The existing `categories.py` and `transitions.py` remain legacy inputs until
experiments justify a migration. V1 should reuse concepts, not silently change
their storage semantics.

## Rollout

1. **Deterministic simulator:** no server integration; generated contexts,
   transitions, ambiguous cues, dormant skills, and known ground truth.
2. **Unit and replay tests:** temporary databases, transaction failures,
   deterministic replay, normalization, and budget enforcement.
3. **Historical shadow replay:** derive observations from existing recall and
   feedback logs without writing to the live database.
4. **Live shadow observation:** record baseline and counterfactual rankings;
   return baseline results unchanged.
5. **Read-only A/B evaluation:** compare frozen model variants on a sealed
   holdout set.
6. **Quiet ranking influence:** only after explicit approval and acceptance;
   no structural consolidation.
7. **Residual learning:** enable context-local learning before durable-core
   consolidation.
8. **Core consolidation:** last, bounded, versioned, and rollbackable.

Shipping code does not advance a rollout stage.

## Acceptance Experiments

All thresholds are preregistered hypotheses. Failure revises the model; it does
not permit tuning on the sealed holdout.

Metric definitions are fixed before generating the holdout:

- recall trajectory similarity uses rank-biased overlap with persistence
  `p = 0.90`;
- context calibration uses multiclass Brier score;
- retrieval quality uses nDCG@10 against scenario-specific relevance labels;
- simulator performance is mean normalized reward over the fixed first block;
- time to competence is the first step at which a fixed rolling-success
  threshold is sustained for the configured window;
- core structural divergence is total-variation distance between the old and
  new normalized core transition kernels;
- reported comparisons include bootstrap 95% confidence intervals across
  scenario seeds, and a gate passes only when its interval satisfies the bound.

### Experiment A — reversible contextual recall

Construct at least four domain-neutral scenario families with identical
structure and different vocabulary. Each contains ambiguous cues, contexts A
and B, gradual and abrupt switches, an explicit-anchor subset, and a return to
A after intervening B observations.

Compare:

1. current static similarity/recency recall;
2. static context-weighted scoring;
3. posterior context gating without retrieval reinstatement;
4. the full joint context-memory model.

Gates:

- labeled context macro-F1 at least `0.80` on the holdout;
- posterior Brier score better than the empirical-frequency predictor;
- full-model ambiguous-cue nDCG@10 at least 15% above static recall;
- full-model ambiguous-cue nDCG@10 at least 5% above posterior-only gating,
  demonstrating value from the feedback loop rather than context labels alone;
- after returning to A, rank-biased overlap with A's prior trajectory at least
  `0.80` within three observations;
- unambiguous same-context recall regresses by no more than 5%;
- context creation false-positive rate at most 5%;
- no inference exceeds its configured resource bounds.

### Experiment B — dormant skill reactivation

Use a simulator in which a skill is learned in several source contexts, remains
unused for a long interval, and returns under altered observations and dynamics.
Preserve a cold-start learner and the source-context model as controls.

Compare:

1. cold start;
2. one global fast/slow skill;
3. context-local skills without transport;
4. durable core plus transport and fast residual.

Gates:

- mean first-block normalized reward after reactivation at least 20% above cold
  start;
- time to the predefined competence threshold at most 60% of cold start;
- source-context performance regresses by no more than 5%;
- core total-variation divergence remains at most `0.02` before any
  consolidation;
- unrelated-skill performance regresses by no more than 2%;
- after residual accessibility decay, a second reactivation remains faster than
  cold start;
- promotion is rejected when evidence is one-off, context-specific, or
  unsuccessful.

### Regression evaluation

Run existing Engram tests and a long-term retrieval benchmark such as
LongMemEval for regression coverage. Those benchmarks test extraction,
multi-session reasoning, temporal reasoning, knowledge updates, and abstention;
they do not replace Experiments A and B.

## Failure Modes to Test Explicitly

- **Context flicker:** rapid switching between nearly identical contexts.
- **Context explosion:** every novelty creates a new graph layer.
- **Self-confirmation:** surfaced memories train the path that surfaced them.
- **Core contamination:** a local adaptation overwrites durable skill structure.
- **False transfer:** structural similarity is mistaken for applicable skill.
- **Popularity collapse:** high-degree state nodes dominate every context.
- **Posterior lock-in:** early context guesses prevent contradictory evidence
  from recovering the correct context.
- **History loss:** materialized counts cannot be reconstructed from events.
- **Budget escape:** sparse inference becomes dense under overlap.
- **Mathematical theater:** higher cells exist without an invariant, witness,
  or acceptance test that uses them.

## Out of Scope for V1

- An unbounded or fully formal infinity-category implementation.
- Automatic higher-cell generation above dimension 2.
- A hierarchical Dirichlet process or particle-learning implementation.
- End-to-end learned neural context inference.
- Replacing existing vector/FTS candidate generation.
- Rewriting or copying physical memory content into context layers.
- Allowing model-generated recalls to count as successful use.
- Automatically enabling live ranking influence or core consolidation.
- Claiming biological equivalence; the cited models supply mechanisms and
  falsifiable precedents, not proof that Engram is brain-like.

## Success Criterion

V1 succeeds only if the full joint model beats simpler ablations on reversible
contextual recall and dormant-skill adaptation, preserves baseline direct
recall, remains calibrated and bounded, and can replay every learned transition
and consolidation decision. If a static context scorer performs just as well,
the stochastic multilayer machinery is not justified and should not ship.
