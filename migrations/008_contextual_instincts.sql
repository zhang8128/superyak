-- Contextual instincts: perceptual attention directives with dual vectors and context feedback.
-- Adds notice/implication fields for perceptual framing and context vector support.

-- New fields on instincts for perceptual framing
ALTER TABLE instincts ADD COLUMN notice TEXT;
ALTER TABLE instincts ADD COLUMN implication TEXT;

-- Context vector table (separate from content vectors in instinct_vectors)
CREATE VIRTUAL TABLE IF NOT EXISTS instinct_context_vectors USING vec0(
    id TEXT PRIMARY KEY,
    embedding float[768]
);

-- Context feedback: per-situation follow/override tracking
CREATE TABLE IF NOT EXISTS instinct_context_feedback (
    id TEXT PRIMARY KEY,
    instinct_id TEXT NOT NULL REFERENCES instincts(id) ON DELETE CASCADE,
    context_text TEXT NOT NULL,
    context_embedding BLOB,
    followed BOOLEAN NOT NULL,
    timestamp TEXT NOT NULL
);
