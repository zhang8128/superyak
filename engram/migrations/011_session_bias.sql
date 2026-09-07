-- Session bias: instinct firings that tilt recall during a session.
-- Biases decay per message and reinforce on re-fire.
-- Not vec0 — embeddings used for blending, not search.

CREATE TABLE IF NOT EXISTS session_bias (
    instinct_id TEXT PRIMARY KEY,
    embedding BLOB NOT NULL,
    strength REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
