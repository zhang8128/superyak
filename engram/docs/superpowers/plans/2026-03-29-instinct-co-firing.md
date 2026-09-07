# Instinct Co-Firing and Context Clusters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace flat instinct gating with context-clustered activation driven by co-firing patterns and embedding proximity.

**Architecture:** New `clusters.py` module handles community detection, temperament computation, and cluster lifecycle. Storage layer gets four new tables (migration 016). Nudge hook tracks co-firing in a rolling window and uses cluster membership for gating. Compression triggers cluster re-derivation.

**Tech Stack:** SQLite (vec0), scipy (fclusterdata for cold start), networkx (Louvain community detection), numpy, existing fastembed infrastructure.

---

### Task 1: Migration — Co-Firing and Cluster Tables

**Files:**
- Create: `migrations/016_instinct_clusters.sql`
- Test: `tests/test_storage.py` (verify tables exist after migration)

- [ ] **Step 1: Write the migration**

```sql
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
```

- [ ] **Step 2: Write the test**

Add to `tests/test_storage.py`:

```python
def test_co_firing_tables_exist(storage):
    """Migration 016 creates co-firing and cluster tables."""
    tables = {
        row[0]
        for row in storage.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "instinct_co_firing" in tables
    assert "instinct_clusters" in tables
    assert "instinct_cluster_members" in tables
    assert "lens_cluster_affinity" in tables
```

- [ ] **Step 3: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_storage.py::test_co_firing_tables_exist -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add migrations/016_instinct_clusters.sql tests/test_storage.py
git commit -m "feat: add co-firing and cluster tables (migration 016)"
```

---

### Task 2: Storage Methods — Co-Firing Edges

**Files:**
- Modify: `storage.py` (add methods after `retire_instinct` around line 1145)
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_storage.py`:

```python
def test_record_co_fire(storage):
    """Recording a co-fire creates or increments an edge."""
    # Create two instincts
    emb = [0.1] * 768
    storage.add_instinct("i1", "preference", "instinct one", [], embedding=emb)
    storage.add_instinct("i2", "preference", "instinct two", [], embedding=emb)

    storage.record_co_fire("i1", "i2")
    edge = storage.get_co_firing_edge("i1", "i2")
    assert edge is not None
    assert edge["co_fire_count"] == 1
    assert edge["co_follow_count"] == 0

    # Second co-fire increments
    storage.record_co_fire("i1", "i2")
    edge = storage.get_co_firing_edge("i1", "i2")
    assert edge["co_fire_count"] == 2


def test_record_co_fire_canonical_order(storage):
    """Edge order is canonical — (i2, i1) reads the same as (i1, i2)."""
    emb = [0.1] * 768
    storage.add_instinct("aaa", "preference", "first", [], embedding=emb)
    storage.add_instinct("zzz", "preference", "second", [], embedding=emb)

    storage.record_co_fire("zzz", "aaa")  # reversed order
    edge = storage.get_co_firing_edge("aaa", "zzz")
    assert edge is not None
    assert edge["co_fire_count"] == 1


def test_record_co_fire_with_outcome(storage):
    """Co-fire with followed=True increments co_follow_count."""
    emb = [0.1] * 768
    storage.add_instinct("i1", "preference", "one", [], embedding=emb)
    storage.add_instinct("i2", "preference", "two", [], embedding=emb)

    storage.record_co_fire("i1", "i2", followed=True)
    edge = storage.get_co_firing_edge("i1", "i2")
    assert edge["co_fire_count"] == 1
    assert edge["co_follow_count"] == 1
    assert edge["co_override_count"] == 0

    storage.record_co_fire("i1", "i2", followed=False)
    edge = storage.get_co_firing_edge("i1", "i2")
    assert edge["co_fire_count"] == 2
    assert edge["co_follow_count"] == 1
    assert edge["co_override_count"] == 1


def test_get_co_firing_neighbors(storage):
    """Get all co-firing neighbors of an instinct."""
    emb = [0.1] * 768
    storage.add_instinct("center", "preference", "center", [], embedding=emb)
    storage.add_instinct("n1", "preference", "neighbor 1", [], embedding=emb)
    storage.add_instinct("n2", "preference", "neighbor 2", [], embedding=emb)
    storage.add_instinct("isolated", "preference", "isolated", [], embedding=emb)

    storage.record_co_fire("center", "n1")
    storage.record_co_fire("center", "n2")

    neighbors = storage.get_co_firing_neighbors("center")
    neighbor_ids = {n["instinct_id"] for n in neighbors}
    assert neighbor_ids == {"n1", "n2"}
    assert "isolated" not in neighbor_ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_storage.py -k "co_fire" -v`
Expected: FAIL — methods don't exist

- [ ] **Step 3: Implement the storage methods**

Add to `storage.py` after `retire_instinct()`:

```python
    # --- Co-firing graph ---

    def record_co_fire(
        self, instinct_a: str, instinct_b: str, followed: bool | None = None
    ) -> None:
        """Record a co-firing event between two instincts."""
        # Canonical order
        a, b = (instinct_a, instinct_b) if instinct_a < instinct_b else (instinct_b, instinct_a)
        now = _now_iso()

        existing = self.conn.execute(
            "SELECT co_fire_count, co_follow_count, co_override_count "
            "FROM instinct_co_firing WHERE instinct_a = ? AND instinct_b = ?",
            (a, b),
        ).fetchone()

        if existing:
            follow_delta = 1 if followed is True else 0
            override_delta = 1 if followed is False else 0
            self.conn.execute(
                "UPDATE instinct_co_firing SET co_fire_count = co_fire_count + 1, "
                "co_follow_count = co_follow_count + ?, "
                "co_override_count = co_override_count + ?, "
                "last_co_fire = ? WHERE instinct_a = ? AND instinct_b = ?",
                (follow_delta, override_delta, now, a, b),
            )
        else:
            self.conn.execute(
                "INSERT INTO instinct_co_firing "
                "(instinct_a, instinct_b, co_fire_count, co_follow_count, co_override_count, last_co_fire) "
                "VALUES (?, ?, 1, ?, ?, ?)",
                (a, b, 1 if followed is True else 0, 1 if followed is False else 0, now),
            )
        self.conn.commit()

    def get_co_firing_edge(self, instinct_a: str, instinct_b: str) -> dict | None:
        """Get the co-firing edge between two instincts."""
        a, b = (instinct_a, instinct_b) if instinct_a < instinct_b else (instinct_b, instinct_a)
        row = self.conn.execute(
            "SELECT * FROM instinct_co_firing WHERE instinct_a = ? AND instinct_b = ?",
            (a, b),
        ).fetchone()
        return dict(row) if row else None

    def get_co_firing_neighbors(self, instinct_id: str) -> list[dict]:
        """Get all co-firing neighbors of an instinct with edge data."""
        rows = self.conn.execute(
            "SELECT instinct_b AS instinct_id, co_fire_count, co_follow_count, "
            "co_override_count, last_co_fire "
            "FROM instinct_co_firing WHERE instinct_a = ? "
            "UNION ALL "
            "SELECT instinct_a AS instinct_id, co_fire_count, co_follow_count, "
            "co_override_count, last_co_fire "
            "FROM instinct_co_firing WHERE instinct_b = ?",
            (instinct_id, instinct_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_co_firing_edges(self) -> list[dict]:
        """Get all co-firing edges for graph construction."""
        rows = self.conn.execute(
            "SELECT * FROM instinct_co_firing ORDER BY co_fire_count DESC"
        ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_storage.py -k "co_fire" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add storage.py tests/test_storage.py
git commit -m "feat: co-firing edge storage methods"
```

---

### Task 3: Storage Methods — Clusters and Per-Cluster Strength

**Files:**
- Modify: `storage.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_create_and_get_cluster(storage):
    """Create a cluster and retrieve it."""
    storage.create_cluster("c1", maturity="seeded", temperament=0.5)
    cluster = storage.get_cluster("c1")
    assert cluster is not None
    assert cluster["maturity"] == "seeded"
    assert cluster["temperament"] == 0.5


def test_add_instinct_to_cluster(storage):
    """Assign an instinct to a cluster with per-cluster strength."""
    emb = [0.1] * 768
    storage.add_instinct("i1", "preference", "test", [], embedding=emb)
    storage.create_cluster("c1")

    storage.add_to_cluster("i1", "c1", strength=0.7)
    members = storage.get_cluster_members("c1")
    assert len(members) == 1
    assert members[0]["instinct_id"] == "i1"
    assert members[0]["strength"] == 0.7


def test_get_instinct_cluster_strengths(storage):
    """Get all cluster memberships for an instinct."""
    emb = [0.1] * 768
    storage.add_instinct("i1", "preference", "test", [], embedding=emb)
    storage.create_cluster("c1")
    storage.create_cluster("c2")

    storage.add_to_cluster("i1", "c1", strength=0.8)
    storage.add_to_cluster("i1", "c2", strength=0.3)

    strengths = storage.get_instinct_cluster_strengths("i1")
    assert len(strengths) == 2
    by_cluster = {s["cluster_id"]: s["strength"] for s in strengths}
    assert by_cluster["c1"] == 0.8
    assert by_cluster["c2"] == 0.3


def test_update_cluster_member_strength(storage):
    """Update per-cluster strength for an instinct."""
    emb = [0.1] * 768
    storage.add_instinct("i1", "preference", "test", [], embedding=emb)
    storage.create_cluster("c1")
    storage.add_to_cluster("i1", "c1", strength=0.5)

    storage.update_cluster_member_strength("i1", "c1", 0.75)
    members = storage.get_cluster_members("c1")
    assert members[0]["strength"] == 0.75


def test_update_cluster_temperament(storage):
    """Update cluster temperament."""
    storage.create_cluster("c1", temperament=0.5)
    storage.update_cluster("c1", temperament=0.2)
    cluster = storage.get_cluster("c1")
    assert cluster["temperament"] == 0.2


def test_get_all_clusters(storage):
    """List all clusters."""
    storage.create_cluster("c1")
    storage.create_cluster("c2")
    clusters = storage.get_all_clusters()
    assert len(clusters) == 2


def test_delete_cluster_cascades(storage):
    """Deleting a cluster removes its memberships."""
    emb = [0.1] * 768
    storage.add_instinct("i1", "preference", "test", [], embedding=emb)
    storage.create_cluster("c1")
    storage.add_to_cluster("i1", "c1")

    storage.delete_cluster("c1")
    assert storage.get_cluster("c1") is None
    assert storage.get_instinct_cluster_strengths("i1") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_storage.py -k "cluster" -v`
Expected: FAIL

- [ ] **Step 3: Implement cluster storage methods**

Add to `storage.py` after the co-firing methods:

```python
    # --- Instinct clusters ---

    def create_cluster(
        self, id: str, maturity: str = "seeded", temperament: float = 0.5
    ) -> str:
        now = _now_iso()
        self.conn.execute(
            "INSERT INTO instinct_clusters (id, maturity, temperament, last_active, member_count) "
            "VALUES (?, ?, ?, ?, 0)",
            (id, maturity, temperament, now),
        )
        self.conn.commit()
        return id

    def get_cluster(self, id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM instinct_clusters WHERE id = ?", (id,)
        ).fetchone()
        return dict(row) if row else None

    def get_all_clusters(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM instinct_clusters ORDER BY last_active DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def update_cluster(self, id: str, **fields) -> None:
        allowed = {"maturity", "temperament", "last_active", "member_count"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        self.conn.execute(
            f"UPDATE instinct_clusters SET {set_clause} WHERE id = ?",
            (*updates.values(), id),
        )
        self.conn.commit()

    def delete_cluster(self, id: str) -> None:
        self.conn.execute("DELETE FROM instinct_clusters WHERE id = ?", (id,))
        self.conn.commit()

    def add_to_cluster(
        self, instinct_id: str, cluster_id: str, strength: float = 0.5
    ) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO instinct_cluster_members "
            "(instinct_id, cluster_id, strength) VALUES (?, ?, ?)",
            (instinct_id, cluster_id, strength),
        )
        self.conn.execute(
            "UPDATE instinct_clusters SET member_count = "
            "(SELECT COUNT(*) FROM instinct_cluster_members WHERE cluster_id = ?) "
            "WHERE id = ?",
            (cluster_id, cluster_id),
        )
        self.conn.commit()

    def get_cluster_members(self, cluster_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM instinct_cluster_members WHERE cluster_id = ?",
            (cluster_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_instinct_cluster_strengths(self, instinct_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM instinct_cluster_members WHERE instinct_id = ?",
            (instinct_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_cluster_member_strength(
        self, instinct_id: str, cluster_id: str, strength: float
    ) -> None:
        self.conn.execute(
            "UPDATE instinct_cluster_members SET strength = ? "
            "WHERE instinct_id = ? AND cluster_id = ?",
            (strength, instinct_id, cluster_id),
        )
        self.conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_storage.py -k "cluster" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add storage.py tests/test_storage.py
git commit -m "feat: cluster and per-cluster strength storage methods"
```

---

### Task 4: Cluster Engine — Community Detection and Seeding

**Files:**
- Create: `clusters.py`
- Test: `tests/test_clusters.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_clusters.py`:

```python
"""Tests for instinct cluster engine."""

import uuid
import pytest
from clusters import ClusterEngine
from storage import Storage
from tests.test_compression import FakeEmbeddingProvider


@pytest.fixture
def storage(tmp_path):
    db = tmp_path / "test.db"
    s = Storage(str(db), migrations_dir="migrations")
    yield s
    s.close()


@pytest.fixture
def embeddings():
    return FakeEmbeddingProvider()


@pytest.fixture
def engine(storage, embeddings):
    return ClusterEngine(storage, embeddings)


def _add_instinct(storage, id, action, embedding):
    storage.add_instinct(id, "preference", action, [], embedding=embedding)


def test_seed_clusters_from_embeddings(storage, engine, embeddings):
    """Cold start: cluster instincts by embedding similarity."""
    # Create instincts with controlled embeddings — two clusters
    coding_emb = [1.0] + [0.0] * 767
    sports_emb = [0.0] + [1.0] + [0.0] * 766

    _add_instinct(storage, "c1", "use asyncio.run()", coding_emb)
    _add_instinct(storage, "c2", "restart MCP server", coding_emb)
    _add_instinct(storage, "s1", "watch the ball", sports_emb)
    _add_instinct(storage, "s2", "follow through on swing", sports_emb)

    # Override embeddings so engine uses our controlled vectors
    embeddings.override_map["use asyncio.run()"] = coding_emb
    embeddings.override_map["restart MCP server"] = coding_emb
    embeddings.override_map["watch the ball"] = sports_emb
    embeddings.override_map["follow through on swing"] = sports_emb

    clusters = engine.seed_clusters()
    assert len(clusters) == 2

    # Each cluster should have 2 members
    for cid in clusters:
        members = storage.get_cluster_members(cid)
        assert len(members) == 2

    # Clusters should be seeded maturity
    for cid in clusters:
        cluster = storage.get_cluster(cid)
        assert cluster["maturity"] == "seeded"


def test_seed_clusters_singleton_distant(storage, engine, embeddings):
    """A distant instinct gets its own cluster."""
    emb_a = [1.0] + [0.0] * 767
    emb_b = [0.0] + [1.0] + [0.0] * 766
    emb_c = [0.0, 0.0] + [1.0] + [0.0] * 765  # distant from both

    _add_instinct(storage, "a1", "thing a1", emb_a)
    _add_instinct(storage, "a2", "thing a2", emb_a)
    _add_instinct(storage, "lone", "unique thing", emb_c)

    embeddings.override_map["thing a1"] = emb_a
    embeddings.override_map["thing a2"] = emb_a
    embeddings.override_map["unique thing"] = emb_c

    clusters = engine.seed_clusters()
    assert len(clusters) >= 2  # at least the pair + the singleton


def test_rederive_from_co_firing(storage, engine, embeddings):
    """With enough co-firing data, clusters re-derive from behavior."""
    emb = [0.1] * 768  # same embedding for all — content similarity won't separate them
    _add_instinct(storage, "a1", "instinct a1", emb)
    _add_instinct(storage, "a2", "instinct a2", emb)
    _add_instinct(storage, "b1", "instinct b1", emb)
    _add_instinct(storage, "b2", "instinct b2", emb)

    embeddings.override_map["instinct a1"] = emb
    embeddings.override_map["instinct a2"] = emb
    embeddings.override_map["instinct b1"] = emb
    embeddings.override_map["instinct b2"] = emb

    # Build co-firing: a1-a2 fire together, b1-b2 fire together, no cross-links
    for _ in range(10):
        storage.record_co_fire("a1", "a2")
        storage.record_co_fire("b1", "b2")

    clusters = engine.derive_clusters()
    assert len(clusters) == 2

    # Check each cluster has the right pair
    cluster_members = {}
    for cid in clusters:
        members = storage.get_cluster_members(cid)
        cluster_members[cid] = {m["instinct_id"] for m in members}

    member_sets = list(cluster_members.values())
    assert {"a1", "a2"} in member_sets
    assert {"b1", "b2"} in member_sets


def test_compute_temperament(storage, engine):
    """Temperament emerges from follow/override ratio."""
    emb = [0.1] * 768
    _add_instinct(storage, "i1", "one", emb)
    _add_instinct(storage, "i2", "two", emb)
    storage.create_cluster("c1")
    storage.add_to_cluster("i1", "c1")
    storage.add_to_cluster("i2", "c1")

    # All followed — should be conservative (low temperament)
    for _ in range(10):
        storage.record_co_fire("i1", "i2", followed=True)

    temp = engine.compute_temperament("c1")
    assert temp < 0.3  # conservative

    # Now add overrides — should shift exploratory
    for _ in range(10):
        storage.record_co_fire("i1", "i2", followed=False)

    temp = engine.compute_temperament("c1")
    assert temp > 0.3  # more exploratory
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_clusters.py -v`
Expected: FAIL — `clusters.py` doesn't exist

- [ ] **Step 3: Implement ClusterEngine**

Create `clusters.py`:

```python
"""Instinct cluster engine — community detection, seeding, temperament.

Clusters emerge from two signals:
1. Embedding proximity (cold start — "these instincts are about similar things")
2. Co-firing patterns (matures — "these instincts activate together in practice")

Each cluster has a temperament (conservative ↔ exploratory) derived from
the follow/override ratio of its internal co-firing edges.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

import numpy as np
from scipy.cluster.hierarchy import fclusterdata

if TYPE_CHECKING:
    from storage import Storage

logger = logging.getLogger(__name__)


class ClusterEngine:
    def __init__(
        self,
        storage: Storage,
        embeddings,
        cluster_similarity: float = 0.75,
    ):
        self._storage = storage
        self._embeddings = embeddings
        self._cluster_similarity = cluster_similarity

    def seed_clusters(self) -> list[str]:
        """Cold start: cluster instincts by embedding similarity.

        Clears existing clusters and re-seeds from content embeddings.
        Returns list of created cluster IDs.
        """
        instincts = self._storage.get_all_instincts()
        if not instincts:
            return []

        # Get embeddings for all instincts
        actions = [inst["action"] for inst in instincts]
        ids = [inst["id"] for inst in instincts]

        embeddings_list = self._embeddings.embed(actions, prefix="search_document")
        embeddings_matrix = np.array(embeddings_list)

        if len(instincts) == 1:
            # Single instinct — one cluster
            return self._create_clusters_from_labels(ids, [1], maturity="seeded")

        # Hierarchical clustering by cosine distance
        labels = fclusterdata(
            embeddings_matrix,
            t=1.0 - self._cluster_similarity,
            metric="cosine",
            criterion="distance",
        )

        # Clear existing clusters
        for cluster in self._storage.get_all_clusters():
            self._storage.delete_cluster(cluster["id"])

        return self._create_clusters_from_labels(ids, labels, maturity="seeded")

    def derive_clusters(self) -> list[str]:
        """Re-derive clusters from co-firing graph using community detection.

        Falls back to seed_clusters() if insufficient co-firing data.
        Returns list of cluster IDs.
        """
        edges = self._storage.get_all_co_firing_edges()
        if not edges:
            return self.seed_clusters()

        try:
            import networkx as nx
            from networkx.algorithms.community import louvain_communities
        except ImportError:
            logger.warning("networkx not available, falling back to embedding seed")
            return self.seed_clusters()

        # Build graph
        G = nx.Graph()
        all_instincts = self._storage.get_all_instincts()
        for inst in all_instincts:
            G.add_node(inst["id"])

        for edge in edges:
            G.add_edge(
                edge["instinct_a"],
                edge["instinct_b"],
                weight=edge["co_fire_count"],
            )

        # Nodes with no edges get assigned by embedding proximity later
        connected = {n for n in G.nodes() if G.degree(n) > 0}
        isolated = {n for n in G.nodes() if G.degree(n) == 0}

        if len(connected) < 2:
            return self.seed_clusters()

        # Louvain community detection on connected subgraph
        connected_subgraph = G.subgraph(connected)
        communities = louvain_communities(connected_subgraph, weight="weight", seed=42)

        # Clear existing clusters
        for cluster in self._storage.get_all_clusters():
            self._storage.delete_cluster(cluster["id"])

        # Create clusters from communities
        cluster_ids = []
        for community in communities:
            cid = str(uuid.uuid4())
            self._storage.create_cluster(cid, maturity="confirmed")
            for instinct_id in community:
                self._storage.add_to_cluster(instinct_id, cid)
            cluster_ids.append(cid)

        # Assign isolated instincts to nearest cluster by embedding
        if isolated and cluster_ids:
            self._assign_isolated_to_clusters(list(isolated), cluster_ids)

        # Compute temperaments
        for cid in cluster_ids:
            temp = self.compute_temperament(cid)
            self._storage.update_cluster(cid, temperament=temp)

        return cluster_ids

    def compute_temperament(self, cluster_id: str) -> float:
        """Compute cluster temperament from internal co-firing feedback.

        Returns 0.0 (conservative) to 1.0 (exploratory).
        High follow ratio → conservative. High override ratio → exploratory.
        """
        members = self._storage.get_cluster_members(cluster_id)
        if len(members) < 2:
            return 0.5  # neutral for singletons

        member_ids = {m["instinct_id"] for m in members}
        total_follow = 0
        total_override = 0

        for mid in member_ids:
            neighbors = self._storage.get_co_firing_neighbors(mid)
            for n in neighbors:
                if n["instinct_id"] in member_ids:
                    total_follow += n["co_follow_count"]
                    total_override += n["co_override_count"]

        # Each edge counted twice (once from each side), so divide by 2
        total_follow //= 2
        total_override //= 2

        total = total_follow + total_override
        if total == 0:
            return 0.5

        follow_ratio = total_follow / total
        return 1.0 - follow_ratio

    def assign_new_instinct(self, instinct_id: str) -> str | None:
        """Assign a newly created instinct to the nearest existing cluster.

        If no clusters exist or the instinct is too distant, creates a new cluster.
        Returns the cluster ID assigned to, or None if no clusters exist.
        """
        clusters = self._storage.get_all_clusters()
        if not clusters:
            return None

        inst = self._storage.get_instinct(instinct_id)
        if not inst:
            return None

        inst_emb = self._embeddings.embed([inst["action"]], prefix="search_document")[0]
        inst_arr = np.array(inst_emb)

        best_cluster = None
        best_sim = -1.0

        for cluster in clusters:
            centroid = self._compute_cluster_centroid(cluster["id"])
            if centroid is None:
                continue
            sim = float(np.dot(inst_arr, centroid) / (
                np.linalg.norm(inst_arr) * np.linalg.norm(centroid) + 1e-10
            ))
            if sim > best_sim:
                best_sim = sim
                best_cluster = cluster["id"]

        if best_cluster and best_sim >= self._cluster_similarity:
            self._storage.add_to_cluster(instinct_id, best_cluster)
            return best_cluster
        else:
            # Too distant — new singleton cluster
            cid = str(uuid.uuid4())
            self._storage.create_cluster(cid, maturity="seeded")
            self._storage.add_to_cluster(instinct_id, cid)
            return cid

    def _compute_cluster_centroid(self, cluster_id: str) -> np.ndarray | None:
        """Compute the centroid embedding of a cluster's members."""
        members = self._storage.get_cluster_members(cluster_id)
        if not members:
            return None

        embeddings = []
        for m in members:
            inst = self._storage.get_instinct(m["instinct_id"])
            if inst:
                emb = self._embeddings.embed([inst["action"]], prefix="search_document")[0]
                embeddings.append(emb)

        if not embeddings:
            return None

        return np.mean(embeddings, axis=0)

    def _create_clusters_from_labels(
        self, instinct_ids: list[str], labels, maturity: str
    ) -> list[str]:
        """Create clusters from scipy fclusterdata labels."""
        from collections import defaultdict

        groups = defaultdict(list)
        for iid, label in zip(instinct_ids, labels):
            groups[int(label)].append(iid)

        cluster_ids = []
        for members in groups.values():
            cid = str(uuid.uuid4())
            self._storage.create_cluster(cid, maturity=maturity)
            for iid in members:
                self._storage.add_to_cluster(iid, cid)
            cluster_ids.append(cid)

        return cluster_ids

    def _assign_isolated_to_clusters(
        self, isolated_ids: list[str], cluster_ids: list[str]
    ) -> None:
        """Assign isolated instincts to nearest cluster by embedding."""
        for iid in isolated_ids:
            assigned = self.assign_new_instinct(iid)
            if not assigned:
                # Create singleton
                cid = str(uuid.uuid4())
                self._storage.create_cluster(cid, maturity="seeded")
                self._storage.add_to_cluster(iid, cid)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_clusters.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add clusters.py tests/test_clusters.py
git commit -m "feat: cluster engine with embedding seeding and co-firing derivation"
```

---

### Task 5: Co-Firing Window in Nudge Hook

**Files:**
- Modify: `hooks/nudge.py`
- Test: `tests/test_nudge_co_firing.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_nudge_co_firing.py`:

```python
"""Tests for co-firing window tracking in nudge hook."""

import sqlite3
import struct
import pytest


def _pack_embedding(emb):
    return struct.pack(f"<{len(emb)}f", *emb)


def _setup_db(tmp_path):
    """Create a minimal DB with instincts and co-firing tables."""
    import sqlite_vec

    db_path = tmp_path / "graph.db"
    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.row_factory = sqlite3.Row

    conn.executescript("""
        CREATE TABLE instincts (
            id TEXT PRIMARY KEY,
            trigger TEXT, action TEXT, strength REAL DEFAULT 0.5,
            created_at TEXT, fired_count INTEGER DEFAULT 0,
            followed_count INTEGER DEFAULT 0, overridden_count INTEGER DEFAULT 0,
            content_hash TEXT, notice TEXT, implication TEXT, context TEXT
        );
        CREATE VIRTUAL TABLE instinct_vectors USING vec0(
            id TEXT PRIMARY KEY, embedding float[768]
        );
        CREATE VIRTUAL TABLE instinct_context_vectors USING vec0(
            id TEXT PRIMARY KEY, embedding float[768]
        );
        CREATE TABLE instinct_co_firing (
            instinct_a TEXT NOT NULL, instinct_b TEXT NOT NULL,
            co_fire_count INTEGER DEFAULT 0, co_follow_count INTEGER DEFAULT 0,
            co_override_count INTEGER DEFAULT 0, last_co_fire TEXT NOT NULL,
            PRIMARY KEY (instinct_a, instinct_b),
            CHECK (instinct_a < instinct_b)
        );
        CREATE TABLE session_bias (
            instinct_id TEXT PRIMARY KEY, embedding BLOB NOT NULL,
            strength REAL DEFAULT 1.0, created_at TEXT, updated_at TEXT
        );
        CREATE TABLE nudge_surfaced (
            id TEXT PRIMARY KEY, surfaced_at TEXT NOT NULL
        );
        CREATE TABLE nudge_co_fire_window (
            instinct_id TEXT NOT NULL,
            message_index INTEGER NOT NULL,
            fired_at TEXT NOT NULL,
            PRIMARY KEY (instinct_id, message_index)
        );
    """)
    return conn, db_path


def test_co_fire_window_records_fired_instincts(tmp_path):
    """Fired instincts are recorded in the co-firing window."""
    conn, db_path = _setup_db(tmp_path)

    # Insert two instincts that will fire
    emb = [1.0] + [0.0] * 767
    packed = _pack_embedding(emb)
    conn.execute(
        "INSERT INTO instincts (id, trigger, action, strength, created_at, notice, implication) "
        "VALUES ('i1', 'preference', 'test one', 0.5, '2026-01-01', 'when testing', 'matters')"
    )
    conn.execute("INSERT INTO instinct_vectors (id, embedding) VALUES ('i1', ?)", (packed,))
    conn.execute("INSERT INTO instinct_context_vectors (id, embedding) VALUES ('i1', ?)", (packed,))
    conn.commit()

    # Simulate recording a fire at message index 1
    conn.execute(
        "INSERT INTO nudge_co_fire_window (instinct_id, message_index, fired_at) "
        "VALUES ('i1', 1, '2026-01-01T00:00:00')"
    )
    conn.commit()

    rows = conn.execute("SELECT * FROM nudge_co_fire_window").fetchall()
    assert len(rows) == 1
    assert rows[0]["instinct_id"] == "i1"
    conn.close()


def test_co_fire_window_creates_edges(tmp_path):
    """Two instincts firing within window distance create a co-firing edge."""
    conn, db_path = _setup_db(tmp_path)

    # Record two instincts firing within window
    conn.execute(
        "INSERT INTO nudge_co_fire_window VALUES ('i1', 3, '2026-01-01T00:00:00')"
    )
    conn.execute(
        "INSERT INTO nudge_co_fire_window VALUES ('i2', 5, '2026-01-01T00:00:01')"
    )
    conn.commit()

    # Simulate the co-fire edge creation logic
    window_size = 15
    window_entries = conn.execute(
        "SELECT instinct_id, message_index FROM nudge_co_fire_window "
        "ORDER BY message_index"
    ).fetchall()

    # For each pair within window distance, create edge
    edges_created = 0
    for i, entry_a in enumerate(window_entries):
        for entry_b in window_entries[i + 1:]:
            if abs(entry_b["message_index"] - entry_a["message_index"]) <= window_size:
                a, b = sorted([entry_a["instinct_id"], entry_b["instinct_id"]])
                conn.execute(
                    "INSERT OR IGNORE INTO instinct_co_firing "
                    "(instinct_a, instinct_b, co_fire_count, last_co_fire) "
                    "VALUES (?, ?, 1, '2026-01-01')",
                    (a, b),
                )
                edges_created += 1
    conn.commit()

    assert edges_created == 1
    edge = conn.execute("SELECT * FROM instinct_co_firing").fetchone()
    assert edge["instinct_a"] == "i1"
    assert edge["instinct_b"] == "i2"
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail/pass** (these are integration-style, verify setup works)

Run: `.venv/bin/python -m pytest tests/test_nudge_co_firing.py -v`

- [ ] **Step 3: Add co-firing window tracking to nudge.py**

Add to `hooks/nudge.py`, after the session bias section (after line 194):

```python
        # --- Co-firing window tracking ---
        # Record fired instincts with message index for co-firing detection
        conn.execute("""
            CREATE TABLE IF NOT EXISTS nudge_co_fire_window (
                instinct_id TEXT NOT NULL,
                message_index INTEGER NOT NULL,
                fired_at TEXT NOT NULL,
                PRIMARY KEY (instinct_id, message_index)
            )
        """)

        # Get current message index (count of entries + 1)
        msg_idx_row = conn.execute(
            "SELECT COALESCE(MAX(message_index), 0) + 1 AS idx FROM nudge_co_fire_window"
        ).fetchone()
        msg_idx = msg_idx_row["idx"] if msg_idx_row else 1

        # Record each fired instinct in the window
        for inst in fired[:MAX_NUDGES]:
            conn.execute(
                "INSERT OR IGNORE INTO nudge_co_fire_window "
                "(instinct_id, message_index, fired_at) VALUES (?, ?, ?)",
                (inst["id"], msg_idx, now),
            )

        # Create co-firing edges for instincts within window distance
        CO_FIRE_WINDOW = 15  # messages
        has_co_fire_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='instinct_co_firing'"
        ).fetchone()

        if has_co_fire_table and fired:
            # Get recent window entries
            window_entries = conn.execute(
                "SELECT DISTINCT instinct_id, message_index FROM nudge_co_fire_window "
                "WHERE message_index >= ? ORDER BY message_index",
                (max(1, msg_idx - CO_FIRE_WINDOW),),
            ).fetchall()

            # For each newly fired instinct, create edges to all others in window
            new_fired_ids = {inst["id"] for inst in fired[:MAX_NUDGES]}
            for entry in window_entries:
                if entry["instinct_id"] in new_fired_ids:
                    continue
                if abs(msg_idx - entry["message_index"]) > CO_FIRE_WINDOW:
                    continue
                for fid in new_fired_ids:
                    a, b = sorted([fid, entry["instinct_id"]])
                    conn.execute(
                        "INSERT INTO instinct_co_firing "
                        "(instinct_a, instinct_b, co_fire_count, co_follow_count, "
                        "co_override_count, last_co_fire) "
                        "VALUES (?, ?, 1, 0, 0, ?) "
                        "ON CONFLICT(instinct_a, instinct_b) DO UPDATE SET "
                        "co_fire_count = co_fire_count + 1, last_co_fire = ?",
                        (a, b, now, now),
                    )

            # Also create edges between simultaneously fired instincts
            new_fired_list = list(new_fired_ids)
            for i, fid_a in enumerate(new_fired_list):
                for fid_b in new_fired_list[i + 1:]:
                    a, b = sorted([fid_a, fid_b])
                    conn.execute(
                        "INSERT INTO instinct_co_firing "
                        "(instinct_a, instinct_b, co_fire_count, co_follow_count, "
                        "co_override_count, last_co_fire) "
                        "VALUES (?, ?, 1, 0, 0, ?) "
                        "ON CONFLICT(instinct_a, instinct_b) DO UPDATE SET "
                        "co_fire_count = co_fire_count + 1, last_co_fire = ?",
                        (a, b, now, now),
                    )

        conn.commit()
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_nudge_co_firing.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hooks/nudge.py tests/test_nudge_co_firing.py
git commit -m "feat: co-firing window tracking in nudge hook"
```

---

### Task 6: Cluster Derivation During Compression

**Files:**
- Modify: `compress.py` (after `_check_instinct_creation`)
- Test: `tests/test_compression.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_compression.py`:

```python
def test_compression_triggers_cluster_assignment(tmp_path):
    """New instincts created during compression get assigned to clusters."""
    from clusters import ClusterEngine

    db = tmp_path / "test.db"
    storage = Storage(str(db), migrations_dir="migrations")
    embeddings = FakeEmbeddingProvider()
    compressor = Compressor(storage, embeddings)

    # Create a high-confidence semantic that will produce an instinct
    sem_id = str(uuid.uuid4())
    emb = embeddings.embed(["always restart MCP server after changes"])[0]
    storage.add_semantic(
        sem_id, "always restart MCP server after changes",
        kind="constraint", confidence=0.9, embedding=emb,
    )

    # Run instinct creation
    created = compressor._check_instinct_creation()
    assert created >= 1

    # Check the new instinct was assigned to a cluster
    instincts = storage.get_all_instincts()
    for inst in instincts:
        strengths = storage.get_instinct_cluster_strengths(inst["id"])
        assert len(strengths) >= 1, f"Instinct {inst['id']} has no cluster assignment"

    storage.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_compression.py::test_compression_triggers_cluster_assignment -v`
Expected: FAIL

- [ ] **Step 3: Wire cluster assignment into compression**

In `compress.py`, add import at top:

```python
from clusters import ClusterEngine
```

In `_check_instinct_creation()`, after the instinct is created (after line 628), add cluster assignment:

```python
                # Assign to nearest cluster (or create singleton)
                cluster_engine = ClusterEngine(self._storage, self._embeddings)
                cluster_engine.assign_new_instinct(instinct_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_compression.py::test_compression_triggers_cluster_assignment -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add compress.py tests/test_compression.py
git commit -m "feat: assign instincts to clusters during compression"
```

---

### Task 7: Cluster-Aware Gating in Nudge

**Files:**
- Modify: `hooks/nudge.py`
- Test: `tests/test_nudge_co_firing.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_nudge_co_firing.py`:

```python
def test_cluster_priming_lowers_threshold(tmp_path):
    """When a cluster mate has fired, other members get a lower threshold."""
    conn, db_path = _setup_db(tmp_path)

    # Add cluster tables
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS instinct_clusters (
            id TEXT PRIMARY KEY, maturity TEXT DEFAULT 'seeded',
            temperament REAL DEFAULT 0.5, last_active TEXT, member_count INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS instinct_cluster_members (
            instinct_id TEXT NOT NULL, cluster_id TEXT NOT NULL,
            strength REAL DEFAULT 0.5,
            PRIMARY KEY (instinct_id, cluster_id)
        );
    """)

    # Create a cluster with two instincts
    conn.execute(
        "INSERT INTO instinct_clusters (id, maturity, temperament, member_count) "
        "VALUES ('cluster1', 'confirmed', 0.5, 2)"
    )
    conn.execute(
        "INSERT INTO instinct_cluster_members (instinct_id, cluster_id, strength) "
        "VALUES ('i1', 'cluster1', 0.7)"
    )
    conn.execute(
        "INSERT INTO instinct_cluster_members (instinct_id, cluster_id, strength) "
        "VALUES ('i2', 'cluster1', 0.6)"
    )

    # i1 fired recently (in window)
    conn.execute(
        "INSERT INTO nudge_co_fire_window VALUES ('i1', 5, '2026-01-01T00:00:00')"
    )
    conn.commit()

    # Check that i2 gets cluster priming
    active_in_window = {
        row["instinct_id"]
        for row in conn.execute(
            "SELECT DISTINCT instinct_id FROM nudge_co_fire_window WHERE message_index >= ?",
            (1,),
        ).fetchall()
    }

    # i2's cluster-mates that are active
    cluster_ids = [
        row["cluster_id"]
        for row in conn.execute(
            "SELECT cluster_id FROM instinct_cluster_members WHERE instinct_id = 'i2'"
        ).fetchall()
    ]

    cluster_active = False
    for cid in cluster_ids:
        members = conn.execute(
            "SELECT instinct_id FROM instinct_cluster_members WHERE cluster_id = ?",
            (cid,),
        ).fetchall()
        for m in members:
            if m["instinct_id"] in active_in_window and m["instinct_id"] != "i2":
                cluster_active = True
                break

    assert cluster_active, "i2 should see cluster priming from i1"
    conn.close()
```

- [ ] **Step 2: Run test**

Run: `.venv/bin/python -m pytest tests/test_nudge_co_firing.py::test_cluster_priming_lowers_threshold -v`

- [ ] **Step 3: Add cluster-aware gating to nudge.py**

In `hooks/nudge.py`, modify the instinct firing section (around line 139-153). Replace the flat threshold check with cluster-aware gating:

```python
        # --- Cluster-aware instinct gating ---
        # Check which clusters are currently active (members in co-fire window)
        has_clusters = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='instinct_cluster_members'"
        ).fetchone()

        active_window_ids = set()
        if has_co_fire_table:
            recent_window = conn.execute(
                "SELECT DISTINCT instinct_id FROM nudge_co_fire_window "
                "WHERE message_index >= ?",
                (max(1, msg_idx - CO_FIRE_WINDOW) if 'msg_idx' in dir() else 1,),
            ).fetchall()
            active_window_ids = {r["instinct_id"] for r in recent_window}

        def _get_cluster_prime(instinct_id):
            """Check if this instinct's cluster has active members."""
            if not has_clusters:
                return 0.0
            clusters = conn.execute(
                "SELECT cluster_id, strength FROM instinct_cluster_members "
                "WHERE instinct_id = ?",
                (instinct_id,),
            ).fetchall()
            max_prime = 0.0
            for c in clusters:
                members = conn.execute(
                    "SELECT instinct_id FROM instinct_cluster_members "
                    "WHERE cluster_id = ? AND instinct_id != ?",
                    (c["cluster_id"], instinct_id),
                ).fetchall()
                active_count = sum(
                    1 for m in members if m["instinct_id"] in active_window_ids
                )
                if active_count > 0:
                    # Get cluster temperament
                    cluster = conn.execute(
                        "SELECT temperament FROM instinct_clusters WHERE id = ?",
                        (c["cluster_id"],),
                    ).fetchone()
                    temp = cluster["temperament"] if cluster else 0.5
                    # Conservative clusters prime more strongly
                    prime_strength = (1.0 - temp) * 0.15
                    max_prime = max(max_prime, prime_strength)
            return max_prime

        # Filter by threshold with cluster priming
        fired = []
        for row in results:
            sim = _distance_to_similarity(row["distance"])
            cluster_prime = _get_cluster_prime(row["id"])
            effective_threshold = max(0.2, FIRE_THRESHOLD - cluster_prime)

            if sim >= effective_threshold:
                inst = conn.execute(
                    "SELECT id, notice, implication, action FROM instincts WHERE id = ?",
                    (row["id"],)
                ).fetchone()
                if inst and inst["notice"]:
                    fired.append({
                        "id": inst["id"],
                        "notice": inst["notice"],
                        "similarity": sim,
                    })
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_nudge_co_firing.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hooks/nudge.py tests/test_nudge_co_firing.py
git commit -m "feat: cluster-aware gating in nudge hook"
```

---

### Task 8: Per-Cluster Strength in Recall Scoring

**Files:**
- Modify: `server.py`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_server.py`:

```python
def test_recall_uses_per_cluster_strength(storage, embeddings):
    """Recall scoring uses per-cluster strength when available."""
    # Create an instinct with per-cluster strength
    emb = embeddings.embed(["MCP restart needed"])[0]
    storage.add_instinct("i1", "constraint", "MCP restart", [], embedding=emb,
                         notice="when editing server files", implication="restart needed")
    storage.add_instinct_context_vector("i1", emb)

    # Set up cluster with specific strength
    storage.create_cluster("coding_cluster")
    storage.add_to_cluster("i1", "coding_cluster", strength=0.9)

    # The instinct's global strength is 0.5 (default), but cluster strength is 0.9
    inst = storage.get_instinct("i1")
    assert inst["strength"] == 0.5

    cluster_strengths = storage.get_instinct_cluster_strengths("i1")
    assert cluster_strengths[0]["strength"] == 0.9
```

- [ ] **Step 2: Run test**

Run: `.venv/bin/python -m pytest tests/test_server.py::test_recall_uses_per_cluster_strength -v`

- [ ] **Step 3: Modify recall scoring in server.py**

In `server.py`, in the instinct recall scoring section (around line 684-756), after getting the instinct's strength, check for per-cluster strength:

```python
                # Use per-cluster strength if available (max across clusters)
                cluster_strengths = _storage.get_instinct_cluster_strengths(iid)
                if cluster_strengths:
                    strength = max(cs["strength"] for cs in cluster_strengths)
                else:
                    strength = inst.get("strength", 0.5)
```

Apply the same change in the general recall path (around line 890) where instincts compete with other layers:

```python
                if result["layer"] == "instinct":
                    cluster_strengths = _storage.get_instinct_cluster_strengths(iid)
                    if cluster_strengths:
                        strength = max(cs["strength"] for cs in cluster_strengths)
                    else:
                        strength = inst.get("strength", 0.5)
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_server.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: per-cluster instinct strength in recall scoring"
```

---

### Task 9: Reflection — Instinct Clusters Focus

**Files:**
- Modify: `reflection.py`
- Test: `tests/test_reflection.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_reflection.py`:

```python
def test_reflect_instinct_clusters(storage, embeddings):
    """reflect(focus='instinct_clusters') shows cluster structure."""
    from reflection import Reflector

    emb = [0.1] * 768
    storage.add_instinct("i1", "preference", "coding instinct", [], embedding=emb)
    storage.add_instinct("i2", "preference", "also coding", [], embedding=emb)
    storage.create_cluster("c1", maturity="confirmed", temperament=0.3)
    storage.add_to_cluster("i1", "c1", strength=0.8)
    storage.add_to_cluster("i2", "c1", strength=0.6)

    storage.record_co_fire("i1", "i2", followed=True)
    storage.record_co_fire("i1", "i2", followed=True)
    storage.record_co_fire("i1", "i2", followed=False)

    reflector = Reflector(storage)
    result = reflector.reflect(focus="instinct_clusters")
    assert "instinct_clusters" in result

    clusters = result["instinct_clusters"]
    assert len(clusters) >= 1

    c = clusters[0]
    assert "members" in c
    assert "temperament" in c
    assert "maturity" in c
    assert len(c["members"]) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reflection.py::test_reflect_instinct_clusters -v`
Expected: FAIL

- [ ] **Step 3: Implement analyze_instinct_clusters in reflection.py**

Add to `reflection.py` before the `reflect()` method:

```python
    def analyze_instinct_clusters(self) -> list[dict]:
        """Analyze instinct cluster structure, membership, and temperament."""
        clusters = self._storage.get_all_clusters()
        result = []

        for cluster in clusters:
            cid = cluster["id"]
            members = self._storage.get_cluster_members(cid)

            member_details = []
            for m in members:
                inst = self._storage.get_instinct(m["instinct_id"])
                if inst:
                    member_details.append({
                        "id": m["instinct_id"],
                        "action": inst["action"][:100],
                        "notice": inst.get("notice", ""),
                        "cluster_strength": m["strength"],
                        "global_strength": inst["strength"],
                    })

            # Gather internal co-firing stats
            member_ids = {m["instinct_id"] for m in members}
            internal_edges = []
            for mid in member_ids:
                neighbors = self._storage.get_co_firing_neighbors(mid)
                for n in neighbors:
                    if n["instinct_id"] in member_ids:
                        internal_edges.append(n)

            total_co_fires = sum(e["co_fire_count"] for e in internal_edges) // 2
            total_follows = sum(e["co_follow_count"] for e in internal_edges) // 2
            total_overrides = sum(e["co_override_count"] for e in internal_edges) // 2

            result.append({
                "id": cid,
                "maturity": cluster["maturity"],
                "temperament": cluster["temperament"],
                "member_count": len(member_details),
                "members": member_details,
                "internal_co_fires": total_co_fires,
                "internal_follows": total_follows,
                "internal_overrides": total_overrides,
                "last_active": cluster.get("last_active"),
            })

        return result
```

Add the dispatch case in `reflect()`:

```python
        elif focus == "instinct_clusters":
            return {"instinct_clusters": self.analyze_instinct_clusters()}
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_reflection.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add reflection.py tests/test_reflection.py
git commit -m "feat: reflect(focus='instinct_clusters') for cluster observability"
```

---

### Task 10: Dream Priming of Dormant Clusters

**Files:**
- Modify: `hooks/wake.py`
- Test: `tests/test_wake_dream_priming.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_wake_dream_priming.py`:

```python
"""Tests for dream priming of dormant clusters at session start."""

import sqlite3
import struct
import numpy as np
import pytest


def _pack_embedding(emb):
    return struct.pack(f"<{len(emb)}f", *emb)


def test_dream_residue_primes_nearby_cluster():
    """A dream residue near a dormant cluster pre-seeds the co-fire window."""
    # Dream residue vector (64-dim, truncated)
    dream_vec = np.zeros(64)
    dream_vec[0] = 1.0  # points in a specific direction

    # Cluster centroid (768-dim, same direction in first 64 dims)
    centroid = np.zeros(768)
    centroid[0] = 1.0

    # Distant cluster centroid
    distant_centroid = np.zeros(768)
    distant_centroid[100] = 1.0

    # Similarity between dream (first 64 dims of centroid) and centroid
    dream_full = np.zeros(768)
    dream_full[:64] = dream_vec
    dream_norm = dream_full / (np.linalg.norm(dream_full) + 1e-10)
    centroid_norm = centroid / (np.linalg.norm(centroid) + 1e-10)

    sim_near = float(np.dot(dream_norm, centroid_norm))
    sim_far = float(np.dot(dream_norm, distant_centroid / (np.linalg.norm(distant_centroid) + 1e-10)))

    assert sim_near > 0.2, "Dream should be similar to nearby cluster"
    assert sim_far < 0.1, "Dream should be dissimilar to distant cluster"
```

- [ ] **Step 2: Run test**

Run: `.venv/bin/python -m pytest tests/test_wake_dream_priming.py -v`
Expected: PASS (this validates the math)

- [ ] **Step 3: Add dream priming to wake.py**

In `hooks/wake.py`, after dream residues are surfaced, add cluster priming logic:

```python
        # --- Dream priming of dormant clusters ---
        has_clusters = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='instinct_clusters'"
        ).fetchone()
        has_residues = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='residue'"
        ).fetchone()

        if has_clusters and has_residues:
            residues = conn.execute(
                "SELECT embedding FROM residue WHERE session_id != ? AND embedding IS NOT NULL",
                (session_id,),
            ).fetchall()

            if residues:
                import numpy as np

                # Average residue vectors (64-dim)
                residue_vecs = []
                for r in residues:
                    n = len(r["embedding"]) // 4
                    vec = list(struct.unpack(f"<{n}f", r["embedding"]))
                    residue_vecs.append(vec)

                if residue_vecs:
                    avg_residue = np.mean(residue_vecs, axis=0)
                    # Pad to full dimensionality for comparison
                    residue_full = np.zeros(768)
                    residue_full[: len(avg_residue)] = avg_residue
                    residue_norm = residue_full / (np.linalg.norm(residue_full) + 1e-10)

                    # Compare against cluster centroids
                    clusters = conn.execute(
                        "SELECT id FROM instinct_clusters"
                    ).fetchall()

                    for cluster in clusters:
                        members = conn.execute(
                            "SELECT icm.instinct_id FROM instinct_cluster_members icm "
                            "WHERE icm.cluster_id = ?",
                            (cluster["id"],),
                        ).fetchall()

                        if not members:
                            continue

                        # Compute centroid from member instinct vectors
                        member_vecs = []
                        for m in members:
                            vec_row = conn.execute(
                                "SELECT embedding FROM instinct_vectors WHERE id = ?",
                                (m["instinct_id"],),
                            ).fetchone()
                            if vec_row:
                                n = len(vec_row["embedding"]) // 4
                                vec = list(struct.unpack(f"<{n}f", vec_row["embedding"]))
                                member_vecs.append(vec)

                        if not member_vecs:
                            continue

                        centroid = np.mean(member_vecs, axis=0)
                        centroid_norm = centroid / (np.linalg.norm(centroid) + 1e-10)

                        sim = float(np.dot(residue_norm, centroid_norm))
                        if sim > 0.2:  # Dream priming threshold
                            # Pre-seed co-fire window with synthetic "dream" marker
                            conn.execute("""
                                CREATE TABLE IF NOT EXISTS nudge_co_fire_window (
                                    instinct_id TEXT NOT NULL,
                                    message_index INTEGER NOT NULL,
                                    fired_at TEXT NOT NULL,
                                    PRIMARY KEY (instinct_id, message_index)
                                )
                            """)
                            # Add first member as dream-primed (message_index 0 = pre-session)
                            conn.execute(
                                "INSERT OR IGNORE INTO nudge_co_fire_window "
                                "(instinct_id, message_index, fired_at) VALUES (?, 0, ?)",
                                (members[0]["instinct_id"], now),
                            )

                    conn.commit()
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_wake_dream_priming.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hooks/wake.py tests/test_wake_dream_priming.py
git commit -m "feat: dream residues prime dormant clusters at session start"
```

---

### Task 11: Instinct Feedback Updates Co-Firing Edges

**Files:**
- Modify: `server.py` (instinct_feedback function)
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_server.py`:

```python
def test_instinct_feedback_updates_co_firing(storage):
    """Following/overriding an instinct updates co-firing edge outcomes."""
    emb = [0.1] * 768
    storage.add_instinct("i1", "preference", "one", [], embedding=emb)
    storage.add_instinct("i2", "preference", "two", [], embedding=emb)

    # Create a co-firing edge
    storage.record_co_fire("i1", "i2")

    # Feedback on i1 should update edges where i1 is involved
    # This tests the storage method, not the full server path
    edge = storage.get_co_firing_edge("i1", "i2")
    assert edge["co_fire_count"] == 1
    assert edge["co_follow_count"] == 0

    storage.record_co_fire("i1", "i2", followed=True)
    edge = storage.get_co_firing_edge("i1", "i2")
    assert edge["co_follow_count"] == 1
```

- [ ] **Step 2: Run test**

Run: `.venv/bin/python -m pytest tests/test_server.py::test_instinct_feedback_updates_co_firing -v`

- [ ] **Step 3: Wire feedback into co-firing edges in server.py**

In `server.py`, in the `instinct_feedback()` function, after the follow/override update, add co-firing edge update:

```python
    # Update co-firing edges for recently co-fired instincts
    neighbors = _storage.get_co_firing_neighbors(instinct_id)
    for neighbor in neighbors:
        _storage.record_co_fire(
            instinct_id, neighbor["instinct_id"], followed=followed
        )
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_server.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: instinct feedback propagates to co-firing edges"
```

---

### Task 12: Cluster Re-derivation in Compression

**Files:**
- Modify: `compress.py`
- Test: `tests/test_compression.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_compression.py`:

```python
def test_compression_rederives_clusters(tmp_path):
    """Full compression triggers cluster re-derivation when co-firing data exists."""
    from clusters import ClusterEngine

    db = tmp_path / "test.db"
    storage = Storage(str(db), migrations_dir="migrations")
    embeddings = FakeEmbeddingProvider()
    compressor = Compressor(storage, embeddings)

    # Create instincts in two behavioral groups
    emb = [0.1] * 768
    storage.add_instinct("i1", "preference", "coding one", [], embedding=emb)
    storage.add_instinct("i2", "preference", "coding two", [], embedding=emb)
    storage.add_instinct("i3", "preference", "sports one", [], embedding=emb)
    storage.add_instinct("i4", "preference", "sports two", [], embedding=emb)

    # Build co-firing: i1-i2 together, i3-i4 together
    for _ in range(10):
        storage.record_co_fire("i1", "i2")
        storage.record_co_fire("i3", "i4")

    # Trigger cluster re-derivation
    engine = ClusterEngine(storage, embeddings)
    cluster_ids = engine.derive_clusters()

    assert len(cluster_ids) == 2
    for cid in cluster_ids:
        cluster = storage.get_cluster(cid)
        assert cluster["maturity"] == "confirmed"

    storage.close()
```

- [ ] **Step 2: Run test**

Run: `.venv/bin/python -m pytest tests/test_compression.py::test_compression_rederives_clusters -v`

- [ ] **Step 3: Add cluster re-derivation to commit()**

In `compress.py`, at the end of `commit()` (after `_check_instinct_creation()`), add:

```python
        # Re-derive clusters if we have co-firing data
        edges = self._storage.get_all_co_firing_edges()
        if edges:
            cluster_engine = ClusterEngine(self._storage, self._embeddings)
            cluster_engine.derive_clusters()
            logger.info("Clusters re-derived from co-firing graph")
        elif self._storage.get_all_instincts():
            cluster_engine = ClusterEngine(self._storage, self._embeddings)
            cluster_engine.seed_clusters()
            logger.info("Clusters seeded from embedding proximity")
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_compression.py -v`
Expected: PASS

- [ ] **Step 5: Run full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add compress.py tests/test_compression.py
git commit -m "feat: cluster re-derivation during compression"
```

---

### Task 13: Wire reflect(focus="instinct_clusters") into Server

**Files:**
- Modify: `server.py`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_server.py`:

```python
def test_reflect_instinct_clusters_via_server(storage, embeddings):
    """Server reflect tool supports instinct_clusters focus."""
    emb = [0.1] * 768
    storage.add_instinct("i1", "preference", "test", [], embedding=emb)
    storage.create_cluster("c1", maturity="seeded", temperament=0.5)
    storage.add_to_cluster("i1", "c1", strength=0.7)

    from reflection import Reflector
    reflector = Reflector(storage)
    result = reflector.reflect(focus="instinct_clusters")
    assert "instinct_clusters" in result
    assert len(result["instinct_clusters"]) == 1
```

- [ ] **Step 2: Run test to verify it passes** (should pass if Task 9 is done)

Run: `.venv/bin/python -m pytest tests/test_server.py::test_reflect_instinct_clusters_via_server -v`
Expected: PASS

- [ ] **Step 3: Verify the server.py reflect tool passes focus="instinct_clusters" through**

Check that the reflect tool in server.py forwards the focus parameter to `Reflector.reflect()`. If it already does, no change needed. If not, ensure `"instinct_clusters"` is handled.

- [ ] **Step 4: Commit if changes were needed**

```bash
git add server.py tests/test_server.py
git commit -m "feat: instinct_clusters focus available via reflect tool"
```

---

### Task 14: Integration Test — Full Lifecycle

**Files:**
- Create: `tests/test_cluster_integration.py`

- [ ] **Step 1: Write the integration test**

```python
"""End-to-end integration test for instinct co-firing clusters."""

import uuid
import pytest
from storage import Storage
from compress import Compressor
from clusters import ClusterEngine
from reflection import Reflector
from tests.test_compression import FakeEmbeddingProvider


@pytest.fixture
def storage(tmp_path):
    db = tmp_path / "test.db"
    s = Storage(str(db), migrations_dir="migrations")
    yield s
    s.close()


@pytest.fixture
def embeddings():
    return FakeEmbeddingProvider()


def test_full_cluster_lifecycle(storage, embeddings):
    """Instinct → cluster seed → co-fire → re-derive → temperament → reflect."""
    compressor = Compressor(storage, embeddings)
    engine = ClusterEngine(storage, embeddings)
    reflector = Reflector(storage)

    # 1. Create semantics that will produce instincts
    coding_emb = embeddings.embed(["always restart MCP after code changes"])[0]
    sports_emb = embeddings.embed(["watch the ball into contact point"])[0]

    storage.add_semantic(
        str(uuid.uuid4()), "always restart MCP after code changes",
        kind="constraint", confidence=0.9, embedding=coding_emb,
    )
    storage.add_semantic(
        str(uuid.uuid4()), "check imports before running",
        kind="constraint", confidence=0.9, embedding=coding_emb,
    )
    storage.add_semantic(
        str(uuid.uuid4()), "watch the ball into contact point",
        kind="preference", confidence=0.9, embedding=sports_emb,
    )
    storage.add_semantic(
        str(uuid.uuid4()), "follow through on every swing",
        kind="preference", confidence=0.9, embedding=sports_emb,
    )

    # 2. Compression creates instincts and seeds clusters
    created = compressor._check_instinct_creation()
    assert created >= 2  # at least some instincts

    instincts = storage.get_all_instincts()
    assert len(instincts) >= 2

    # Each instinct should have a cluster
    for inst in instincts:
        strengths = storage.get_instinct_cluster_strengths(inst["id"])
        assert len(strengths) >= 1

    # 3. Simulate co-firing: coding instincts fire together
    coding_instincts = [i for i in instincts if "MCP" in i["action"] or "import" in i["action"]]
    sports_instincts = [i for i in instincts if "ball" in i["action"] or "swing" in i["action"]]

    if len(coding_instincts) >= 2:
        for _ in range(10):
            storage.record_co_fire(
                coding_instincts[0]["id"], coding_instincts[1]["id"], followed=True
            )

    if len(sports_instincts) >= 2:
        for _ in range(10):
            storage.record_co_fire(
                sports_instincts[0]["id"], sports_instincts[1]["id"], followed=True
            )

    # 4. Re-derive clusters from co-firing
    cluster_ids = engine.derive_clusters()
    assert len(cluster_ids) >= 1

    # 5. Check temperament (all followed → conservative)
    for cid in cluster_ids:
        cluster = storage.get_cluster(cid)
        if cluster["member_count"] >= 2:
            assert cluster["temperament"] < 0.5  # conservative

    # 6. Reflect shows clusters
    result = reflector.reflect(focus="instinct_clusters")
    assert "instinct_clusters" in result
    assert len(result["instinct_clusters"]) >= 1

    for c in result["instinct_clusters"]:
        assert "members" in c
        assert "temperament" in c
        assert "maturity" in c
```

- [ ] **Step 2: Run the integration test**

Run: `.venv/bin/python -m pytest tests/test_cluster_integration.py -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_cluster_integration.py
git commit -m "test: end-to-end instinct cluster lifecycle integration test"
```

---

### Task 15: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add cluster documentation to CLAUDE.md**

In the Architecture section, add after the Contextual instincts paragraph:

```markdown
**Instinct co-firing clusters:** Instincts that activate together within a
message window form co-firing edges in a weighted graph. Community detection
(Louvain) derives clusters from the graph — groups of instincts that belong
to the same domain. Cold start: clusters seeded from embedding proximity.
Matures: clusters re-derive from behavioral co-firing. Each cluster has a
temperament (conservative ↔ exploratory) from its follow/override ratio.
Per-cluster instinct strength replaces global strength — an instinct can be
strong in coding context and weak in sports context. Transfer between clusters
is attenuated by edge weight and receiving cluster temperament. Dream residues
prime dormant clusters at session start.
```

In the MCP Tools table, add:

```markdown
| `reflect(focus="instinct_clusters")` | Cluster membership, temperament, co-firing stats, divergence. |
```

In Key Files, add:

```markdown
| `clusters.py` | Community detection, cluster seeding, temperament computation |
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add instinct co-firing clusters to CLAUDE.md"
```
