-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

-- Meta table for key-value settings (e.g., last_indexed_commit)
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Entities: typed nodes
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    description TEXT,
    metadata JSON,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);

-- Relationships: typed edges with temporal validity
CREATE TABLE IF NOT EXISTS relationships (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    rel_type TEXT NOT NULL,
    description TEXT,
    weight REAL DEFAULT 1.0,
    valid_from TEXT NOT NULL,
    invalid_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rel_source ON relationships(source_id);
CREATE INDEX IF NOT EXISTS idx_rel_target ON relationships(target_id);
CREATE INDEX IF NOT EXISTS idx_rel_type ON relationships(rel_type);
CREATE INDEX IF NOT EXISTS idx_rel_valid ON relationships(invalid_at);

-- Episodes: raw conversation fragments
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    content TEXT NOT NULL,
    episode_type TEXT,
    created_at TEXT NOT NULL
);

-- Episode-entity links
CREATE TABLE IF NOT EXISTS episode_entities (
    episode_id TEXT REFERENCES episodes(id) ON DELETE CASCADE,
    entity_id TEXT REFERENCES entities(id) ON DELETE CASCADE,
    PRIMARY KEY (episode_id, entity_id)
);

-- sqlite-vec virtual tables (sole vector storage)
CREATE VIRTUAL TABLE IF NOT EXISTS entity_vectors USING vec0(
    id TEXT PRIMARY KEY,
    embedding float[384]
);

CREATE VIRTUAL TABLE IF NOT EXISTS episode_vectors USING vec0(
    id TEXT PRIMARY KEY,
    embedding float[384]
);

-- Full-text search on entities
CREATE VIRTUAL TABLE IF NOT EXISTS entity_fts USING fts5(
    name, description, entity_type,
    content=entities, content_rowid=rowid
);

-- FTS sync triggers
CREATE TRIGGER IF NOT EXISTS entity_fts_insert AFTER INSERT ON entities BEGIN
    INSERT INTO entity_fts(rowid, name, description, entity_type)
    VALUES (new.rowid, new.name, new.description, new.entity_type);
END;

CREATE TRIGGER IF NOT EXISTS entity_fts_delete AFTER DELETE ON entities BEGIN
    INSERT INTO entity_fts(entity_fts, rowid, name, description, entity_type)
    VALUES ('delete', old.rowid, old.name, old.description, old.entity_type);
END;

CREATE TRIGGER IF NOT EXISTS entity_fts_update AFTER UPDATE ON entities BEGIN
    INSERT INTO entity_fts(entity_fts, rowid, name, description, entity_type)
    VALUES ('delete', old.rowid, old.name, old.description, old.entity_type);
    INSERT INTO entity_fts(rowid, name, description, entity_type)
    VALUES (new.rowid, new.name, new.description, new.entity_type);
END;
