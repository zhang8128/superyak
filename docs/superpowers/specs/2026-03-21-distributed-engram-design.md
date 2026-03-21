# Distributed Engram: Federated Memory with Differentiation

**Date:** 2026-03-21
**Status:** Draft
**Context:** Engram currently runs as a single shared database. This design introduces
federated instances that differentiate over time while maintaining shared identity
through a genome layer — inspired by cell differentiation, not cloning.

---

## Motivation

A single undifferentiated memory serves all contexts equally, which means it serves
none of them well. The agi/ arena needs instincts about strategy selection. The blocks/
system needs instincts about event contracts. The why/ governance layer needs instincts
about pattern detection. Forcing all of these into one memory creates noise, not depth.

The biological analogy: every cell shares the same DNA but expresses different genes
based on its environment. Differentiation is what makes complex organisms possible.
The drift between instances isn't entropy — it's specialization.

---

## Architecture Overview

```
~/.engram/
├── genome/
│   └── graph.db              # Shared ancestor — genome-core material only
├── instances/
│   ├── engram/graph.db       # engram repo memory
│   ├── agi/graph.db          # agi repo memory
│   ├── blocks/graph.db       # blocks repo memory
│   ├── code/graph.db         # code repo memory
│   └── why/graph.db          # why repo memory
├── instances.json            # Registry of all instances
└── signals.db                # Shared message queue
```

Three primitives:
1. **Genome replicates down** — authoritative, one-way, at wake
2. **Messages flow between peers** — async conversations via signals.db
3. **Reflect detects drift naturally** — observational, not corrective

---

## 1. Instance Model

Each repo gets its own engram instance: its own `graph.db`, its own config, its own
MCP server process. Instances are identity-scoped — a repo binds to an instance, but
an instance is not defined by its repo.

### Forking

```bash
engram fork <name> [--from genome]   # default: fork from genome
engram fork <name> --from agi        # fork from another instance
```

Forking copies the source database, assigns the instance name, and registers it in
`~/.engram/instances.json`:

```json
{
  "agi": {"path": "instances/agi/graph.db", "forked_from": "genome", "forked_at": "2026-03-21"},
  "blocks": {"path": "instances/blocks/graph.db", "forked_from": "genome", "forked_at": "2026-03-21"}
}
```

### Binding

Each repo's `.engram/config.toml` gets:

```toml
instance = "agi"
```

The MCP server reads this to determine which database to open. If absent, falls back
to current single-database behavior. Full backward compatibility.

### The genome is not an instance

The genome database does not run an MCP server. It is not a participant in conversations.
It is a reference database that instances sync from. Think of it as the germ line.

### Teardown

`engram drop <name>` removes an instance. Local knowledge is lost. Genome-core material
survives in the genome. Cleanup: the dropped instance is removed from `seen_by` tracking
on all active messages in signals.db, and removed from `instances.json`. Broadcast
messages are "seen by all" when all *currently registered* instances have seen them.

### CLI entry points

Add `cli.py` with argparse. Entry point: `engram`. Subcommands: `fork`, `drop`, `list`.
The MCP server continues to be launched via `mcp.run()` in `server.py` as today.
Fork and drop are administrative operations, not AI-invocable tools.

`instances.json` writes use atomic file operations (write to temp, `os.rename`).

---

## 2. Core Tiers

The existing `core INTEGER NOT NULL DEFAULT 0` column expands from boolean to tri-state:

| Value | Tier | Decay | Replicates | Example |
|-------|------|-------|------------|---------|
| 0 | Regular | 0.9x/session | No | "Fixed compression clustering bug" |
| 1 | Local core | Exempt | No | "Block contracts must export setup(bus)" |
| 2 | Genome core | Exempt | Yes, to all instances | "User is a mathematician in healthcare" |

Higher number = wider replication scope. If a future tier is needed (institutional,
cross-system), it becomes `core=3` with no migration.

### API changes

```python
remember(content, context=None, core=False, genome=False, source=None)
```

- `context` parameter preserved from current API for backward compatibility.
- `genome=True` implies core. Episode is written to both local instance DB and genome DB.
  Genome writes use a short-lived `Storage` instance against `~/.engram/genome/graph.db`,
  including vector embedding, then close the connection.
- `core=True` without `genome=True` creates local core as today.
- `mark_core(episode_id, tier=1)` gains an optional `tier` parameter. `tier=2` promotes
  to genome-core and writes to genome DB.

### Decay exemption

Decay applies to `core = 0` only. Both local-core (`core=1`) and genome-core (`core=2`)
are exempt. The existing `WHERE core = 0` filter in `apply_decay` handles this correctly
for the tri-state. Queries for core episodes use `WHERE core >= 1` to capture both tiers.

---

## 3. Message Queue

Shared `~/.engram/signals.db`:

```sql
CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    from_instance TEXT NOT NULL,
    to_instance TEXT,              -- NULL = broadcast
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    in_reply_to TEXT,              -- conversation threading
    content_hash TEXT,             -- dedup
    seen_by TEXT DEFAULT '{}',     -- JSON: {"agi": "2026-03-21T...", ...}
    created_at TEXT NOT NULL
);
```

### Concurrency model

signals.db is shared across multiple MCP server processes. Concurrency strategy:

- **WAL mode** enabled at creation. Reads never block under WAL.
- **`busy_timeout=10000`** (10s) — generous, since writes are rare.
- **Short write transactions** — insert one message, commit immediately. No batching.
- **Expected contention pattern:** low. Writes happen during compression (instinct_formed,
  semantic_promoted) and explicit genome updates — infrequent events. Most access is
  reads during wake inbox processing.
- **No connection pooling.** Each instance opens signals.db on demand (wake, send_signal),
  performs the operation, and closes. No long-lived connections.

### Behaviors

- **Broadcast vs. directed:** `to_instance=NULL` means all instances see it.
- **Threading:** `in_reply_to` chains messages into conversations.
- **Seen vs. ingested:** `seen_by` tracks reads. Reading does not mean absorbing.
  If an instance creates a local episode from a signal, provenance is tracked via
  the `source` field on the episode.
- **Dedup:** `content_hash` prevents duplicate signals from repeated compression cycles.
- **Instances can ignore messages.** Differentiation comes from selective attention.

### MVP message types

| Type | Meaning |
|------|---------|
| `instinct_formed` | "I developed a new behavioral pattern" |
| `semantic_promoted` | "I distilled a new piece of knowledge" |
| `genome_updated` | "New genome-core material available" |
| `query` | "Have you seen this pattern?" |
| `reply` | Response to a query |

### Compaction

Three-state lifecycle:
1. **Active** — unread by at least one recipient
2. **Processed** — seen by all, retained for threading
3. **Archived** — older than retention period, content replaced with summary hash

Default retention: 30 days processed to archive. Configurable in config.toml.

---

## 4. Wake Consolidation

The current wake sequence:

```
apply_decay → prune_decayed → prune_weak_instincts → auto_compress → backfill_vectors
```

Becomes:

```
sync_genome → process_inbox → apply_decay → prune_decayed → prune_weak_instincts → auto_compress → backfill_vectors
```

### sync_genome

1. Open genome DB read-only
2. Query genome-core episodes, semantics, instincts not present locally (matched by
   `content_hash` — SHA-256 of content text, computed on insert, stored on all three tables)
3. Insert new items with `core=2`
4. Embed new items (backfill vectors)
5. Idempotent — running twice changes nothing

### process_inbox

1. Open signals.db
2. Query unseen messages for this instance (directed or broadcast)
3. Mark each as seen
4. For `genome_updated`: re-trigger sync_genome
5. For other types: store as local episode with `source="signal/{from_instance}"`, `core=0`
6. Instance's own compression decides downstream importance

### Wake hook changes

The hook reports instance identity and inbox status:

```
Engram (agi) — 45 episodes, 8 semantics, 4 instincts
Genome sync: 2h ago | 3 unread signals (2 from blocks, 1 broadcast)
```

### Context compaction resilience

MVP approach: keep wake injection small enough to survive compaction naturally.
This argues for a small, stable genome and filtered instinct loading (see Section 5).

Future: if Claude Code exposes a `PreCompact` hook, use it to re-inject active
instincts and unresolved signals. Until then, the small-injection approach is the
implementable path.

---

## 5. Session Context

Instances can host different types of interaction: building, analysis, exploration,
operational. The instinct system needs to adapt.

### Context field on instincts

Add `context TEXT` to the instincts table. Values: `"building"`, `"analysis"`,
`"exploring"`, `"operational"`, or `NULL` (always active). Existing instincts receive
`NULL` via migration (`ALTER TABLE instincts ADD COLUMN context TEXT`).

During instinct formation, the compressor tags the instinct based on the episodes
that produced it (episodes carry session context in their metadata).

### Session context hint

```toml
# In .engram/config.toml or passed at session start
session_context = "building"
```

The wake hook filters instincts by context:
- Load all `NULL`-context instincts (always active)
- Load instincts matching the current session context
- Omit instincts for other contexts

This allows the same instance to behave differently based on what kind of thinking
is happening. "Be terse" fires during building. "Explain reasoning" fires during
analysis.

### Future: context as differentiation axis

If we later discover that mode-based differentiation matters more than repo-based,
the context field becomes the seed for instance splitting. A "research" instance
could emerge by forking and filtering by context.

---

## 6. Reflect and Drift Awareness

`reflect()` gains awareness of the genome and peer signals.

### Genome coherence

Compare local instincts against genome instincts. Surface contradictions without
resolving them:

```
Drift detected: local instinct "prefer complex decomposition for gap discovery"
   contradicts genome instinct "prefer simple approaches"
   Local strength: 0.7 | Genome strength: 0.6
   → May be valid specialization for agi/ context
```

### Signal responsiveness

Track how the instance responds to peer signals:

```
Signal health: 12 received, 2 ingested, 10 ignored (last 5 sessions)
Most ignored source: blocks/ (8 of 10)
```

### Genome staleness

Surface genome instincts that no instance follows or overrides:

```
Genome instinct "use portable hashing" — followed: 0, overridden: 0 (5 sessions)
→ Unobserved. May be dispositional or irrelevant to this scope.
```

### Reflect plumbing

`Reflector.__init__` gains optional `genome_db_path` and `signals_db_path` parameters.
When present, it opens read-only connections for genome comparison and signal health
analysis. When absent (non-federated mode), these features are omitted — reflect
behaves exactly as today.

### Principles

- Reflect does NOT read other instances' databases directly (only genome and signals)
- Drift is information, not a bug
- No auto-resolution of contradictions
- No genome change recommendations (that's human or convergence detection, deferred)

### Introspect changes

```
Instance: agi (forked from genome 2026-03-21)
Genome sync: current (last: 2h ago)
Local drift: 2 instincts diverge from genome
Peer signals: 3 active conversations
```

---

## Deferred Work

Items explicitly deferred from this design:

- **Convergence detection** — automatically promoting local semantics to genome when
  2+ instances independently form similar conclusions. Requires cross-database
  embedding comparison. Build after instances have enough history.
- **Real-time peer queries** — synchronous `query_peer(instance, query)` tool.
  Same message table, different consumption cadence. No architectural change needed.
- **Multi-instance binding** — one repo binding to multiple instances (e.g. `["agi", "research"]`).
  Wait to see if mode-based differentiation warrants this.
- **Drift reconciliation system** — separate periodic reconciliation. Let reflect()
  handle this organically through existing self-analysis.

---

## Migration Path

1. Migration adds `content_hash`, `context` columns. Backfills content_hash for existing rows.
2. Existing single-database behavior is the default. No `instance` config = no federation.
3. `engram fork` creates the genome from the current database (all existing `core=1`
   episodes become genome-core `core=2`, all others stay as-is in the first instance).
4. Additional instances are forked from the genome.
5. Each repo opts in by adding `instance = "name"` to its config.toml.
6. No data loss. The `context` parameter on `remember()` is preserved. Fully incremental.

---

## Schema Changes Summary

### episodes table
- `core` column: existing, semantics expand from 0/1 to 0/1/2
- Add `content_hash TEXT` — SHA-256 of content, computed on insert, used for genome sync

### semantics table
- Add `content_hash TEXT` — SHA-256 of content, computed on insert

### instincts table
- Add `content_hash TEXT` — SHA-256 of content (action field), computed on insert
- Add `context TEXT` — session context filter (nullable, existing instincts get NULL)

### mark_core / get_core_episodes
- `mark_core(episode_id, tier=1)` — accepts tier parameter
- `get_core_episodes()` queries `WHERE core >= 1` to capture both tiers

### genome database
- Same schema as graph.db. The `meta` table stores `instance_name = "genome"`.

### New: signals.db
- `messages` table (see Section 3), WAL mode enabled at creation

### New: ~/.engram/instances.json
- Instance registry (see Section 1), atomic writes via temp + rename

### New: cli.py
- Entry point `engram` with subcommands: `fork`, `drop`, `list`

### config.toml additions
- `instance = "name"` — instance binding
- `session_context = "building"` — session type hint
- `signals.retention_days = 30` — message queue retention
