-- 018: memory lanes — separate work (reference) from personal (identity) content.
-- Work-lane memories decay and recall normally but never become core episodes,
-- instincts, or reinforcement for personal semantics.
ALTER TABLE episodes ADD COLUMN lane TEXT NOT NULL DEFAULT 'personal'
    CHECK (lane IN ('personal', 'work'));
ALTER TABLE semantics ADD COLUMN lane TEXT NOT NULL DEFAULT 'personal'
    CHECK (lane IN ('personal', 'work'));
CREATE INDEX IF NOT EXISTS idx_episodes_lane ON episodes(lane);
CREATE INDEX IF NOT EXISTS idx_semantics_lane ON semantics(lane);
