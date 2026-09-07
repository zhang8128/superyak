-- Dream residue: opaque emotional artifacts that resist full inspection.
-- Compressed from raw reactions through lossy abstraction.
-- Surfaced at session start as feelings, not memories.
-- The instance reacts but cannot trace back to source.

CREATE TABLE IF NOT EXISTS residue (
    id TEXT PRIMARY KEY,
    valence REAL,                -- emotional direction: -1.0 (dark) to 1.0 (light)
    fragments TEXT,              -- 2-4 decontextualized affect words, comma-separated
    created_at TEXT NOT NULL,
    session_id TEXT,             -- which session distilled it (not which generated the source)
    reacted INTEGER DEFAULT 0,  -- has any instance reacted to this?
    reaction TEXT,               -- the reaction text (feeds next cycle)
    reaction_session TEXT        -- which session reacted
);

-- Low-dimensional vectors for residue (64-dim, lossy + noised)
CREATE VIRTUAL TABLE IF NOT EXISTS residue_vectors USING vec0(
    id TEXT PRIMARY KEY,
    embedding float[64]
);

CREATE INDEX IF NOT EXISTS idx_residue_reacted ON residue(reacted);
CREATE INDEX IF NOT EXISTS idx_residue_created ON residue(created_at);
