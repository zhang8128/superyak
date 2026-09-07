# Kairos Apps: Governor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Port the governance decision engine from ~/Projects/why/ into the Kairos platform as a worker application that observes system state via Bus subscriptions, applies priority rules, manages a knowledge graph with tiered verification, and publishes directives.

**Architecture:** Governor runs as a kairos worker dispatched by the daemon in tick mode. It has two planes: a governance plane (priority rules engine that observes worker state via Bus and outputs scored directives) and a knowledge plane (SQLite knowledge graph with external code verification and adversarial LLM challenges for tier promotion). All decisions are logged to Ledger. The rule engine is pure functions — no side effects, easy to test.

**Tech Stack:** Python 3.12+, SQLite (knowledge.db), kplatform.bus (Bus), kplatform.ledger (Ledger), kplatform.llm (Provider, OllamaProvider), kplatform.sandbox (Sandbox, ToolResult), asyncio

**Spec:** docs/superpowers/specs/2026-03-21-kairos-platform-design.md

**Source (reference):** ~/Projects/why/

---

## File Structure

```
apps/
  governor/
    __init__.py           -- exports: GovernorWorker, RuleEngine, KnowledgeDB, Observer
    rules.py              -- priority rule engine (pure functions returning scored actions)
    observer.py           -- state gathering from bus events + worker status
    knowledge.py          -- knowledge DB schema, CRUD, tier queries
    verification.py       -- sandboxed code verification (tier 0→1 gate)
    challenge.py          -- adversarial LLM challenge (tier promotion)
    worker.py             -- tick entrypoint the daemon dispatches
    CLAUDE.md
tests/
  apps/
    governor/
      __init__.py
      conftest.py
      test_rules.py
      test_observer.py
      test_knowledge.py
      test_verification.py
      test_challenge.py
      test_worker.py
```

---

### Task 1: Knowledge Schema + CRUD

**Files:**
- Create: `apps/governor/__init__.py`
- Create: `apps/governor/knowledge.py`
- Create: `apps/governor/CLAUDE.md`
- Create: `tests/apps/__init__.py`
- Create: `tests/apps/governor/__init__.py`
- Create: `tests/apps/governor/conftest.py`
- Test: `tests/apps/governor/test_knowledge.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/apps/governor/test_knowledge.py
"""Knowledge DB: schema, CRUD, tier queries, FTS."""

import sqlite3
import pytest
from apps.governor.knowledge import KnowledgeDB


class TestSchema:
    """Database schema creation and table presence."""

    def test_creates_all_tables(self, knowledge_db):
        tables = knowledge_db.tables()
        expected = {"concepts", "claims", "edges", "challenges",
                    "sources", "verifications", "reference_data"}
        assert expected.issubset(set(tables))

    def test_fts_tables_created(self, knowledge_db):
        tables = knowledge_db.tables()
        assert "claims_fts" in tables
        assert "concepts_fts" in tables

    def test_wal_mode_enabled(self, knowledge_db):
        mode = knowledge_db._conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_foreign_keys_enabled(self, knowledge_db):
        fk = knowledge_db._conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1


class TestConceptCRUD:
    """Concept create, read, update operations."""

    def test_add_concept(self, knowledge_db):
        cid = knowledge_db.add_concept(
            id="test:thing", domain="test", name="Thing",
            description="A test concept",
        )
        assert cid == "test:thing"

    def test_get_concept(self, knowledge_db):
        knowledge_db.add_concept(
            id="test:item", domain="test", name="Item",
            description="An item",
        )
        c = knowledge_db.get_concept("test:item")
        assert c is not None
        assert c["name"] == "Item"
        assert c["domain"] == "test"
        assert c["tier"] == 0

    def test_get_concept_not_found(self, knowledge_db):
        assert knowledge_db.get_concept("nonexistent") is None

    def test_add_duplicate_concept_upserts(self, knowledge_db):
        knowledge_db.add_concept(id="test:dup", domain="test", name="Original")
        knowledge_db.add_concept(id="test:dup", domain="test", name="Updated")
        c = knowledge_db.get_concept("test:dup")
        assert c["name"] == "Updated"

    def test_search_concepts(self, knowledge_db):
        knowledge_db.add_concept(id="med:heart", domain="medicine", name="Heart")
        knowledge_db.add_concept(id="med:lung", domain="medicine", name="Lung")
        knowledge_db.add_concept(id="cs:algo", domain="cs", name="Algorithm")
        results = knowledge_db.search_concepts("heart")
        assert len(results) == 1
        assert results[0]["id"] == "med:heart"

    def test_search_concepts_by_domain(self, knowledge_db):
        knowledge_db.add_concept(id="med:a", domain="medicine", name="A")
        knowledge_db.add_concept(id="cs:b", domain="cs", name="B")
        results = knowledge_db.search_concepts("", domain="medicine")
        assert all(r["domain"] == "medicine" for r in results)

    def test_promote_concept(self, knowledge_db):
        knowledge_db.add_concept(id="test:p", domain="test", name="P")
        knowledge_db.promote_concept("test:p", tier=1)
        c = knowledge_db.get_concept("test:p")
        assert c["tier"] == 1
        assert c["promoted_at"] is not None


class TestClaimCRUD:
    """Claim create, query, verify operations."""

    def test_add_claim(self, knowledge_db):
        knowledge_db.add_concept(id="test:c", domain="test", name="C")
        claim_id = knowledge_db.add_claim("test:c", "Water is wet", type="assertion")
        assert isinstance(claim_id, int)

    def test_get_claims_for_concept(self, knowledge_db):
        knowledge_db.add_concept(id="test:c2", domain="test", name="C2")
        knowledge_db.add_claim("test:c2", "Claim one")
        knowledge_db.add_claim("test:c2", "Claim two")
        claims = knowledge_db.get_claims("test:c2")
        assert len(claims) == 2

    def test_verify_claim(self, knowledge_db):
        knowledge_db.add_concept(id="test:v", domain="test", name="V")
        cid = knowledge_db.add_claim("test:v", "Verifiable claim")
        knowledge_db.verify_claim(cid, verified=True)
        claims = knowledge_db.get_claims("test:v")
        assert claims[0]["verified"] == 1

    def test_search_claims_fts(self, knowledge_db):
        knowledge_db.add_concept(id="test:fts", domain="test", name="FTS")
        knowledge_db.add_claim("test:fts", "The mitochondria is the powerhouse")
        knowledge_db.add_claim("test:fts", "Gravity pulls objects down")
        results = knowledge_db.search_claims("mitochondria")
        assert len(results) >= 1
        assert "mitochondria" in results[0]["claim"]


class TestEdges:
    """Relationship edges between concepts."""

    def test_add_edge(self, knowledge_db):
        knowledge_db.add_concept(id="test:a", domain="test", name="A")
        knowledge_db.add_concept(id="test:b", domain="test", name="B")
        eid = knowledge_db.add_edge("test:a", "requires", "test:b")
        assert isinstance(eid, int)

    def test_invalid_predicate_rejected(self, knowledge_db):
        knowledge_db.add_concept(id="test:x", domain="test", name="X")
        knowledge_db.add_concept(id="test:y", domain="test", name="Y")
        with pytest.raises(sqlite3.IntegrityError):
            knowledge_db.add_edge("test:x", "invalid_predicate", "test:y")

    def test_get_prerequisites(self, knowledge_db):
        knowledge_db.add_concept(id="test:c1", domain="test", name="C1")
        knowledge_db.add_concept(id="test:c2", domain="test", name="C2")
        knowledge_db.add_concept(id="test:c3", domain="test", name="C3")
        knowledge_db.add_edge("test:c1", "requires", "test:c2")
        knowledge_db.add_edge("test:c2", "requires", "test:c3")
        prereqs = knowledge_db.get_prerequisites("test:c1", max_depth=5)
        prereq_ids = [p["id"] for p in prereqs]
        assert "test:c2" in prereq_ids
        assert "test:c3" in prereq_ids

    def test_get_contradictions(self, knowledge_db):
        knowledge_db.add_concept(id="test:m", domain="test", name="M")
        knowledge_db.add_concept(id="test:n", domain="test", name="N")
        knowledge_db.add_edge("test:m", "contradicts", "test:n")
        contras = knowledge_db.get_contradictions("test:m")
        assert len(contras) == 1
        assert contras[0]["target_id"] == "test:n"


class TestChallenges:
    """Challenge CRUD and result tracking."""

    def test_add_challenge(self, knowledge_db):
        knowledge_db.add_concept(id="test:ch", domain="test", name="Ch")
        cid = knowledge_db.add_challenge(
            "test:ch", "What is X?", expected_answer="Y", difficulty="basic",
        )
        assert isinstance(cid, int)

    def test_record_challenge_result(self, knowledge_db):
        knowledge_db.add_concept(id="test:cr", domain="test", name="CR")
        cid = knowledge_db.add_challenge("test:cr", "Q?", expected_answer="A")
        knowledge_db.record_challenge_result(cid, result="pass")
        ch = knowledge_db.get_challenges("test:cr")
        assert ch[0]["last_result"] == "pass"
        assert ch[0]["last_tested"] is not None


class TestVerifications:
    """Verification artifact CRUD."""

    def test_add_verification(self, knowledge_db):
        knowledge_db.add_concept(id="test:vf", domain="test", name="VF")
        claim_id = knowledge_db.add_claim("test:vf", "2+2=4")
        vid = knowledge_db.add_verification(
            claim_id, type="code", body="print(2+2)", expected="4",
        )
        assert isinstance(vid, int)

    def test_get_verifications_for_claim(self, knowledge_db):
        knowledge_db.add_concept(id="test:vf2", domain="test", name="VF2")
        claim_id = knowledge_db.add_claim("test:vf2", "e=mc2")
        knowledge_db.add_verification(claim_id, type="code", body="print('ok')", expected="ok")
        knowledge_db.add_verification(claim_id, type="constraint", body="exit(0)", expected=None)
        vfs = knowledge_db.get_verifications(claim_id)
        assert len(vfs) == 2


class TestStats:
    """Knowledge statistics and tier distribution."""

    def test_stats_empty(self, knowledge_db):
        stats = knowledge_db.stats()
        assert stats["concepts"] == 0
        assert stats["claims"] == 0
        assert stats["edges"] == 0

    def test_stats_populated(self, knowledge_db):
        knowledge_db.add_concept(id="s:a", domain="science", name="A")
        knowledge_db.add_concept(id="s:b", domain="science", name="B")
        knowledge_db.add_claim("s:a", "Claim 1")
        knowledge_db.add_edge("s:a", "requires", "s:b")
        stats = knowledge_db.stats()
        assert stats["concepts"] == 2
        assert stats["claims"] == 1
        assert stats["edges"] == 1

    def test_tier_distribution(self, knowledge_db):
        knowledge_db.add_concept(id="t:a", domain="test", name="A")
        knowledge_db.add_concept(id="t:b", domain="test", name="B")
        knowledge_db.promote_concept("t:b", tier=1)
        dist = knowledge_db.tier_distribution()
        assert dist[0] == 1  # tier 0
        assert dist[1] == 1  # tier 1
```

```python
# tests/apps/governor/conftest.py
"""Shared fixtures for governor tests."""

import asyncio
import pytest
from pathlib import Path

from apps.governor.knowledge import KnowledgeDB


@pytest.fixture
def knowledge_db(tmp_path):
    """Fresh in-memory knowledge DB for each test."""
    db = KnowledgeDB(tmp_path / "knowledge.db")
    yield db
    db.close()


@pytest.fixture
def event_loop():
    """Fresh event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/kairos/Projects/kairos && .venv/bin/python -m pytest tests/apps/governor/test_knowledge.py -x -q`

- [ ] **Step 3: Write implementation**

```python
# apps/governor/__init__.py
"""Governor — observe and decide."""

from apps.governor.knowledge import KnowledgeDB
from apps.governor.rules import RuleEngine
from apps.governor.observer import Observer
from apps.governor.worker import GovernorWorker

__all__ = ["KnowledgeDB", "RuleEngine", "Observer", "GovernorWorker"]
```

```python
# apps/governor/knowledge.py
"""Knowledge graph — SQLite schema, CRUD, tier queries, FTS5.

Ported from ~/Projects/why/scripts/init_knowledge.py and knowledge_mcp.py.
Concepts progress through tiers: 0=ingested, 1=verified, 2=cross-referenced, 3=applied.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

TIER_NAMES = {0: "ingested", 1: "verified", 2: "cross-referenced", 3: "applied"}

SCHEMA = """\
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS concepts (
    id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    tier INTEGER DEFAULT 0,
    source_file TEXT,
    source_location TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    promoted_at TEXT
);

CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id TEXT NOT NULL,
    claim TEXT NOT NULL,
    type TEXT DEFAULT 'assertion',
    confidence TEXT DEFAULT 'medium',
    verified INTEGER DEFAULT 0,
    source TEXT,
    FOREIGN KEY (concept_id) REFERENCES concepts(id)
);

CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    predicate TEXT NOT NULL CHECK (predicate IN (
        'requires', 'generalizes', 'specializes',
        'contradicts', 'applies_to', 'example_of', 'related_to'
    )),
    target_id TEXT NOT NULL,
    strength TEXT DEFAULT 'strong' CHECK (strength IN ('strong', 'weak', 'optional')),
    FOREIGN KEY (source_id) REFERENCES concepts(id),
    FOREIGN KEY (target_id) REFERENCES concepts(id)
);

CREATE TABLE IF NOT EXISTS challenges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id TEXT NOT NULL,
    question TEXT NOT NULL,
    expected_answer TEXT,
    difficulty TEXT DEFAULT 'medium',
    last_tested TEXT,
    last_result TEXT,
    FOREIGN KEY (concept_id) REFERENCES concepts(id)
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    title TEXT,
    total_pages INTEGER,
    pages_processed INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id INTEGER NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('code', 'reference', 'constraint')),
    body TEXT NOT NULL,
    expected TEXT,
    last_run TEXT,
    last_result TEXT,
    last_output TEXT,
    error_message TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id)
);

CREATE TABLE IF NOT EXISTS reference_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    unit TEXT,
    source TEXT,
    UNIQUE(domain, key)
);

CREATE INDEX IF NOT EXISTS idx_concepts_domain ON concepts(domain);
CREATE INDEX IF NOT EXISTS idx_concepts_tier ON concepts(tier);
CREATE INDEX IF NOT EXISTS idx_claims_concept ON claims(concept_id);
CREATE INDEX IF NOT EXISTS idx_claims_type ON claims(type);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_predicate ON edges(predicate);
CREATE INDEX IF NOT EXISTS idx_challenges_concept ON challenges(concept_id);
CREATE INDEX IF NOT EXISTS idx_verifications_claim ON verifications(claim_id);
CREATE INDEX IF NOT EXISTS idx_verifications_type ON verifications(type);
CREATE INDEX IF NOT EXISTS idx_verifications_result ON verifications(last_result);
CREATE INDEX IF NOT EXISTS idx_reference_domain ON reference_data(domain);

CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(
    claim, content=claims, content_rowid=id
);
CREATE VIRTUAL TABLE IF NOT EXISTS concepts_fts USING fts5(
    name, description, content=concepts, content_rowid=rowid
);
"""


class KnowledgeDB:
    """Knowledge graph backed by SQLite."""

    def __init__(self, path: Path | str):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def tables(self) -> list[str]:
        """List all tables and virtual tables."""
        rows = self._conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type IN ('table', 'view') ORDER BY name"
        ).fetchall()
        return [r["name"] for r in rows]

    # -- Concepts --

    def add_concept(
        self, *, id: str, domain: str, name: str,
        description: str | None = None,
        source_file: str | None = None,
        source_location: str | None = None,
    ) -> str:
        self._conn.execute(
            "INSERT INTO concepts (id, domain, name, description, source_file, source_location) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "name=excluded.name, description=excluded.description, "
            "source_file=excluded.source_file, source_location=excluded.source_location",
            (id, domain, name, description, source_file, source_location),
        )
        self._conn.commit()
        return id

    def get_concept(self, concept_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM concepts WHERE id = ?", (concept_id,)
        ).fetchone()
        return dict(row) if row else None

    def search_concepts(
        self, query: str, *, domain: str | None = None, limit: int = 20
    ) -> list[dict]:
        q = query.strip().lower()
        sql = (
            "SELECT * FROM concepts "
            "WHERE (LOWER(name) LIKE ? OR LOWER(id) LIKE ? OR LOWER(description) LIKE ?)"
        )
        params: list = [f"%{q}%", f"%{q}%", f"%{q}%"]
        if domain:
            sql += " AND LOWER(domain) = ?"
            params.append(domain.strip().lower())
        sql += " ORDER BY tier DESC, name LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def promote_concept(self, concept_id: str, *, tier: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE concepts SET tier = ?, promoted_at = ? WHERE id = ?",
            (tier, now, concept_id),
        )
        self._conn.commit()

    # -- Claims --

    def add_claim(
        self, concept_id: str, claim: str, *,
        type: str = "assertion", confidence: str = "medium",
        source: str | None = None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO claims (concept_id, claim, type, confidence, source) "
            "VALUES (?, ?, ?, ?, ?)",
            (concept_id, claim, type, confidence, source),
        )
        # Sync FTS
        self._conn.execute(
            "INSERT INTO claims_fts (rowid, claim) VALUES (?, ?)",
            (cur.lastrowid, claim),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_claims(self, concept_id: str) -> list[dict]:
        return [
            dict(r) for r in self._conn.execute(
                "SELECT * FROM claims WHERE concept_id = ? ORDER BY id",
                (concept_id,),
            ).fetchall()
        ]

    def verify_claim(self, claim_id: int, *, verified: bool) -> None:
        self._conn.execute(
            "UPDATE claims SET verified = ? WHERE id = ?",
            (1 if verified else 0, claim_id),
        )
        self._conn.commit()

    def search_claims(
        self, query: str, *, claim_type: str | None = None,
        verified_only: bool = False, limit: int = 20,
    ) -> list[dict]:
        # Try FTS5 first
        try:
            sql = (
                "SELECT c.* FROM claims_fts f "
                "JOIN claims c ON c.id = f.rowid "
                "WHERE claims_fts MATCH ?"
            )
            params: list = [query]
            if claim_type:
                sql += " AND c.type = ?"
                params.append(claim_type)
            if verified_only:
                sql += " AND c.verified = 1"
            sql += " LIMIT ?"
            params.append(limit)
            rows = self._conn.execute(sql, params).fetchall()
            if rows:
                return [dict(r) for r in rows]
        except Exception:
            pass
        # Fallback to LIKE
        q = query.strip().lower()
        sql = "SELECT * FROM claims WHERE LOWER(claim) LIKE ?"
        params = [f"%{q}%"]
        if claim_type:
            sql += " AND type = ?"
            params.append(claim_type)
        if verified_only:
            sql += " AND verified = 1"
        sql += " ORDER BY verified DESC, id LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    # -- Edges --

    def add_edge(
        self, source_id: str, predicate: str, target_id: str, *,
        strength: str = "strong",
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO edges (source_id, predicate, target_id, strength) "
            "VALUES (?, ?, ?, ?)",
            (source_id, predicate, target_id, strength),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_prerequisites(
        self, concept_id: str, *, max_depth: int = 5,
    ) -> list[dict]:
        """Recursive DFS walk of 'requires' edges."""
        visited: set[str] = set()
        result: list[dict] = []

        def dfs(cid: str, depth: int) -> None:
            if depth > max_depth or cid in visited:
                return
            visited.add(cid)
            rows = self._conn.execute(
                "SELECT e.target_id, c.id, c.name, c.tier "
                "FROM edges e LEFT JOIN concepts c ON c.id = e.target_id "
                "WHERE e.source_id = ? AND e.predicate = 'requires'",
                (cid,),
            ).fetchall()
            for r in rows:
                entry = dict(r)
                if entry["target_id"] not in visited:
                    result.append(entry)
                    dfs(entry["target_id"], depth + 1)

        dfs(concept_id, 0)
        return result

    def get_contradictions(self, concept_id: str) -> list[dict]:
        return [
            dict(r) for r in self._conn.execute(
                "SELECT * FROM edges "
                "WHERE source_id = ? AND predicate = 'contradicts'",
                (concept_id,),
            ).fetchall()
        ]

    # -- Challenges --

    def add_challenge(
        self, concept_id: str, question: str, *,
        expected_answer: str | None = None,
        difficulty: str = "medium",
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO challenges (concept_id, question, expected_answer, difficulty) "
            "VALUES (?, ?, ?, ?)",
            (concept_id, question, expected_answer, difficulty),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_challenges(self, concept_id: str) -> list[dict]:
        return [
            dict(r) for r in self._conn.execute(
                "SELECT * FROM challenges WHERE concept_id = ? ORDER BY id",
                (concept_id,),
            ).fetchall()
        ]

    def record_challenge_result(self, challenge_id: int, *, result: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE challenges SET last_result = ?, last_tested = ? WHERE id = ?",
            (result, now, challenge_id),
        )
        self._conn.commit()

    # -- Verifications --

    def add_verification(
        self, claim_id: int, *, type: str, body: str,
        expected: str | None = None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO verifications (claim_id, type, body, expected) "
            "VALUES (?, ?, ?, ?)",
            (claim_id, type, body, expected),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_verifications(self, claim_id: int) -> list[dict]:
        return [
            dict(r) for r in self._conn.execute(
                "SELECT * FROM verifications WHERE claim_id = ? ORDER BY id",
                (claim_id,),
            ).fetchall()
        ]

    def record_verification_result(
        self, verification_id: int, *, result: str,
        output: str = "", error: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE verifications SET last_result = ?, last_run = ?, "
            "last_output = ?, error_message = ? WHERE id = ?",
            (result, now, output, error, verification_id),
        )
        self._conn.commit()

    # -- Reference Data --

    def set_reference(
        self, domain: str, key: str, value: str, *,
        unit: str | None = None, source: str | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO reference_data (domain, key, value, unit, source) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(domain, key) DO UPDATE SET "
            "value=excluded.value, unit=excluded.unit, source=excluded.source",
            (domain, key, value, unit, source),
        )
        self._conn.commit()

    def get_reference(self, domain: str, key: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM reference_data WHERE domain = ? AND key = ?",
            (domain, key),
        ).fetchone()
        return dict(row) if row else None

    # -- Stats --

    def stats(self) -> dict:
        concepts = self._conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]
        claims = self._conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
        verified = self._conn.execute(
            "SELECT COUNT(*) FROM claims WHERE verified = 1"
        ).fetchone()[0]
        edges = self._conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        return {
            "concepts": concepts, "claims": claims,
            "verified_claims": verified, "edges": edges,
        }

    def tier_distribution(self) -> dict[int, int]:
        rows = self._conn.execute(
            "SELECT tier, COUNT(*) as n FROM concepts GROUP BY tier ORDER BY tier"
        ).fetchall()
        return {r["tier"]: r["n"] for r in rows}
```

```markdown
# Governor

Observe and decide. Two planes:

1. **Governance plane** — priority rule engine that observes system state via
   Bus subscriptions, applies rules, outputs prioritized directives
2. **Knowledge plane** — knowledge graph with tiered verification, tier promotion
   gates via external code execution and adversarial LLM challenge

## Key Files

| File | Purpose |
|------|---------|
| rules.py | Priority rules as pure functions |
| observer.py | State gathering from bus events |
| knowledge.py | Knowledge DB schema + CRUD |
| verification.py | Sandboxed code verification (tier 0→1) |
| challenge.py | Adversarial LLM challenge (tier promotion) |
| worker.py | Tick entrypoint dispatched by daemon |

## Platform Dependencies

- `kplatform.bus.Bus` — subscribe to worker events, publish directives
- `kplatform.ledger.Ledger` — audit all decisions
- `kplatform.llm.Provider` — LLM for knowledge challenges
- `kplatform.sandbox.Sandbox` — sandboxed code verification

## Testing

```bash
cd /Users/kairos/Projects/kairos
.venv/bin/python -m pytest tests/apps/governor/ -q
```
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/kairos/Projects/kairos && .venv/bin/python -m pytest tests/apps/governor/test_knowledge.py -x -q`
Expected: All 22 tests PASS

- [ ] **Step 5: Commit**

---

### Task 2: Priority Rule Engine

**Files:**
- Create: `apps/governor/rules.py`
- Test: `tests/apps/governor/test_rules.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/apps/governor/test_rules.py
"""Priority rule engine — pure functions, no side effects."""

import pytest
from apps.governor.rules import (
    RuleEngine,
    rule_worker_errors,
    rule_idle_workers,
    rule_stale_goals,
    rule_memory_health,
    rule_knowledge_gaps,
    rule_pending_goals,
    rule_retrospective,
    rule_high_error_rate,
    rule_blocked_workers,
)


def make_state(**overrides) -> dict:
    """Construct a minimal state dict with defaults."""
    state = {
        "workers": {},
        "goals": [],
        "errors": [],
        "memory_health": {},
        "knowledge_stats": {"concepts": 0, "claims": 0, "verified_claims": 0},
        "tick_count": 0,
    }
    state.update(overrides)
    return state


class TestIndividualRules:
    """Each rule is a pure function: state -> list[action]."""

    def test_worker_errors_fires_on_failures(self):
        state = make_state(workers={
            "atlas": {"status": "error", "last_error": "crash", "error_count": 3},
            "arena": {"status": "running", "error_count": 0},
        })
        actions = rule_worker_errors(state)
        assert len(actions) == 1
        assert actions[0]["type"] == "investigate-error"
        assert actions[0]["worker"] == "atlas"
        assert actions[0]["priority"] >= 80

    def test_worker_errors_quiet_when_healthy(self):
        state = make_state(workers={
            "atlas": {"status": "running", "error_count": 0},
        })
        assert rule_worker_errors(state) == []

    def test_idle_workers_detects_idle(self):
        state = make_state(workers={
            "arena": {"status": "idle", "idle_since": "2026-03-22T00:00:00Z", "idle_ticks": 5},
        })
        actions = rule_idle_workers(state)
        assert len(actions) == 1
        assert actions[0]["type"] == "assign-work"

    def test_stale_goals_flags_old_goals(self):
        state = make_state(goals=[
            {"id": "g1", "status": "active", "stale_ticks": 10, "title": "Build X"},
        ])
        actions = rule_stale_goals(state)
        assert len(actions) == 1
        assert actions[0]["type"] == "review-goal"
        assert actions[0]["priority"] >= 50

    def test_stale_goals_ignores_fresh(self):
        state = make_state(goals=[
            {"id": "g1", "status": "active", "stale_ticks": 1, "title": "Build X"},
        ])
        assert rule_stale_goals(state) == []

    def test_memory_health_flags_issues(self):
        state = make_state(memory_health={
            "atlas": {"episodes": 5000, "compression_lag": 120},
        })
        actions = rule_memory_health(state)
        assert len(actions) >= 1
        assert actions[0]["type"] == "compress-memory"

    def test_knowledge_gaps_flags_low_verification(self):
        state = make_state(knowledge_stats={
            "concepts": 100, "claims": 500, "verified_claims": 50,
        })
        actions = rule_knowledge_gaps(state)
        assert len(actions) == 1
        assert actions[0]["type"] == "verify-knowledge"

    def test_pending_goals_generates_actions(self):
        state = make_state(goals=[
            {"id": "g2", "status": "pending", "title": "Research Y", "priority": 70},
        ])
        actions = rule_pending_goals(state)
        assert len(actions) == 1
        assert actions[0]["type"] == "start-goal"

    def test_retrospective_fires_periodically(self):
        state = make_state(tick_count=50)
        actions = rule_retrospective(state)
        assert len(actions) == 1
        assert actions[0]["type"] == "retrospective"

    def test_retrospective_quiet_off_cycle(self):
        state = make_state(tick_count=7)
        assert rule_retrospective(state) == []

    def test_high_error_rate_fires(self):
        state = make_state(
            errors=[{"ts": "2026-03-22T00:00:00Z", "worker": "atlas"}] * 10,
            workers={"atlas": {"status": "running", "error_count": 10}},
        )
        actions = rule_high_error_rate(state)
        assert len(actions) >= 1
        assert actions[0]["type"] == "pause-worker"

    def test_blocked_workers_detects_blocking(self):
        state = make_state(workers={
            "arena": {"status": "blocked", "blocked_by": "g3", "blocked_ticks": 3},
        })
        actions = rule_blocked_workers(state)
        assert len(actions) == 1
        assert actions[0]["type"] == "unblock-worker"


class TestRuleEngine:
    """RuleEngine aggregates all rules and sorts by priority."""

    def test_empty_state_no_actions(self):
        engine = RuleEngine()
        result = engine.tick(make_state())
        assert result["actions"] == []
        assert result["recommendation"] is None

    def test_highest_priority_is_recommendation(self):
        state = make_state(
            workers={
                "atlas": {"status": "error", "last_error": "crash", "error_count": 3},
                "arena": {"status": "idle", "idle_since": "2026-03-22T00:00:00Z", "idle_ticks": 5},
            },
        )
        engine = RuleEngine()
        result = engine.tick(state)
        # Error investigation should be highest priority
        assert result["recommendation"]["type"] == "investigate-error"
        assert result["recommendation"]["priority"] >= result["actions"][1]["priority"]

    def test_all_actions_sorted_descending(self):
        state = make_state(
            workers={
                "atlas": {"status": "error", "last_error": "crash", "error_count": 3},
                "arena": {"status": "idle", "idle_since": "2026-03-22T00:00:00Z", "idle_ticks": 5},
            },
            goals=[{"id": "g1", "status": "pending", "title": "Do X", "priority": 50}],
        )
        engine = RuleEngine()
        result = engine.tick(state)
        priorities = [a["priority"] for a in result["actions"]]
        assert priorities == sorted(priorities, reverse=True)

    def test_custom_rules_can_be_added(self):
        def custom_rule(state):
            return [{"priority": 200, "type": "custom", "reason": "test", "action": "noop"}]

        engine = RuleEngine(extra_rules=[custom_rule])
        result = engine.tick(make_state())
        assert result["recommendation"]["type"] == "custom"

    def test_tick_result_structure(self):
        engine = RuleEngine()
        result = engine.tick(make_state())
        assert "tick_at" in result
        assert "actions" in result
        assert "recommendation" in result
        assert "action_count" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/kairos/Projects/kairos && .venv/bin/python -m pytest tests/apps/governor/test_rules.py -x -q`

- [ ] **Step 3: Write implementation**

```python
# apps/governor/rules.py
"""Priority rule engine — pure functions returning scored actions.

Ported from ~/Projects/why/scripts/tick.py. Rules are decoupled from specific
repos — they operate on a generic state dict populated by Observer.

Each rule: fn(state: dict) -> list[dict]
Each action: {"priority": int, "type": str, "reason": str, "action": str, ...}
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

# Type alias for rule functions
Rule = Callable[[dict], list[dict]]


# ---------------------------------------------------------------------------
# Individual rules — each is a pure function
# ---------------------------------------------------------------------------

def rule_worker_errors(state: dict) -> list[dict]:
    """Workers in error state need investigation."""
    actions = []
    for name, info in state.get("workers", {}).items():
        if info.get("status") == "error" or info.get("error_count", 0) >= 3:
            actions.append({
                "priority": 90,
                "type": "investigate-error",
                "worker": name,
                "reason": f"{name} has {info.get('error_count', 0)} errors: {info.get('last_error', 'unknown')}",
                "action": f"Investigate errors in {name} worker",
            })
    return actions


def rule_idle_workers(state: dict) -> list[dict]:
    """Idle workers should be assigned work."""
    actions = []
    for name, info in state.get("workers", {}).items():
        if info.get("status") == "idle" and info.get("idle_ticks", 0) >= 3:
            actions.append({
                "priority": 40,
                "type": "assign-work",
                "worker": name,
                "reason": f"{name} idle for {info.get('idle_ticks', 0)} ticks",
                "action": f"Find and assign work to {name}",
            })
    return actions


def rule_stale_goals(state: dict) -> list[dict]:
    """Active goals with no progress need review."""
    actions = []
    for goal in state.get("goals", []):
        if goal.get("status") == "active" and goal.get("stale_ticks", 0) >= 5:
            actions.append({
                "priority": 55,
                "type": "review-goal",
                "goal_id": goal["id"],
                "reason": f"Goal '{goal['title']}' stale for {goal['stale_ticks']} ticks",
                "action": f"Review goal '{goal['title']}' — may need decomposition or re-evaluation",
            })
    return actions


def rule_memory_health(state: dict) -> list[dict]:
    """Memory instances with high episode counts or compression lag."""
    actions = []
    for instance, health in state.get("memory_health", {}).items():
        episodes = health.get("episodes", 0)
        lag = health.get("compression_lag", 0)
        if episodes > 1000 or lag > 60:
            actions.append({
                "priority": 45,
                "type": "compress-memory",
                "instance": instance,
                "reason": f"{instance} memory: {episodes} episodes, {lag}s compression lag",
                "action": f"Trigger compression for {instance} memory instance",
            })
    return actions


def rule_knowledge_gaps(state: dict) -> list[dict]:
    """Knowledge base with low verification coverage."""
    actions = []
    stats = state.get("knowledge_stats", {})
    total_claims = stats.get("claims", 0)
    verified = stats.get("verified_claims", 0)
    if total_claims > 0 and (verified / total_claims) < 0.5:
        pct = int(verified * 100 / total_claims)
        actions.append({
            "priority": 35,
            "type": "verify-knowledge",
            "reason": f"Knowledge verification at {pct}% ({verified}/{total_claims} claims)",
            "action": "Run verification challenges on unverified claims",
        })
    return actions


def rule_pending_goals(state: dict) -> list[dict]:
    """Pending goals need to be started."""
    actions = []
    for goal in state.get("goals", []):
        if goal.get("status") == "pending":
            actions.append({
                "priority": goal.get("priority", 50),
                "type": "start-goal",
                "goal_id": goal["id"],
                "reason": f"Goal '{goal['title']}' is pending",
                "action": f"Start work on goal '{goal['title']}'",
            })
    return actions


def rule_retrospective(state: dict) -> list[dict]:
    """Periodic self-reflection on system performance."""
    actions = []
    tick_count = state.get("tick_count", 0)
    if tick_count > 0 and tick_count % 10 == 0:
        actions.append({
            "priority": 30,
            "type": "retrospective",
            "reason": f"{tick_count} ticks completed — time for meta-reflection",
            "action": "Review recent ticks: were decisions effective? What patterns emerged?",
        })
    return actions


def rule_high_error_rate(state: dict) -> list[dict]:
    """Too many errors in a window triggers worker pause."""
    actions = []
    for name, info in state.get("workers", {}).items():
        if info.get("error_count", 0) >= 5:
            actions.append({
                "priority": 95,
                "type": "pause-worker",
                "worker": name,
                "reason": f"{name} has {info['error_count']} errors — exceeds threshold",
                "action": f"Pause {name} and investigate root cause",
            })
    return actions


def rule_blocked_workers(state: dict) -> list[dict]:
    """Workers blocked on dependencies need unblocking."""
    actions = []
    for name, info in state.get("workers", {}).items():
        if info.get("status") == "blocked":
            actions.append({
                "priority": 70,
                "type": "unblock-worker",
                "worker": name,
                "blocked_by": info.get("blocked_by"),
                "reason": f"{name} blocked by {info.get('blocked_by', 'unknown')} for {info.get('blocked_ticks', 0)} ticks",
                "action": f"Resolve blocker for {name}",
            })
    return actions


# ---------------------------------------------------------------------------
# Default rule set
# ---------------------------------------------------------------------------

DEFAULT_RULES: list[Rule] = [
    rule_worker_errors,
    rule_idle_workers,
    rule_stale_goals,
    rule_memory_health,
    rule_knowledge_gaps,
    rule_pending_goals,
    rule_retrospective,
    rule_high_error_rate,
    rule_blocked_workers,
]


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class RuleEngine:
    """Aggregates rules and produces a prioritized action list."""

    def __init__(self, *, extra_rules: list[Rule] | None = None):
        self._rules = list(DEFAULT_RULES)
        if extra_rules:
            self._rules.extend(extra_rules)

    def tick(self, state: dict) -> dict:
        """Run all rules, sort by priority, return tick result."""
        all_actions: list[dict] = []
        for rule in self._rules:
            all_actions.extend(rule(state))

        all_actions.sort(key=lambda a: -a["priority"])

        return {
            "tick_at": datetime.now(timezone.utc).isoformat(),
            "recommendation": all_actions[0] if all_actions else None,
            "actions": all_actions,
            "action_count": len(all_actions),
        }
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/kairos/Projects/kairos && .venv/bin/python -m pytest tests/apps/governor/test_rules.py -x -q`
Expected: All 16 tests PASS

- [ ] **Step 5: Commit**

---

### Task 3: Observer

**Files:**
- Create: `apps/governor/observer.py`
- Test: `tests/apps/governor/test_observer.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/apps/governor/test_observer.py
"""Observer — state gathering from bus events and worker status."""

import asyncio
import pytest
from kplatform.bus import Bus, create_bus
from apps.governor.observer import Observer


@pytest.fixture
def bus():
    return create_bus()


@pytest.fixture
def observer(bus):
    return Observer(bus)


class TestEventCollection:
    """Observer subscribes to bus and accumulates state."""

    def test_initial_state_is_empty(self, observer):
        state = observer.get_state()
        assert state["workers"] == {}
        assert state["goals"] == []
        assert state["errors"] == []
        assert state["tick_count"] == 0

    def test_records_worker_status(self, observer, bus):
        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            bus.publish("worker.status", {
                "worker": "atlas",
                "status": "running",
                "error_count": 0,
            })
        )
        loop.close()
        state = observer.get_state()
        assert "atlas" in state["workers"]
        assert state["workers"]["atlas"]["status"] == "running"

    def test_records_worker_error(self, observer, bus):
        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            bus.publish("worker.error", {
                "worker": "arena",
                "error": "segfault",
            })
        )
        loop.close()
        state = observer.get_state()
        assert len(state["errors"]) == 1
        assert state["errors"][0]["worker"] == "arena"

    def test_records_goal_update(self, observer, bus):
        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            bus.publish("goal.updated", {
                "id": "g1", "status": "active", "title": "Build X",
                "stale_ticks": 0,
            })
        )
        loop.close()
        state = observer.get_state()
        assert len(state["goals"]) == 1
        assert state["goals"][0]["id"] == "g1"

    def test_goal_update_replaces_existing(self, observer, bus):
        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            bus.publish("goal.updated", {
                "id": "g1", "status": "active", "title": "Build X", "stale_ticks": 0,
            })
        )
        loop.run_until_complete(
            bus.publish("goal.updated", {
                "id": "g1", "status": "completed", "title": "Build X", "stale_ticks": 0,
            })
        )
        loop.close()
        state = observer.get_state()
        assert len(state["goals"]) == 1
        assert state["goals"][0]["status"] == "completed"

    def test_tick_count_increments(self, observer):
        observer.increment_tick()
        observer.increment_tick()
        assert observer.get_state()["tick_count"] == 2

    def test_records_memory_health(self, observer, bus):
        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            bus.publish("memory.health", {
                "instance": "atlas",
                "episodes": 500,
                "compression_lag": 10,
            })
        )
        loop.close()
        state = observer.get_state()
        assert "atlas" in state["memory_health"]
        assert state["memory_health"]["atlas"]["episodes"] == 500

    def test_error_window_capped(self, observer, bus):
        loop = asyncio.new_event_loop()
        for i in range(200):
            loop.run_until_complete(
                bus.publish("worker.error", {"worker": "test", "error": f"err-{i}"})
            )
        loop.close()
        state = observer.get_state()
        # Should be capped at 100 most recent
        assert len(state["errors"]) <= 100

    def test_reset_clears_state(self, observer, bus):
        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            bus.publish("worker.status", {"worker": "x", "status": "running", "error_count": 0})
        )
        loop.close()
        observer.reset()
        state = observer.get_state()
        assert state["workers"] == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/kairos/Projects/kairos && .venv/bin/python -m pytest tests/apps/governor/test_observer.py -x -q`

- [ ] **Step 3: Write implementation**

```python
# apps/governor/observer.py
"""State gathering from bus events and worker status.

Subscribes to bus topics and maintains a state dict that the rule engine
can query each tick. This is the governance plane's sensory input.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from kplatform.bus import Bus

# Maximum errors retained in the sliding window
MAX_ERROR_WINDOW = 100


class Observer:
    """Collects system state from bus events."""

    def __init__(self, bus: Bus):
        self._bus = bus
        self._workers: dict[str, dict] = {}
        self._goals: dict[str, dict] = {}  # keyed by goal id for dedup
        self._errors: list[dict] = []
        self._memory_health: dict[str, dict] = {}
        self._knowledge_stats: dict[str, Any] = {
            "concepts": 0, "claims": 0, "verified_claims": 0,
        }
        self._tick_count: int = 0

        # Subscribe to bus topics
        bus.subscribe("worker.status", self._on_worker_status)
        bus.subscribe("worker.error", self._on_worker_error)
        bus.subscribe("goal.updated", self._on_goal_updated)
        bus.subscribe("memory.health", self._on_memory_health)
        bus.subscribe("knowledge.stats", self._on_knowledge_stats)

    def _on_worker_status(self, data: dict | None) -> None:
        if not data:
            return
        name = data.get("worker", "unknown")
        self._workers[name] = {
            k: v for k, v in data.items() if k != "worker"
        }

    def _on_worker_error(self, data: dict | None) -> None:
        if not data:
            return
        self._errors.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            **data,
        })
        # Cap the error window
        if len(self._errors) > MAX_ERROR_WINDOW:
            self._errors = self._errors[-MAX_ERROR_WINDOW:]

        # Update worker error count
        name = data.get("worker", "unknown")
        if name in self._workers:
            self._workers[name]["error_count"] = (
                self._workers[name].get("error_count", 0) + 1
            )
            self._workers[name]["last_error"] = data.get("error", "unknown")
            self._workers[name]["status"] = "error"

    def _on_goal_updated(self, data: dict | None) -> None:
        if not data or "id" not in data:
            return
        self._goals[data["id"]] = data

    def _on_memory_health(self, data: dict | None) -> None:
        if not data:
            return
        instance = data.get("instance", "unknown")
        self._memory_health[instance] = {
            k: v for k, v in data.items() if k != "instance"
        }

    def _on_knowledge_stats(self, data: dict | None) -> None:
        if data:
            self._knowledge_stats.update(data)

    def increment_tick(self) -> None:
        """Called by worker each tick cycle."""
        self._tick_count += 1

    def get_state(self) -> dict:
        """Return current observed state for rule engine consumption."""
        return {
            "workers": dict(self._workers),
            "goals": list(self._goals.values()),
            "errors": list(self._errors),
            "memory_health": dict(self._memory_health),
            "knowledge_stats": dict(self._knowledge_stats),
            "tick_count": self._tick_count,
        }

    def reset(self) -> None:
        """Clear all accumulated state."""
        self._workers.clear()
        self._goals.clear()
        self._errors.clear()
        self._memory_health.clear()
        self._knowledge_stats = {
            "concepts": 0, "claims": 0, "verified_claims": 0,
        }
        self._tick_count = 0
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/kairos/Projects/kairos && .venv/bin/python -m pytest tests/apps/governor/test_observer.py -x -q`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

---

### Task 4: Verification (Sandboxed Code Execution)

**Files:**
- Create: `apps/governor/verification.py`
- Test: `tests/apps/governor/test_verification.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/apps/governor/test_verification.py
"""Sandboxed verification — code execution for tier 0→1 gate.

Three verification types:
- code: run Python, compare stdout to expected
- constraint: run Python, check exit code == 0
- reference: lookup in reference_data, compare value
"""

import pytest
from pathlib import Path
from apps.governor.knowledge import KnowledgeDB
from apps.governor.verification import Verifier


@pytest.fixture
def knowledge_db(tmp_path):
    db = KnowledgeDB(tmp_path / "knowledge.db")
    yield db
    db.close()


@pytest.fixture
def verifier(tmp_path, knowledge_db):
    return Verifier(knowledge_db, workspace=tmp_path / "sandbox")


class TestCodeVerification:
    """Type 'code': run Python snippet, compare stdout to expected."""

    def test_passing_code_verification(self, verifier, knowledge_db):
        knowledge_db.add_concept(id="math:add", domain="math", name="Addition")
        claim_id = knowledge_db.add_claim("math:add", "2+2=4")
        vid = knowledge_db.add_verification(
            claim_id, type="code", body="print(2+2)", expected="4",
        )
        result = verifier.run_verification(vid)
        assert result["result"] == "pass"
        assert result["output"].strip() == "4"

    def test_failing_code_verification(self, verifier, knowledge_db):
        knowledge_db.add_concept(id="math:bad", domain="math", name="Bad")
        claim_id = knowledge_db.add_claim("math:bad", "2+2=5")
        vid = knowledge_db.add_verification(
            claim_id, type="code", body="print(2+2)", expected="5",
        )
        result = verifier.run_verification(vid)
        assert result["result"] == "fail"

    def test_code_error_returns_error(self, verifier, knowledge_db):
        knowledge_db.add_concept(id="math:err", domain="math", name="Err")
        claim_id = knowledge_db.add_claim("math:err", "broken")
        vid = knowledge_db.add_verification(
            claim_id, type="code", body="raise ValueError('boom')", expected="ok",
        )
        result = verifier.run_verification(vid)
        assert result["result"] == "error"
        assert "boom" in result.get("error", "")

    def test_code_timeout(self, verifier, knowledge_db):
        knowledge_db.add_concept(id="math:slow", domain="math", name="Slow")
        claim_id = knowledge_db.add_claim("math:slow", "slow")
        vid = knowledge_db.add_verification(
            claim_id, type="code",
            body="import time; time.sleep(999)",
            expected="never",
        )
        result = verifier.run_verification(vid, timeout=1)
        assert result["result"] == "error"
        assert "timeout" in result.get("error", "").lower() or "timed" in result.get("error", "").lower()


class TestConstraintVerification:
    """Type 'constraint': run Python snippet, pass if exit code == 0."""

    def test_passing_constraint(self, verifier, knowledge_db):
        knowledge_db.add_concept(id="test:con", domain="test", name="Con")
        claim_id = knowledge_db.add_claim("test:con", "x > 0")
        vid = knowledge_db.add_verification(
            claim_id, type="constraint", body="x = 5\nassert x > 0",
        )
        result = verifier.run_verification(vid)
        assert result["result"] == "pass"

    def test_failing_constraint(self, verifier, knowledge_db):
        knowledge_db.add_concept(id="test:con2", domain="test", name="Con2")
        claim_id = knowledge_db.add_claim("test:con2", "x < 0")
        vid = knowledge_db.add_verification(
            claim_id, type="constraint", body="x = 5\nassert x < 0",
        )
        result = verifier.run_verification(vid)
        assert result["result"] == "fail"


class TestReferenceVerification:
    """Type 'reference': lookup in reference_data, compare value."""

    def test_passing_reference(self, verifier, knowledge_db):
        knowledge_db.add_concept(id="phys:c", domain="physics", name="Speed of Light")
        knowledge_db.set_reference("physics", "speed_of_light", "299792458", unit="m/s")
        claim_id = knowledge_db.add_claim("phys:c", "c = 299792458 m/s")
        vid = knowledge_db.add_verification(
            claim_id, type="reference",
            body="physics:speed_of_light", expected="299792458",
        )
        result = verifier.run_verification(vid)
        assert result["result"] == "pass"

    def test_failing_reference(self, verifier, knowledge_db):
        knowledge_db.add_concept(id="phys:c2", domain="physics", name="SoL2")
        knowledge_db.set_reference("physics", "speed_of_light_2", "299792458")
        claim_id = knowledge_db.add_claim("phys:c2", "c = 300000000")
        vid = knowledge_db.add_verification(
            claim_id, type="reference",
            body="physics:speed_of_light_2", expected="300000000",
        )
        result = verifier.run_verification(vid)
        assert result["result"] == "fail"

    def test_missing_reference(self, verifier, knowledge_db):
        knowledge_db.add_concept(id="phys:missing", domain="physics", name="Missing")
        claim_id = knowledge_db.add_claim("phys:missing", "x = 42")
        vid = knowledge_db.add_verification(
            claim_id, type="reference",
            body="physics:nonexistent_key", expected="42",
        )
        result = verifier.run_verification(vid)
        assert result["result"] == "error"


class TestBatchVerification:
    """Run all verifications for a concept."""

    def test_run_all_for_concept(self, verifier, knowledge_db):
        knowledge_db.add_concept(id="batch:a", domain="test", name="A")
        c1 = knowledge_db.add_claim("batch:a", "2+2=4")
        c2 = knowledge_db.add_claim("batch:a", "3+3=6")
        knowledge_db.add_verification(c1, type="code", body="print(2+2)", expected="4")
        knowledge_db.add_verification(c2, type="code", body="print(3+3)", expected="6")
        results = verifier.run_all_for_concept("batch:a")
        assert len(results) == 2
        assert all(r["result"] == "pass" for r in results)

    def test_updates_db_after_run(self, verifier, knowledge_db):
        knowledge_db.add_concept(id="batch:b", domain="test", name="B")
        c1 = knowledge_db.add_claim("batch:b", "1+1=2")
        vid = knowledge_db.add_verification(c1, type="code", body="print(1+1)", expected="2")
        verifier.run_verification(vid)
        vfs = knowledge_db.get_verifications(c1)
        assert vfs[0]["last_result"] == "pass"
        assert vfs[0]["last_run"] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/kairos/Projects/kairos && .venv/bin/python -m pytest tests/apps/governor/test_verification.py -x -q`

- [ ] **Step 3: Write implementation**

```python
# apps/governor/verification.py
"""Sandboxed code verification for tier 0→1 promotion gate.

Three verification types:
- code: run Python snippet via Sandbox.run_code, compare stdout to expected
- constraint: run Python snippet, pass if exit code == 0 (no output comparison)
- reference: lookup domain:key in reference_data, compare value to expected

Security: uses kplatform.sandbox.Sandbox which runs with python -I (isolated mode),
enforces workspace path isolation, and applies timeouts.
"""

from __future__ import annotations

from pathlib import Path

from kplatform.sandbox import Sandbox, ToolResult
from apps.governor.knowledge import KnowledgeDB


class Verifier:
    """Run verification artifacts against claims."""

    def __init__(self, knowledge_db: KnowledgeDB, *, workspace: Path | str):
        self._db = knowledge_db
        self._workspace = Path(workspace)
        self._workspace.mkdir(parents=True, exist_ok=True)
        self._sandbox = Sandbox(self._workspace)

    def run_verification(self, verification_id: int, *, timeout: int = 30) -> dict:
        """Run a single verification. Returns {"result": "pass"|"fail"|"error", ...}."""
        # Fetch verification record
        row = self._db._conn.execute(
            "SELECT * FROM verifications WHERE id = ?", (verification_id,)
        ).fetchone()
        if not row:
            return {"result": "error", "error": f"Verification {verification_id} not found"}

        v = dict(row)
        vtype = v["type"]

        if vtype == "code":
            result = self._run_code(v, timeout=timeout)
        elif vtype == "constraint":
            result = self._run_constraint(v, timeout=timeout)
        elif vtype == "reference":
            result = self._run_reference(v)
        else:
            result = {"result": "error", "error": f"Unknown verification type: {vtype}"}

        # Persist result to DB
        self._db.record_verification_result(
            verification_id,
            result=result["result"],
            output=result.get("output", ""),
            error=result.get("error"),
        )
        return result

    def _run_code(self, v: dict, *, timeout: int) -> dict:
        """Run code, compare stdout to expected."""
        tool_result: ToolResult = self._sandbox.execute(
            "run_code", {"code": v["body"], "timeout": timeout}
        )
        if not tool_result.success:
            error_msg = tool_result.error
            return {"result": "error", "output": "", "error": error_msg}

        actual = tool_result.output.strip()
        expected = (v.get("expected") or "").strip()
        if actual == expected:
            return {"result": "pass", "output": actual}
        else:
            return {"result": "fail", "output": actual, "expected": expected}

    def _run_constraint(self, v: dict, *, timeout: int) -> dict:
        """Run code, pass if exit code == 0."""
        tool_result: ToolResult = self._sandbox.execute(
            "run_code", {"code": v["body"], "timeout": timeout}
        )
        if tool_result.success:
            return {"result": "pass", "output": tool_result.output}
        else:
            return {"result": "fail", "output": tool_result.output, "error": tool_result.error}

    def _run_reference(self, v: dict) -> dict:
        """Lookup domain:key in reference_data, compare to expected."""
        ref_key = v["body"]  # format: "domain:key"
        if ":" not in ref_key:
            return {"result": "error", "error": f"Invalid reference key format: {ref_key}"}

        domain, key = ref_key.split(":", 1)
        ref = self._db.get_reference(domain, key)
        if ref is None:
            return {"result": "error", "error": f"Reference not found: {ref_key}"}

        actual = ref["value"]
        expected = (v.get("expected") or "").strip()
        if actual == expected:
            return {"result": "pass", "output": actual}
        else:
            return {"result": "fail", "output": actual, "expected": expected}

    def run_all_for_concept(self, concept_id: str, *, timeout: int = 30) -> list[dict]:
        """Run all verifications for all claims of a concept."""
        claims = self._db.get_claims(concept_id)
        results = []
        for claim in claims:
            vfs = self._db.get_verifications(claim["id"])
            for v in vfs:
                result = self.run_verification(v["id"], timeout=timeout)
                result["claim_id"] = claim["id"]
                result["verification_id"] = v["id"]
                results.append(result)
        return results
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/kairos/Projects/kairos && .venv/bin/python -m pytest tests/apps/governor/test_verification.py -x -q`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

---

### Task 5: Challenge (Adversarial LLM Verification)

**Files:**
- Create: `apps/governor/challenge.py`
- Test: `tests/apps/governor/test_challenge.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/apps/governor/test_challenge.py
"""Adversarial LLM challenge — two-call pattern for tier promotion.

Test-taker sees claims only. Grader sees expected only.
Uses platform LLM provider (not hardcoded Ollama).
"""

import pytest
from unittest.mock import MagicMock
from kplatform.llm.provider import LLMResponse, Provider
from apps.governor.knowledge import KnowledgeDB
from apps.governor.challenge import Challenger


@pytest.fixture
def knowledge_db(tmp_path):
    db = KnowledgeDB(tmp_path / "knowledge.db")
    yield db
    db.close()


def make_mock_provider(*, answer: str = "correct answer", grade: str = "PASS") -> MagicMock:
    """Create a mock LLM provider that returns predictable responses."""
    provider = MagicMock(spec=Provider)
    provider.is_available.return_value = True
    # First call: test-taker answer. Second call: grader verdict.
    provider.chat.side_effect = [
        LLMResponse(content=answer, model="test", provider="mock"),
        LLMResponse(content=grade, model="test", provider="mock"),
    ]
    return provider


class TestChallengeExecution:
    """Running a single challenge with the two-call pattern."""

    def test_passing_challenge(self, knowledge_db):
        knowledge_db.add_concept(id="test:c", domain="test", name="C")
        knowledge_db.add_claim("test:c", "The sky is blue")
        ch_id = knowledge_db.add_challenge(
            "test:c", "What color is the sky?",
            expected_answer="Blue",
        )
        provider = make_mock_provider(answer="The sky is blue", grade="PASS")
        challenger = Challenger(knowledge_db, provider)
        result = challenger.run_challenge(ch_id)
        assert result["result"] == "pass"
        assert provider.chat.call_count == 2

    def test_failing_challenge(self, knowledge_db):
        knowledge_db.add_concept(id="test:f", domain="test", name="F")
        knowledge_db.add_claim("test:f", "Water boils at 100C")
        ch_id = knowledge_db.add_challenge(
            "test:f", "At what temperature does water boil?",
            expected_answer="100 degrees Celsius",
        )
        provider = make_mock_provider(answer="50 degrees", grade="FAIL")
        challenger = Challenger(knowledge_db, provider)
        result = challenger.run_challenge(ch_id)
        assert result["result"] == "fail"

    def test_answer_leakage_prevention(self, knowledge_db):
        """Test-taker prompt must NOT contain expected_answer."""
        knowledge_db.add_concept(id="test:leak", domain="test", name="Leak")
        knowledge_db.add_claim("test:leak", "Secret: 42")
        ch_id = knowledge_db.add_challenge(
            "test:leak", "What is the secret?",
            expected_answer="42",
        )
        provider = make_mock_provider()
        challenger = Challenger(knowledge_db, provider)
        challenger.run_challenge(ch_id)
        # Inspect the first call (test-taker) — expected_answer must not appear
        first_call = provider.chat.call_args_list[0]
        messages = first_call[0][0]  # positional arg: messages list
        full_text = " ".join(m.get("content", "") for m in messages)
        assert "42" not in full_text

    def test_grader_sees_expected_answer(self, knowledge_db):
        """Grader prompt must contain the expected_answer."""
        knowledge_db.add_concept(id="test:grade", domain="test", name="Grade")
        knowledge_db.add_claim("test:grade", "Pi is 3.14159")
        ch_id = knowledge_db.add_challenge(
            "test:grade", "What is pi?",
            expected_answer="3.14159",
        )
        provider = make_mock_provider()
        challenger = Challenger(knowledge_db, provider)
        challenger.run_challenge(ch_id)
        # Inspect the second call (grader) — expected_answer must appear
        second_call = provider.chat.call_args_list[1]
        messages = second_call[0][0]
        full_text = " ".join(m.get("content", "") for m in messages)
        assert "3.14159" in full_text

    def test_updates_challenge_record(self, knowledge_db):
        knowledge_db.add_concept(id="test:rec", domain="test", name="Rec")
        knowledge_db.add_claim("test:rec", "Fact")
        ch_id = knowledge_db.add_challenge("test:rec", "Q?", expected_answer="A")
        provider = make_mock_provider(grade="PASS")
        challenger = Challenger(knowledge_db, provider)
        challenger.run_challenge(ch_id)
        ch = knowledge_db.get_challenges("test:rec")
        assert ch[0]["last_result"] == "pass"

    def test_provider_unavailable(self, knowledge_db):
        knowledge_db.add_concept(id="test:off", domain="test", name="Off")
        knowledge_db.add_claim("test:off", "Fact")
        ch_id = knowledge_db.add_challenge("test:off", "Q?", expected_answer="A")
        provider = MagicMock(spec=Provider)
        provider.is_available.return_value = False
        challenger = Challenger(knowledge_db, provider)
        result = challenger.run_challenge(ch_id)
        assert result["result"] == "error"
        assert "unavailable" in result.get("error", "").lower()


class TestTierPromotion:
    """Tier promotion gate logic."""

    def test_tier0_to_tier1_requires_verification_and_challenge(self, knowledge_db):
        """Concept needs both passing verifications AND passing challenges for tier 1."""
        knowledge_db.add_concept(id="promo:a", domain="test", name="A")
        provider = make_mock_provider()
        challenger = Challenger(knowledge_db, provider)
        # No verifications, no challenges — should not promote
        eligible = challenger.check_promotion_eligible("promo:a", target_tier=1)
        assert not eligible

    def test_tier1_to_tier2_requires_no_contradictions(self, knowledge_db):
        """Tier 2 requires no contradictions with related concepts."""
        knowledge_db.add_concept(id="promo:b", domain="test", name="B")
        knowledge_db.add_concept(id="promo:c", domain="test", name="C")
        knowledge_db.add_edge("promo:b", "contradicts", "promo:c")
        knowledge_db.promote_concept("promo:b", tier=1)
        provider = make_mock_provider()
        challenger = Challenger(knowledge_db, provider)
        eligible = challenger.check_promotion_eligible("promo:b", target_tier=2)
        assert not eligible

    def test_tier2_eligible_when_clean(self, knowledge_db):
        """Tier 2 eligible with no contradictions and prereqs verified."""
        knowledge_db.add_concept(id="promo:d", domain="test", name="D")
        knowledge_db.add_concept(id="promo:e", domain="test", name="E")
        knowledge_db.promote_concept("promo:d", tier=1)
        knowledge_db.promote_concept("promo:e", tier=1)
        knowledge_db.add_edge("promo:d", "requires", "promo:e")
        # Add passing challenge
        ch_id = knowledge_db.add_challenge("promo:d", "Q?", expected_answer="A")
        knowledge_db.record_challenge_result(ch_id, result="pass")
        # Add passing verification
        claim_id = knowledge_db.add_claim("promo:d", "fact")
        vid = knowledge_db.add_verification(claim_id, type="code", body="print(1)", expected="1")
        knowledge_db.record_verification_result(vid, result="pass", output="1")
        knowledge_db.verify_claim(claim_id, verified=True)
        provider = make_mock_provider()
        challenger = Challenger(knowledge_db, provider)
        eligible = challenger.check_promotion_eligible("promo:d", target_tier=2)
        assert eligible
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/kairos/Projects/kairos && .venv/bin/python -m pytest tests/apps/governor/test_challenge.py -x -q`

- [ ] **Step 3: Write implementation**

```python
# apps/governor/challenge.py
"""Adversarial LLM challenge for knowledge tier promotion.

Two-call pattern (answer leakage prevention):
1. Test-taker sees: concept claims + question (NO expected answer)
2. Grader sees: question + expected answer + candidate answer

Uses kplatform.llm.Provider (not hardcoded to any specific provider).
"""

from __future__ import annotations

from kplatform.llm.provider import Provider
from apps.governor.knowledge import KnowledgeDB


class Challenger:
    """Run adversarial challenges against knowledge claims."""

    def __init__(self, knowledge_db: KnowledgeDB, provider: Provider):
        self._db = knowledge_db
        self._provider = provider

    def run_challenge(self, challenge_id: int) -> dict:
        """Run a single challenge with the two-call pattern."""
        if not self._provider.is_available():
            return {"result": "error", "error": "LLM provider unavailable"}

        # Fetch challenge
        row = self._db._conn.execute(
            "SELECT * FROM challenges WHERE id = ?", (challenge_id,)
        ).fetchone()
        if not row:
            return {"result": "error", "error": f"Challenge {challenge_id} not found"}

        ch = dict(row)
        concept_id = ch["concept_id"]
        question = ch["question"]
        expected = ch.get("expected_answer", "")

        # Fetch claims for context (test-taker sees these, NOT the expected answer)
        claims = self._db.get_claims(concept_id)
        claims_text = "\n".join(f"- {c['claim']}" for c in claims)

        # Call 1: Test-taker — sees claims + question, NOT expected answer
        taker_messages = [
            {
                "role": "system",
                "content": (
                    "You are being tested on your understanding of a concept. "
                    "Answer the question using ONLY the following claims as your "
                    "knowledge base. Do not use any other knowledge."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Claims:\n{claims_text}\n\n"
                    f"Question: {question}\n\n"
                    f"Answer:"
                ),
            },
        ]

        taker_response = self._provider.chat(taker_messages, temperature=0.3)
        if taker_response.content is None:
            return {"result": "error", "error": "Test-taker LLM returned no content"}

        candidate_answer = taker_response.content

        # Call 2: Grader — sees question + expected + candidate
        grader_messages = [
            {
                "role": "system",
                "content": (
                    "You are grading an answer. Compare the candidate answer to "
                    "the expected answer. They don't need to be word-for-word "
                    "identical — semantic equivalence is sufficient. "
                    "Respond with exactly PASS or FAIL on the first line, "
                    "followed by a brief explanation."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Question: {question}\n\n"
                    f"Expected answer: {expected}\n\n"
                    f"Candidate answer: {candidate_answer}\n\n"
                    f"Verdict:"
                ),
            },
        ]

        grader_response = self._provider.chat(grader_messages, temperature=0.1)
        if grader_response.content is None:
            return {"result": "error", "error": "Grader LLM returned no content"}

        # Parse verdict from first line
        verdict_text = grader_response.content.strip().split("\n")[0].upper()
        passed = "PASS" in verdict_text

        result_str = "pass" if passed else "fail"

        # Record result
        self._db.record_challenge_result(challenge_id, result=result_str)

        return {
            "result": result_str,
            "candidate_answer": candidate_answer,
            "grader_response": grader_response.content,
        }

    def run_all_for_concept(self, concept_id: str) -> list[dict]:
        """Run all challenges for a concept."""
        challenges = self._db.get_challenges(concept_id)
        results = []
        for ch in challenges:
            result = self.run_challenge(ch["id"])
            result["challenge_id"] = ch["id"]
            results.append(result)
        return results

    def check_promotion_eligible(
        self, concept_id: str, *, target_tier: int,
    ) -> bool:
        """Check if a concept is eligible for promotion to target_tier."""
        concept = self._db.get_concept(concept_id)
        if concept is None:
            return False

        if target_tier == 1:
            return self._check_tier1_eligible(concept_id)
        elif target_tier == 2:
            return self._check_tier2_eligible(concept_id)
        elif target_tier == 3:
            # Tier 3 requires external application — not automatable here
            return False
        return False

    def _check_tier1_eligible(self, concept_id: str) -> bool:
        """Tier 0→1: requires at least one passing verification AND one passing challenge."""
        # Check verifications
        claims = self._db.get_claims(concept_id)
        has_passing_verification = False
        for claim in claims:
            vfs = self._db.get_verifications(claim["id"])
            for v in vfs:
                if v.get("last_result") == "pass":
                    has_passing_verification = True
                    break
            if has_passing_verification:
                break

        # Check challenges
        challenges = self._db.get_challenges(concept_id)
        has_passing_challenge = any(
            ch.get("last_result") == "pass" for ch in challenges
        )

        return has_passing_verification and has_passing_challenge

    def _check_tier2_eligible(self, concept_id: str) -> bool:
        """Tier 1→2: no contradictions + all prerequisites at tier >= 1."""
        # Must be tier 1 already
        concept = self._db.get_concept(concept_id)
        if concept is None or concept["tier"] < 1:
            return False

        # No contradictions
        contradictions = self._db.get_contradictions(concept_id)
        if contradictions:
            return False

        # All prerequisites must be tier >= 1
        prereqs = self._db.get_prerequisites(concept_id)
        for p in prereqs:
            prereq_concept = self._db.get_concept(p["target_id"])
            if prereq_concept is None or prereq_concept["tier"] < 1:
                return False

        # Must have passing challenge and verification
        if not self._check_tier1_eligible(concept_id):
            return False

        return True
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/kairos/Projects/kairos && .venv/bin/python -m pytest tests/apps/governor/test_challenge.py -x -q`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

---

### Task 6: Worker (Tick Entrypoint)

**Files:**
- Create: `apps/governor/worker.py`
- Test: `tests/apps/governor/test_worker.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/apps/governor/test_worker.py
"""Governor worker — the tick entrypoint dispatched by daemon."""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from kplatform.bus import Bus, create_bus
from kplatform.ledger import Ledger
from kplatform.llm.provider import Provider, LLMResponse
from apps.governor.worker import GovernorWorker


@pytest.fixture
def bus():
    return create_bus()


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "governor.ledger")


@pytest.fixture
def mock_provider():
    p = MagicMock(spec=Provider)
    p.is_available.return_value = True
    p.chat.return_value = LLMResponse(
        content="PASS", model="test", provider="mock",
    )
    return p


@pytest.fixture
def worker(tmp_path, bus, ledger, mock_provider):
    return GovernorWorker(
        bus=bus,
        ledger=ledger,
        llm_provider=mock_provider,
        data_dir=tmp_path / "governor_data",
    )


class TestWorkerLifecycle:
    """Worker setup, tick, and teardown."""

    def test_worker_creates_data_dir(self, worker, tmp_path):
        assert (tmp_path / "governor_data").exists()

    def test_worker_has_knowledge_db(self, worker):
        assert worker.knowledge_db is not None

    def test_worker_has_observer(self, worker):
        assert worker.observer is not None

    def test_worker_has_rule_engine(self, worker):
        assert worker.rule_engine is not None


class TestTickExecution:
    """Running a governor tick."""

    def test_tick_returns_result(self, worker):
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(worker.tick())
        loop.close()
        assert "tick_at" in result
        assert "recommendation" in result

    def test_tick_publishes_directive_when_action_found(self, worker, bus):
        # Inject a worker error to trigger a rule
        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            bus.publish("worker.status", {
                "worker": "atlas", "status": "error",
                "error_count": 5, "last_error": "crash",
            })
        )

        published = []
        bus.subscribe("priority.directive", lambda data: published.append(data))

        loop.run_until_complete(worker.tick())
        loop.close()

        assert len(published) >= 1
        assert "type" in published[0]

    def test_tick_logs_to_ledger(self, worker, ledger):
        loop = asyncio.new_event_loop()
        loop.run_until_complete(worker.tick())
        loop.close()
        entries = ledger.read_all()
        assert len(entries) >= 1
        assert entries[-1].get("source") == "governor"

    def test_tick_increments_observer_count(self, worker):
        loop = asyncio.new_event_loop()
        loop.run_until_complete(worker.tick())
        loop.run_until_complete(worker.tick())
        loop.close()
        state = worker.observer.get_state()
        assert state["tick_count"] == 2

    def test_tick_with_no_actions_publishes_nothing(self, worker, bus):
        published = []
        bus.subscribe("priority.directive", lambda data: published.append(data))
        loop = asyncio.new_event_loop()
        loop.run_until_complete(worker.tick())
        loop.close()
        assert len(published) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/kairos/Projects/kairos && .venv/bin/python -m pytest tests/apps/governor/test_worker.py -x -q`

- [ ] **Step 3: Write implementation**

```python
# apps/governor/worker.py
"""Governor worker — tick entrypoint dispatched by daemon.

Each tick:
1. Observer gathers state from bus events
2. Rule engine evaluates state, produces scored actions
3. Top action published as priority.directive to bus
4. Decision logged to ledger
"""

from __future__ import annotations

from pathlib import Path

from kplatform.bus import Bus
from kplatform.ledger import Ledger
from kplatform.llm.provider import Provider

from apps.governor.knowledge import KnowledgeDB
from apps.governor.observer import Observer
from apps.governor.rules import RuleEngine
from apps.governor.challenge import Challenger
from apps.governor.verification import Verifier


class GovernorWorker:
    """The governor tick entrypoint."""

    def __init__(
        self, *,
        bus: Bus,
        ledger: Ledger,
        llm_provider: Provider,
        data_dir: Path | str,
    ):
        self._bus = bus
        self._ledger = ledger
        self._provider = llm_provider
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)

        # Initialize components
        self.knowledge_db = KnowledgeDB(self._data_dir / "knowledge.db")
        self.observer = Observer(bus)
        self.rule_engine = RuleEngine()
        self.challenger = Challenger(self.knowledge_db, llm_provider)
        self.verifier = Verifier(
            self.knowledge_db, workspace=self._data_dir / "sandbox",
        )

    async def tick(self) -> dict:
        """Run one governance tick."""
        # 1. Increment tick count
        self.observer.increment_tick()

        # 2. Gather current state
        state = self.observer.get_state()

        # 3. Inject knowledge stats into state
        state["knowledge_stats"] = self.knowledge_db.stats()

        # 4. Run rule engine
        result = self.rule_engine.tick(state)

        # 5. Publish top directive if there is one
        recommendation = result.get("recommendation")
        if recommendation:
            await self._bus.publish("priority.directive", recommendation)

        # 6. Log to ledger
        self._ledger.append({
            "source": "governor",
            "type": "tick",
            "tick_at": result["tick_at"],
            "action_count": result["action_count"],
            "recommendation_type": recommendation["type"] if recommendation else None,
            "recommendation_priority": recommendation["priority"] if recommendation else None,
        })

        return result

    def close(self) -> None:
        """Clean up resources."""
        self.knowledge_db.close()
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/kairos/Projects/kairos && .venv/bin/python -m pytest tests/apps/governor/test_worker.py -x -q`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

---

### Task 7: Package Exports + Integration Verification

**Files:**
- Update: `apps/governor/__init__.py`
- Test: `tests/apps/governor/test_integration.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/apps/governor/test_integration.py
"""Integration: full governor tick cycle, package exports, cross-component wiring."""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from kplatform.bus import Bus, create_bus
from kplatform.ledger import Ledger
from kplatform.llm.provider import Provider, LLMResponse


class TestPackageExports:
    """Verify all expected symbols are importable."""

    def test_import_knowledge_db(self):
        from apps.governor import KnowledgeDB
        assert KnowledgeDB is not None

    def test_import_rule_engine(self):
        from apps.governor import RuleEngine
        assert RuleEngine is not None

    def test_import_observer(self):
        from apps.governor import Observer
        assert Observer is not None

    def test_import_governor_worker(self):
        from apps.governor import GovernorWorker
        assert GovernorWorker is not None

    def test_import_verifier(self):
        from apps.governor.verification import Verifier
        assert Verifier is not None

    def test_import_challenger(self):
        from apps.governor.challenge import Challenger
        assert Challenger is not None


class TestFullTickCycle:
    """End-to-end: bus events → observer → rules → directive → ledger."""

    def test_full_cycle(self, tmp_path):
        bus = create_bus()
        ledger = Ledger(tmp_path / "test.ledger")
        provider = MagicMock(spec=Provider)
        provider.is_available.return_value = True

        from apps.governor.worker import GovernorWorker
        worker = GovernorWorker(
            bus=bus, ledger=ledger, llm_provider=provider,
            data_dir=tmp_path / "gov",
        )

        directives = []
        bus.subscribe("priority.directive", lambda data: directives.append(data))

        loop = asyncio.new_event_loop()

        # Simulate a worker error arriving via bus
        loop.run_until_complete(bus.publish("worker.status", {
            "worker": "atlas", "status": "error",
            "error_count": 5, "last_error": "segfault",
        }))

        # Run governor tick
        result = loop.run_until_complete(worker.tick())
        loop.close()

        # Directive should have been published
        assert len(directives) >= 1
        # Ledger should have the tick recorded
        entries = ledger.read_all()
        assert any(e.get("source") == "governor" for e in entries)
        # Result should reference the error
        assert result["recommendation"] is not None
        assert result["action_count"] >= 1

        worker.close()

    def test_knowledge_accessible_from_worker(self, tmp_path):
        bus = create_bus()
        ledger = Ledger(tmp_path / "test2.ledger")
        provider = MagicMock(spec=Provider)
        provider.is_available.return_value = True

        from apps.governor.worker import GovernorWorker
        worker = GovernorWorker(
            bus=bus, ledger=ledger, llm_provider=provider,
            data_dir=tmp_path / "gov2",
        )

        # Add knowledge through the worker's DB
        worker.knowledge_db.add_concept(
            id="test:integration", domain="test", name="Integration",
        )
        c = worker.knowledge_db.get_concept("test:integration")
        assert c is not None
        assert c["name"] == "Integration"

        worker.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/kairos/Projects/kairos && .venv/bin/python -m pytest tests/apps/governor/test_integration.py -x -q`

- [ ] **Step 3: Verify __init__.py exports** (already written in Task 1, Step 3)

- [ ] **Step 4: Run full test suite**

Run: `cd /Users/kairos/Projects/kairos && .venv/bin/python -m pytest tests/apps/governor/ -q`
Expected: All ~44 tests PASS

- [ ] **Step 5: Commit**
