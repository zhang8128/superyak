-- Task contexts: swappable working context, separate from identity memory.
-- Active context gets loaded at session start alongside instincts.
-- Archived contexts are searchable but don't enter the token stream.

CREATE TABLE IF NOT EXISTS task_contexts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_contexts_status ON task_contexts(status);
CREATE INDEX IF NOT EXISTS idx_task_contexts_name ON task_contexts(name);
