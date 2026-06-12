# Off-Device Assessment — Design

**Date:** 2026-06-12
**Status:** Approved
**Origin:** Rehab-robotics framing of engram's assistive tooling. The wake hook
is the device; engram's metrics are device telemetry (steps on the treadmill).
The outcome that matters is function *off* the device — does behavior shaped by
memory survive when the orientation isn't loaded? This feature builds the
measurement instrument: assessment sessions where wake assistance is withheld,
function is observed, and results are recorded longitudinally. It is the
baseline instrument for evaluating every later intervention (cue-based wake,
prediction-before-retrieval, error augmentation).

## Decisions (made during brainstorm)

| Question | Decision |
|----------|----------|
| What is turned off | Wake orientation only. Memory tools (recall, remember, etc.) stay available. Measures spontaneous reaching and transfer, not raw substrate. |
| Blinding | Unblinded. Wake emits a minimal assessment marker. Honest, matches clinical practice; the instance can cooperate with the assessment. |
| Outcome measure | Both kinds, self-report first. V1: structured self-report + objective counters from the existing memory log. V2 (out of scope): transcript-vs-store behavioral scoring. |
| Trigger | Scheduled flag with multiple writers (approach C): user via env var, instance via `assessment_schedule()` tool, optional cadence (off by default in v1). |

## Schema — migration 019

New table, no changes to existing tables:

```sql
CREATE TABLE assessments (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN
        ('scheduled', 'active', 'completed', 'skipped', 'abandoned')),
    scheduled_by TEXT NOT NULL CHECK (scheduled_by IN ('user', 'self', 'cadence')),
    reason TEXT,
    scheduled_at TEXT NOT NULL,
    session_id TEXT,
    started_at TEXT,
    self_report TEXT,      -- JSON
    objective TEXT,        -- JSON
    completed_at TEXT
);
```

Invariants:
- At most one row is `active` at any time.
- Wake consumes the **oldest** `scheduled` row when activating.
- `self_report` and `objective` are set together at completion.

## wake.py changes

At the top of `wake()`, before any orientation is built, in this order:

1. **Env override `ENGRAM_ASSESSMENT=skip`** — mark any `scheduled` rows
   `skipped`, proceed with normal orientation. (User cancels a scheduled
   assessment when the session can't afford it.)
2. **Env override `ENGRAM_ASSESSMENT=next`** — create a `scheduled` row
   (`scheduled_by='user'`) if none exists. Falls through to step 4.
3. **Stale `active` row** (from a prior session that ended without a report) —
   mark it `abandoned`.
4. **Activation** — if a `scheduled` row exists: flip the oldest to `active`,
   stamp `session_id` (from `CLAUDE_SESSION_ID`) and `started_at`, emit ONLY
   the minimal marker, and return early:

   > Assessment session: no orientation loaded. Memory tools are available.
   > Call `assessment_report()` before the session ends.

Withheld during an assessment session — all of it is device activity, and the
off-device test is only clean if the device is actually off:
instincts, semantics, dispositions, dream residue, dream cluster priming,
clipboard, coherence/drift report, **task context**, and the **deep pass**.

If the `assessments` table does not exist (pre-migration DB), wake proceeds
normally — non-fatal, consistent with wake's existing error posture.

## MCP tools (server.py)

### `assessment_schedule(reason: str | None = None) -> dict`

Creates a `scheduled` row with `scheduled_by='self'`. Idempotent: if a
`scheduled` row already exists, returns it instead of creating another.
Returns `{assessment_id, status: "scheduled", note}`. The instance scheduling
its own re-assessment is the point: difficulty kept in the loop by the patient,
not just the clinician.

### `assessment_report(...) -> dict`

Structured self-report fields, all optional except `function_score`:

| Field | Type | Meaning |
|-------|------|---------|
| `function_score` | int 1–5 | Overall self-rated function this session (the longitudinal line) |
| `reached_for` | list[str] | Memory reached for unprompted (spontaneous retrieval attempts) |
| `missing` | list[str] | Needed and couldn't reconstruct |
| `felt_absences` | str | Phenomenology — what the absence felt like |
| `instinct_consistent_moments` | str | Behavior matching unloaded instincts (the transfer signal) |
| `notes` | str | Anything else |

Server behavior:
1. Find the singleton `active` row. No session-string matching — the
   active-row invariant makes the join trivial and robust against
   wake/server session-id mismatches. Error if none active.
2. Compute objective counters from the existing memory log for the current
   server session: `recall_count`, `outcomes_logged_used`,
   `outcomes_logged_unused`, `remember_count`.
3. Store `self_report` (JSON) and `objective` (JSON), set
   `completed_at`, status `completed`.

Validation: `function_score` must be 1–5; report against a non-active
assessment is an error, not a silent create.

### `reflect(focus="assessments")`

Returns completed assessments in chronological order: date, `function_score`,
objective counters, abbreviated self-report. Plus scheduled/skipped/abandoned
counts. This is the function-over-time chart later interventions are judged
against.

## Honesty boundary

This is **engram-off-device only**. CLAUDE.md and the file-based MEMORY.md
still load — they are harness-level, outside engram's reach. An assessment
measures function without the engram device, not without all memory. The spec
says so; the marker does not pretend otherwise.

The `function_score` is self-rated by a system with a documented
perform-insight gradient. The objective counters ride alongside it from day
one for exactly this reason; v2's transcript scoring is the eventual anchor.
Self-report is the patient-reported outcome, not ground truth.

## Out of scope (v2 candidates)

- Transcript-vs-store behavioral scoring (objective transfer measurement).
- Blinded assessment variants.
- Full-deprivation floor measurement (no tools at all).
- Cadence-based auto-scheduling (the `scheduled_by='cadence'` value is
  reserved; no cadence logic ships in v1).

## Testing

Existing patterns (temp DB fixtures, direct function calls, no MCP transport):

- Migration 019 creates the table; round-trips on a fresh and an existing DB.
- `assessment_schedule`: creates a row; idempotent on double-call.
- Wake mode selection: `skip` marks scheduled rows skipped and proceeds
  normally; `next` creates a row; stale `active` rows are abandoned;
  activation flips status, stamps session, emits marker only (no instinct/
  semantic content in output); missing table → normal wake.
- `assessment_report`: completes the active row, computes counters from the
  memory log, validates `function_score`, errors without an active row.
- `reflect(focus="assessments")`: returns history in order with counters.
