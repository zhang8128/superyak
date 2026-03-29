-- 015_dispositions.sql
-- Add 'disposition' as a valid semantic kind.
-- SQLite CHECK constraints cannot be altered in place — table recreation required.

PRAGMA foreign_keys = OFF;

CREATE TABLE semantics_new (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('fact', 'relationship', 'preference', 'constraint', 'disposition')),
    confidence REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL,
    auto_generated INTEGER NOT NULL DEFAULT 0,
    reinforced_count INTEGER NOT NULL DEFAULT 0,
    last_reinforced TEXT,
    contradicted_by TEXT,
    content_hash TEXT
);

INSERT INTO semantics_new SELECT * FROM semantics;

DROP TABLE semantics;

ALTER TABLE semantics_new RENAME TO semantics;

PRAGMA foreign_keys = ON;
