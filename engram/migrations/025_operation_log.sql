CREATE TABLE IF NOT EXISTS operation_log (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    operation TEXT NOT NULL,
    session_id TEXT,
    harness TEXT,
    model TEXT,
    repo TEXT,
    target_ids TEXT NOT NULL,
    details TEXT NOT NULL,
    outcome TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_operation_log_session ON operation_log(session_id);
CREATE INDEX IF NOT EXISTS idx_operation_log_timestamp ON operation_log(timestamp);
