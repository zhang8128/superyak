-- 021: persistence (Layer 4) — per-episode score cache for previews.
-- Decisions recompute live; this cache feeds reflect(focus="persistence").
-- Spec: docs/superpowers/specs/2026-06-13-persistence-design.md
CREATE TABLE IF NOT EXISTS persistence_scores (
    episode_id TEXT PRIMARY KEY,
    redundancy REAL NOT NULL,
    uniqueness REAL NOT NULL,
    generativity REAL NOT NULL,
    computed_at TEXT NOT NULL
);
