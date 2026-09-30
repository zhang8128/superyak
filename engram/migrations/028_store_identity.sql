-- Store identity. The storage migration runner assigns meta.instance_id
-- after this script, in the same transaction (store_identity.assign):
-- random for a store created by this open (origin 'creation'), otherwise
-- derived from the earliest episode (origin 'retroactive'; random when the
-- old store has no episodes). An existing instance_id is never replaced.
--
-- Provenance for episodes copied from another store (genome sync): the
-- source store's identity and the episode's original id and timestamp,
-- rather than only a fresh local UUID.
ALTER TABLE episodes ADD COLUMN origin_instance_id TEXT;
ALTER TABLE episodes ADD COLUMN origin_id TEXT;
ALTER TABLE episodes ADD COLUMN origin_created_at TEXT;
CREATE INDEX IF NOT EXISTS idx_episodes_origin ON episodes(origin_instance_id, origin_id);
