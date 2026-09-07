-- Dormant episodes: soft-deleted by decay, revivable on demand.
-- Dormant episodes stay in vec0 but are skipped during normal recall.
ALTER TABLE episodes ADD COLUMN dormant INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_episodes_dormant ON episodes(dormant);
