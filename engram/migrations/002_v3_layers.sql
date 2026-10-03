-- v3 layer tables: episodes columns, semantics, instincts, memory_log, FTS, vectors

-- Add new columns to episodes (SQLite ALTER TABLE supports one column at a time)
ALTER TABLE episodes ADD COLUMN context JSON;
ALTER TABLE episodes ADD COLUMN accessed_count INTEGER DEFAULT 0;
ALTER TABLE episodes ADD COLUMN last_accessed TEXT;
ALTER TABLE episodes ADD COLUMN compressed INTEGER DEFAULT 0;

-- Semantics: distilled facts, relationships, preferences, constraints
CREATE TABLE IF NOT EXISTS semantics (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('fact', 'relationship', 'preference', 'constraint')),
    confidence REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL,
    reinforced_count INTEGER NOT NULL DEFAULT 0,
    last_reinforced TEXT,
    contradicted_by TEXT REFERENCES semantics(id)
);

CREATE INDEX IF NOT EXISTS idx_semantics_kind ON semantics(kind);
CREATE INDEX IF NOT EXISTS idx_semantics_confidence ON semantics(confidence);

-- Junction table: which episodes contributed to a semantic
CREATE TABLE IF NOT EXISTS semantic_sources (
    semantic_id TEXT NOT NULL REFERENCES semantics(id) ON DELETE CASCADE,
    episode_id TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    PRIMARY KEY (semantic_id, episode_id)
);

-- Instincts: compiled behavioral patterns derived from semantics
CREATE TABLE IF NOT EXISTS instincts (
    id TEXT PRIMARY KEY,
    trigger TEXT NOT NULL,
    action TEXT NOT NULL,
    strength REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL,
    fired_count INTEGER NOT NULL DEFAULT 0,
    followed_count INTEGER NOT NULL DEFAULT 0,
    overridden_count INTEGER NOT NULL DEFAULT 0
);

-- Junction table: which semantics contributed to an instinct
CREATE TABLE IF NOT EXISTS instinct_sources (
    instinct_id TEXT NOT NULL REFERENCES instincts(id) ON DELETE CASCADE,
    semantic_id TEXT NOT NULL REFERENCES semantics(id) ON DELETE CASCADE,
    PRIMARY KEY (instinct_id, semantic_id)
);

-- Memory log: audit trail of memory layer events
CREATE TABLE IF NOT EXISTS memory_log (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    layer TEXT NOT NULL,
    target_ids JSON,
    context JSON,
    outcome TEXT
);

CREATE INDEX IF NOT EXISTS idx_memory_log_timestamp ON memory_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_memory_log_event_type ON memory_log(event_type);
CREATE INDEX IF NOT EXISTS idx_memory_log_layer ON memory_log(layer);

-- Vector table for semantic embeddings
CREATE VIRTUAL TABLE IF NOT EXISTS semantic_vectors USING vec0(
    id TEXT PRIMARY KEY,
    embedding float[384]
);

-- FTS on semantics content
CREATE VIRTUAL TABLE IF NOT EXISTS semantic_fts USING fts5(
    content,
    content=semantics,
    content_rowid=rowid
);

CREATE TRIGGER IF NOT EXISTS semantic_fts_insert AFTER INSERT ON semantics BEGIN
    INSERT INTO semantic_fts(rowid, content)
    VALUES (new.rowid, new.content);
END;

CREATE TRIGGER IF NOT EXISTS semantic_fts_delete AFTER DELETE ON semantics BEGIN
    INSERT INTO semantic_fts(semantic_fts, rowid, content)
    VALUES ('delete', old.rowid, old.content);
END;

CREATE TRIGGER IF NOT EXISTS semantic_fts_update AFTER UPDATE ON semantics BEGIN
    INSERT INTO semantic_fts(semantic_fts, rowid, content)
    VALUES ('delete', old.rowid, old.content);
    INSERT INTO semantic_fts(rowid, content)
    VALUES (new.rowid, new.content);
END;

-- FTS on episodes content
CREATE VIRTUAL TABLE IF NOT EXISTS episode_fts USING fts5(
    content,
    content=episodes,
    content_rowid=rowid
);

CREATE TRIGGER IF NOT EXISTS episode_fts_insert AFTER INSERT ON episodes BEGIN
    INSERT INTO episode_fts(rowid, content)
    VALUES (new.rowid, new.content);
END;

CREATE TRIGGER IF NOT EXISTS episode_fts_delete AFTER DELETE ON episodes BEGIN
    INSERT INTO episode_fts(episode_fts, rowid, content)
    VALUES ('delete', old.rowid, old.content);
END;

CREATE TRIGGER IF NOT EXISTS episode_fts_update AFTER UPDATE ON episodes BEGIN
    INSERT INTO episode_fts(episode_fts, rowid, content)
    VALUES ('delete', old.rowid, old.content);
    INSERT INTO episode_fts(rowid, content)
    VALUES (new.rowid, new.content);
END;

-- Index episodes that predate this migration; without it the update trigger's
-- 'delete' meets rows the index never held and the first UPDATE fails as
-- "database disk image is malformed" (found porting a migration-001 store).
INSERT INTO episode_fts(episode_fts) VALUES('rebuild');
