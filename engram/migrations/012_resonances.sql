-- Lateral associations between memories that resonate without being equivalent.
-- Stochastic weight per-instance for individuality. Canonical ordering: memory_a < memory_b.
CREATE TABLE IF NOT EXISTS resonances (
    id TEXT PRIMARY KEY,
    memory_a TEXT NOT NULL,
    layer_a TEXT NOT NULL,
    memory_b TEXT NOT NULL,
    layer_b TEXT NOT NULL,
    similarity REAL,
    weight REAL NOT NULL,
    strength REAL NOT NULL DEFAULT 0.5,
    co_occurrences INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    UNIQUE(memory_a, memory_b)
);

CREATE INDEX IF NOT EXISTS idx_resonances_a ON resonances(memory_a);
CREATE INDEX IF NOT EXISTS idx_resonances_b ON resonances(memory_b);
