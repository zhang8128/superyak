-- Coherence layer: vital sign anchors and drift tracking.
CREATE TABLE IF NOT EXISTS anchors (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK(type IN ('identity', 'value', 'capability')),
    content TEXT NOT NULL,
    expected TEXT NOT NULL,
    baseline_score REAL,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'proposed_retirement', 'retired')),
    retirement_sessions INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_checked TEXT,
    last_result TEXT
);

CREATE TABLE IF NOT EXISTS drift_reports (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    drifted_apart TEXT NOT NULL DEFAULT '[]',
    drifted_together TEXT NOT NULL DEFAULT '[]',
    unchallenged TEXT NOT NULL DEFAULT '[]',
    anchor_results TEXT NOT NULL DEFAULT '[]',
    summary TEXT
);
