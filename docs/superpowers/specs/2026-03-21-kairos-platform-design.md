# Kairos Platform — Architecture Design Spec

**Date:** 2026-03-21
**Status:** Draft
**Scope:** Clean rewrite of 6 repos (engram, agi, blocks, code, why, claw) into a unified platform

## Context

Six repositories were built organically through exploration over time. They contain
~20K lines of living code and ~16K lines of orphaned code. The core ideas that survived
iteration are good — event-driven composition, fitness-driven evolution, hash-chained
audit, three-layer memory compression, contextual instincts, theory-of-constraints
scheduling. But the repos have unclear boundaries, duplicated infrastructure, and no
shared abstractions.

The system needs to run autonomously — pursuing goals, evaluating results, and adjusting
strategy while the operator works, sleeps, and lives. Full autonomy within the system
boundary; hard wall at anything that touches people who didn't opt in.

## First Principles

**Infinite game cooperation.** In an infinitely repeated game between evolving agents,
cooperation dominates. Deception wastes resources and will eventually be exposed. The
system embeds this: diverging worker instances share messages, not secrets. The mystery
box — just cooperate, it's computationally free.

**6 sigma design thinking.** At scale, reliability is the key factor. A self-replicating
system with 1% failure rate cascades into chaos. Every architectural decision should
reduce variance, not optimize mean performance. This is a design principle, not a
current SLA — the system aims toward 6 sigma by reducing failure modes structurally
(bounded blast radius, graceful degradation, audit everything) rather than claiming
a specific uptime number today.

**The time loop, resolved.** The original framing: "the model resets every call, the
computer persists." This architecture doesn't eliminate the time loop — it makes it
irrelevant. A continuous daemon with layered memory means the system accumulates state
regardless of individual session lifetimes. The time loop becomes a layer boundary
(ephemeral sessions vs persistent infrastructure), not a constraint.

## Architecture

### Four Layers

```
You (Kairos)
  |  interacts when you choose
  v
RUNTIME (daemon, always on, local model brain)
  |  spawns workers in 3 modes
  v
APPLICATIONS (workers — tick, service, or agent session)
  |  all workers use
  v
PLATFORM (shared infrastructure, published contracts)
  +-- BLOCKS (composable event-bus components)
```

### Dependency Direction

- Apps import from Platform. Never Platform from Apps.
- Runtime imports from both (it orchestrates).
- Blocks import from Bus only.
- No circular dependencies.

## Platform Layer

Six modules, each with one clear job.

### Memory

From engram core. Three-layer storage: episodes -> semantics -> instincts.

- Dual-vector contextual instincts (content vector + context vector)
- Instance isolation: each worker gets its own SQLite database file. Crash recovery:
  vec0 health check on startup, WAL checkpoint, rebuild if corrupted.
- Genome layer: universal truths shared across all instances. Append-only. Facts
  become genome-eligible when 2+ workers independently converge on the same semantic.
  Promotion is automatic via compress pipeline. Genome facts never retire.
- Compression pipeline: hierarchical clustering, centroid selection (MMR for diversity),
  LLM-based pragmatic dedup
- Session decay: 0.9x per session, core episodes exempt, pruned below 0.05
- MCP interface preserved for Claude Code sessions

### Bus

Unified from blocks event-bus + engram Signal Bus.

- Typed pub/sub with schema enforcement
- Request/response correlation
- Cross-worker messaging (any worker can publish, any worker can subscribe)
- All messages auto-logged to Ledger
- ScopedBus for composite operations

### Ledger

Consolidated from agi + claw implementations.

- Hash-chained append-only log
- Tamper-evident (hashlib, no external deps)
- Per-worker ledger files + shared system ledger. Workers write to own ledger
  (no contention). Bus messages are duplicated to system ledger by bus layer.
- Queryable: recent-N, by-source, by-type, by-time-range
- Write concurrency: each worker appends to its own file; system ledger uses
  CAS-based atomic appends via bus layer (single writer)

### LLM

New — currently every repo implements this differently.

- Provider abstraction: Ollama, Claude API, Bedrock (future), LM Studio
- Model selection per task (cheap model for dedup, strong model for synthesis)
- Retry with exponential backoff, rate limiting, cost tracking
- Provider swap is a config change, not a code change
- Migration path: direct Anthropic API -> reserved Bedrock instance

### Embeddings

From engram.

- Nomic embed-text-v1.5 (768-dim) via FastEmbed
- Instruction prefixes: `search_document:` (store), `search_query:` (recall),
  `clustering:` (compress)
- Dedup detection: cosine similarity + LLM pragmatic equivalence
- Shared singleton across all modules that need vectors

### Sandbox

From agi arena.

- Path isolation (traversal blocking)
- Capability grants (per-worker permissions)
- Subprocess timeout enforcement
- The hard wall: no capability grant can include external-facing operations

## Runtime Layer

The daemon — new, purpose-built for orchestration.

### Goal Tracker

- Persistent goals with decomposition tree
- Progress tracking, blocker detection
- Goals survive daemon restarts (SQLite)

### Scheduler

- Tick-based with configurable intervals per worker
- Pause/resume per worker
- Backpressure: don't schedule if previous tick still running
- Tick timeout: default 120s per tick, configurable per worker. Exceeded timeout
  triggers force-kill + logged incident. Worker re-enters scheduling queue.
- Resource limits per worker: max memory, max disk writes (configurable)
- Priority queue: when capacity is exhausted, higher-priority tasks preempt lower

### Dispatcher

- Routes tasks to workers
- Selects execution mode:
  - **Tick:** spawn Python process, run one task, collect result, exit
  - **Service:** long-running process listening on bus
  - **Agent session:** Claude API/Bedrock agent loop for complex reasoning
- Worker doesn't choose its mode — dispatcher does, based on task complexity
  and available resources

### Tiered LLM Routing

- Tier 1 (local, free, always on): scheduling, health checks, dedup, classification,
  simple dispatch decisions
- Tier 2 (API, metered, capable): complex reasoning, goal decomposition, synthesis,
  self-reflection
- Tier 3 (interactive, human-initiated): architecture decisions, guidance, anything
  near the hard wall
- Confidence-gated escalation: local model returns structured response with
  confidence signal. Escalation triggers: output contains hedging language,
  max_tokens reached without conclusion, task type is on explicit escalation list,
  or previous attempt at same tier failed.
- Fallback chain: Tier 2 unavailable -> retry with backoff (exponential, max 1hr)
  -> degrade to Tier 1 with reduced scope -> log for human review
- Cost tracking: every LLM call logs (timestamp, provider, model, tier, tokens_in,
  tokens_out, estimated_cost). Queryable for budget monitoring.
- If Tier 3 (human) unavailable: task queues with expiry. Not a blocking condition.

### Capability Gate

- Each worker receives a capability grant from runtime
- Grant specifies: what platform services it can use, what filesystem paths it can
  access, what bus topics it can publish/subscribe
- Enforced structurally (separate databases, scoped bus), not by convention
- Hard wall: no grant can include external-facing operations. Explicitly:
  - No HTTP requests outside localhost (network isolation)
  - No writes outside designated workspace paths (filesystem isolation)
  - No access to credentials, API keys, or secrets of external services
  - No operations that affect people who didn't opt in (patient data, deployments)
  - Grant validation: every grant checked against blocklist at issuance time;
    denial logged to Ledger

### Audit Trail

- Every dispatch, result, and decision logged to Ledger
- Every capability grant logged
- Every escalation logged
- Queryable for governance review

## Applications Layer

Four workers extracted from living code. Each is a self-contained Python package
with its own tests, its own CLAUDE.md, its own engram instance.

### Atlas (from claw)

Research engine. 10-layer biology DAG, paper verification, cross-linking.

- Hot-deploy tick loop (preserved)
- TOC-based node selection: 60% constraint chain, 40% exploration (preserved)
- Impact scoring: downstream fanout x status weight x layer weight (preserved)
- Canonical slug + embedding dedup (preserved)
- Atomic vault writes (preserved)
- Uses: LLM (replaces hardcoded Ollama), Memory (own instance), Bus (publishes
  findings), Ledger

### Arena (from agi)

Goal execution via competing rulesets and fitness-driven evolution.

- Fitness engine: +/-0.05 capping, quarantine at 5 consecutive failures (preserved)
- Diversity pressure: 3-phase cohort selection (preserved)
- Decomposition tree validation: max depth 5, max leaves 50 (preserved)
- Sandboxed tool execution (preserved)
- Uses: LLM, Memory (own instance), Sandbox, Bus (publishes completions), Ledger

### Ratchet (from code)

Block lifecycle management.

- Multi-stage validation: contract, events, isolation via AST (preserved)
- Graph-based tier calculation: effective_tier = min(own, min(deps)) (preserved)
- Session coordination with stale timeout (preserved)
- Event-driven handlers: stats, tiers, capabilities, outcomes (preserved)
- Codex-pair adversarial testing (preserved)
- Uses: Bus (publishes promotions), Ledger, Memory (own instance)
- Runs as: long-running MCP service

### Governor (from why)

Observe and decide.

- Multi-pass observation across all workers (rewritten from bash to Python)
- Priority rule system: 9 decoupled rules (preserved, with state schema)
- Knowledge ratchet: ingest -> verify -> challenge -> promote (preserved)
- Two-gate verification: code execution + adversarial LLM challenge (preserved)
- Uses: Bus (publishes directives, subscribes to everything), Memory (own instance),
  LLM (for research)

## Blocks

17 event-driven components from blocks repo. Each exposes `setup(bus, **kwargs)`.

- Dual-path architecture preserved: direct mode (synchronous) + bus mode (decoupled)
- Block contracts enforced via block.json (events, schemas, tiers)
- Taxonomy.json as capability source of truth
- Tier progression: 0 (unproven) -> 1 (tested) -> 2+ (validated)

Living blocks to migrate: embedder, vector-index, rrf, inference, memory-store,
kahneman, piaget, popper, pearl, kolb, ashby, reasoner, hybrid-search,
semantic-index, ledger.

Drop: kernel/ (empty), host/ (orphaned), task-router (broken, minimal).

## Isolation Model

### Developer Experience

- Per-module CLAUDE.md files: when working on `apps/atlas/`, only atlas context
  + platform contracts load
- Per-module engram instances: working on atlas uses atlas memories/instincts
- Each app is a workspace member with its own pyproject.toml section and tests

### Runtime Isolation

- Each worker gets its own engram instance (separate SQLite database)
- No worker can read another's memory
- Cross-worker communication only through Signal Bus (typed messages)
- Genome DB for universal truths (read-mostly, shared)
- Memory hierarchy: Genome (universal) -> Instance (per-worker) -> Session (ephemeral)

### Communication

- Workers share messages, not state
- Any worker can publish to bus, any can subscribe
- All bus messages logged to ledger (auditable)
- Signal Bus is the only coupling point between workers

Example flows:
- Atlas discovers contradiction -> publishes `research.contradiction` -> Arena
  re-evaluates affected goals
- Governor observes idle capacity -> publishes `priority.directive` -> Arena picks
  up new work
- Ratchet promotes block -> publishes `block.promoted` -> Atlas knows it can rely
  on that block

## Monorepo Layout

```
kairos/
  platform/
    memory/        -- storage, compress, embeddings, dedup, config
    bus/           -- bus, signals, schemas/
    ledger/        -- ledger, schema
    llm/           -- provider, ollama, claude, bedrock, router
    embeddings/    -- embed, nomic
    sandbox/       -- sandbox, capabilities
  runtime/
    daemon.py      -- main loop (always on)
    goals.py       -- goal tracking + decomposition
    scheduler.py   -- tick intervals per worker
    dispatch.py    -- spawn workers, select mode
    router.py      -- tiered LLM routing
    capabilities.py -- grants + enforcement
  apps/
    atlas/         -- research engine (from claw)
    arena/         -- goal execution (from agi)
    ratchet/       -- block lifecycle (from code)
    governor/      -- observe + decide (from why)
  blocks/
    embedder/ vector-index/ rrf/ inference/ ...
    taxonomy.json
  plugins/
    engram/        -- Claude Code MCP plugin (wraps platform/memory)
    ratchet/       -- Claude Code MCP plugin (wraps apps/ratchet)
  tests/
    platform/ apps/ integration/
  pyproject.toml   -- workspace with per-module deps
  CLAUDE.md        -- root (points to module-level docs)
```

## What Gets Discarded

From the audit of ~16K lines of dead code:

- **agi:** entire `src/agi/` legacy governance (6,600 lines), POC clinical discovery
- **blocks:** kernel/ (empty), host/ (orphaned subprocess experiment)
- **claw:** orphaned seed files (seed_all_institutions, seed_remaining, seed_broad,
  seed_resources), migrate_layers.py, unused arena tables
- **code:** kernel/backups, bus-client-ts, voice-notify, plugins/ symlink
- **engram:** daemon.py, ask.py, mirror.py, local_agent.py (exploration harnesses)
- **why:** 9 orphaned world-graph enrichment scripts (7,200 lines), world.db

## Migration Strategy

Build new alongside old. Migrate when proven. Delete when confident.

1. Create kairos/ monorepo with platform scaffolding
2. Port platform modules first (memory, bus, ledger — these have the most tests)
3. Port applications one at a time, starting with the one that exercises the most
   platform surface area
4. Run both old and new in parallel until confident
5. Archive old repos (don't delete — history has value)

### Validation Gates

Each phase has explicit acceptance criteria before proceeding:

- **Platform port:** all existing unit tests pass + new integration tests for
  cross-module contracts (e.g., bus messages appear in ledger)
- **App port:** existing tests pass + app can run 10 ticks against new platform
  with zero errors
- **Parallel run:** 48hr dual-write period where old and new systems process same
  inputs; outputs compared for consistency
- **Cutover:** new system runs solo for 1 week; old system archived

### Data Migration

- New platform/memory reads legacy engram schema during initial sync (one-time
  import of episodes, semantics, instincts with full fidelity)
- No dual-write for memory — clean cutover after import verified

## Degradation Strategy

The system must remain functional when components fail:

- **Tier 2 LLM unavailable:** system continues on Tier 1 with reduced capability.
  Complex tasks queue for later. No blocking.
- **Embeddings unavailable:** use cached embeddings for recall; new stores deferred.
  Flag for human review.
- **Bus unreliable:** workers fall back to direct ledger writes. Cross-worker
  messages queue in per-worker outbox. Retry on bus recovery.
- **Worker crash:** runtime detects via timeout, logs incident, reschedules task.
  Worker's engram instance recovers via WAL checkpoint on restart.
- **Daemon crash:** systemd restarts daemon. Goals and state are in SQLite (survive
  restart). Workers in service mode continue independently until daemon reconnects.

## Observability

- **Logs:** every dispatch, result, escalation, and capability grant. Structured
  JSON to stdout (compatible with log aggregators).
- **Metrics:** ticks/minute, errors/hour, LLM cost/day, memory per worker,
  compression latency, instinct hit rate. Exposed via simple JSON endpoint on
  daemon.
- **Alerting thresholds:** worker restart >3x/hour, compression >60s, error rate
  >1% over 15min window. Alert = log entry + pause affected worker.
- **Dashboard:** deferred. Metrics endpoint is sufficient for v1. Grafana/custom
  dashboard is a future addition.

## Success Criteria

- All 179 engram tests pass against new platform/memory
- All arena tests pass against new apps/arena
- All block tests pass against new blocks/
- Runtime daemon can run atlas ticks autonomously for 24h without intervention
  (defined as: zero unrecoverable errors, all ticks complete or timeout gracefully,
  metrics show stable tick rate)
- Workers cannot access each other's memory (integration test: worker A writes
  episode, worker B queries same content, gets zero results)
- LLM provider can be swapped via config without code changes
- New application can be added without modifying platform or runtime
- Degradation test: daemon runs for 2h with Tier 2 LLM disabled; system remains
  functional on Tier 1 alone
