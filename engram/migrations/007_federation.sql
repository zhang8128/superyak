-- Federation support: content_hash for dedup during genome sync,
-- context on instincts for session-type filtering.
ALTER TABLE episodes ADD COLUMN content_hash TEXT;
ALTER TABLE semantics ADD COLUMN content_hash TEXT;
ALTER TABLE instincts ADD COLUMN content_hash TEXT;
ALTER TABLE instincts ADD COLUMN context TEXT;
