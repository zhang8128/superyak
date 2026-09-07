-- Upgrade vec0 tables from 384-dim (MiniLM) to 768-dim (nomic-embed-text-v1.5).
-- vec0 virtual tables can't be ALTERed — must drop and recreate.
-- Existing vectors are lost; they'll be re-embedded on next write/reindex.
-- Episodes and semantics retain their text content — only the vector index is rebuilt.

DROP TABLE IF EXISTS entity_vectors;
DROP TABLE IF EXISTS episode_vectors;
DROP TABLE IF EXISTS semantic_vectors;

CREATE VIRTUAL TABLE entity_vectors USING vec0(
    id TEXT PRIMARY KEY,
    embedding float[768]
);

CREATE VIRTUAL TABLE episode_vectors USING vec0(
    id TEXT PRIMARY KEY,
    embedding float[768]
);

CREATE VIRTUAL TABLE semantic_vectors USING vec0(
    id TEXT PRIMARY KEY,
    embedding float[768]
);

-- Add decay_strength column to episodes for forgetting mechanism.
-- 1.0 = full strength (new), decays toward 0.0 over time without access.
ALTER TABLE episodes ADD COLUMN decay_strength REAL DEFAULT 1.0;
