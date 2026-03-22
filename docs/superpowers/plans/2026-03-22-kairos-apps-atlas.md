# Kairos Apps: Atlas — Implementation Plan

> **Status:** Not started
>
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the Atlas research engine from `~/Projects/claw/atlas/` into the Kairos monorepo as `apps/atlas/`. Replace hardcoded Ollama calls with platform LLM provider, replace custom embeddings with platform NomicEmbedProvider, and wire into Bus for cross-worker communication.

**Architecture:** Atlas is a tick worker. Each tick: select a node from the 10-layer biology DAG, search for papers, synthesize sub-problems via LLM, deduplicate, validate, compute impact scores, sync to Obsidian vault, and publish findings to the bus. It gets its own Memory instance and Ledger.

**Tech Stack:** Python 3.12+, SQLite, kplatform (LLM, Memory, Bus, Ledger)

**Spec:** `docs/superpowers/specs/2026-03-21-kairos-platform-design.md` (Applications Layer > Atlas section)

**Source:** `~/Projects/claw/atlas/` (tick.py, db.py, graph.py, research.py, synthesize.py, dedup.py, validate.py, vault_sync.py)

---

## File Structure

```
apps/
  atlas/
    __init__.py           -- exports: AtlasDB, Graph, NodeSelector, Dedup, Validate, VaultSync, Worker
    db.py                 -- SQLite schema: nodes, edges, papers, ticks
    graph.py              -- DAG traversal, impact scoring, SCC, layer weights
    node_selector.py      -- TOC-based selection (constraint chain + exploration)
    research.py           -- Paper search interface (mock-friendly)
    synthesize.py         -- LLM-driven sub-problem synthesis via platform Provider
    dedup.py              -- Embedding-based duplicate detection via NomicEmbedProvider
    validate.py           -- Input quality filters (stateless pure functions)
    vault.py              -- Obsidian vault sync (atomic writes, YAML frontmatter)
    worker.py             -- Tick entrypoint: the full research loop
    CLAUDE.md             -- module docs
tests/
  apps/
    atlas/
      __init__.py
      conftest.py         -- fixtures: tmp db, mock LLM, mock embeddings
      test_db.py
      test_graph.py
      test_node_selector.py
      test_dedup.py
      test_validate.py
      test_vault.py
      test_worker.py
```

---

### Task 1: Database Schema

**Files:**
- Create: `apps/__init__.py`
- Create: `apps/atlas/__init__.py`
- Create: `apps/atlas/db.py`
- Create: `apps/atlas/CLAUDE.md`
- Create: `tests/apps/__init__.py`
- Create: `tests/apps/atlas/__init__.py`
- Create: `tests/apps/atlas/conftest.py`
- Create: `tests/apps/atlas/test_db.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/apps/atlas/test_db.py
import sqlite3
from apps.atlas.db import AtlasDB, LAYERS

# --- schema ---

def test_init_creates_tables(atlas_db):
    tables = atlas_db.tables()
    assert "nodes" in tables
    assert "edges" in tables
    assert "papers" in tables
    assert "node_papers" in tables
    assert "ticks" in tables


def test_layers_enum():
    assert len(LAYERS) == 10
    assert "math" in LAYERS
    assert "neuroscience" in LAYERS
    assert "computational-bio" in LAYERS


# --- nodes ---

def test_insert_node(atlas_db):
    atlas_db.insert_node(
        id="math.topology.knot-invariants",
        title="Knot invariants in protein folding",
        layer="math",
        domain="topology",
        description="How topological knot invariants constrain protein folding pathways.",
    )
    node = atlas_db.get_node("math.topology.knot-invariants")
    assert node is not None
    assert node["title"] == "Knot invariants in protein folding"
    assert node["status"] == "open"
    assert node["confidence_tier"] == 0


def test_insert_duplicate_node_ignored(atlas_db):
    atlas_db.insert_node(id="a", title="First", layer="math", domain="d", description="desc")
    atlas_db.insert_node(id="a", title="Second", layer="math", domain="d", description="other")
    node = atlas_db.get_node("a")
    assert node["title"] == "First"


def test_update_node_status(atlas_db):
    atlas_db.insert_node(id="n1", title="Test node", layer="physics", domain="d", description="desc")
    atlas_db.update_node("n1", status="partially-solved", confidence_tier=1)
    node = atlas_db.get_node("n1")
    assert node["status"] == "partially-solved"
    assert node["confidence_tier"] == 1


def test_layer_check_constraint(atlas_db):
    """Invalid layer should raise IntegrityError."""
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        atlas_db.insert_node(id="bad", title="Bad", layer="not-a-layer", domain="d", description="d")


# --- edges ---

def test_insert_edge(atlas_db):
    atlas_db.insert_node(id="a", title="A", layer="math", domain="d", description="d")
    atlas_db.insert_node(id="b", title="B", layer="math", domain="d", description="d")
    atlas_db.insert_edge("a", "b", "requires", strength=0.8, tick=1)
    edges = atlas_db.edges_from("a")
    assert len(edges) == 1
    assert edges[0]["target_id"] == "b"
    assert edges[0]["strength"] == 0.8


def test_duplicate_edge_ignored(atlas_db):
    atlas_db.insert_node(id="a", title="A", layer="math", domain="d", description="d")
    atlas_db.insert_node(id="b", title="B", layer="math", domain="d", description="d")
    atlas_db.insert_edge("a", "b", "requires")
    atlas_db.insert_edge("a", "b", "requires")
    assert len(atlas_db.edges_from("a")) == 1


# --- papers ---

def test_insert_paper_and_link(atlas_db):
    atlas_db.insert_node(id="n1", title="N", layer="math", domain="d", description="d")
    atlas_db.insert_paper(id="p1", title="Paper one", source="arxiv", url="https://arxiv.org/abs/1234")
    atlas_db.link_paper("n1", "p1", relevance="search-verified")
    papers = atlas_db.papers_for_node("n1")
    assert len(papers) == 1
    assert papers[0]["title"] == "Paper one"


# --- FTS ---

def test_fts_search(atlas_db):
    atlas_db.insert_node(id="n1", title="CRISPR gene editing mechanisms", layer="molecular-bio", domain="genetics", description="Clustered regularly interspaced short palindromic repeats")
    atlas_db.insert_node(id="n2", title="Quantum tunneling in enzymes", layer="physics", domain="biophysics", description="Quantum effects in catalysis")
    results = atlas_db.search_nodes("CRISPR")
    assert any(r["id"] == "n1" for r in results)
    assert not any(r["id"] == "n2" for r in results)
```

- [ ] **Step 2: Write conftest.py**

```python
# tests/apps/atlas/conftest.py
import pytest
from apps.atlas.db import AtlasDB


@pytest.fixture
def atlas_db(tmp_path):
    db = AtlasDB(str(tmp_path / "atlas.db"))
    yield db
    db.close()
```

- [ ] **Step 3: Write db.py**

Port from `~/Projects/claw/atlas/db.py`. Simplify: drop arena tables (assessments, comparisons, workers), resource graph (institutions, facilities, equipment, capabilities), and legacy ledger — those belong to other modules. Keep: nodes (with 10-layer constraint, status, confidence_tier, impact_score, trl, cost, timeline, falsification), edges (requires/enables/partially-enables/contradicts/subsumes with strength), papers, node_papers, ticks. Add FTS5 on nodes(title, description).

```python
# apps/atlas/db.py
"""SQLite schema for Atlas — nodes, edges, papers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

LAYERS = (
    "math", "physics", "chemistry",
    "molecular-bio", "cellular-bio", "systems-bio",
    "evolutionary-bio", "ecology", "neuroscience",
    "computational-bio",
)

_LAYER_CHECK = ", ".join(f"'{l}'" for l in LAYERS)


class AtlasDB:
    """Atlas graph database backed by SQLite."""

    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(f"""
            CREATE TABLE IF NOT EXISTS nodes (
                id                    TEXT PRIMARY KEY,
                title                 TEXT NOT NULL,
                layer                 TEXT NOT NULL CHECK(layer IN ({_LAYER_CHECK})),
                domain                TEXT NOT NULL,
                description           TEXT NOT NULL,
                status                TEXT NOT NULL DEFAULT 'open'
                                          CHECK(status IN ('solved','partially-solved','open','blocked')),
                status_evidence       TEXT,
                confidence_tier       INTEGER DEFAULT 0 CHECK(confidence_tier BETWEEN 0 AND 3),
                tractability          TEXT DEFAULT 'unknown'
                                          CHECK(tractability IN ('near-term','medium','long-term','unknown')),
                tractability_rationale TEXT,
                impact_score          REAL DEFAULT 0,
                trl                   INTEGER DEFAULT NULL,
                cost_low_m            REAL DEFAULT NULL,
                cost_high_m           REAL DEFAULT NULL,
                timeline_years        REAL DEFAULT NULL,
                falsification         TEXT DEFAULT NULL,
                investment_relevance  TEXT,
                key_papers            TEXT DEFAULT '[]',
                key_labs              TEXT DEFAULT '[]',
                created_at            TEXT DEFAULT (datetime('now')),
                updated_at            TEXT DEFAULT (datetime('now')),
                tick_created          INTEGER,
                tick_updated          INTEGER,
                expanded_at_tick      INTEGER DEFAULT NULL
            );

            CREATE TABLE IF NOT EXISTS edges (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id   TEXT NOT NULL REFERENCES nodes(id),
                target_id   TEXT NOT NULL REFERENCES nodes(id),
                edge_type   TEXT NOT NULL CHECK(edge_type IN (
                                'requires','enables','partially-enables',
                                'contradicts','subsumes')),
                evidence    TEXT,
                strength    REAL DEFAULT 1.0 CHECK(strength BETWEEN 0 AND 1),
                created_at  TEXT DEFAULT (datetime('now')),
                tick_created INTEGER,
                UNIQUE(source_id, target_id, edge_type)
            );

            CREATE TABLE IF NOT EXISTS papers (
                id         TEXT PRIMARY KEY,
                title      TEXT NOT NULL,
                authors    TEXT,
                year       INTEGER,
                source     TEXT CHECK(source IN ('arxiv','semantic-scholar','pubmed','web','llm-cited')),
                abstract   TEXT,
                url        TEXT,
                fetched_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS node_papers (
                node_id   TEXT REFERENCES nodes(id),
                paper_id  TEXT REFERENCES papers(id),
                relevance TEXT,
                PRIMARY KEY (node_id, paper_id)
            );

            CREATE TABLE IF NOT EXISTS ticks (
                tick_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at     TEXT DEFAULT (datetime('now')),
                completed_at   TEXT,
                node_id        TEXT,
                action         TEXT CHECK(action IN ('seed','expand','cross-link','verify','assess')),
                nodes_added    INTEGER DEFAULT 0,
                edges_added    INTEGER DEFAULT 0,
                papers_fetched INTEGER DEFAULT 0,
                summary        TEXT
            );

            -- FTS5 for node search
            CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
                title, description, content=nodes, content_rowid=rowid
            );

            -- Triggers to keep FTS in sync
            CREATE TRIGGER IF NOT EXISTS nodes_ai AFTER INSERT ON nodes BEGIN
                INSERT INTO nodes_fts(rowid, title, description)
                VALUES (new.rowid, new.title, new.description);
            END;

            CREATE TRIGGER IF NOT EXISTS nodes_au AFTER UPDATE ON nodes BEGIN
                INSERT INTO nodes_fts(nodes_fts, rowid, title, description)
                VALUES ('delete', old.rowid, old.title, old.description);
                INSERT INTO nodes_fts(rowid, title, description)
                VALUES (new.rowid, new.title, new.description);
            END;

            CREATE TRIGGER IF NOT EXISTS nodes_ad AFTER DELETE ON nodes BEGIN
                INSERT INTO nodes_fts(nodes_fts, rowid, title, description)
                VALUES ('delete', old.rowid, old.title, old.description);
            END;
        """)

    # --- query helpers ---

    def tables(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return [r["name"] for r in rows]

    # --- nodes ---

    def insert_node(self, *, id: str, title: str, layer: str, domain: str,
                    description: str, tick_created: int | None = None, **kwargs) -> None:
        self._conn.execute(
            """INSERT OR IGNORE INTO nodes
               (id, title, layer, domain, description, tick_created, tick_updated)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (id, title, layer, domain, description, tick_created, tick_created),
        )
        self._conn.commit()

    def get_node(self, node_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()

    def update_node(self, node_id: str, **fields) -> None:
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [node_id]
        self._conn.execute(
            f"UPDATE nodes SET {sets}, updated_at = datetime('now') WHERE id = ?", vals
        )
        self._conn.commit()

    def all_nodes(self) -> list[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM nodes").fetchall()

    def search_nodes(self, query: str, limit: int = 20) -> list[sqlite3.Row]:
        return self._conn.execute(
            """SELECT n.* FROM nodes_fts f
               JOIN nodes n ON n.rowid = f.rowid
               WHERE nodes_fts MATCH ? LIMIT ?""",
            (query, limit),
        ).fetchall()

    # --- edges ---

    def insert_edge(self, source_id: str, target_id: str, edge_type: str,
                    strength: float = 1.0, tick: int | None = None,
                    evidence: str | None = None) -> bool:
        self._conn.execute(
            """INSERT OR IGNORE INTO edges
               (source_id, target_id, edge_type, strength, evidence, tick_created)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (source_id, target_id, edge_type, strength, evidence, tick),
        )
        changed = self._conn.execute("SELECT changes() AS c").fetchone()["c"] > 0
        self._conn.commit()
        return changed

    def edges_from(self, node_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM edges WHERE source_id = ?", (node_id,)
        ).fetchall()

    def edges_to(self, node_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM edges WHERE target_id = ?", (node_id,)
        ).fetchall()

    def all_edges(self, edge_types: tuple[str, ...] | None = None) -> list[sqlite3.Row]:
        if edge_types:
            placeholders = ",".join("?" for _ in edge_types)
            return self._conn.execute(
                f"SELECT * FROM edges WHERE edge_type IN ({placeholders})", edge_types
            ).fetchall()
        return self._conn.execute("SELECT * FROM edges").fetchall()

    # --- papers ---

    def insert_paper(self, *, id: str, title: str, source: str | None = None,
                     authors: str | None = None, year: int | None = None,
                     abstract: str | None = None, url: str | None = None) -> None:
        self._conn.execute(
            """INSERT OR IGNORE INTO papers (id, title, source, authors, year, abstract, url)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (id, title, source, authors, year, abstract, url),
        )
        self._conn.commit()

    def link_paper(self, node_id: str, paper_id: str, relevance: str = "") -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO node_papers (node_id, paper_id, relevance) VALUES (?, ?, ?)",
            (node_id, paper_id, relevance),
        )
        self._conn.commit()

    def papers_for_node(self, node_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            """SELECT p.* FROM papers p
               JOIN node_papers np ON np.paper_id = p.id
               WHERE np.node_id = ?""",
            (node_id,),
        ).fetchall()

    # --- ticks ---

    def log_tick(self, *, node_id: str, action: str, nodes_added: int = 0,
                 edges_added: int = 0, papers_fetched: int = 0, summary: str = "") -> None:
        self._conn.execute(
            """INSERT INTO ticks (completed_at, node_id, action, nodes_added, edges_added,
               papers_fetched, summary) VALUES (datetime('now'), ?, ?, ?, ?, ?, ?)""",
            (node_id, action, nodes_added, edges_added, papers_fetched, summary),
        )
        self._conn.commit()

    # --- connection ---

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Write __init__.py, CLAUDE.md**

```python
# apps/__init__.py
"""Kairos applications."""
```

```python
# apps/atlas/__init__.py
"""Atlas — research engine with 10-layer biology DAG."""
```

```markdown
# Atlas

Research engine. 10-layer biology DAG, paper verification, cross-linking.

Ported from `~/Projects/claw/atlas/`.

## Key Files

| File | Purpose |
|------|---------|
| db.py | SQLite schema: nodes, edges, papers |
| graph.py | DAG traversal, impact scoring, layer weights |
| node_selector.py | TOC-based node selection |
| research.py | Paper search interface |
| synthesize.py | LLM synthesis via platform Provider |
| dedup.py | Embedding-based duplicate detection |
| validate.py | Input quality filters |
| vault.py | Obsidian vault sync |
| worker.py | Tick entrypoint |

## Platform Dependencies

- **LLM:** `kplatform.llm.Provider` for synthesis (replaces hardcoded Ollama)
- **Memory:** `kplatform.memory.EmbeddingProvider` for dedup embeddings
- **Bus:** `kplatform.bus.Bus` for publishing findings
- **Ledger:** `kplatform.ledger.Ledger` for audit trail
```

- [ ] **Step 5: Run tests, commit**

```bash
cd /Users/kairos/Projects/kairos
uv run pytest tests/apps/atlas/test_db.py -v
git add apps/ tests/apps/
git commit -m "feat(atlas): database schema with nodes, edges, papers, FTS5"
```

---

### Task 2: Graph Engine

**Files:**
- Create: `apps/atlas/graph.py`
- Create: `tests/apps/atlas/test_graph.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/apps/atlas/test_graph.py
from apps.atlas.graph import (
    compute_impact_scores, compute_layer_weights, compute_priority,
    find_critical_path, identify_constraint, find_sccs,
    STATIC_LAYER_WEIGHTS, STATUS_WEIGHTS, TRAVERSAL_EDGE_TYPES,
)


def test_static_layer_weights_cover_all_layers():
    from apps.atlas.db import LAYERS
    for layer in LAYERS:
        assert layer in STATIC_LAYER_WEIGHTS


def test_traversal_edge_types():
    assert "requires" in TRAVERSAL_EDGE_TYPES
    assert "enables" in TRAVERSAL_EDGE_TYPES
    assert "contradicts" not in TRAVERSAL_EDGE_TYPES


def test_impact_score_simple_chain(atlas_db):
    """A -> B -> C: A should have higher impact than B."""
    atlas_db.insert_node(id="a", title="Node A", layer="math", domain="d", description="d")
    atlas_db.insert_node(id="b", title="Node B", layer="math", domain="d", description="d")
    atlas_db.insert_node(id="c", title="Node C", layer="math", domain="d", description="d")
    atlas_db.insert_edge("a", "b", "requires")
    atlas_db.insert_edge("b", "c", "requires")
    compute_impact_scores(atlas_db)
    a = atlas_db.get_node("a")
    b = atlas_db.get_node("b")
    assert a["impact_score"] > b["impact_score"]


def test_impact_score_isolated_node(atlas_db):
    """Node with no edges has zero downstream impact."""
    atlas_db.insert_node(id="lone", title="Lone node", layer="math", domain="d", description="d")
    compute_impact_scores(atlas_db)
    node = atlas_db.get_node("lone")
    assert node["impact_score"] == 0.0


def test_find_sccs_no_cycle(atlas_db):
    atlas_db.insert_node(id="a", title="A", layer="math", domain="d", description="d")
    atlas_db.insert_node(id="b", title="B", layer="math", domain="d", description="d")
    atlas_db.insert_edge("a", "b", "requires")
    sccs = find_sccs(atlas_db)
    # No cycle, so all SCCs should be singletons
    assert all(len(scc) == 1 for scc in sccs)


def test_find_sccs_with_cycle(atlas_db):
    atlas_db.insert_node(id="a", title="A", layer="math", domain="d", description="d")
    atlas_db.insert_node(id="b", title="B", layer="math", domain="d", description="d")
    atlas_db.insert_edge("a", "b", "requires")
    atlas_db.insert_edge("b", "a", "enables")
    sccs = find_sccs(atlas_db)
    cycle_scc = [s for s in sccs if len(s) > 1]
    assert len(cycle_scc) == 1
    assert set(cycle_scc[0]) == {"a", "b"}


def test_critical_path_returns_longest_chain(atlas_db):
    atlas_db.insert_node(id="a", title="A", layer="math", domain="d", description="d")
    atlas_db.insert_node(id="b", title="B", layer="math", domain="d", description="d")
    atlas_db.insert_node(id="c", title="C", layer="math", domain="d", description="d")
    atlas_db.insert_edge("a", "b", "requires")
    atlas_db.insert_edge("b", "c", "requires")
    path = find_critical_path(atlas_db)
    assert len(path) == 3


def test_compute_priority_unexpanded_preferred(atlas_db):
    """Unexpanded nodes should have higher priority than recently-expanded ones."""
    atlas_db.insert_node(id="fresh", title="Fresh", layer="math", domain="d", description="d")
    atlas_db.insert_node(id="stale", title="Stale", layer="math", domain="d", description="d")
    atlas_db.update_node("stale", expanded_at_tick=95)
    compute_impact_scores(atlas_db)
    p_fresh = compute_priority(atlas_db, "fresh", current_tick=100)
    p_stale = compute_priority(atlas_db, "stale", current_tick=100)
    assert p_fresh > p_stale
```

- [ ] **Step 2: Write graph.py**

Port from `~/Projects/claw/atlas/graph.py`. The interface changes from raw `conn` to `AtlasDB` object. Keep: static/empirical layer weights, status weights, BFS impact scoring, SCC detection (Tarjan's), priority computation with freshness, critical path via DFS, constraint identification. The graph module operates on the `AtlasDB` instance rather than a raw SQLite connection.

```python
# apps/atlas/graph.py
"""DAG traversal, impact scoring, layer weights."""

from __future__ import annotations

from collections import defaultdict, deque

from apps.atlas.db import AtlasDB, LAYERS

# Static fallback weights — used when graph has < 50 cross-layer edges
STATIC_LAYER_WEIGHTS = {
    "math": 1.0, "physics": 0.9, "chemistry": 0.8,
    "molecular-bio": 0.7, "cellular-bio": 0.6, "systems-bio": 0.5,
    "evolutionary-bio": 0.7, "ecology": 0.6, "neuroscience": 0.6,
    "computational-bio": 0.8,
}

STATUS_WEIGHTS = {
    "blocked": 2.0, "open": 1.5, "partially-solved": 1.0, "solved": 0.1,
}

TRAVERSAL_EDGE_TYPES = ("requires", "enables", "partially-enables")


def compute_layer_weights(db: AtlasDB, min_cross_edges: int = 50) -> dict[str, float]:
    """Compute layer weights empirically from cross-layer edge density.
    Falls back to STATIC_LAYER_WEIGHTS if graph too sparse."""
    # ... (port logic from claw graph.py compute_layer_weights)


def compute_impact_scores(db: AtlasDB) -> None:
    """BFS downstream impact scoring with SCC equalization.
    Writes impact_score back to each node."""
    # ... (port logic from claw graph.py compute_impact_scores)


def find_sccs(db: AtlasDB) -> list[list[str]]:
    """Tarjan's SCC detection over traversal edges."""
    # ... (port logic from claw graph.py find_sccs)


def compute_priority(db: AtlasDB, node_id: str, current_tick: int) -> float:
    """Priority = (impact + freshness) * layer_weight * status_weight.
    Freshness: NULL -> 10.0, >50 ticks -> 3.0, >20 -> 1.0, <=20 -> -1.0"""
    # ... (port logic from claw graph.py compute_priority)


def find_critical_path(db: AtlasDB) -> list[str]:
    """Longest chain of open/blocked nodes via DFS with cycle guard."""
    # ... (port logic from claw graph.py find_critical_path)


def identify_constraint(db: AtlasDB) -> dict | None:
    """TOC: highest-impact open/blocked node on critical path.
    Returns {id, title, layer, impact_score, trl, chain} or None."""
    # ... (port logic from claw graph.py identify_constraint)
```

The implementation should directly port the algorithms from `~/Projects/claw/atlas/graph.py`, replacing `conn` parameter with `db: AtlasDB` and using `db.conn` for SQL queries, `db.all_nodes()` / `db.all_edges()` for data loading.

- [ ] **Step 3: Run tests, commit**

```bash
cd /Users/kairos/Projects/kairos
uv run pytest tests/apps/atlas/test_graph.py -v
git add apps/atlas/graph.py tests/apps/atlas/test_graph.py
git commit -m "feat(atlas): graph engine with impact scoring, SCC, critical path"
```

---

### Task 3: Node Selector

**Files:**
- Create: `apps/atlas/node_selector.py`
- Create: `tests/apps/atlas/test_node_selector.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/apps/atlas/test_node_selector.py
import random
from apps.atlas.node_selector import select_next_node, SelectionMode
from apps.atlas.graph import compute_impact_scores


def test_select_from_empty_db(atlas_db):
    result = select_next_node(atlas_db, current_tick=1)
    assert result is None


def test_select_returns_node_id(atlas_db):
    atlas_db.insert_node(id="n1", title="Only node", layer="math", domain="d", description="d")
    compute_impact_scores(atlas_db)
    result = select_next_node(atlas_db, current_tick=1)
    assert result is not None
    assert result.node_id == "n1"


def test_constraint_mode_prefers_blocking_node(atlas_db):
    """Constraint chain: node that blocks the most downstream work wins."""
    atlas_db.insert_node(id="blocker", title="Blocker", layer="math", domain="d", description="d")
    atlas_db.insert_node(id="leaf1", title="Leaf 1", layer="math", domain="d", description="d")
    atlas_db.insert_node(id="leaf2", title="Leaf 2", layer="math", domain="d", description="d")
    atlas_db.insert_node(id="solo", title="Solo", layer="math", domain="d", description="d")
    atlas_db.insert_edge("blocker", "leaf1", "requires")
    atlas_db.insert_edge("blocker", "leaf2", "requires")
    compute_impact_scores(atlas_db)
    result = select_next_node(atlas_db, current_tick=1, mode=SelectionMode.CONSTRAINT)
    assert result.node_id == "blocker"


def test_explore_mode_returns_valid_node(atlas_db):
    atlas_db.insert_node(id="n1", title="Node 1", layer="math", domain="d", description="d")
    atlas_db.insert_node(id="n2", title="Node 2", layer="ecology", domain="d", description="d")
    compute_impact_scores(atlas_db)
    result = select_next_node(atlas_db, current_tick=1, mode=SelectionMode.EXPLORE)
    assert result is not None


def test_toc_split_60_40(atlas_db):
    """Over many calls, TOC split should approximate 60% constraint / 40% explore."""
    atlas_db.insert_node(id="n1", title="Node 1", layer="math", domain="d", description="d")
    atlas_db.insert_node(id="n2", title="Node 2", layer="ecology", domain="d", description="d")
    compute_impact_scores(atlas_db)
    rng = random.Random(42)
    modes = []
    for _ in range(100):
        r = rng.random()
        modes.append("constraint" if r < 0.6 else "explore")
    constraint_pct = modes.count("constraint") / len(modes)
    assert 0.45 < constraint_pct < 0.75  # within reason


def test_cooldown_excludes_recent(atlas_db):
    """Nodes expanded within 20 ticks should not be selected."""
    atlas_db.insert_node(id="recent", title="Recent", layer="math", domain="d", description="d")
    atlas_db.update_node("recent", expanded_at_tick=85)
    atlas_db.insert_node(id="old", title="Old", layer="math", domain="d", description="d")
    compute_impact_scores(atlas_db)
    result = select_next_node(atlas_db, current_tick=100)
    assert result is not None
    assert result.node_id == "old"
```

- [ ] **Step 2: Write node_selector.py**

```python
# apps/atlas/node_selector.py
"""TOC-based node selection: 60% constraint chain, 40% exploration."""

from __future__ import annotations

import enum
import random
from dataclasses import dataclass

from apps.atlas.db import AtlasDB
from apps.atlas.graph import compute_priority, identify_constraint


class SelectionMode(enum.Enum):
    CONSTRAINT = "constraint"
    EXPLORE = "explore"
    AUTO = "auto"  # 60/40 split


@dataclass
class Selection:
    node_id: str
    mode: SelectionMode
    priority: float


def select_next_node(
    db: AtlasDB,
    current_tick: int,
    mode: SelectionMode = SelectionMode.AUTO,
    rng: random.Random | None = None,
) -> Selection | None:
    """Select the next node to expand.

    AUTO mode: 60% chance constraint chain, 40% exploration.
    CONSTRAINT: pick the most-blocking node (highest impact on critical path).
    EXPLORE: pick from under-explored layers weighted by staleness.
    """
    # ... (implement selection logic)
    # For CONSTRAINT: use identify_constraint() to find the binding constraint
    # For EXPLORE: score all eligible nodes by priority, pick randomly weighted
    # For AUTO: use rng.random() < 0.6 to choose mode, then delegate
```

- [ ] **Step 3: Run tests, commit**

```bash
cd /Users/kairos/Projects/kairos
uv run pytest tests/apps/atlas/test_node_selector.py -v
git add apps/atlas/node_selector.py tests/apps/atlas/test_node_selector.py
git commit -m "feat(atlas): TOC-based node selector with 60/40 constraint/explore split"
```

---

### Task 4: Dedup

**Files:**
- Create: `apps/atlas/dedup.py`
- Create: `tests/apps/atlas/test_dedup.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/apps/atlas/test_dedup.py
import math
from apps.atlas.dedup import (
    canonical_node_id, cosine_similarity, find_duplicate,
    deduplicate_sub_problems, SIMILARITY_THRESHOLD,
)


def test_canonical_node_id():
    nid = canonical_node_id("molecular-bio", "genetics", "CRISPR gene editing mechanisms")
    assert nid.startswith("mole.")
    assert "crispr" in nid.lower()


def test_canonical_slug_strips_stopwords():
    id1 = canonical_node_id("math", "topology", "The theory of knot invariants")
    id2 = canonical_node_id("math", "topology", "A theory of knot invariants")
    assert id1 == id2


def test_cosine_similarity_identical():
    v = [1.0, 0.0, 0.0]
    assert cosine_similarity(v, v) == 1.0


def test_cosine_similarity_orthogonal():
    a = [1.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0]
    assert cosine_similarity(a, b) == 0.0


def test_find_duplicate_exact_title(atlas_db, mock_embedder):
    atlas_db.insert_node(id="existing", title="CRISPR mechanisms", layer="molecular-bio",
                         domain="genetics", description="How CRISPR works")
    dup = find_duplicate(atlas_db, "CRISPR mechanisms", "something", "molecular-bio", mock_embedder)
    assert dup == "existing"


def test_find_duplicate_no_match(atlas_db, mock_embedder):
    atlas_db.insert_node(id="unrelated", title="Quantum tunneling", layer="physics",
                         domain="biophysics", description="Quantum effects")
    dup = find_duplicate(atlas_db, "CRISPR mechanisms", "gene editing", "molecular-bio", mock_embedder)
    assert dup is None  # Different layer, no match


def test_deduplicate_creates_new_nodes(atlas_db, mock_embedder):
    sub_problems = [
        {"title": "Sub-problem A", "description": "Description A"},
        {"title": "Sub-problem B", "description": "Description B"},
    ]
    results = deduplicate_sub_problems(
        atlas_db, sub_problems, "math", "topology", tick=1, embedder=mock_embedder
    )
    assert len(results) == 2
    assert all(is_new for _, is_new in results)
```

- [ ] **Step 2: Add mock_embedder fixture to conftest.py**

```python
# Add to tests/apps/atlas/conftest.py

@pytest.fixture
def mock_embedder():
    """Deterministic embedder for testing — hashes text to a fixed vector."""
    import hashlib

    class MockEmbedder:
        def dimension(self) -> int:
            return 64

        def embed(self, texts, *, prefix="search_document"):
            results = []
            for text in texts:
                h = hashlib.sha256(text.encode()).digest()
                vec = [float(b) / 255.0 for b in h[:64]]
                mag = sum(x*x for x in vec) ** 0.5
                results.append([x / mag for x in vec] if mag > 0 else vec)
            return results

    return MockEmbedder()
```

- [ ] **Step 3: Write dedup.py**

Port from `~/Projects/claw/atlas/dedup.py`. Replace `research.get_embedding()` with platform `EmbeddingProvider` passed as parameter. Keep: cosine similarity, canonical slug, find_duplicate (exact title match + embedding similarity), deduplicate_sub_problems. Threshold: 0.90.

```python
# apps/atlas/dedup.py
"""Embedding-based duplicate detection using platform embeddings."""

from __future__ import annotations

import math
import re

from apps.atlas.db import AtlasDB
from kplatform.memory.embeddings import EmbeddingProvider

SIMILARITY_THRESHOLD = 0.90


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    # ... (port from claw dedup.py _cosine_similarity)


def canonical_node_id(layer: str, domain: str, title: str) -> str:
    """Generate canonical node ID: {layer[:4]}.{domain_slug}.{title_slug}"""
    # ... (port from claw dedup.py canonical_node_id + _canonical_slug)


def find_duplicate(
    db: AtlasDB, title: str, description: str, layer: str,
    embedder: EmbeddingProvider,
) -> str | None:
    """Check if semantically equivalent node exists in same layer.
    Returns existing node ID or None."""
    # ... (port from claw dedup.py find_duplicate, using embedder.embed())


def deduplicate_sub_problems(
    db: AtlasDB, sub_problems: list[dict], parent_layer: str,
    parent_domain: str, tick: int, embedder: EmbeddingProvider,
) -> list[tuple[str, bool]]:
    """Process sub-problems with dedup. Returns [(node_id, is_new), ...]."""
    # ... (port from claw dedup.py deduplicate_sub_problems)
```

- [ ] **Step 4: Run tests, commit**

```bash
cd /Users/kairos/Projects/kairos
uv run pytest tests/apps/atlas/test_dedup.py -v
git add apps/atlas/dedup.py tests/apps/atlas/test_dedup.py
git commit -m "feat(atlas): embedding-based dedup via platform EmbeddingProvider"
```

---

### Task 5: Validate

**Files:**
- Create: `apps/atlas/validate.py`
- Create: `tests/apps/atlas/test_validate.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/apps/atlas/test_validate.py
from apps.atlas.validate import is_valid_node, filter_sub_problems


def test_valid_node():
    ok, reason = is_valid_node("CRISPR gene editing mechanisms", "How CRISPR-Cas9 enables targeted genome editing")
    assert ok
    assert reason == ""


def test_reject_short_title():
    ok, reason = is_valid_node("Too short")
    assert not ok
    assert "title too short" in reason


def test_reject_garbage_title():
    ok, reason = is_valid_node("Placeholder node for testing")
    assert not ok
    assert "garbage" in reason


def test_reject_numbered_title():
    ok, reason = is_valid_node("12345")
    assert not ok


def test_filter_sub_problems_mixed():
    sps = [
        {"title": "Real sub-problem about protein folding", "description": "A meaningful description of the problem"},
        {"title": "TBD", "description": "placeholder"},
        {"title": "Another real problem in computational biology", "description": "Real description here too"},
    ]
    valid, rejected = filter_sub_problems(sps)
    assert len(valid) == 2
    assert rejected == 1
```

- [ ] **Step 2: Write validate.py**

Direct port from `~/Projects/claw/atlas/validate.py`. Pure stateless functions, no dependencies.

```python
# apps/atlas/validate.py
"""Input quality filters — reject garbage before insertion."""

from __future__ import annotations

import re

GARBAGE_PATTERNS = [
    r"^title(\s|$)", r"^sub[- ]?problem", r"^another\s", r"^example\s",
    r"^placeholder", r"^todo", r"^tbd", r"^n/?a$", r"^\d+$",
    r"^unnamed", r"^untitled",
]
_GARBAGE_RE = re.compile("|".join(GARBAGE_PATTERNS), re.IGNORECASE)

MIN_TITLE_LENGTH = 10
MIN_DESCRIPTION_LENGTH = 20


def is_valid_node(title: str, description: str = "", layer: str | None = None) -> tuple[bool, str]:
    """Check if a proposed node meets quality thresholds.
    Returns (valid, reason). Reason is empty if valid."""
    # ... (port directly from claw validate.py)


def filter_sub_problems(sub_problems: list[dict]) -> tuple[list[dict], int]:
    """Filter proposed sub-problems, rejecting invalid ones.
    Returns (valid_list, rejected_count)."""
    # ... (port directly from claw validate.py)
```

- [ ] **Step 3: Run tests, commit**

```bash
cd /Users/kairos/Projects/kairos
uv run pytest tests/apps/atlas/test_validate.py -v
git add apps/atlas/validate.py tests/apps/atlas/test_validate.py
git commit -m "feat(atlas): input quality validation filters"
```

---

### Task 6: Research + Synthesize

**Files:**
- Create: `apps/atlas/research.py`
- Create: `apps/atlas/synthesize.py`
- Create: `tests/apps/atlas/test_research.py` (merged — research and synthesize are tightly coupled)

- [ ] **Step 1: Write the failing tests**

```python
# tests/apps/atlas/test_research.py
from apps.atlas.research import format_search_queries, PaperSearcher
from apps.atlas.synthesize import Synthesizer, parse_synthesis_response


def test_format_queries_always_has_base_queries():
    queries = format_search_queries("CRISPR", "genetics", "molecular-bio")
    assert len(queries) >= 2
    assert any("CRISPR" in q for q in queries)


def test_format_queries_capped_at_5():
    queries = format_search_queries("test", "domain", "math")
    assert len(queries) <= 5


def test_paper_searcher_interface():
    """PaperSearcher has search method returning list of dicts."""
    class MockSearcher(PaperSearcher):
        def search(self, query, max_results=5):
            return [{"title": "Mock paper", "source": "mock", "url": "http://example.com"}]
    s = MockSearcher()
    papers = s.search("test")
    assert len(papers) == 1


def test_parse_synthesis_json():
    raw = '{"sub_problems": [{"title": "Sub A", "description": "Desc A"}], "status": "open", "tractability": "near-term"}'
    result = parse_synthesis_response(raw, "math", "topology")
    assert len(result["sub_problems"]) == 1
    assert result["status"] == "open"
    assert result["tractability"] == "near-term"


def test_parse_synthesis_empty():
    result = parse_synthesis_response("{}", "math", "topology")
    assert result["sub_problems"] == []
    assert result["status"] == "open"


def test_synthesizer_uses_provider(mock_llm):
    synth = Synthesizer(mock_llm)
    result = synth.synthesize(
        title="Test node", description="A test", layer="math",
        domain="topology", evidence="some evidence", existing_nodes=[],
    )
    assert "sub_problems" in result
    assert "status" in result
```

- [ ] **Step 2: Add mock_llm fixture to conftest.py**

```python
# Add to tests/apps/atlas/conftest.py

@pytest.fixture
def mock_llm():
    """Mock LLM provider that returns structured JSON."""
    import json
    from kplatform.llm.provider import LLMResponse

    class MockProvider:
        def is_available(self):
            return True

        def generate(self, prompt, *, system=None, temperature=0.7, max_tokens=4096):
            return LLMResponse(
                content=json.dumps({
                    "sub_problems": [{"title": "Generated sub", "description": "A sub-problem"}],
                    "status": "open",
                    "tractability": "medium",
                }),
                model="mock", provider="mock",
            )

        def chat(self, messages, *, temperature=0.7, max_tokens=4096, tools=None):
            return self.generate(messages[-1].get("content", ""))

    return MockProvider()
```

- [ ] **Step 3: Write research.py**

Port query formatting from `~/Projects/claw/atlas/research.py`. Define `PaperSearcher` as a Protocol (abstract interface) so external API calls can be mocked. Don't import urllib or make real HTTP calls — that's the caller's responsibility.

```python
# apps/atlas/research.py
"""Paper search interface — mock-friendly, no hardcoded API calls."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PaperSearcher(Protocol):
    """Protocol for paper search backends (arXiv, PubMed, Semantic Scholar)."""
    def search(self, query: str, max_results: int = 5) -> list[dict]:
        """Returns list of {title, authors, year, source, url, abstract}."""
        ...


def format_search_queries(title: str, domain: str, layer: str) -> list[str]:
    """Generate 2-5 search queries for a node. Capped at 5."""
    # ... (port from claw research.py format_search_queries)
```

- [ ] **Step 4: Write synthesize.py**

Port from `~/Projects/claw/atlas/synthesize.py`. Replace `_call_ollama()` with platform `Provider.generate()`. Keep: JSON response parsing, markdown fallback parsing, sub-problem normalization, parse_labs.

```python
# apps/atlas/synthesize.py
"""LLM-driven sub-problem synthesis via platform Provider."""

from __future__ import annotations

import json
import re

from kplatform.llm.provider import Provider


class Synthesizer:
    """Synthesize sub-problems and metadata for a node using an LLM."""

    def __init__(self, llm: Provider):
        self._llm = llm

    def synthesize(self, *, title: str, description: str, layer: str,
                   domain: str, evidence: str, existing_nodes: list[str]) -> dict:
        """Call LLM and parse structured response.
        Returns {sub_problems, cross_links, status, tractability, trl, ...}"""
        # ... (port from claw synthesize.py synthesize_node, using self._llm.generate())

    def reassess(self, *, title: str, description: str, layer: str,
                 domain: str, status: str, tractability: str) -> dict:
        """Lightweight metadata-only reassessment."""
        # ... (port from claw synthesize.py reassess_node)


def parse_synthesis_response(response: str, parent_layer: str, parent_domain: str) -> dict:
    """Parse JSON or markdown LLM response into structured dict."""
    # ... (port from claw synthesize.py _parse_json_response + parse_decomposition_response)


def parse_labs(who_working: str) -> list[str]:
    """Parse who_working text into clean list of lab names."""
    # ... (port from claw synthesize.py parse_labs)
```

- [ ] **Step 5: Run tests, commit**

```bash
cd /Users/kairos/Projects/kairos
uv run pytest tests/apps/atlas/test_research.py -v
git add apps/atlas/research.py apps/atlas/synthesize.py tests/apps/atlas/test_research.py
git commit -m "feat(atlas): research interface and LLM synthesis via platform Provider"
```

---

### Task 7: Vault Sync

**Files:**
- Create: `apps/atlas/vault.py`
- Create: `tests/apps/atlas/test_vault.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/apps/atlas/test_vault.py
import os
from apps.atlas.vault import VaultSync, init_vault


def test_init_vault_creates_directories(tmp_path):
    vault_dir = str(tmp_path / "vault")
    init_vault(vault_dir)
    assert os.path.isdir(os.path.join(vault_dir, "Nodes", "math"))
    assert os.path.isdir(os.path.join(vault_dir, "Nodes", "neuroscience"))
    assert os.path.isdir(os.path.join(vault_dir, "Status"))


def test_sync_node_creates_markdown(atlas_db, tmp_path):
    vault_dir = str(tmp_path / "vault")
    init_vault(vault_dir)
    atlas_db.insert_node(id="n1", title="CRISPR mechanisms", layer="molecular-bio",
                         domain="genetics", description="How CRISPR-Cas9 works")
    sync = VaultSync(atlas_db, vault_dir)
    sync.sync_node("n1")
    md_path = os.path.join(vault_dir, "Nodes", "molecular-bio", "crispr-mechanisms.md")
    assert os.path.exists(md_path)
    content = open(md_path).read()
    assert "CRISPR mechanisms" in content
    assert "molecular-bio" in content


def test_sync_node_has_frontmatter(atlas_db, tmp_path):
    vault_dir = str(tmp_path / "vault")
    init_vault(vault_dir)
    atlas_db.insert_node(id="n1", title="Test node", layer="math", domain="topology",
                         description="A test node")
    sync = VaultSync(atlas_db, vault_dir)
    sync.sync_node("n1")
    md_path = os.path.join(vault_dir, "Nodes", "math", "test-node.md")
    content = open(md_path).read()
    assert content.startswith("---")
    assert "id: n1" in content


def test_sync_node_with_edges(atlas_db, tmp_path):
    vault_dir = str(tmp_path / "vault")
    init_vault(vault_dir)
    atlas_db.insert_node(id="a", title="Parent node", layer="math", domain="d", description="d")
    atlas_db.insert_node(id="b", title="Child node", layer="math", domain="d", description="d")
    atlas_db.insert_edge("a", "b", "requires")
    sync = VaultSync(atlas_db, vault_dir)
    sync.sync_node("a")
    md_path = os.path.join(vault_dir, "Nodes", "math", "parent-node.md")
    content = open(md_path).read()
    assert "child-node" in content


def test_atomic_write_survives_crash(atlas_db, tmp_path):
    """Atomic write: file should be complete or absent, never partial."""
    vault_dir = str(tmp_path / "vault")
    init_vault(vault_dir)
    atlas_db.insert_node(id="n1", title="Atomic test", layer="math", domain="d", description="d")
    sync = VaultSync(atlas_db, vault_dir)
    sync.sync_node("n1")
    md_path = os.path.join(vault_dir, "Nodes", "math", "atomic-test.md")
    content = open(md_path).read()
    assert content.endswith("\n")
```

- [ ] **Step 2: Write vault.py**

Port from `~/Projects/claw/atlas/vault_sync.py`. Simplify: drop resource graph sync (institutions, facilities, equipment — those belong to other modules). Keep: init_vault, atomic writes via tempfile+rename, node note generation with YAML frontmatter, dependency links via wikilinks, paper references.

```python
# apps/atlas/vault.py
"""Obsidian vault sync — atomic writes, YAML frontmatter, wikilinks."""

from __future__ import annotations

import json
import os
import re
import tempfile

from apps.atlas.db import AtlasDB, LAYERS


def init_vault(vault_dir: str) -> None:
    """Create Obsidian vault directory structure."""
    for layer in LAYERS:
        os.makedirs(os.path.join(vault_dir, "Nodes", layer), exist_ok=True)
    for d in ("Status", "Maps"):
        os.makedirs(os.path.join(vault_dir, d), exist_ok=True)


class VaultSync:
    """Sync Atlas nodes to Obsidian vault as Markdown notes."""

    def __init__(self, db: AtlasDB, vault_dir: str):
        self._db = db
        self._vault_dir = vault_dir

    def sync_node(self, node_id: str) -> None:
        """Generate and atomically write a Markdown note for a node."""
        # ... (port from claw vault_sync.py sync_vault_for_node)
        # Use _atomic_write and _slugify_title

    def sync_dashboard(self) -> None:
        """Generate Status/dashboard.md with coverage stats."""
        # ... (port from claw vault_sync.py sync_dashboard)
```

- [ ] **Step 3: Run tests, commit**

```bash
cd /Users/kairos/Projects/kairos
uv run pytest tests/apps/atlas/test_vault.py -v
git add apps/atlas/vault.py tests/apps/atlas/test_vault.py
git commit -m "feat(atlas): Obsidian vault sync with atomic writes and frontmatter"
```

---

### Task 8: Worker + Integration

**Files:**
- Create: `apps/atlas/worker.py`
- Create: `tests/apps/atlas/test_worker.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/apps/atlas/test_worker.py
from apps.atlas.worker import AtlasWorker


def test_worker_creates(atlas_db, mock_llm, mock_embedder, tmp_path):
    vault_dir = str(tmp_path / "vault")
    worker = AtlasWorker(
        db=atlas_db, llm=mock_llm, embedder=mock_embedder, vault_dir=vault_dir,
    )
    assert worker is not None


def test_worker_tick_empty_db(atlas_db, mock_llm, mock_embedder, tmp_path):
    """Tick on empty DB should return gracefully, not crash."""
    vault_dir = str(tmp_path / "vault")
    worker = AtlasWorker(
        db=atlas_db, llm=mock_llm, embedder=mock_embedder, vault_dir=vault_dir,
    )
    result = worker.tick(tick_number=1)
    assert result["nodes_added"] == 0
    assert "no node" in result["summary"].lower() or "empty" in result["summary"].lower()


def test_worker_tick_expands_node(atlas_db, mock_llm, mock_embedder, tmp_path):
    """Tick with a seeded node should produce sub-nodes."""
    vault_dir = str(tmp_path / "vault")
    atlas_db.insert_node(id="seed", title="Protein folding energy landscapes",
                         layer="molecular-bio", domain="biophysics",
                         description="Energy landscape theory of protein folding")
    worker = AtlasWorker(
        db=atlas_db, llm=mock_llm, embedder=mock_embedder, vault_dir=vault_dir,
    )
    result = worker.tick(tick_number=1)
    assert result["node_id"] == "seed"
    assert result["nodes_added"] >= 0  # Mock LLM may produce sub-problems


def test_worker_tick_logs_to_db(atlas_db, mock_llm, mock_embedder, tmp_path):
    """Tick should create a ticks record."""
    vault_dir = str(tmp_path / "vault")
    atlas_db.insert_node(id="seed", title="Protein folding energy landscapes",
                         layer="molecular-bio", domain="biophysics",
                         description="Energy landscape theory of protein folding")
    worker = AtlasWorker(
        db=atlas_db, llm=mock_llm, embedder=mock_embedder, vault_dir=vault_dir,
    )
    worker.tick(tick_number=1)
    ticks = atlas_db.conn.execute("SELECT * FROM ticks").fetchall()
    assert len(ticks) >= 1


def test_worker_tick_publishes_to_bus(atlas_db, mock_llm, mock_embedder, tmp_path):
    """If bus is provided, tick should publish a research.expanded event."""
    from kplatform.bus import Bus
    vault_dir = str(tmp_path / "vault")
    bus = Bus()
    received = []
    bus.subscribe("research.expanded", lambda msg: received.append(msg))
    atlas_db.insert_node(id="seed", title="Protein folding energy landscapes",
                         layer="molecular-bio", domain="biophysics",
                         description="Energy landscape theory of protein folding")
    worker = AtlasWorker(
        db=atlas_db, llm=mock_llm, embedder=mock_embedder,
        vault_dir=vault_dir, bus=bus,
    )
    worker.tick(tick_number=1)
    # Bus publishing is best-effort; just verify no crash
```

- [ ] **Step 2: Write worker.py**

The tick entrypoint. Orchestrates the full research loop:
1. Select node (via NodeSelector)
2. Synthesize sub-problems (via Synthesizer + LLM)
3. Validate inputs (via validate.filter_sub_problems)
4. Deduplicate (via dedup.deduplicate_sub_problems)
5. Create sub-nodes and edges
6. Compute impact scores (via graph.compute_impact_scores)
7. Sync to vault (via VaultSync)
8. Log tick
9. Publish to bus (optional)

Paper search is deferred — the worker accepts a `PaperSearcher` but defaults to no-op, since real API calls should be injected by the runtime.

```python
# apps/atlas/worker.py
"""Atlas tick worker — the full research loop."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apps.atlas.db import AtlasDB
from apps.atlas.graph import compute_impact_scores
from apps.atlas.node_selector import select_next_node
from apps.atlas.synthesize import Synthesizer
from apps.atlas.validate import filter_sub_problems
from apps.atlas.dedup import deduplicate_sub_problems
from apps.atlas.vault import VaultSync, init_vault

if TYPE_CHECKING:
    from kplatform.llm.provider import Provider
    from kplatform.memory.embeddings import EmbeddingProvider
    from kplatform.bus import Bus

logger = logging.getLogger(__name__)


class AtlasWorker:
    """Single-tick research worker."""

    def __init__(
        self, *,
        db: AtlasDB,
        llm: Provider,
        embedder: EmbeddingProvider,
        vault_dir: str,
        bus: Bus | None = None,
    ):
        self._db = db
        self._synth = Synthesizer(llm)
        self._embedder = embedder
        self._vault_dir = vault_dir
        self._bus = bus
        init_vault(vault_dir)

    def tick(self, tick_number: int) -> dict:
        """Execute one research tick. Returns {node_id, nodes_added, edges_added, summary}."""
        # 1. Select node
        selection = select_next_node(self._db, current_tick=tick_number)
        if selection is None:
            return {"node_id": None, "nodes_added": 0, "edges_added": 0,
                    "summary": "No node selected — empty database"}

        node = self._db.get_node(selection.node_id)
        nodes_added = 0
        edges_added = 0

        try:
            # 2. Synthesize
            synthesis = self._synth.synthesize(
                title=node["title"], description=node["description"],
                layer=node["layer"], domain=node["domain"],
                evidence="", existing_nodes=[],
            )

            # 3. Validate
            sub_problems = synthesis.get("sub_problems", [])
            sub_problems, rejected = filter_sub_problems(sub_problems)

            # 4. Deduplicate and insert
            dedup_results = deduplicate_sub_problems(
                self._db, sub_problems, node["layer"], node["domain"],
                tick=tick_number, embedder=self._embedder,
            )

            for sub_id, is_new in dedup_results:
                if is_new:
                    nodes_added += 1
                if self._db.insert_edge(selection.node_id, sub_id, "requires", tick=tick_number):
                    edges_added += 1

            # 5. Update node assessment
            self._db.update_node(
                selection.node_id,
                status=synthesis.get("status", "open"),
                tractability=synthesis.get("tractability", "unknown"),
                tick_updated=tick_number,
                expanded_at_tick=tick_number,
            )

            # 6. Recompute impact
            compute_impact_scores(self._db)

            # 7. Vault sync
            vault = VaultSync(self._db, self._vault_dir)
            vault.sync_node(selection.node_id)

            summary = f"Expanded '{node['title']}': {nodes_added} sub-nodes, {edges_added} edges"

        except Exception as exc:
            summary = f"Tick {tick_number} failed for {selection.node_id}: {exc}"
            logger.error(summary)

        # 8. Log tick
        self._db.log_tick(
            node_id=selection.node_id, action="expand",
            nodes_added=nodes_added, edges_added=edges_added,
            summary=summary,
        )

        # 9. Publish to bus (best-effort)
        if self._bus:
            try:
                self._bus.publish("research.expanded", {
                    "node_id": selection.node_id,
                    "nodes_added": nodes_added,
                    "edges_added": edges_added,
                    "tick": tick_number,
                })
            except Exception:
                pass

        return {
            "node_id": selection.node_id,
            "nodes_added": nodes_added,
            "edges_added": edges_added,
            "summary": summary,
        }
```

- [ ] **Step 3: Update apps/atlas/__init__.py**

```python
# apps/atlas/__init__.py
"""Atlas — research engine with 10-layer biology DAG."""

from apps.atlas.db import AtlasDB, LAYERS
from apps.atlas.graph import compute_impact_scores, compute_priority, find_critical_path
from apps.atlas.node_selector import select_next_node, SelectionMode
from apps.atlas.dedup import find_duplicate, deduplicate_sub_problems
from apps.atlas.validate import is_valid_node, filter_sub_problems
from apps.atlas.vault import VaultSync, init_vault
from apps.atlas.synthesize import Synthesizer
from apps.atlas.worker import AtlasWorker

__all__ = [
    "AtlasDB", "LAYERS",
    "compute_impact_scores", "compute_priority", "find_critical_path",
    "select_next_node", "SelectionMode",
    "find_duplicate", "deduplicate_sub_problems",
    "is_valid_node", "filter_sub_problems",
    "VaultSync", "init_vault",
    "Synthesizer", "AtlasWorker",
]
```

- [ ] **Step 4: Run full test suite, commit**

```bash
cd /Users/kairos/Projects/kairos
uv run pytest tests/apps/atlas/ -v --tb=short
git add apps/atlas/ tests/apps/atlas/
git commit -m "feat(atlas): worker tick loop with full research pipeline"
```

- [ ] **Step 5: Verify all imports and run full monorepo suite**

```bash
cd /Users/kairos/Projects/kairos
uv run python -c "
from apps.atlas import AtlasDB, AtlasWorker, Synthesizer, VaultSync
from apps.atlas import compute_impact_scores, select_next_node, is_valid_node
print('Atlas imports OK')
"
uv run pytest tests/ -v --tb=short
```

---

## Summary

| Task | What | Tests |
|------|------|-------|
| 1 | Database schema (nodes, edges, papers, FTS5) | ~8 |
| 2 | Graph engine (impact scoring, SCC, critical path) | ~8 |
| 3 | Node selector (TOC: 60% constraint, 40% explore) | ~6 |
| 4 | Dedup (embedding similarity, canonical slugs) | ~5 |
| 5 | Validate (garbage rejection, quality thresholds) | ~5 |
| 6 | Research + Synthesize (LLM via platform Provider) | ~6 |
| 7 | Vault sync (atomic writes, YAML frontmatter) | ~5 |
| 8 | Worker + integration (full tick loop, bus publish) | ~5 |
| **Total** | **8 tasks** | **~48 tests** |

## Key Porting Decisions

- **Hardcoded Ollama calls** in `synthesize.py` and `research.py` replaced with `kplatform.llm.Provider` protocol. Provider is injected, not imported.
- **Custom embeddings** via Ollama's `/api/embed` replaced with `kplatform.memory.EmbeddingProvider` (NomicEmbedProvider). Embedder is injected into dedup.
- **Arena tables** (assessments, comparisons, workers) dropped from Atlas schema — those belong to `apps/arena/`.
- **Resource graph** (institutions, facilities, equipment, capabilities) dropped from Atlas schema — future shared module.
- **Legacy ledger** table dropped — use `kplatform.ledger.Ledger` instead.
- **Paper search** abstracted behind `PaperSearcher` Protocol for mock-friendly testing. Real API implementations (PubMed, arXiv, Semantic Scholar) injected by runtime.
- **Bus integration** is optional — worker publishes `research.expanded` events but continues without bus.

## Next Plans

After this plan is complete:
1. **Apps: Arena** — port goal execution from agi
2. **Apps: Ratchet** — port block lifecycle from code
3. **Apps: Governor** — port observe/decide from why
