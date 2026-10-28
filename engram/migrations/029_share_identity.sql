-- Share identity (permissions by place, P 12.2): which store a placement came from, and which record placed it.
ALTER TABLE shared_memories ADD COLUMN source_instance_id TEXT;
ALTER TABLE shared_memories ADD COLUMN record_id TEXT;

-- A counter raised by every insert, update and delete on shared_memories. A row count or highest rowid would miss
-- a delete followed by an insert.
CREATE TABLE IF NOT EXISTS shared_memories_changes (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    count INTEGER NOT NULL
);
INSERT OR IGNORE INTO shared_memories_changes (id, count) VALUES (1, 0);

CREATE TRIGGER IF NOT EXISTS shared_memories_changes_insert AFTER INSERT ON shared_memories
BEGIN UPDATE shared_memories_changes SET count = count + 1 WHERE id = 1; END;
CREATE TRIGGER IF NOT EXISTS shared_memories_changes_update AFTER UPDATE ON shared_memories
BEGIN UPDATE shared_memories_changes SET count = count + 1 WHERE id = 1; END;
CREATE TRIGGER IF NOT EXISTS shared_memories_changes_delete AFTER DELETE ON shared_memories
BEGIN UPDATE shared_memories_changes SET count = count + 1 WHERE id = 1; END;
