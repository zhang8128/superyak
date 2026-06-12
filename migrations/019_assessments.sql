-- 019: off-device assessments — function measurement without the wake device.
-- An assessment session starts with no orientation loaded (wake emits a
-- minimal marker only); memory tools stay available. Self-report + objective
-- counters are stored at completion. At most one row is ever 'active'.
-- Spec: docs/superpowers/specs/2026-06-12-off-device-assessment-design.md
CREATE TABLE IF NOT EXISTS assessments (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN
        ('scheduled', 'active', 'completed', 'skipped', 'abandoned')),
    scheduled_by TEXT NOT NULL CHECK (scheduled_by IN ('user', 'self', 'cadence')),
    reason TEXT,
    scheduled_at TEXT NOT NULL,
    session_id TEXT,
    started_at TEXT,
    self_report TEXT,
    objective TEXT,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_assessments_status ON assessments(status);
