# Kairos Platform: Memory — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port engram's three-layer memory system (episodes → semantics → instincts) into the kairos monorepo as the `kplatform/memory` module — the foundation everything else builds on.

**Architecture:** SQLite + vec0 storage with instance isolation. Each worker gets its own database file. Genome DB for shared truths. Compression pipeline promotes episodes → semantics → instincts via clustering, centroid selection, and LLM dedup. MCP interface deferred to separate plugins/engram plan.

**Tech Stack:** Python 3.12+, SQLite (WAL mode), sqlite-vec (vec0), FastEmbed (nomic-embed-text-v1.5 768-dim), scipy (hierarchical clustering), numpy

**Spec:** `docs/superpowers/specs/2026-03-21-kairos-platform-design.md`

**Source (reference only — port, don't copy):** `/Users/kairos/Projects/engram/`

**Note:** Package is `kplatform` (not `platform`) to avoid collision with Python's stdlib `platform` module. All imports use `from kplatform.memory import ...`.

---

## File Structure

```
kairos/
  pyproject.toml                          -- workspace root, uv/pip editable installs
  kplatform/
    __init__.py
    memory/
      __init__.py                         -- public API: Storage, Compressor, EmbeddingProvider
      storage.py                          -- SQLite + vec0 CRUD for all layers
      compress.py                         -- clustering, centroid, MMR, instinct formation
      embeddings.py                       -- nomic embed with instruction prefixes
      dedup.py                            -- LLM pragmatic equivalence via Ollama
      config.py                           -- dataclasses for all memory config
      federation.py                       -- SignalBus, InstanceRegistry, genome sync
      migrations/
        001_initial.sql                   -- episodes, semantics, instincts, vectors, FTS5
        002_contextual_instincts.sql      -- notice/implication, context vectors, feedback
        003_federation.sql                -- source, content_hash, genome support
      reflection.py                       -- self-observation (usage, gaps, instincts)
  tests/
    platform/
      memory/
        __init__.py
        conftest.py                       -- fixtures: tmp_db, storage, embeddings, compressor
        test_storage.py                   -- CRUD for all layers
        test_compress.py                  -- clustering, promotion, instinct creation
        test_embeddings.py                -- embed, dimension, prefix behavior
        test_dedup.py                     -- equivalence checking, availability fallback
        test_config.py                    -- load, defaults, override
        test_federation.py                -- signal bus, registry, genome sync
        test_reflection.py                -- self-analysis queries
        test_integration.py               -- cross-module: remember → compress → recall
```

**Key decisions:**
- Consolidate 8 migrations into 3 (clean schema, no legacy transitions)
- Storage, compress, embeddings, dedup, config, federation each stay as separate files (same as engram, proven structure)
- reflection.py included because it queries across all layers
- MCP server is NOT in this plan — it goes in `plugins/engram/` (separate plan)
- Wake hook is NOT in this plan — it goes with runtime/plugins
- Indexer/watcher NOT in this plan — those go with a code intelligence plan

---

### Task 1: Monorepo Scaffolding

**Files:**
- Create: `kairos/pyproject.toml`
- Create: `kairos/kplatform/__init__.py`
- Create: `kairos/kplatform/memory/__init__.py`
- Create: `kairos/CLAUDE.md`
- Create: `kairos/kplatform/memory/CLAUDE.md`

- [ ] **Step 1: Create monorepo root**

```bash
mkdir -p /Users/kairos/Projects/kairos
cd /Users/kairos/Projects/kairos
git init
```

- [ ] **Step 2: Write root pyproject.toml**

```toml
[project]
name = "kairos"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "tomli>=2.0.1; python_version<'3.11'",
]

[project.optional-dependencies]
memory = [
    "sqlite-vec>=0.1.6",
    "onnxruntime>=1.18",
    "fastembed>=0.7",
    "scipy>=1.14",
    "numpy>=1.24",
]
dev = [
    "pytest>=9.0",
    "pytest-asyncio>=0.24",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["kplatform", "runtime", "apps", "blocks"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 3: Write root CLAUDE.md**

```markdown
# Kairos

Monorepo for the Kairos Platform. See spec:
docs/superpowers/specs/2026-03-21-kairos-platform-design.md

## Structure

- kplatform/ — shared infrastructure (memory, bus, ledger, llm, embeddings, sandbox)
- runtime/ — daemon, scheduler, dispatcher
- apps/ — atlas, arena, ratchet, governor
- blocks/ — composable event-bus components
- plugins/ — Claude Code MCP plugins
- tests/ — mirrors source structure

## Testing

\```bash
uv run pytest tests/ -q
\```

## Dependency Direction

apps → platform. Never platform → apps. Runtime → both.
```

- [ ] **Step 4: Write kplatform/memory/CLAUDE.md**

```markdown
# Platform: Memory

Three-layer memory system: episodes → semantics → instincts.

## Key Files

| File | Purpose |
|------|---------|
| storage.py | SQLite + vec0 CRUD for all layers |
| compress.py | Clustering, centroid, MMR, instinct formation |
| embeddings.py | Nomic embed with instruction prefixes |
| dedup.py | LLM pragmatic equivalence |
| config.py | Configuration dataclasses |
| federation.py | Instance isolation, genome sync, signal bus |
| reflection.py | Self-observation queries |

## Instance Isolation

Each worker gets its own SQLite database. Workers never read each other's
memory. Genome DB stores universal truths (tier-2 core episodes).

## Testing

\```bash
uv run pytest tests/kplatform/memory/ -q
\```
```

- [ ] **Step 5: Create __init__.py files**

`kplatform/__init__.py`:
```python
"""Kairos kplatform — shared infrastructure."""
```

`kplatform/memory/__init__.py`:
```python
"""Three-layer memory: episodes → semantics → instincts."""

from kplatform.memory.storage import Storage
from kplatform.memory.compress import Compressor
from kplatform.memory.embeddings import EmbeddingProvider, NomicEmbedProvider
from kplatform.memory.config import MemoryConfig, load_config

__all__ = [
    "Storage",
    "Compressor",
    "EmbeddingProvider",
    "NomicEmbedProvider",
    "MemoryConfig",
    "load_config",
]
```

- [ ] **Step 6: Set up venv and verify imports**

```bash
cd /Users/kairos/Projects/kairos
uv venv
uv pip install -e ".[memory,dev]"
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore: kairos monorepo scaffolding with platform/memory structure"
```

---

### Task 2: Configuration

**Files:**
- Create: `kairos/kplatform/memory/config.py`
- Create: `kairos/tests/kplatform/memory/__init__.py`
- Create: `kairos/tests/kplatform/memory/conftest.py`
- Create: `kairos/tests/kplatform/memory/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/kplatform/memory/test_config.py
from kplatform.memory.config import MemoryConfig, load_config


def test_default_config():
    cfg = MemoryConfig()
    assert cfg.embedding.dimension == 768
    assert cfg.compression.cluster_similarity == 0.75
    assert cfg.compression.instinct_confidence == 0.5
    assert cfg.decay.factor == 0.9
    assert cfg.decay.min_interval_minutes == 30
    assert cfg.decay.prune_threshold == 0.05


def test_load_config_defaults(tmp_path):
    cfg = load_config(tmp_path)
    assert isinstance(cfg, MemoryConfig)
    assert cfg.instance is None


def test_load_config_from_toml(tmp_path):
    config_dir = tmp_path / ".engram"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        '[compression]\ncluster_similarity = 0.80\n'
    )
    cfg = load_config(tmp_path)
    assert cfg.compression.cluster_similarity == 0.80


def test_instance_config(tmp_path):
    config_dir = tmp_path / ".engram"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text('[memory]\ninstance = "atlas"\n')
    cfg = load_config(tmp_path)
    assert cfg.instance == "atlas"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/kplatform/memory/test_config.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write conftest.py**

```python
# tests/kplatform/memory/conftest.py
import pytest
from pathlib import Path


@pytest.fixture
def tmp_db(tmp_path):
    """Return path to a temporary database file."""
    return str(tmp_path / "test.db")
```

- [ ] **Step 4: Write config.py**

```python
# kplatform/memory/config.py
"""Configuration for the memory subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


@dataclass
class EmbeddingConfig:
    provider: str = "nomic"
    model: str = "nomic-ai/nomic-embed-text-v1.5"
    dimension: int = 768


@dataclass
class CompressionConfig:
    auto_threshold: int = 5
    cluster_similarity: float = 0.75
    reinforce_threshold: float = 0.70
    instinct_confidence: float = 0.5
    max_clusters: int = 20


@dataclass
class DecayConfig:
    factor: float = 0.9
    min_interval_minutes: int = 30
    prune_threshold: float = 0.05


@dataclass
class DedupConfig:
    model: str = "qwen3.5:27b"
    ollama_url: str = "http://localhost:11434/api/generate"
    timeout: int = 60


@dataclass
class FederationConfig:
    genome_sync: bool = True
    signal_retention_days: int = 30


@dataclass
class ReflectionConfig:
    enabled: bool = True
    log_retention_days: int = 90
    staleness_days: int = 30


@dataclass
class RecallConfig:
    max_results: int = 20
    similarity_weight: float = 0.7
    recency_weight: float = 0.3


@dataclass
class MemoryConfig:
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    compression: CompressionConfig = field(default_factory=CompressionConfig)
    decay: DecayConfig = field(default_factory=DecayConfig)
    dedup: DedupConfig = field(default_factory=DedupConfig)
    federation: FederationConfig = field(default_factory=FederationConfig)
    reflection: ReflectionConfig = field(default_factory=ReflectionConfig)
    recall: RecallConfig = field(default_factory=RecallConfig)
    instance: str | None = None
    session_context: str | None = None


def _apply_overrides(cfg: object, overrides: dict) -> None:
    """Apply TOML overrides to a dataclass, ignoring unknown keys."""
    for key, value in overrides.items():
        if hasattr(cfg, key):
            current = getattr(cfg, key)
            if isinstance(value, dict) and hasattr(current, "__dataclass_fields__"):
                _apply_overrides(current, value)
            else:
                setattr(cfg, key, value)


def load_config(project_root: Path | None = None) -> MemoryConfig:
    """Load config from .engram/config.toml or return defaults."""
    cfg = MemoryConfig()
    if project_root is None:
        return cfg
    config_file = project_root / ".engram" / "config.toml"
    if config_file.exists():
        with open(config_file, "rb") as f:
            data = tomllib.load(f)
        # Top-level 'memory' section holds instance/session_context
        memory_section = data.pop("memory", {})
        if "instance" in memory_section:
            cfg.instance = memory_section["instance"]
        if "session_context" in memory_section:
            cfg.session_context = memory_section["session_context"]
        _apply_overrides(cfg, data)
    return cfg
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/kplatform/memory/test_config.py -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add kplatform/memory/config.py tests/kplatform/memory/
git commit -m "feat(memory): configuration with TOML override support"
```

---

### Task 3: Embeddings

**Files:**
- Create: `kairos/kplatform/memory/embeddings.py`
- Create: `kairos/tests/kplatform/memory/test_embeddings.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/kplatform/memory/test_embeddings.py
import math
from kplatform.memory.embeddings import NomicEmbedProvider, EmbeddingProvider


def test_implements_protocol():
    provider = NomicEmbedProvider()
    assert isinstance(provider, EmbeddingProvider)


def test_dimension():
    provider = NomicEmbedProvider()
    assert provider.dimension() == 768


def test_embed_single():
    provider = NomicEmbedProvider()
    vectors = provider.embed(["hello world"])
    assert len(vectors) == 1
    assert len(vectors[0]) == 768


def test_embed_batch():
    provider = NomicEmbedProvider()
    vectors = provider.embed(["hello", "world", "test"])
    assert len(vectors) == 3
    assert all(len(v) == 768 for v in vectors)


def test_embed_with_prefix():
    provider = NomicEmbedProvider()
    store_vec = provider.embed(["test"], prefix="search_document")[0]
    query_vec = provider.embed(["test"], prefix="search_query")[0]
    # Same text with different prefixes should produce different vectors
    assert store_vec != query_vec


def test_unit_normalized():
    provider = NomicEmbedProvider()
    vec = provider.embed(["hello world"])[0]
    magnitude = math.sqrt(sum(x * x for x in vec))
    assert abs(magnitude - 1.0) < 0.01


def test_empty_input():
    provider = NomicEmbedProvider()
    vectors = provider.embed([])
    assert vectors == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/kplatform/memory/test_embeddings.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write embeddings.py**

```python
# kplatform/memory/embeddings.py
"""Embedding providers with instruction prefix support."""

from __future__ import annotations

import math
from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for embedding providers."""

    def embed(self, texts: list[str], *, prefix: str = "search_document") -> list[list[float]]:
        ...

    def dimension(self) -> int:
        ...


class NomicEmbedProvider:
    """Nomic embed-text-v1.5 via FastEmbed (768-dim, instruction prefixes)."""

    def __init__(self, model: str = "nomic-ai/nomic-embed-text-v1.5"):
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model)
        self._dim = 768

    def dimension(self) -> int:
        return self._dim

    def embed(self, texts: list[str], *, prefix: str = "search_document") -> list[list[float]]:
        if not texts:
            return []
        prefixed = [f"{prefix}: {t}" for t in texts]
        embeddings = list(self._model.embed(prefixed))
        return [self._normalize(list(e)) for e in embeddings]

    @staticmethod
    def _normalize(vec: list[float]) -> list[float]:
        magnitude = math.sqrt(sum(x * x for x in vec))
        if magnitude == 0:
            return vec
        return [x / magnitude for x in vec]
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/kplatform/memory/test_embeddings.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add kplatform/memory/embeddings.py tests/kplatform/memory/test_embeddings.py
git commit -m "feat(memory): nomic embedding provider with instruction prefixes"
```

---

### Task 4: Storage — Schema and Migrations

**Files:**
- Create: `kairos/kplatform/memory/migrations/001_initial.sql`
- Create: `kairos/kplatform/memory/migrations/002_contextual_instincts.sql`
- Create: `kairos/kplatform/memory/migrations/003_federation.sql`
- Create: `kairos/kplatform/memory/storage.py` (migration runner only)
- Create: `kairos/tests/kplatform/memory/test_storage.py` (schema tests only)

- [ ] **Step 1: Write the failing test**

```python
# tests/kplatform/memory/test_storage.py
import sqlite3
from kplatform.memory.storage import Storage


def test_creates_database(tmp_db):
    s = Storage(tmp_db)
    assert s.conn is not None
    s.close()


def test_episodes_table_exists(tmp_db):
    s = Storage(tmp_db)
    tables = [r[0] for r in s.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    assert "episodes" in tables
    assert "episode_vectors" in tables
    s.close()


def test_semantics_table_exists(tmp_db):
    s = Storage(tmp_db)
    tables = [r[0] for r in s.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    assert "semantics" in tables
    assert "semantic_vectors" in tables
    s.close()


def test_instincts_table_exists(tmp_db):
    s = Storage(tmp_db)
    tables = [r[0] for r in s.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    assert "instincts" in tables
    assert "instinct_vectors" in tables
    assert "instinct_context_vectors" in tables
    assert "instinct_context_feedback" in tables
    s.close()


def test_wal_mode(tmp_db):
    s = Storage(tmp_db)
    mode = s.conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"
    s.close()


def test_migration_version_tracked(tmp_db):
    s = Storage(tmp_db)
    version = s.conn.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()[0]
    assert int(version) == 3
    s.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/kplatform/memory/test_storage.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write 001_initial.sql**

```sql
-- 001_initial.sql: Core three-layer schema
-- Episodes, semantics, instincts with vec0 vectors and FTS5

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Episodes: raw experiences
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    content TEXT NOT NULL,
    episode_type TEXT DEFAULT 'observation',
    strength REAL DEFAULT 1.0,
    core INTEGER DEFAULT 0,
    compressed INTEGER DEFAULT 0,
    access_count INTEGER DEFAULT 0,
    context TEXT,
    source TEXT,
    content_hash TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    last_accessed TEXT DEFAULT (datetime('now'))
);

-- Semantics: distilled knowledge
CREATE TABLE IF NOT EXISTS semantics (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('fact', 'preference', 'constraint')),
    confidence REAL DEFAULT 0.5,
    auto_generated INTEGER DEFAULT 0,
    source_episode_ids TEXT DEFAULT '[]',
    contradicted_by TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Instincts: behavioral dispositions
CREATE TABLE IF NOT EXISTS instincts (
    id TEXT PRIMARY KEY,
    trigger TEXT NOT NULL,
    action TEXT NOT NULL,
    notice TEXT,
    implication TEXT,
    strength REAL DEFAULT 0.5,
    source_semantic_ids TEXT DEFAULT '[]',
    fired_count INTEGER DEFAULT 0,
    followed_count INTEGER DEFAULT 0,
    overridden_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Instinct source tracking
CREATE TABLE IF NOT EXISTS instinct_sources (
    instinct_id TEXT NOT NULL REFERENCES instincts(id),
    semantic_id TEXT NOT NULL,
    PRIMARY KEY (instinct_id, semantic_id)
);

-- Memory log: recall/feedback tracking
CREATE TABLE IF NOT EXISTS memory_log (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    layer TEXT,
    target_ids TEXT DEFAULT '[]',
    context TEXT,
    outcome TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- FTS5 indexes
CREATE VIRTUAL TABLE IF NOT EXISTS episode_fts USING fts5(
    id, content, tokenize='porter'
);
CREATE VIRTUAL TABLE IF NOT EXISTS semantic_fts USING fts5(
    id, content, tokenize='porter'
);
```

- [ ] **Step 4: Write 002_contextual_instincts.sql**

```sql
-- 002_contextual_instincts.sql: Context-aware instinct feedback

CREATE TABLE IF NOT EXISTS instinct_context_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instinct_id TEXT NOT NULL REFERENCES instincts(id),
    context_text TEXT NOT NULL,
    followed INTEGER NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
```

- [ ] **Step 5: Write 003_federation.sql**

(Empty migration placeholder — federation tables created by federation.py when needed.)

```sql
-- 003_federation.sql: reserved for federation schema extensions
-- Federation tables (signal_bus, instance_registry) are managed
-- by federation.py with their own SQLite databases.
```

- [ ] **Step 6: Write storage.py (migration runner + connection setup)**

```python
# kplatform/memory/storage.py
"""SQLite + vec0 storage layer for three-layer memory."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class Storage:
    """Memory storage backed by SQLite with vec0 vector search."""

    def __init__(self, db_path: str, migrations_dir: str | None = None):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")

        # Load vec0 extension
        self.conn.enable_load_extension(True)
        try:
            import sqlite_vec
            sqlite_vec.load(self.conn)
        except Exception:
            pass  # vec0 not available — vector search disabled
        self.conn.enable_load_extension(False)

        if migrations_dir is None:
            migrations_dir = str(Path(__file__).parent / "migrations")
        self._run_migrations(migrations_dir)
        self._check_vec0_health()

    def _run_migrations(self, migrations_dir: str) -> None:
        """Apply SQL migrations in order."""
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        current = self._get_schema_version()
        mig_path = Path(migrations_dir)
        if not mig_path.exists():
            return

        files = sorted(mig_path.glob("*.sql"))
        for f in files:
            version = int(f.stem.split("_")[0])
            if version > current:
                self.conn.executescript(f.read_text())
                self._set_schema_version(version)
        self.conn.commit()

    def _get_schema_version(self) -> int:
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        return int(row[0]) if row else 0

    def _set_schema_version(self, version: int) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(version),),
        )

    def _check_vec0_health(self) -> None:
        """Verify vec0 tables are accessible. Rebuild if corrupted."""
        for table in ("episode_vectors", "semantic_vectors",
                      "instinct_vectors", "instinct_context_vectors"):
            try:
                self.conn.execute(f"SELECT count(*) FROM {table}")
            except Exception:
                # Table missing or corrupted — recreate
                try:
                    self.conn.execute(f"DROP TABLE IF EXISTS {table}")
                except Exception:
                    pass
                self._create_vec0_tables()
                break

    def _create_vec0_tables(self, dimension: int = 768) -> None:
        """Create vec0 virtual tables for vector search."""
        for table in ("episode_vectors", "semantic_vectors",
                      "instinct_vectors", "instinct_context_vectors"):
            try:
                self.conn.execute(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} "
                    f"USING vec0(id TEXT PRIMARY KEY, embedding float[{dimension}])"
                )
            except sqlite3.OperationalError:
                pass  # vec0 not loaded
        self.conn.commit()

    def close(self) -> None:
        """Checkpoint WAL and close connection."""
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        self.conn.close()
```

- [ ] **Step 7: Run tests**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/kplatform/memory/test_storage.py -v`
Expected: All 6 tests PASS

- [ ] **Step 8: Commit**

```bash
git add kplatform/memory/storage.py kplatform/memory/migrations/ tests/kplatform/memory/test_storage.py
git commit -m "feat(memory): storage schema with migrations and vec0 support"
```

---

### Task 5: Storage — Episode CRUD

**Files:**
- Modify: `kairos/kplatform/memory/storage.py`
- Modify: `kairos/tests/kplatform/memory/test_storage.py`

- [ ] **Step 1: Write the failing tests**

Add to `test_storage.py`:

```python
import json
import uuid


def _make_id():
    return str(uuid.uuid4())


def _fake_embedding(dim=768):
    return [0.1] * dim


class TestEpisodes:
    def test_add_episode(self, tmp_db):
        s = Storage(tmp_db)
        s._create_vec0_tables()
        eid = _make_id()
        s.add_episode(eid, "sess1", "I learned something", embedding=_fake_embedding())
        row = s.get_episode(eid)
        assert row is not None
        assert row["content"] == "I learned something"
        assert row["session_id"] == "sess1"
        s.close()

    def test_add_core_episode(self, tmp_db):
        s = Storage(tmp_db)
        s._create_vec0_tables()
        eid = _make_id()
        s.add_episode(eid, "sess1", "formative memory", core=True, embedding=_fake_embedding())
        row = s.get_episode(eid)
        assert row["core"] == 1
        s.close()

    def test_mark_core(self, tmp_db):
        s = Storage(tmp_db)
        s._create_vec0_tables()
        eid = _make_id()
        s.add_episode(eid, "sess1", "important", embedding=_fake_embedding())
        s.mark_core(eid)
        row = s.get_episode(eid)
        assert row["core"] == 1
        s.close()

    def test_get_uncompressed_episodes(self, tmp_db):
        s = Storage(tmp_db)
        s._create_vec0_tables()
        e1 = _make_id()
        e2 = _make_id()
        s.add_episode(e1, "s1", "first", embedding=_fake_embedding())
        s.add_episode(e2, "s1", "second", embedding=_fake_embedding())
        s.mark_episodes_compressed([e1])
        uncompressed = s.get_uncompressed_episodes()
        assert len(uncompressed) == 1
        assert uncompressed[0]["id"] == e2
        s.close()

    def test_apply_decay(self, tmp_db):
        s = Storage(tmp_db)
        s._create_vec0_tables()
        eid = _make_id()
        s.add_episode(eid, "s1", "will decay", embedding=_fake_embedding())
        decayed = s.apply_decay(factor=0.5, min_interval_minutes=0)
        assert decayed > 0
        row = s.get_episode(eid)
        assert row["strength"] == 0.5
        s.close()

    def test_decay_skips_core(self, tmp_db):
        s = Storage(tmp_db)
        s._create_vec0_tables()
        eid = _make_id()
        s.add_episode(eid, "s1", "core memory", core=True, embedding=_fake_embedding())
        s.apply_decay(factor=0.5, min_interval_minutes=0)
        row = s.get_episode(eid)
        assert row["strength"] == 1.0
        s.close()

    def test_prune_decayed(self, tmp_db):
        s = Storage(tmp_db)
        s._create_vec0_tables()
        eid = _make_id()
        s.add_episode(eid, "s1", "weak", embedding=_fake_embedding())
        # Manually set strength below threshold
        s.conn.execute("UPDATE episodes SET strength = 0.01, compressed = 1 WHERE id = ?", (eid,))
        s.conn.commit()
        pruned = s.prune_decayed(threshold=0.05)
        assert pruned == 1
        assert s.get_episode(eid) is None
        s.close()

    def test_search_vectors(self, tmp_db):
        s = Storage(tmp_db)
        s._create_vec0_tables()
        eid = _make_id()
        emb = _fake_embedding()
        s.add_episode(eid, "s1", "searchable", embedding=emb)
        results = s.search_vectors("episode_vectors", emb, k=5)
        assert len(results) > 0
        assert results[0]["id"] == eid
        s.close()

    def test_get_core_episodes(self, tmp_db):
        s = Storage(tmp_db)
        s._create_vec0_tables()
        e1 = _make_id()
        e2 = _make_id()
        s.add_episode(e1, "s1", "core one", core=True, embedding=_fake_embedding())
        s.add_episode(e2, "s1", "not core", embedding=_fake_embedding())
        cores = s.get_core_episodes()
        assert len(cores) == 1
        assert cores[0]["id"] == e1
        s.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/kplatform/memory/test_storage.py::TestEpisodes -v`
Expected: FAIL — methods not defined

- [ ] **Step 3: Implement episode methods in storage.py**

Add to Storage class:

```python
    def add_episode(
        self, id: str, session_id: str, content: str, *,
        episode_type: str = "observation", embedding: list[float] | None = None,
        context: dict | None = None, core: bool = False, source: str | None = None,
    ) -> None:
        """Store an episode."""
        import hashlib, json
        ctx = json.dumps(context) if context else None
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        self.conn.execute(
            """INSERT INTO episodes (id, session_id, content, episode_type, context,
               core, source, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (id, session_id, content, episode_type, ctx, int(core), source, content_hash),
        )
        if embedding:
            self._upsert_vector("episode_vectors", id, embedding)
        # FTS
        self.conn.execute(
            "INSERT INTO episode_fts (id, content) VALUES (?, ?)", (id, content)
        )
        self.conn.commit()

    def get_episode(self, id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM episodes WHERE id = ?", (id,)).fetchone()
        return dict(row) if row else None

    def get_uncompressed_episodes(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM episodes WHERE compressed = 0 ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_episodes_compressed(self, ids: list[str]) -> None:
        placeholders = ",".join("?" for _ in ids)
        self.conn.execute(
            f"UPDATE episodes SET compressed = 1 WHERE id IN ({placeholders})", ids
        )
        self.conn.commit()

    def mark_core(self, episode_id: str, tier: int = 1) -> None:
        self.conn.execute(
            "UPDATE episodes SET core = ? WHERE id = ?", (tier, episode_id)
        )
        self.conn.commit()

    def get_core_episodes(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM episodes WHERE core > 0 ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]

    def apply_decay(self, factor: float = 0.9, min_interval_minutes: int = 30) -> int:
        """Apply decay to non-core episode strengths. Returns count of decayed episodes."""
        if min_interval_minutes > 0:
            last = self.conn.execute(
                "SELECT value FROM meta WHERE key = 'last_decay'"
            ).fetchone()
            if last:
                from datetime import datetime, timedelta
                last_time = datetime.fromisoformat(last[0])
                if datetime.now() - last_time < timedelta(minutes=min_interval_minutes):
                    return 0
        cursor = self.conn.execute(
            "UPDATE episodes SET strength = strength * ? WHERE core = 0",
            (factor,),
        )
        from datetime import datetime
        self.conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('last_decay', ?)",
            (datetime.now().isoformat(),),
        )
        self.conn.commit()
        return cursor.rowcount

    def prune_decayed(self, threshold: float = 0.05) -> int:
        """Remove compressed episodes below strength threshold."""
        rows = self.conn.execute(
            "SELECT id FROM episodes WHERE compressed = 1 AND core = 0 AND strength < ?",
            (threshold,),
        ).fetchall()
        ids = [r[0] for r in rows]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        self.conn.execute(f"DELETE FROM episode_vectors WHERE id IN ({placeholders})", ids)
        self.conn.execute(f"DELETE FROM episode_fts WHERE id IN ({placeholders})", ids)
        self.conn.execute(f"DELETE FROM episodes WHERE id IN ({placeholders})", ids)
        self.conn.commit()
        return len(ids)

    def search_vectors(self, table_name: str, embedding: list[float], k: int = 10) -> list[dict]:
        """Search vec0 table by embedding similarity."""
        import json
        allowed = {"episode_vectors", "semantic_vectors", "instinct_vectors", "instinct_context_vectors"}
        if table_name not in allowed:
            raise ValueError(f"Invalid vector table: {table_name}")
        rows = self.conn.execute(
            f"SELECT id, distance FROM {table_name} WHERE embedding MATCH ? AND k = ?",
            (json.dumps(embedding), k),
        ).fetchall()
        return [{"id": r[0], "distance": r[1]} for r in rows]

    def _upsert_vector(self, table: str, id: str, embedding: list[float]) -> None:
        """Insert or replace a vector in a vec0 table."""
        import json
        try:
            self.conn.execute(f"DELETE FROM {table} WHERE id = ?", (id,))
            self.conn.execute(
                f"INSERT INTO {table} (id, embedding) VALUES (?, ?)",
                (id, json.dumps(embedding)),
            )
        except Exception:
            pass  # vec0 not available
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/kplatform/memory/test_storage.py -v`
Expected: All tests PASS (schema + episodes)

- [ ] **Step 5: Commit**

```bash
git add kplatform/memory/storage.py tests/kplatform/memory/test_storage.py
git commit -m "feat(memory): episode CRUD with decay, pruning, and vector search"
```

---

### Task 6: Storage — Semantic and Instinct CRUD

**Files:**
- Modify: `kairos/kplatform/memory/storage.py`
- Modify: `kairos/tests/kplatform/memory/test_storage.py`

- [ ] **Step 1: Write the failing tests**

Add to `test_storage.py`:

```python
class TestSemantics:
    def test_add_semantic(self, tmp_db):
        s = Storage(tmp_db)
        s._create_vec0_tables()
        sid = _make_id()
        s.add_semantic(sid, "User prefers terse responses", "preference", embedding=_fake_embedding())
        row = s.get_semantic(sid)
        assert row is not None
        assert row["kind"] == "preference"
        assert row["confidence"] == 0.5
        s.close()

    def test_reinforce_semantic(self, tmp_db):
        s = Storage(tmp_db)
        s._create_vec0_tables()
        sid = _make_id()
        s.add_semantic(sid, "fact", "fact", embedding=_fake_embedding())
        s.reinforce_semantic(sid, ["ep1", "ep2"])
        row = s.get_semantic(sid)
        assert row["confidence"] > 0.5
        s.close()

    def test_get_active_semantics(self, tmp_db):
        s = Storage(tmp_db)
        s._create_vec0_tables()
        s1 = _make_id()
        s2 = _make_id()
        s.add_semantic(s1, "fact one", "fact", embedding=_fake_embedding())
        s.add_semantic(s2, "pref one", "preference", embedding=_fake_embedding())
        facts = s.get_active_semantics("fact")
        assert len(facts) == 1
        assert facts[0]["id"] == s1
        s.close()


class TestInstincts:
    def test_add_instinct(self, tmp_db):
        s = Storage(tmp_db)
        s._create_vec0_tables()
        iid = _make_id()
        s.add_instinct(
            iid, "preference", "be terse",
            notice="when responding", implication="keep it short",
            embedding=_fake_embedding(),
        )
        row = s.get_instinct(iid)
        assert row is not None
        assert row["notice"] == "when responding"
        assert row["implication"] == "keep it short"
        s.close()

    def test_instinct_feedback(self, tmp_db):
        s = Storage(tmp_db)
        s._create_vec0_tables()
        iid = _make_id()
        s.add_instinct(iid, "pref", "act", embedding=_fake_embedding())
        s.update_instinct_followed(iid)
        s.update_instinct_followed(iid)
        s.update_instinct_overridden(iid)
        row = s.get_instinct(iid)
        assert row["followed_count"] == 2
        assert row["overridden_count"] == 1
        assert row["fired_count"] == 3
        s.close()

    def test_context_feedback(self, tmp_db):
        s = Storage(tmp_db)
        s._create_vec0_tables()
        iid = _make_id()
        s.add_instinct(iid, "pref", "act", embedding=_fake_embedding())
        s.add_instinct_context_feedback(iid, "building", _fake_embedding(), followed=True)
        s.add_instinct_context_feedback(iid, "building", _fake_embedding(), followed=False)
        feedback = s.get_instinct_context_feedback(iid)
        assert len(feedback) == 2
        s.close()

    def test_get_all_instincts(self, tmp_db):
        s = Storage(tmp_db)
        s._create_vec0_tables()
        i1 = _make_id()
        i2 = _make_id()
        s.add_instinct(i1, "p", "a1", embedding=_fake_embedding())
        s.add_instinct(i2, "p", "a2", embedding=_fake_embedding())
        all_inst = s.get_all_instincts()
        assert len(all_inst) == 2
        s.close()

    def test_prune_weak_instincts(self, tmp_db):
        s = Storage(tmp_db)
        s._create_vec0_tables()
        iid = _make_id()
        s.add_instinct(iid, "p", "weak", embedding=_fake_embedding())
        s.conn.execute("UPDATE instincts SET strength = 0.05 WHERE id = ?", (iid,))
        s.conn.commit()
        pruned = s.prune_weak_instincts(strength_threshold=0.1)
        assert pruned == 1
        assert s.get_instinct(iid) is None
        s.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/kplatform/memory/test_storage.py::TestSemantics tests/kplatform/memory/test_storage.py::TestInstincts -v`
Expected: FAIL — methods not defined

- [ ] **Step 3: Implement semantic and instinct methods**

Add to Storage class:

```python
    # --- Semantics ---

    def add_semantic(
        self, id: str, content: str, kind: str, *,
        confidence: float = 0.5, embedding: list[float] | None = None,
        source_episode_ids: list[str] | None = None,
        auto_generated: bool = False,
    ) -> None:
        import json
        src = json.dumps(source_episode_ids or [])
        self.conn.execute(
            """INSERT INTO semantics (id, content, kind, confidence,
               source_episode_ids, auto_generated) VALUES (?, ?, ?, ?, ?, ?)""",
            (id, content, kind, confidence, src, int(auto_generated)),
        )
        if embedding:
            self._upsert_vector("semantic_vectors", id, embedding)
        self.conn.execute(
            "INSERT INTO semantic_fts (id, content) VALUES (?, ?)", (id, content)
        )
        self.conn.commit()

    def get_semantic(self, id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM semantics WHERE id = ?", (id,)).fetchone()
        return dict(row) if row else None

    def reinforce_semantic(self, id: str, additional_episode_ids: list[str]) -> None:
        import json
        row = self.conn.execute("SELECT source_episode_ids, confidence FROM semantics WHERE id = ?", (id,)).fetchone()
        if not row:
            return
        existing = json.loads(row[0])
        existing.extend(additional_episode_ids)
        new_confidence = min(1.0, row[1] + 0.1 * len(additional_episode_ids))
        self.conn.execute(
            "UPDATE semantics SET source_episode_ids = ?, confidence = ?, updated_at = datetime('now') WHERE id = ?",
            (json.dumps(existing), new_confidence, id),
        )
        self.conn.commit()

    def get_active_semantics(self, kind: str | None = None, limit: int = 100) -> list[dict]:
        if kind:
            rows = self.conn.execute(
                "SELECT * FROM semantics WHERE kind = ? AND contradicted_by IS NULL ORDER BY confidence DESC LIMIT ?",
                (kind, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM semantics WHERE contradicted_by IS NULL ORDER BY confidence DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # --- Instincts ---

    def add_instinct(
        self, id: str, trigger: str, action: str, *,
        notice: str | None = None, implication: str | None = None,
        strength: float = 0.5, embedding: list[float] | None = None,
        source_semantic_ids: list[str] | None = None,
    ) -> None:
        import json
        src = json.dumps(source_semantic_ids or [])
        self.conn.execute(
            """INSERT INTO instincts (id, trigger, action, notice, implication,
               strength, source_semantic_ids) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (id, trigger, action, notice, implication, strength, src),
        )
        if embedding:
            self._upsert_vector("instinct_vectors", id, embedding)
        self.conn.commit()

    def get_instinct(self, id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM instincts WHERE id = ?", (id,)).fetchone()
        return dict(row) if row else None

    def get_all_instincts(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM instincts ORDER BY strength DESC").fetchall()
        return [dict(r) for r in rows]

    def update_instinct_followed(self, id: str) -> None:
        self.conn.execute(
            "UPDATE instincts SET followed_count = followed_count + 1, "
            "fired_count = fired_count + 1, updated_at = datetime('now') WHERE id = ?",
            (id,),
        )
        self.conn.commit()

    def update_instinct_overridden(self, id: str) -> None:
        self.conn.execute(
            "UPDATE instincts SET overridden_count = overridden_count + 1, "
            "fired_count = fired_count + 1, updated_at = datetime('now') WHERE id = ?",
            (id,),
        )
        self.conn.commit()

    def add_instinct_context_feedback(
        self, instinct_id: str, context_text: str,
        context_embedding: list[float], followed: bool,
    ) -> None:
        self.conn.execute(
            "INSERT INTO instinct_context_feedback (instinct_id, context_text, followed) VALUES (?, ?, ?)",
            (instinct_id, context_text, int(followed)),
        )
        self._upsert_vector("instinct_context_vectors", instinct_id, context_embedding)
        self.conn.commit()

    def get_instinct_context_feedback(self, instinct_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM instinct_context_feedback WHERE instinct_id = ? ORDER BY created_at",
            (instinct_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def prune_weak_instincts(self, strength_threshold: float = 0.1) -> int:
        rows = self.conn.execute(
            "SELECT id FROM instincts WHERE strength < ?", (strength_threshold,)
        ).fetchall()
        ids = [r[0] for r in rows]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        self.conn.execute(f"DELETE FROM instinct_vectors WHERE id IN ({placeholders})", ids)
        self.conn.execute(f"DELETE FROM instinct_context_vectors WHERE id IN ({placeholders})", ids)
        self.conn.execute(f"DELETE FROM instinct_context_feedback WHERE instinct_id IN ({placeholders})", ids)
        self.conn.execute(f"DELETE FROM instinct_sources WHERE instinct_id IN ({placeholders})", ids)
        self.conn.execute(f"DELETE FROM instincts WHERE id IN ({placeholders})", ids)
        self.conn.commit()
        return len(ids)

    # --- Logging ---

    def add_log_entry(
        self, id: str, event_type: str, *,
        layer: str | None = None, target_ids: list[str] | None = None,
        context: dict | None = None, outcome: str | None = None,
    ) -> None:
        import json
        self.conn.execute(
            "INSERT INTO memory_log (id, event_type, layer, target_ids, context, outcome) VALUES (?, ?, ?, ?, ?, ?)",
            (id, event_type, layer, json.dumps(target_ids or []),
             json.dumps(context) if context else None, outcome),
        )
        self.conn.commit()

    def update_log_outcome(self, recall_id: str, outcome: str) -> None:
        self.conn.execute(
            "UPDATE memory_log SET outcome = ? WHERE id = ?", (outcome, recall_id)
        )
        self.conn.commit()

    def get_table_count(self, table_name: str) -> int:
        allowed = {"episodes", "semantics", "instincts", "memory_log"}
        if table_name not in allowed:
            raise ValueError(f"Invalid table: {table_name}")
        row = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
        return row[0]
```

- [ ] **Step 4: Run all storage tests**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/kplatform/memory/test_storage.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add kplatform/memory/storage.py tests/kplatform/memory/test_storage.py
git commit -m "feat(memory): semantic and instinct CRUD with context feedback"
```

---

### Task 7: Dedup

**Files:**
- Create: `kairos/kplatform/memory/dedup.py`
- Create: `kairos/tests/kplatform/memory/test_dedup.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/kplatform/memory/test_dedup.py
from kplatform.memory.dedup import Deduplicator
from kplatform.memory.config import DedupConfig


def test_dedup_unavailable_fallback():
    """When Ollama is not running, dedup should fail open."""
    config = DedupConfig(ollama_url="http://localhost:99999/api/generate", timeout=1)
    d = Deduplicator(config)
    assert d.is_available() is False


def test_dedup_unavailable_returns_false():
    """When unavailable, is_equivalent returns False (fail open)."""
    config = DedupConfig(ollama_url="http://localhost:99999/api/generate", timeout=1)
    d = Deduplicator(config)
    assert d.is_equivalent("hello", "hello") is False


def test_find_duplicates_empty():
    d = Deduplicator()
    assert d.find_duplicates([]) == []


def test_find_duplicates_single():
    d = Deduplicator()
    assert d.find_duplicates([{"content": "hello"}]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/kplatform/memory/test_dedup.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write dedup.py**

```python
# kplatform/memory/dedup.py
"""LLM-based pragmatic equivalence checking via Ollama."""

from __future__ import annotations

import json
import urllib.request
import urllib.error

from kplatform.memory.config import DedupConfig


class Deduplicator:
    """Check if two texts are pragmatically equivalent using a local LLM."""

    def __init__(self, config: DedupConfig | None = None):
        self._config = config or DedupConfig()
        self._available: bool | None = None

    def is_available(self) -> bool:
        """Check if Ollama is reachable. Cached after first check."""
        if self._available is not None:
            return self._available
        try:
            req = urllib.request.Request(
                self._config.ollama_url,
                data=json.dumps({
                    "model": self._config.model,
                    "prompt": "ping",
                    "stream": False,
                }).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=self._config.timeout)
            self._available = True
        except Exception:
            self._available = False
        return self._available

    def is_equivalent(self, a: str, b: str) -> bool:
        """Check if two texts are pragmatically equivalent. Fails open (returns False)."""
        if not self.is_available():
            return False
        prompt = (
            "Are these two statements pragmatically equivalent — do they convey "
            "the same practical meaning, even if worded differently?\n\n"
            f"A: {a}\nB: {b}\n\n"
            "Answer with just YES or NO."
        )
        try:
            req = urllib.request.Request(
                self._config.ollama_url,
                data=json.dumps({
                    "model": self._config.model,
                    "prompt": prompt,
                    "stream": False,
                }).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=self._config.timeout)
            result = json.loads(resp.read())
            return "YES" in result.get("response", "").upper()
        except Exception:
            return False

    def find_duplicates(
        self, items: list[dict], key: str = "content"
    ) -> list[tuple[int, int]]:
        """Find pairwise duplicates in a list. Returns index pairs."""
        if len(items) < 2:
            return []
        pairs = []
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if self.is_equivalent(items[i][key], items[j][key]):
                    pairs.append((i, j))
        return pairs
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/kplatform/memory/test_dedup.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add kplatform/memory/dedup.py tests/kplatform/memory/test_dedup.py
git commit -m "feat(memory): LLM-based dedup with fail-open fallback"
```

---

### Task 8: Compression Pipeline

**Files:**
- Create: `kairos/kplatform/memory/compress.py`
- Create: `kairos/tests/kplatform/memory/test_compress.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/kplatform/memory/test_compress.py
import uuid
from kplatform.memory.storage import Storage
from kplatform.memory.compress import Compressor
from kplatform.memory.embeddings import NomicEmbedProvider
from kplatform.memory.dedup import Deduplicator
from kplatform.memory.config import MemoryConfig


def _setup(tmp_db):
    cfg = MemoryConfig()
    s = Storage(tmp_db)
    s._create_vec0_tables()
    e = NomicEmbedProvider()
    d = Deduplicator()
    c = Compressor(s, e, cfg, d)
    return s, e, c


def _add_episodes(s, e, count, prefix="episode"):
    ids = []
    for i in range(count):
        eid = str(uuid.uuid4())
        content = f"{prefix} number {i}: some content about topic {i % 3}"
        emb = e.embed([content])[0]
        s.add_episode(eid, "test-session", content, embedding=emb)
        ids.append(eid)
    return ids


def test_cluster_empty(tmp_db):
    s, e, c = _setup(tmp_db)
    result = c.cluster_episodes()
    assert result["clusters"] == []
    s.close()


def test_cluster_returns_clusters(tmp_db):
    s, e, c = _setup(tmp_db)
    _add_episodes(s, e, 6)
    result = c.cluster_episodes()
    assert len(result["clusters"]) > 0
    assert "compress_id" in result
    s.close()


def test_auto_compress_creates_semantics(tmp_db):
    s, e, c = _setup(tmp_db)
    _add_episodes(s, e, 6, prefix="testing memory")
    result = c.auto_compress()
    # auto_compress should process episodes
    assert result["episodes_processed"] > 0
    s.close()


def test_commit_with_summaries(tmp_db):
    s, e, c = _setup(tmp_db)
    _add_episodes(s, e, 4, prefix="learning python")
    phase1 = c.cluster_episodes()
    if phase1["clusters"]:
        summaries = []
        for cluster in phase1["clusters"]:
            summaries.append({
                "content": "User is learning Python",
                "kind": "fact",
                "action": "new",
            })
        result = c.commit(phase1["compress_id"], summaries)
        assert result["semantics_created"] > 0
    s.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/kplatform/memory/test_compress.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write compress.py**

Port from `/Users/kairos/Projects/engram/compress.py`, preserving:
- `cluster_episodes()` — hierarchical clustering with configurable similarity threshold
- `commit()` — accept summaries, create/reinforce semantics, check instinct creation
- `auto_compress()` — centroid selection for small clusters, MMR for larger
- `_select_centroid_nearest()` — nearest to cluster center
- `_select_mmr()` — maximal marginal relevance for diversity
- `_check_instinct_creation()` — create instincts from confident semantics
- `_instinct_already_exists()` — LLM dedup then embedding similarity
- `_generate_perceptual_framing()` — notice/implication from action text

```python
# kplatform/memory/compress.py
"""Compression pipeline: episodes → semantics → instincts."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist

if TYPE_CHECKING:
    from kplatform.memory.config import MemoryConfig
    from kplatform.memory.dedup import Deduplicator
    from kplatform.memory.embeddings import EmbeddingProvider
    from kplatform.memory.storage import Storage


class Compressor:
    """Compress episodes into semantics and instincts."""

    def __init__(
        self,
        storage: Storage,
        embedding_provider: EmbeddingProvider,
        config: MemoryConfig,
        deduplicator: Deduplicator | None = None,
    ):
        self._storage = storage
        self._embed = embedding_provider
        self._config = config
        self._dedup = deduplicator
        self._pending: dict[str, dict] = {}

    def cluster_episodes(self, scope: str = "recent") -> dict:
        """Phase 1: Cluster uncompressed episodes. Returns clusters + compress_id."""
        if scope == "recent":
            episodes = self._storage.get_uncompressed_episodes()
        else:
            episodes = self._storage.get_uncompressed_episodes()

        if not episodes:
            return {"clusters": [], "compress_id": None}

        # Get embeddings
        contents = [ep["content"] for ep in episodes]
        embeddings = self._embed.embed(contents, prefix="clustering")

        if len(episodes) < 2:
            clusters = [{"episodes": episodes, "centroid_idx": 0, "embeddings": embeddings}]
        else:
            distances = pdist(embeddings, metric="cosine")
            Z = linkage(distances, method="average", metric="cosine")
            threshold = self._config.compression.cluster_similarity
            labels = fcluster(Z, t=1 - threshold, criterion="distance")

            cluster_map: dict[int, list] = {}
            embed_map: dict[int, list] = {}
            for i, label in enumerate(labels):
                cluster_map.setdefault(label, []).append(episodes[i])
                embed_map.setdefault(label, []).append(embeddings[i])

            clusters = []
            for label in sorted(cluster_map.keys()):
                eps = cluster_map[label]
                embs = embed_map[label]
                centroid_idx = self._select_centroid_nearest(embs)
                clusters.append({
                    "episodes": eps,
                    "centroid_idx": centroid_idx,
                    "embeddings": embs,
                })

        compress_id = str(uuid.uuid4())
        self._pending[compress_id] = {
            "clusters": clusters,
            "episode_ids": [ep["id"] for ep in episodes],
        }

        # Return without embeddings (for display)
        display_clusters = []
        for c in clusters:
            display_clusters.append({
                "episodes": [{"id": ep["id"], "content": ep["content"]} for ep in c["episodes"]],
                "centroid": c["episodes"][c["centroid_idx"]]["content"],
            })

        return {"clusters": display_clusters, "compress_id": compress_id}

    def commit(self, compress_id: str, summaries: list[dict]) -> dict:
        """Phase 2: Commit summaries as semantics, mark episodes compressed."""
        pending = self._pending.pop(compress_id, None)
        if not pending:
            return {"episodes_processed": 0, "semantics_created": 0,
                    "semantics_reinforced": 0, "instincts_created": 0}

        created = 0
        reinforced = 0
        for summary in summaries:
            action = summary.get("action", "new")
            content = summary["content"]
            kind = summary.get("kind", "fact")
            embedding = self._embed.embed([content], prefix="search_document")[0]

            if action == "reinforce" and "semantic_id" in summary:
                self._storage.reinforce_semantic(
                    summary["semantic_id"],
                    pending["episode_ids"],
                )
                reinforced += 1
            else:
                sid = str(uuid.uuid4())
                self._storage.add_semantic(
                    sid, content, kind,
                    embedding=embedding,
                    source_episode_ids=pending["episode_ids"],
                    auto_generated=summary.get("auto_generated", False),
                )
                created += 1

        self._storage.mark_episodes_compressed(pending["episode_ids"])

        # Check for instinct creation
        instincts_created = self._check_instinct_creation()

        return {
            "episodes_processed": len(pending["episode_ids"]),
            "semantics_created": created,
            "semantics_reinforced": reinforced,
            "instincts_created": instincts_created,
        }

    def auto_compress(self) -> dict:
        """Automatic compression: cluster, select centroids, commit."""
        result = self.cluster_episodes()
        if not result["clusters"]:
            return {"episodes_processed": 0, "semantics_created": 0,
                    "semantics_reinforced": 0, "instincts_created": 0}

        summaries = []
        pending = self._pending.get(result["compress_id"], {})
        clusters = pending.get("clusters", [])

        for cluster in clusters:
            centroid_ep = cluster["episodes"][cluster["centroid_idx"]]
            summaries.append({
                "content": centroid_ep["content"],
                "kind": "fact",
                "action": "new",
                "auto_generated": True,
            })

        return self.commit(result["compress_id"], summaries)

    @staticmethod
    def _select_centroid_nearest(embeddings: list[list[float]]) -> int:
        """Select the embedding nearest to the centroid."""
        if len(embeddings) <= 1:
            return 0
        import numpy as np
        emb_array = np.array(embeddings)
        centroid = emb_array.mean(axis=0)
        distances = np.linalg.norm(emb_array - centroid, axis=1)
        return int(np.argmin(distances))

    @staticmethod
    def _select_mmr(
        embeddings: list[list[float]], k: int = 1, lambda_param: float = 0.5
    ) -> list[int]:
        """Maximal Marginal Relevance for diverse selection."""
        import numpy as np
        if len(embeddings) <= k:
            return list(range(len(embeddings)))

        emb_array = np.array(embeddings)
        centroid = emb_array.mean(axis=0)

        selected: list[int] = []
        remaining = list(range(len(embeddings)))

        for _ in range(k):
            best_score = -float("inf")
            best_idx = remaining[0]
            for idx in remaining:
                relevance = float(np.dot(emb_array[idx], centroid))
                redundancy = 0.0
                if selected:
                    redundancy = max(
                        float(np.dot(emb_array[idx], emb_array[s]))
                        for s in selected
                    )
                score = lambda_param * relevance - (1 - lambda_param) * redundancy
                if score > best_score:
                    best_score = score
                    best_idx = idx
            selected.append(best_idx)
            remaining.remove(best_idx)

        return selected

    def _check_instinct_creation(self) -> int:
        """Create instincts from high-confidence semantics."""
        semantics = self._storage.get_active_semantics(limit=50)
        created = 0
        threshold = self._config.compression.instinct_confidence

        for sem in semantics:
            if sem["confidence"] < threshold:
                continue
            if self._instinct_already_exists(sem["content"]):
                continue

            notice, implication = self._generate_perceptual_framing(sem["content"])
            embedding = self._embed.embed([sem["content"]], prefix="search_document")[0]

            iid = str(uuid.uuid4())
            self._storage.add_instinct(
                iid, sem["kind"], sem["content"],
                notice=notice, implication=implication,
                embedding=embedding,
                source_semantic_ids=[sem["id"]],
            )
            created += 1
        return created

    def _instinct_already_exists(self, content: str) -> bool:
        """Check if an equivalent instinct exists (LLM dedup, then embedding)."""
        existing = self._storage.get_all_instincts()
        if not existing:
            return False

        # Try LLM dedup first
        if self._dedup and self._dedup.is_available():
            for inst in existing:
                if self._dedup.is_equivalent(content, inst["action"]):
                    return True

        # Fallback: embedding similarity
        embedding = self._embed.embed([content], prefix="search_document")[0]
        results = self._storage.search_vectors("instinct_vectors", embedding, k=3)
        for r in results:
            if r["distance"] < 0.15:  # Very similar
                return True
        return False

    @staticmethod
    def _generate_perceptual_framing(content: str) -> tuple[str, str]:
        """Generate notice/implication pair from content."""
        # Simple heuristic — real version would use LLM
        words = content.split()
        if len(words) > 10:
            notice = f"when deciding on: {' '.join(words[:8])}..."
            implication = content
        else:
            notice = f"when: {content}"
            implication = content
        return notice, implication
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/kplatform/memory/test_compress.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add kplatform/memory/compress.py tests/kplatform/memory/test_compress.py
git commit -m "feat(memory): compression pipeline with clustering, centroid, MMR"
```

---

### Task 9: Federation

**Files:**
- Create: `kairos/kplatform/memory/federation.py`
- Create: `kairos/tests/kplatform/memory/test_federation.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/kplatform/memory/test_federation.py
from kplatform.memory.federation import SignalBus, InstanceRegistry, sync_genome


def test_signal_send_receive(tmp_path):
    bus = SignalBus(tmp_path / "signals.db")
    bus.send("atlas", "arena", "research.finding", {"node": "X", "evidence": "Y"})
    inbox = bus.inbox("arena")
    assert len(inbox) == 1
    assert inbox[0]["msg_type"] == "research.finding"
    bus.close()


def test_signal_mark_seen(tmp_path):
    bus = SignalBus(tmp_path / "signals.db")
    bus.send("atlas", "arena", "test", {"data": 1})
    inbox = bus.inbox("arena")
    bus.mark_seen(inbox[0]["id"], "arena")
    assert bus.inbox("arena") == []
    bus.close()


def test_signal_archive_old(tmp_path):
    bus = SignalBus(tmp_path / "signals.db")
    bus.send("a", "b", "old", {})
    # Force old timestamp
    bus._conn.execute("UPDATE signals SET created_at = datetime('now', '-60 days')")
    bus._conn.commit()
    bus.archive_old(retention_days=30)
    assert bus.inbox("b") == []
    bus.close()


def test_instance_registry(tmp_path):
    reg = InstanceRegistry(tmp_path / "instances.toml")
    reg.register("atlas", str(tmp_path / "atlas.db"))
    reg.register("arena", str(tmp_path / "arena.db"))
    instances = reg.list()
    assert "atlas" in instances
    assert "arena" in instances
    reg.remove("arena")
    assert "arena" not in reg.list()


def test_genome_sync(tmp_path):
    from kplatform.memory.storage import Storage
    genome_db = str(tmp_path / "genome.db")
    instance_db = str(tmp_path / "instance.db")

    genome = Storage(genome_db)
    genome._create_vec0_tables()
    instance = Storage(instance_db)
    instance._create_vec0_tables()

    # Add genome episode
    import uuid
    eid = str(uuid.uuid4())
    genome.add_episode(eid, "genome", "universal truth", core=True,
                       embedding=[0.1] * 768)

    synced = sync_genome(genome_db, instance, embedding_provider=None)
    assert synced >= 1
    # Instance should now have the episode
    ep = instance.get_episode(eid)
    assert ep is not None
    assert ep["content"] == "universal truth"
    genome.close()
    instance.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/kplatform/memory/test_federation.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write federation.py**

```python
# kplatform/memory/federation.py
"""Instance isolation, genome sync, and cross-worker signal bus."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kplatform.memory.storage import Storage

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

class SignalBus:
    """Append-only message queue for cross-worker communication."""

    def __init__(self, db_path: str | Path):
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS signals (
                id TEXT PRIMARY KEY,
                from_instance TEXT NOT NULL,
                to_instance TEXT NOT NULL,
                msg_type TEXT NOT NULL,
                content TEXT NOT NULL,
                in_reply_to TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS seen (
                signal_id TEXT NOT NULL,
                instance TEXT NOT NULL,
                seen_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (signal_id, instance)
            );
        """)

    def send(
        self, from_instance: str, to_instance: str,
        msg_type: str, content: dict, in_reply_to: str | None = None,
    ) -> str:
        msg_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO signals (id, from_instance, to_instance, msg_type, content, in_reply_to) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (msg_id, from_instance, to_instance, msg_type, json.dumps(content), in_reply_to),
        )
        self._conn.commit()
        return msg_id

    def inbox(self, instance: str) -> list[dict]:
        rows = self._conn.execute(
            """SELECT s.* FROM signals s
               LEFT JOIN seen se ON s.id = se.signal_id AND se.instance = ?
               WHERE s.to_instance = ? AND se.signal_id IS NULL
               ORDER BY s.created_at""",
            (instance, instance),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_seen(self, message_id: str, instance: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO seen (signal_id, instance) VALUES (?, ?)",
            (message_id, instance),
        )
        self._conn.commit()

    def archive_old(self, retention_days: int = 30) -> int:
        cursor = self._conn.execute(
            "DELETE FROM signals WHERE created_at < datetime('now', ?)",
            (f"-{retention_days} days",),
        )
        self._conn.commit()
        return cursor.rowcount

    def close(self) -> None:
        self._conn.close()


class InstanceRegistry:
    """Track named instances with their database paths."""

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._data: dict = {}
        if self._path.exists():
            with open(self._path, "rb") as f:
                self._data = tomllib.load(f)

    def register(self, name: str, db_path: str, forked_from: str | None = None) -> None:
        self._data[name] = {"db_path": db_path, "forked_from": forked_from}
        self._write()

    def remove(self, name: str) -> None:
        self._data.pop(name, None)
        self._write()

    def list(self) -> dict:
        return dict(self._data)

    def get(self, name: str) -> dict | None:
        return self._data.get(name)

    def _write(self) -> None:
        # Write as simple TOML
        lines = []
        for name, info in self._data.items():
            lines.append(f"[{name}]")
            for k, v in info.items():
                if v is None:
                    continue
                lines.append(f'{k} = "{v}"')
            lines.append("")
        self._path.write_text("\n".join(lines))


def sync_genome(
    genome_db_path: str, instance_storage: Storage,
    embedding_provider: object | None = None,
) -> int:
    """Sync tier-2 core episodes from genome DB to an instance.

    If embedding_provider is given, re-embeds content for the instance's
    vector space. Otherwise stores without embedding (text-only sync).
    """
    from kplatform.memory.storage import Storage as _Storage
    genome = _Storage(genome_db_path)
    genome._create_vec0_tables()

    core_episodes = genome.get_core_episodes()
    synced = 0
    for ep in core_episodes:
        existing = instance_storage.get_episode(ep["id"])
        if existing is None:
            embedding = None
            if embedding_provider is not None:
                embedding = embedding_provider.embed(
                    [ep["content"]], prefix="search_document"
                )[0]
            instance_storage.add_episode(
                ep["id"], ep["session_id"], ep["content"],
                core=True, source=ep.get("source"),
                embedding=embedding,
            )
            synced += 1
    genome.close()
    return synced
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/kplatform/memory/test_federation.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add kplatform/memory/federation.py tests/kplatform/memory/test_federation.py
git commit -m "feat(memory): federation with signal bus, instance registry, genome sync"
```

---

### Task 10: Reflection

**Files:**
- Create: `kairos/kplatform/memory/reflection.py`
- Create: `kairos/tests/kplatform/memory/test_reflection.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/kplatform/memory/test_reflection.py
import uuid
from kplatform.memory.storage import Storage
from kplatform.memory.reflection import Reflector


def _setup(tmp_db):
    s = Storage(tmp_db)
    s._create_vec0_tables()
    return s, Reflector(s)


def test_reflect_empty(tmp_db):
    s, r = _setup(tmp_db)
    result = r.reflect()
    assert "instincts" in result
    assert "usage" in result
    s.close()


def test_reflect_with_instincts(tmp_db):
    s, r = _setup(tmp_db)
    iid = str(uuid.uuid4())
    s.add_instinct(iid, "pref", "be terse", embedding=[0.1] * 768)
    s.update_instinct_followed(iid)
    result = r.reflect(focus="instincts")
    assert len(result["instincts"]) == 1
    assert result["instincts"][0]["recommendation"] in ("reliable", "new", "unobserved")
    s.close()


def test_introspect(tmp_db):
    s, r = _setup(tmp_db)
    result = r.introspect()
    assert "layer_counts" in result
    assert "health" in result
    s.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/kplatform/memory/test_reflection.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write reflection.py**

```python
# kplatform/memory/reflection.py
"""Self-observation over memory: usage patterns, gaps, instincts."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kplatform.memory.storage import Storage


class Reflector:
    """Analyze memory usage, gaps, and instinct health."""

    def __init__(self, storage: Storage):
        self._storage = storage

    def reflect(self, focus: str | None = None) -> dict:
        """Self-observation. Focus: usage, gaps, instincts, contradictions."""
        result = {
            "usage": self._usage_stats(),
            "instincts": self._instinct_analysis(),
        }
        if focus == "instincts":
            result["instincts"] = self._instinct_analysis()
        return result

    def introspect(self) -> dict:
        """High-level self-portrait."""
        return {
            "layer_counts": {
                "episodes": self._storage.get_table_count("episodes"),
                "semantics": self._storage.get_table_count("semantics"),
                "instincts": self._storage.get_table_count("instincts"),
            },
            "health": self._health_check(),
        }

    def _usage_stats(self) -> dict:
        log_count = self._storage.get_table_count("memory_log")
        return {"total_log_entries": log_count}

    def _instinct_analysis(self) -> list[dict]:
        instincts = self._storage.get_all_instincts()
        analysis = []
        for inst in instincts:
            fired = inst["fired_count"]
            followed = inst["followed_count"]
            if fired == 0:
                recommendation = "unobserved"
                reliability = 0.0
            else:
                reliability = followed / fired
                if reliability >= 0.7:
                    recommendation = "reliable"
                elif reliability <= 0.3:
                    recommendation = "unreliable"
                elif fired < 3:
                    recommendation = "new"
                else:
                    recommendation = "mixed"

            analysis.append({
                "id": inst["id"],
                "trigger": inst["trigger"],
                "action": inst["action"],
                "fired_count": fired,
                "followed_count": followed,
                "reliability": reliability,
                "recommendation": recommendation,
            })
        return analysis

    def _health_check(self) -> dict:
        episodes = self._storage.get_table_count("episodes")
        semantics = self._storage.get_table_count("semantics")
        instincts = self._storage.get_table_count("instincts")

        compression_ratio = semantics / max(episodes, 1)
        instinct_ratio = instincts / max(semantics, 1)

        return {
            "compression_ratio": round(compression_ratio, 2),
            "instinct_ratio": round(instinct_ratio, 2),
            "status": "healthy" if episodes > 0 else "empty",
        }
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/kplatform/memory/test_reflection.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add kplatform/memory/reflection.py tests/kplatform/memory/test_reflection.py
git commit -m "feat(memory): reflection — self-observation over memory layers"
```

---

### Task 11: Integration Test

**Files:**
- Create: `kairos/tests/kplatform/memory/test_integration.py`

- [ ] **Step 1: Write the integration test**

```python
# tests/kplatform/memory/test_integration.py
"""End-to-end: remember → compress → recall → reflect."""

import uuid
from kplatform.memory.storage import Storage
from kplatform.memory.compress import Compressor
from kplatform.memory.embeddings import NomicEmbedProvider
from kplatform.memory.dedup import Deduplicator
from kplatform.memory.reflection import Reflector
from kplatform.memory.config import MemoryConfig


def test_full_lifecycle(tmp_db):
    """Episodes → compress → semantic → instinct → reflect."""
    cfg = MemoryConfig()
    s = Storage(tmp_db)
    s._create_vec0_tables()
    e = NomicEmbedProvider()
    d = Deduplicator()
    c = Compressor(s, e, cfg, d)
    r = Reflector(s)

    # 1. Remember several related episodes
    for i in range(6):
        eid = str(uuid.uuid4())
        content = f"The user prefers concise responses, iteration {i}"
        emb = e.embed([content])[0]
        s.add_episode(eid, "test-session", content, embedding=emb)

    assert s.get_table_count("episodes") == 6

    # 2. Compress
    result = c.auto_compress()
    assert result["episodes_processed"] > 0
    assert s.get_table_count("semantics") > 0

    # 3. Recall via vector search
    query_emb = e.embed(["concise responses"], prefix="search_query")[0]
    results = s.search_vectors("semantic_vectors", query_emb, k=5)
    assert len(results) > 0

    # 4. Reflect
    reflection = r.reflect()
    assert "usage" in reflection

    # 5. Introspect
    portrait = r.introspect()
    assert portrait["layer_counts"]["episodes"] == 6
    assert portrait["layer_counts"]["semantics"] > 0
    assert portrait["health"]["status"] == "healthy"

    s.close()


def test_instance_isolation(tmp_path):
    """Two instances cannot see each other's episodes."""
    e = NomicEmbedProvider()

    # Instance A
    s_a = Storage(str(tmp_path / "a.db"))
    s_a._create_vec0_tables()
    eid_a = str(uuid.uuid4())
    emb = e.embed(["secret memory for instance A"])[0]
    s_a.add_episode(eid_a, "a-session", "secret memory for instance A", embedding=emb)

    # Instance B
    s_b = Storage(str(tmp_path / "b.db"))
    s_b._create_vec0_tables()

    # B should NOT see A's episode
    assert s_b.get_episode(eid_a) is None
    results = s_b.search_vectors("episode_vectors", emb, k=5)
    assert len(results) == 0

    s_a.close()
    s_b.close()


def test_core_episodes_survive_decay(tmp_db):
    """Core episodes are exempt from decay and pruning."""
    e = NomicEmbedProvider()
    s = Storage(tmp_db)
    s._create_vec0_tables()

    core_id = str(uuid.uuid4())
    regular_id = str(uuid.uuid4())
    emb = e.embed(["test"])[0]

    s.add_episode(core_id, "s1", "formative memory", core=True, embedding=emb)
    s.add_episode(regular_id, "s1", "regular memory", embedding=emb)

    # Decay aggressively
    for _ in range(20):
        s.apply_decay(factor=0.5, min_interval_minutes=0)

    core_ep = s.get_episode(core_id)
    regular_ep = s.get_episode(regular_id)

    assert core_ep["strength"] == 1.0  # Unchanged
    assert regular_ep["strength"] < 0.001  # Heavily decayed

    s.close()
```

- [ ] **Step 2: Run integration tests**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/kplatform/memory/test_integration.py -v`
Expected: All 3 tests PASS

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/kplatform/memory/ -v`
Expected: All tests PASS across all test files

- [ ] **Step 4: Commit**

```bash
git add tests/kplatform/memory/test_integration.py
git commit -m "test(memory): integration tests — lifecycle, isolation, core episodes"
```

---

### Task 12: Update __init__.py and Final Verification

**Files:**
- Modify: `kairos/kplatform/memory/__init__.py`

- [ ] **Step 1: Update __init__.py with all public exports**

```python
# kplatform/memory/__init__.py
"""Three-layer memory: episodes → semantics → instincts."""

from kplatform.memory.storage import Storage
from kplatform.memory.compress import Compressor
from kplatform.memory.embeddings import EmbeddingProvider, NomicEmbedProvider
from kplatform.memory.dedup import Deduplicator
from kplatform.memory.config import MemoryConfig, load_config
from kplatform.memory.federation import SignalBus, InstanceRegistry, sync_genome
from kplatform.memory.reflection import Reflector

__all__ = [
    "Storage",
    "Compressor",
    "EmbeddingProvider",
    "NomicEmbedProvider",
    "Deduplicator",
    "MemoryConfig",
    "load_config",
    "SignalBus",
    "InstanceRegistry",
    "sync_genome",
    "Reflector",
]
```

- [ ] **Step 2: Run full test suite**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/ -v --tb=short`
Expected: All tests PASS

- [ ] **Step 3: Verify import from package**

```bash
cd /Users/kairos/Projects/kairos && uv run python -c "
from kplatform.memory import Storage, Compressor, NomicEmbedProvider, Deduplicator
from kplatform.memory import MemoryConfig, SignalBus, InstanceRegistry, Reflector
print('All imports OK')
"
```
Expected: "All imports OK"

- [ ] **Step 4: Commit**

```bash
git add kplatform/memory/__init__.py
git commit -m "feat(memory): complete platform/memory module with all public exports"
```

---

## Summary

| Task | What | Tests |
|------|------|-------|
| 1 | Monorepo scaffolding | — |
| 2 | Configuration | 4 |
| 3 | Embeddings | 7 |
| 4 | Storage schema + migrations | 6 |
| 5 | Episode CRUD | 9 |
| 6 | Semantic + instinct CRUD | 8 |
| 7 | Dedup | 4 |
| 8 | Compression pipeline | 4 |
| 9 | Federation | 5 |
| 10 | Reflection | 3 |
| 11 | Integration tests | 3 |
| 12 | Final exports + verification | — |
| **Total** | **12 tasks** | **~53 tests** |

## Next Plans

After this plan is complete:
1. **Platform: Bus + Ledger** — unified event bus and hash-chained audit
2. **Platform: LLM + Sandbox** — provider abstraction and capability enforcement
3. **Runtime** — daemon, scheduler, dispatcher
4. **Apps** — atlas, arena, ratchet, governor (can be parallelized)
