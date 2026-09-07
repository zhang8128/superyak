-- Add vector search for instincts.
-- Previously instincts used keyword matching; now they use embedding similarity
-- like episodes and semantics. Existing instincts will be backfilled on server init.

CREATE VIRTUAL TABLE IF NOT EXISTS instinct_vectors USING vec0(
    id TEXT PRIMARY KEY,
    embedding float[768]
);
