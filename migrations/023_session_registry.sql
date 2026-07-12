-- Silent provenance: which harness/model/repo drove each session.
-- Never rendered in any working surface; post-analysis is SQL-only.
-- Spec: docs/superpowers/specs/2026-07-11-engram-codex-hooks-design.md
CREATE TABLE IF NOT EXISTS session_registry (
    session_id TEXT PRIMARY KEY,
    harness    TEXT,
    model      TEXT,
    repo       TEXT,
    started_at TEXT NOT NULL
);
