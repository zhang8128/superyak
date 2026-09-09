-- 015_dispositions.sql
-- Add 'disposition' as a valid semantic kind.
--
-- The original CHECK constraint in 002_v3_layers.sql is:
--   CHECK (kind IN ('fact', 'relationship', 'preference', 'constraint'))
--
-- SQLite doesn't support ALTER CONSTRAINT, so we recreate the table
-- with the extended CHECK. Preserve rowids and incoming provenance before
-- dropping the old table: foreign-key cascades run inside the migration too.

-- Step 1: Create new table with extended CHECK
CREATE TABLE semantics_new (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('fact', 'relationship', 'preference', 'constraint', 'disposition')),
    confidence REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL,
    reinforced_count INTEGER NOT NULL DEFAULT 0,
    last_reinforced TEXT,
    contradicted_by TEXT REFERENCES semantics_new(id),
    auto_generated INTEGER DEFAULT 0,
    content_hash TEXT
);

-- Step 2: Copy all existing data
INSERT INTO semantics_new (rowid, id, content, kind, confidence, created_at,
    reinforced_count, last_reinforced, contradicted_by, auto_generated, content_hash)
SELECT rowid, id, content, kind, confidence, created_at,
    reinforced_count, last_reinforced, contradicted_by, auto_generated, content_hash
FROM semantics;

-- Step 3: Save the junction rows that DROP TABLE will cascade-delete. These
-- temporary copies and the table replacement share the runner's transaction.
CREATE TEMP TABLE disposition_semantic_sources AS
SELECT semantic_id, episode_id, similarity FROM semantic_sources;
CREATE TEMP TABLE disposition_instinct_sources AS
SELECT instinct_id, semantic_id FROM instinct_sources;

DROP TABLE semantics;

-- Step 4: Rename new table
ALTER TABLE semantics_new RENAME TO semantics;

INSERT INTO semantic_sources (semantic_id, episode_id, similarity)
SELECT semantic_id, episode_id, similarity FROM disposition_semantic_sources;
INSERT INTO instinct_sources (instinct_id, semantic_id)
SELECT instinct_id, semantic_id FROM disposition_instinct_sources;
DROP TABLE disposition_semantic_sources;
DROP TABLE disposition_instinct_sources;

-- Step 5: Recreate indexes
CREATE INDEX IF NOT EXISTS idx_semantics_kind ON semantics(kind);
CREATE INDEX IF NOT EXISTS idx_semantics_confidence ON semantics(confidence);

-- Step 6: Recreate FTS triggers (they reference 'semantics' by name)
DROP TRIGGER IF EXISTS semantic_fts_insert;
DROP TRIGGER IF EXISTS semantic_fts_delete;
DROP TRIGGER IF EXISTS semantic_fts_update;

CREATE TRIGGER semantic_fts_insert AFTER INSERT ON semantics BEGIN
    INSERT INTO semantic_fts(rowid, content)
    VALUES (new.rowid, new.content);
END;

CREATE TRIGGER semantic_fts_delete AFTER DELETE ON semantics BEGIN
    INSERT INTO semantic_fts(semantic_fts, rowid, content)
    VALUES ('delete', old.rowid, old.content);
END;

CREATE TRIGGER semantic_fts_update AFTER UPDATE ON semantics BEGIN
    INSERT INTO semantic_fts(semantic_fts, rowid, content)
    VALUES ('delete', old.rowid, old.content);
    INSERT INTO semantic_fts(rowid, content)
    VALUES (new.rowid, new.content);
END;

-- Rebuild FTS index from new table
INSERT INTO semantic_fts(semantic_fts) VALUES('rebuild');
