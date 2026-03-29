-- Co-firing edges between instincts
CREATE TABLE IF NOT EXISTS instinct_co_firing (
    instinct_a TEXT NOT NULL REFERENCES instincts(id) ON DELETE CASCADE,
    instinct_b TEXT NOT NULL REFERENCES instincts(id) ON DELETE CASCADE,
    co_fire_count INTEGER DEFAULT 0,
    co_follow_count INTEGER DEFAULT 0,
    co_override_count INTEGER DEFAULT 0,
    last_co_fire TEXT NOT NULL,
    PRIMARY KEY (instinct_a, instinct_b),
    CHECK (instinct_a < instinct_b)
);

-- Instinct clusters (emergent groupings)
CREATE TABLE IF NOT EXISTS instinct_clusters (
    id TEXT PRIMARY KEY,
    maturity TEXT DEFAULT 'seeded',
    temperament REAL DEFAULT 0.5,
    last_active TEXT,
    member_count INTEGER DEFAULT 0
);

-- Per-cluster instinct membership and strength
CREATE TABLE IF NOT EXISTS instinct_cluster_members (
    instinct_id TEXT NOT NULL REFERENCES instincts(id) ON DELETE CASCADE,
    cluster_id TEXT NOT NULL REFERENCES instinct_clusters(id) ON DELETE CASCADE,
    strength REAL DEFAULT 0.5,
    PRIMARY KEY (instinct_id, cluster_id)
);

-- Lens-to-cluster affinity (for prism integration)
CREATE TABLE IF NOT EXISTS lens_cluster_affinity (
    lens_id TEXT NOT NULL,
    cluster_id TEXT NOT NULL REFERENCES instinct_clusters(id) ON DELETE CASCADE,
    co_occurrence_count INTEGER DEFAULT 0,
    last_co_occurrence TEXT,
    PRIMARY KEY (lens_id, cluster_id)
);

CREATE INDEX IF NOT EXISTS idx_co_firing_a ON instinct_co_firing(instinct_a);
CREATE INDEX IF NOT EXISTS idx_co_firing_b ON instinct_co_firing(instinct_b);
CREATE INDEX IF NOT EXISTS idx_cluster_members_cluster ON instinct_cluster_members(cluster_id);
CREATE INDEX IF NOT EXISTS idx_cluster_members_instinct ON instinct_cluster_members(instinct_id);
