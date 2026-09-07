-- Runtime-only bridge between Codex hook identity and its stdio MCP process.
-- Never rendered in a working surface; durable provenance remains in session_registry.
CREATE TABLE IF NOT EXISTS session_bindings (
    run_key    TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    bound_at   TEXT NOT NULL
);
