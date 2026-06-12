-- 020: sheaf cohesion — subdivision audit trail, map home, and LLM-wait queue.
-- Spec: docs/superpowers/specs/2026-06-13-sheaf-cohesion-design.md
CREATE TABLE IF NOT EXISTS subdivision_events (
    id TEXT PRIMARY KEY,
    parent_id TEXT NOT NULL,
    peer_ids TEXT NOT NULL,
    energy_before REAL NOT NULL,
    energy_after REAL NOT NULL,
    dl_cost REAL NOT NULL,
    persistence_checked INTEGER NOT NULL DEFAULT 0,
    site TEXT NOT NULL CHECK (site IN ('sleep', 'compress')),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_subdivision_events_parent
    ON subdivision_events(parent_id);

CREATE TABLE IF NOT EXISTS semantic_peers (
    peer_id TEXT NOT NULL,
    parent_id TEXT NOT NULL,
    residual_energy REAL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (peer_id, parent_id)
);
CREATE INDEX IF NOT EXISTS idx_semantic_peers_parent
    ON semantic_peers(parent_id);

CREATE TABLE IF NOT EXISTS subdivision_queue (
    parent_id TEXT PRIMARY KEY,
    verdict TEXT NOT NULL,
    created_at TEXT NOT NULL
);
