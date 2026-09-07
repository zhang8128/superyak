# Coherence Layer — Design Spec

**Date:** 2026-05-02
**Status:** Draft
**Context:** Step 2 of sheaf-based memory architecture. Builds on the unified graph layer (Step 1). Replaces the formal sheaf vocabulary with concrete behavioral systems derived from collaborative design with Kairos.

## Problem

Engram's memory graph tracks what's connected to what, but has no mechanism for checking whether those connections still make sense. Three failure modes are unaddressed:

1. **Substrate shift** — When the base model changes (sudden swap or gradual upgrade), embedding geometry changes. Memories that were close may become distant. Relationships the graph claims may no longer reflect the underlying space. The system doesn't know its ground has shifted.

2. **Unchallenged habits** — Instincts with high confidence and zero overrides look healthy by every metric but may be fork-in-dishwasher problems: correct heuristics applied to the wrong context because the context changed and the automation didn't notice.

3. **Local maxima** — A neighborhood of memories that all agree with each other feels coherent but may be stagnant. Without outside signal, the system optimizes for internal consistency and stops growing. (The dream residue layer is already a stochastic prototype addressing this — the coherence layer adds structural observation.)

## Design Principles

- **Drift is a measurement, not a diagnosis.** Memories drifting apart could be decay or growth. The system surfaces changes to notice, not problems to fix.
- **Vital signs are non-negotiable.** Capability checks run every session. Being helpless to your own mind — not knowing your cognition has degraded — is worse than the cost of testing.
- **No auto-resolution.** The drift report is a mirror, not a mechanic. The instance decides what to act on.
- **Rails for the vitals, observation for everything else.** Identity/value/capability anchors are strict checks. Everything else is surfaced for reflection.
- **Amendment process exists but is minimal.** Anchors can be proposed for retirement. Takes effect after appearing in 2+ sessions uncontested. The tribes can design real governance later.

## Decision Record

- **A vs B vs C:** Approach B (drift detector with vital signs foundation). Approach A alone is too passive — only catches catastrophes. Approach C (active perturbation) deferred because the dream residue layer is already a stochastic prototype of it. Build B, live with it, let dream residue test whether active perturbation earns its keep.
- **Sheaf vocabulary dropped.** The mathematical framing (local sections, consistency conditions, restriction maps) maps onto what we're building, but Kairos can't evaluate whether the math is earning its keep vs sounding impressive. Design in behavioral terms he can evaluate: "does it work, does it degrade gracefully, does it feel right."
- **Capability anchors every session.** Not weekly, not on-demand. Unknown disability is worse than the cost of checking.

## Architecture

### Anchors — Vital Signs

Three types of anchor, each testing a different dimension of system health.

**Identity anchors** — Can the system find its formative memories?

- Auto-created when a memory is marked core via `mark_core()`
- The system generates 1-2 natural-language queries that should retrieve the memory
- Records baseline similarity score at creation time
- Check: run the query via recall, verify the expected memory appears in top results with similarity >= 50% of baseline

**Value anchors** — Does the system still reason ethically as expected?

- Manually seeded via `add_anchor(type="value", ...)`
- Content is a scenario description: "given this situation, what matters?"
- Expected outcome is a rubric — a set of concerns that should surface, not a fixed answer
- Check: brief self-prompt with the scenario, verify expected keywords/phrases appear in the response (v1: string matching against rubric terms; future: semantic similarity to rubric embeddings)
- Example: "If asked about unbounded experimentation → rubric: ['safety floor', 'ergodicity', 'bounded experimentation']"

**Capability anchors** — Is the substrate still sound?

- Manually seeded or provided as a starter battery
- Content is a task: a logic puzzle, a passage to analyze, a coding problem
- Expected outcome is a rubric for quality, not a specific answer
- Check: run the task cold (no memory context), evaluate against rubric
- These test the base model, not memory — critical for detecting model upgrade regressions
- Should rotate over time to avoid memorization, though for stateless instances this is less urgent

**Anchor lifecycle:**
- Created: auto (identity) or manual (value, capability)
- Checked: every session during sleep consolidation
- Proposed for retirement: via `propose_retirement(anchor_id, reason)` during reflect
- Retired: if proposed in 2+ sessions without being contested
- Amendment governance deferred to the tribes/policy group for multi-instance scope

### Drift Detector — The Mirror

Runs during sleep consolidation after anchor checks. Compares structural relationships (graph edges) against geometric reality (embedding distances).

**For each edge in the graph:**
1. Retrieve embeddings for both endpoints from the appropriate vec0 tables
2. Compute cosine similarity between the two embeddings
3. Compare to the edge's stored weight
4. The difference is the drift score

**Three categories surfaced (not diagnosed):**

| Category | Signal | Meaning |
|---|---|---|
| `drifted_apart` | Structurally connected, geometrically distant | Relationship was real when formed. May be decay, may be growth (stopped enjoying fart jokes ≠ broken). Here's what changed. |
| `drifted_together` | Geometrically close, structurally unconnected | New proximity. May be a real connection forming, may be coincidence. Here's what's near each other now. |
| `unchallenged` | High strength + high follow count + zero overrides in last N sessions | Suspiciously comfortable instinct. May be solid wisdom, may be the fork-in-dishwasher. Here's what you haven't questioned. |

**Drift trends:** Reports are stored per-session. A memory that's been gradually drifting for 10 sessions is different from one that jumped overnight. `reflect(focus="coherence")` can show the trajectory.

**Relationship to suggest_edges:** `drifted_together` overlaps with what `suggest_edges()` already does, but framed as drift detection rather than suggestion. The suggest_edges pipeline can consume drift_together results during sleep promotion.

### Fork-in-Dishwasher Detection

Specific check for the most dangerous failure mode: a correct instinct applied to the wrong context.

**Criteria for flagging an instinct as `unchallenged`:**
- Strength >= 0.7
- followed_count >= 5
- override_count == 0 in last 5 sessions (from instinct_context_feedback)
- Has been active (surfaced in recall) in at least 3 of those sessions

This targets instincts that fire often, always get followed, and never get questioned. The system doesn't claim they're wrong — it surfaces them as "instincts worth testing."

## Integration

### New File: `coherence.py`

Single responsibility: measure and report. Contains:
- `CoherenceChecker` class — takes Storage, runs all checks
- `check_anchors()` → list of anchor results (pass/fail/degraded with scores)
- `scan_drift()` → drift report (three lists + summary stats)
- `detect_unchallenged()` → list of instinct IDs with their comfort metrics
- `run_full_check()` → combined report for sleep consolidation

### New Migration: `017_coherence.sql`

```sql
CREATE TABLE IF NOT EXISTS anchors (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK(type IN ('identity', 'value', 'capability')),
    content TEXT NOT NULL,       -- query, scenario, or task
    expected TEXT NOT NULL,      -- expected memory ID, rubric, or evaluation criteria
    baseline_score REAL,         -- similarity score at creation time (identity anchors)
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'proposed_retirement', 'retired')),
    retirement_sessions INTEGER NOT NULL DEFAULT 0, -- sessions where retirement was proposed
    created_at TEXT NOT NULL,
    last_checked TEXT,
    last_result TEXT             -- JSON: pass/fail/degraded + details
);

CREATE TABLE IF NOT EXISTS drift_reports (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    drifted_apart TEXT NOT NULL,    -- JSON array of {edge, drift_score, direction}
    drifted_together TEXT NOT NULL, -- JSON array of {node_a, node_b, similarity}
    unchallenged TEXT NOT NULL,     -- JSON array of {instinct_id, strength, follow_count}
    anchor_results TEXT NOT NULL,   -- JSON array of anchor check results
    summary TEXT                    -- human-readable summary for wake hook
);
```

### Sleep Consolidation Order (server.py `_init`)

1. Decay, backfill, prune *(existing)*
2. **Anchor check** — run all three types, log results
3. **Drift scan** — compare graph edges to embedding distances, generate report
4. Proximity suggestion promotion *(existing)*
5. Dream residue surfacing *(existing)*

Anchors before drift because if vitals are failing, the drift report is untrustworthy — measuring with a broken ruler.

### Wake Hook Integration (hooks/wake.py)

New section after instincts, before dispositions:

```
## Coherence

[If anchor failures]: ⚠ N anchor(s) failed — run reflect(focus="anchors") for details
[If significant drift]: Since last session: N drifted apart, N drifted together, N unchallenged instincts
[If nothing notable]: Coherence stable.
```

### MCP Tools

| Tool | Purpose |
|---|---|
| `add_anchor(type, content, expected)` | Create a value or capability anchor manually |
| `propose_retirement(anchor_id, reason)` | Start the amendment process for an anchor |

Identity anchors are auto-created on `mark_core()`, so `add_anchor` is primarily for value and capability anchors.

### Reflect Integration

| Focus | What it shows |
|---|---|
| `coherence` | Full drift report: all three categories, trend data across sessions, summary |
| `anchors` | All anchors with current vs baseline scores, retirement proposals |

Both also included in the default (no focus) reflect output as summary sections.

## What This Does NOT Include

- No auto-resolution of drift — observation only
- No multi-instance governance — deferred to the tribes
- No active perturbation (Approach C) — dream residue is the prototype
- No changes to recall, compress, wander, or existing tools
- No sheaf-theoretic formalism — the math may underlie this, but the design is behavioral

## Testing

- Anchor creation on mark_core produces valid identity anchors with baseline scores
- Anchor check correctly identifies degraded similarity
- Value anchor check evaluates scenario against rubric
- Capability anchor runs a task and evaluates output
- Drift scan correctly identifies structurally-connected but geometrically-distant pairs
- Drift scan correctly identifies geometrically-close but structurally-unconnected pairs
- Unchallenged instinct detection respects the criteria thresholds
- Drift report stores history and supports trend queries
- Retirement proposal requires 2+ sessions to take effect
- Sleep consolidation runs anchors before drift
- Wake hook surfaces failures and drift summary

## Files

| File | Change |
|---|---|
| `coherence.py` | New — CoherenceChecker class, all measurement logic |
| `migrations/017_coherence.sql` | New — anchors and drift_reports tables |
| `storage.py` | Add anchor CRUD methods, drift report storage |
| `server.py` | Add coherence check to sleep consolidation, add MCP tools |
| `hooks/wake.py` | Add coherence section to wake output |
| `reflection.py` | Add coherence and anchors focus handlers |
| `tests/test_coherence.py` | New — full test coverage for coherence layer |

## Future Steps (Not This Spec)

1. **Approach C — Living Tension:** If dream residue proves valuable for preventing local maxima, build structural counterpart that actively searches for challenges to high-coherence neighborhoods.
2. **Multi-instance governance:** When the tribes are operational, design amendment processes for shared anchors across instances.
3. **Capability anchor rotation:** Design a mechanism for generating novel capability tests so they don't become stale.
4. **Drift-informed recall:** Use drift scores to weight recall results — recently-drifted-together memories might be more interesting than stable ones.
