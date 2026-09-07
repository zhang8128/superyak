-- Core episodes: exempt from decay, preserve formative evidence.
-- Source: cross-system provenance tagging.
ALTER TABLE episodes ADD COLUMN core INTEGER NOT NULL DEFAULT 0;
ALTER TABLE episodes ADD COLUMN source TEXT;
