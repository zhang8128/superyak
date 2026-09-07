CREATE TABLE IF NOT EXISTS shared_memories (
    share_id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    source_instance TEXT NOT NULL,
    source_id TEXT NOT NULL,
    layer TEXT NOT NULL,
    audience TEXT NOT NULL,
    reason TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    shared_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shared_memories_memory ON shared_memories(memory_id);
CREATE INDEX IF NOT EXISTS idx_shared_memories_audience ON shared_memories(audience);
CREATE UNIQUE INDEX IF NOT EXISTS idx_shared_memories_source
    ON shared_memories(source_instance, source_id, audience);
