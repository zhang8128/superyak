# Distributed Engram Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Federate engram into per-instance databases with a shared genome layer and inter-instance messaging.

**Architecture:** Each repo gets its own SQLite database forked from a shared genome. A signals.db message queue enables async inter-instance conversation. Wake consolidation syncs genome material and processes inbox. Instincts gain session context for modal behavior.

**Tech Stack:** Python 3.12, SQLite + sqlite-vec, FastMCP, pytest

**Spec:** `docs/superpowers/specs/2026-03-21-distributed-engram-design.md`

---

## File Structure

### New files
| File | Responsibility |
|------|---------------|
| `migrations/007_federation.sql` | Add `content_hash` to episodes/semantics/instincts, `context` to instincts |
| `federation.py` | Genome sync, inbox processing, signal sending, instance registry |
| `cli.py` | `engram fork/drop/list` CLI commands |
| `tests/test_federation.py` | All federation tests (genome sync, messaging, inbox processing) |
| `tests/test_cli.py` | CLI command tests |

### Modified files
| File | Changes |
|------|---------|
| `storage.py` | `mark_core(tier=)`, `get_core_episodes()` → `core >= 1`, content_hash on insert |
| `server.py` | `_init()` adds genome sync + inbox, `remember()` gains `genome` param |
| `hooks/wake.py` | Instance identity, inbox count, instinct context filtering |
| `config.py` | `instance`, `session_context`, `signals.retention_days` fields |
| `reflection.py` | `Reflector` gains genome/signals awareness |

---

## Task 1: Migration — content_hash and context columns

**Files:**
- Create: `migrations/007_federation.sql`
- Modify: `storage.py:322-340` (add_episode), `storage.py:520-540` (add_semantic), `storage.py:660-700` (add_instinct)
- Test: `tests/test_federation.py`

- [ ] **Step 1: Write the migration SQL**

```sql
-- migrations/007_federation.sql
ALTER TABLE episodes ADD COLUMN content_hash TEXT;
ALTER TABLE semantics ADD COLUMN content_hash TEXT;
ALTER TABLE instincts ADD COLUMN content_hash TEXT;
ALTER TABLE instincts ADD COLUMN context TEXT;
```

Note: SQLite has no built-in SHA-256, so backfilling existing rows must be done in
Python. Add a post-migration backfill in `storage.py._run_migrations()`: after
applying migration 007, compute and update `content_hash` for all rows where it is
NULL. This runs once on first startup after the migration.

```python
# In _run_migrations, after applying version 7:
if ver == 7:
    self._backfill_content_hashes()

def _backfill_content_hashes(self):
    """One-time backfill of content_hash for pre-federation rows."""
    import hashlib
    for table, col in [("episodes", "content"), ("semantics", "content"), ("instincts", "action")]:
        rows = self.conn.execute(
            f"SELECT id, {col} FROM {table} WHERE content_hash IS NULL"
        ).fetchall()
        for row in rows:
            h = hashlib.sha256(row[col].encode()).hexdigest()
            self.conn.execute(
                f"UPDATE {table} SET content_hash = ? WHERE id = ?", (h, row["id"])
            )
    self.conn.commit()
```

- [ ] **Step 2: Write failing test for content_hash on episode insert**

```python
# tests/test_federation.py
import hashlib
import pytest
from storage import Storage

@pytest.fixture
def store(tmp_path):
    db = tmp_path / "test.db"
    return Storage(str(db))

def test_episode_has_content_hash(store):
    """Episodes should have a SHA-256 content_hash after insert."""
    store.add_episode(
        id="ep1", session_id="s1", content="test episode",
        episode_type="observation",
    )
    store.conn.commit()
    row = store.conn.execute(
        "SELECT content_hash FROM episodes WHERE id = 'ep1'"
    ).fetchone()
    expected = hashlib.sha256("test episode".encode()).hexdigest()
    assert row["content_hash"] == expected
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_federation.py::test_episode_has_content_hash -v`
Expected: FAIL — `content_hash` is NULL

- [ ] **Step 4: Add content_hash computation to `add_episode`**

In `storage.py`, modify `add_episode` to compute and store content_hash:

```python
import hashlib

# Inside add_episode, after the INSERT:
content_hash = hashlib.sha256(content.encode()).hexdigest()
```

Add `content_hash` to the INSERT statement's columns and values.

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_federation.py::test_episode_has_content_hash -v`
Expected: PASS

- [ ] **Step 6: Write failing test for content_hash on semantic insert**

```python
def test_semantic_has_content_hash(store):
    store.add_semantic(
        id="sem1", content="user prefers terse responses",
        kind="preference", confidence=0.7,
        embedding=[0.0] * 768,
        source_episode_ids=[],
    )
    store.conn.commit()
    row = store.conn.execute(
        "SELECT content_hash FROM semantics WHERE id = 'sem1'"
    ).fetchone()
    expected = hashlib.sha256("user prefers terse responses".encode()).hexdigest()
    assert row["content_hash"] == expected
```

- [ ] **Step 7: Add content_hash to `add_semantic`, run test**

Run: `.venv/bin/python -m pytest tests/test_federation.py::test_semantic_has_content_hash -v`
Expected: PASS

- [ ] **Step 8: Write failing test for content_hash on instinct insert + context column**

```python
def test_instinct_has_content_hash_and_context(store):
    store.add_instinct(
        id="inst1", trigger="preference",
        action="be terse", strength=0.5,
        source_semantic_ids=[],
    )
    store.conn.commit()
    row = store.conn.execute(
        "SELECT content_hash, context FROM instincts WHERE id = 'inst1'"
    ).fetchone()
    expected = hashlib.sha256("be terse".encode()).hexdigest()
    assert row["content_hash"] == expected
    assert row["context"] is None  # default
```

- [ ] **Step 9: Add content_hash to `create_instinct`, run test**

Run: `.venv/bin/python -m pytest tests/test_federation.py::test_instinct_has_content_hash_and_context -v`
Expected: PASS

- [ ] **Step 10: Run full test suite to verify no regressions**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All 129+ tests pass

- [ ] **Step 11: Commit**

```bash
git add migrations/007_federation.sql storage.py tests/test_federation.py
git commit -m "feat: add content_hash and context columns for federation"
```

---

## Task 2: Core tiers — mark_core(tier=) and get_core_episodes update

**Files:**
- Modify: `storage.py:470-497` (mark_core, mark_core_batch, get_core_episodes)
- Test: `tests/test_federation.py`

- [ ] **Step 1: Write failing test for mark_core with tier**

```python
def test_mark_core_with_tier(store):
    """mark_core should accept a tier parameter (1=local, 2=genome)."""
    store.add_episode(id="ep1", session_id="s1", content="local core",
                      episode_type="observation")
    store.add_episode(id="ep2", session_id="s1", content="genome core",
                      episode_type="observation")
    store.conn.commit()

    store.mark_core("ep1")          # default tier=1
    store.mark_core("ep2", tier=2)  # genome core
    store.conn.commit()

    row1 = store.conn.execute("SELECT core FROM episodes WHERE id='ep1'").fetchone()
    row2 = store.conn.execute("SELECT core FROM episodes WHERE id='ep2'").fetchone()
    assert row1["core"] == 1
    assert row2["core"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_federation.py::test_mark_core_with_tier -v`
Expected: FAIL — `mark_core() got unexpected keyword argument 'tier'`

- [ ] **Step 3: Update mark_core to accept tier parameter**

```python
def mark_core(self, episode_id: str, tier: int = 1) -> None:
    """Mark an episode as core. tier=1 for local core, tier=2 for genome core."""
    self.conn.execute(
        "UPDATE episodes SET core = ?, decay_strength = 1.0 WHERE id = ?",
        (tier, episode_id),
    )
    self.conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_federation.py::test_mark_core_with_tier -v`
Expected: PASS

- [ ] **Step 5: Write failing test for get_core_episodes capturing both tiers**

```python
def test_get_core_episodes_both_tiers(store):
    """get_core_episodes should return both local-core and genome-core."""
    store.add_episode(id="ep1", session_id="s1", content="local",
                      episode_type="observation")
    store.add_episode(id="ep2", session_id="s1", content="genome",
                      episode_type="observation")
    store.conn.commit()
    store.mark_core("ep1", tier=1)
    store.mark_core("ep2", tier=2)
    store.conn.commit()

    cores = store.get_core_episodes()
    assert len(cores) == 2
    ids = {c["id"] for c in cores}
    assert ids == {"ep1", "ep2"}
```

- [ ] **Step 6: Update get_core_episodes to use `core >= 1`**

```python
def get_core_episodes(self) -> list[dict]:
    rows = self.conn.execute(
        "SELECT id, content, source, created_at FROM episodes WHERE core >= 1 "
        "ORDER BY created_at"
    ).fetchall()
    return [{"id": r[0], "content": r[1], "source": r[2], "created_at": r[3]} for r in rows]
```

- [ ] **Step 7: Run test, then full suite**

Run: `.venv/bin/python -m pytest tests/test_federation.py::test_get_core_episodes_both_tiers -v`
Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add storage.py tests/test_federation.py
git commit -m "feat: core tiers — mark_core(tier=) and get_core_episodes captures both tiers"
```

---

## Task 3: Config — instance, session_context, signals settings

**Files:**
- Modify: `config.py`
- Test: `tests/test_config.py` (add cases)

- [ ] **Step 1: Write failing test for new config fields**

```python
# Add to tests/test_config.py
def test_federation_config_defaults(tmp_path):
    """Federation config fields should have sensible defaults."""
    config = load_config(tmp_path)
    assert config.instance is None
    assert config.session_context is None
    assert config.signals.retention_days == 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_config.py::test_federation_config_defaults -v`
Expected: FAIL — `EngramConfig` has no `instance` attribute

- [ ] **Step 3: Add federation fields to config.py**

```python
@dataclass
class SignalsConfig:
    retention_days: int = 30

@dataclass
class EngramConfig:
    # ... existing fields ...
    signals: SignalsConfig = field(default_factory=SignalsConfig)
    instance: str | None = None
    session_context: str | None = None
```

Update `_DEFAULT_TOML` to include:

```toml
[signals]
retention_days = 30
```

Update `load_config` to parse the new fields:

```python
signals=SignalsConfig(**raw.get("signals", {})),
instance=raw.get("instance"),
session_context=raw.get("session_context"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_config.py::test_federation_config_defaults -v`
Expected: PASS

- [ ] **Step 5: Write test for config with explicit instance**

```python
def test_federation_config_with_instance(tmp_path):
    config_dir = tmp_path / ".engram"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        '[signals]\nretention_days = 60\n\ninstance = "agi"\nsession_context = "building"\n'
    )
    config = load_config(tmp_path)
    assert config.instance == "agi"
    assert config.session_context == "building"
    assert config.signals.retention_days == 60
```

- [ ] **Step 6: Run test, then full suite**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: add federation config — instance, session_context, signals"
```

---

## Task 4: Federation module — signals.db and instance registry

**Files:**
- Create: `federation.py`
- Test: `tests/test_federation.py` (extend)

- [ ] **Step 1: Write failing test for signals.db creation**

```python
def test_signals_db_creation(tmp_path):
    """SignalBus should create signals.db with messages table."""
    from federation import SignalBus
    bus = SignalBus(tmp_path / "signals.db")
    # Should be able to insert a message
    bus.send("agi", None, "instinct_formed", "be terse")
    messages = bus.inbox("blocks")
    assert len(messages) == 1
    assert messages[0]["from_instance"] == "agi"
    assert messages[0]["type"] == "instinct_formed"
    bus.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_federation.py::test_signals_db_creation -v`
Expected: FAIL — `No module named 'federation'`

- [ ] **Step 3: Implement SignalBus class**

```python
# federation.py
"""Engram federation — genome sync, inter-instance messaging, instance registry."""

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

ENGRAM_ROOT = Path(os.environ.get("ENGRAM_HOME", Path.home() / "Projects" / "engram"))
ENGRAM_DIR = ENGRAM_ROOT / ".engram"

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SignalBus:
    """Append-only message queue backed by a shared SQLite database."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=10000")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._create_schema()

    def _create_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                from_instance TEXT NOT NULL,
                to_instance TEXT,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                in_reply_to TEXT,
                content_hash TEXT,
                seen_by TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_to ON messages(to_instance);
            CREATE INDEX IF NOT EXISTS idx_messages_type ON messages(type);
            CREATE INDEX IF NOT EXISTS idx_messages_reply ON messages(in_reply_to);
        """)

    def send(self, from_instance: str, to_instance: str | None,
             msg_type: str, content: str, in_reply_to: str | None = None) -> str:
        """Send a message. to_instance=None for broadcast. Returns message id."""
        msg_id = str(uuid.uuid4())
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        self.conn.execute(
            "INSERT INTO messages (id, from_instance, to_instance, type, content, "
            "in_reply_to, content_hash, seen_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, '{}', ?)",
            (msg_id, from_instance, to_instance, msg_type, content,
             in_reply_to, content_hash, _now_iso()),
        )
        self.conn.commit()
        return msg_id

    def inbox(self, instance: str) -> list[dict]:
        """Get unseen messages for this instance (directed or broadcast).
        Excludes messages from self (broadcasts shouldn't echo back)."""
        rows = self.conn.execute(
            "SELECT * FROM messages "
            "WHERE (to_instance = ? OR to_instance IS NULL) "
            "AND from_instance != ? "
            "AND seen_by NOT LIKE ? "
            "ORDER BY created_at",
            (instance, instance, f'%"{instance}"%'),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_seen(self, message_id: str, instance: str) -> None:
        """Mark a message as seen by an instance."""
        row = self.conn.execute(
            "SELECT seen_by FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
        if not row:
            return
        seen = json.loads(row["seen_by"])
        seen[instance] = _now_iso()
        self.conn.execute(
            "UPDATE messages SET seen_by = ? WHERE id = ?",
            (json.dumps(seen), message_id),
        )
        self.conn.commit()

    def archive_old(self, retention_days: int = 30) -> int:
        """Remove content from fully-processed messages older than retention_days."""
        cutoff = datetime.now(timezone.utc).isoformat()
        # For now, just delete old fully-seen messages
        cursor = self.conn.execute(
            "DELETE FROM messages WHERE created_at < datetime(?, '-' || ? || ' days') "
            "AND seen_by != '{}'",
            (cutoff, retention_days),
        )
        self.conn.commit()
        return cursor.rowcount

    def close(self):
        self.conn.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_federation.py::test_signals_db_creation -v`
Expected: PASS

- [ ] **Step 5: Write test for broadcast vs directed messaging**

```python
def test_broadcast_vs_directed(tmp_path):
    from federation import SignalBus
    bus = SignalBus(tmp_path / "signals.db")

    bus.send("agi", None, "semantic_promoted", "broadcast message")
    bus.send("agi", "blocks", "query", "directed to blocks")
    bus.send("agi", "why", "query", "directed to why")

    blocks_inbox = bus.inbox("blocks")
    why_inbox = bus.inbox("why")
    engram_inbox = bus.inbox("engram")

    # blocks gets broadcast + its directed message
    assert len(blocks_inbox) == 2
    # why gets broadcast + its directed message
    assert len(why_inbox) == 2
    # engram gets only the broadcast
    assert len(engram_inbox) == 1
    bus.close()
```

- [ ] **Step 6: Run test**

Run: `.venv/bin/python -m pytest tests/test_federation.py::test_broadcast_vs_directed -v`
Expected: PASS

- [ ] **Step 7: Write test for mark_seen and threading**

```python
def test_mark_seen_and_threading(tmp_path):
    from federation import SignalBus
    bus = SignalBus(tmp_path / "signals.db")

    msg_id = bus.send("agi", None, "instinct_formed", "be terse")
    bus.mark_seen(msg_id, "blocks")

    # blocks should no longer see it
    assert len(bus.inbox("blocks")) == 0
    # why hasn't seen it yet
    assert len(bus.inbox("why")) == 1

    # Reply threading
    reply_id = bus.send("why", "agi", "reply", "noted", in_reply_to=msg_id)
    agi_inbox = bus.inbox("agi")
    assert len(agi_inbox) == 1
    assert agi_inbox[0]["in_reply_to"] == msg_id
    bus.close()
```

- [ ] **Step 8: Run test, then full suite**

Run: `.venv/bin/python -m pytest tests/test_federation.py -v`
Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 9: Commit**

```bash
git add federation.py tests/test_federation.py
git commit -m "feat: SignalBus — inter-instance message queue with broadcast and threading"
```

---

## Task 5: Federation module — instance registry

**Files:**
- Modify: `federation.py`
- Test: `tests/test_federation.py`

- [ ] **Step 1: Write failing test for instance registry**

```python
def test_instance_registry(tmp_path):
    from federation import InstanceRegistry
    reg = InstanceRegistry(tmp_path / "instances.json")

    reg.register("agi", tmp_path / "agi" / "graph.db", forked_from="genome")
    reg.register("blocks", tmp_path / "blocks" / "graph.db", forked_from="genome")

    instances = reg.list()
    assert "agi" in instances
    assert "blocks" in instances
    assert instances["agi"]["forked_from"] == "genome"

    reg.remove("blocks")
    assert "blocks" not in reg.list()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_federation.py::test_instance_registry -v`
Expected: FAIL — `cannot import name 'InstanceRegistry'`

- [ ] **Step 3: Implement InstanceRegistry**

```python
class InstanceRegistry:
    """Manages ~/.engram/instances.json with atomic writes."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {}

    def _save(self):
        """Atomic write — temp file + rename."""
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        tmp.rename(self.path)

    def register(self, name: str, db_path: Path, forked_from: str) -> None:
        self._data[name] = {
            "path": str(db_path),
            "forked_from": forked_from,
            "forked_at": _now_iso(),
        }
        self._save()

    def remove(self, name: str) -> None:
        self._data.pop(name, None)
        self._save()

    def list(self) -> dict:
        return dict(self._data)

    def get(self, name: str) -> dict | None:
        return self._data.get(name)
```

- [ ] **Step 4: Run test**

Run: `.venv/bin/python -m pytest tests/test_federation.py::test_instance_registry -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add federation.py tests/test_federation.py
git commit -m "feat: InstanceRegistry — atomic JSON-backed instance tracking"
```

---

## Task 6: Federation module — genome sync

**Files:**
- Modify: `federation.py`
- Test: `tests/test_federation.py`

- [ ] **Step 1: Write failing test for genome sync**

```python
def test_genome_sync(tmp_path):
    """sync_genome should pull new genome-core episodes into local instance."""
    from federation import sync_genome
    from storage import Storage

    # Set up genome DB with a genome-core episode
    genome_dir = tmp_path / "genome"
    genome_dir.mkdir()
    genome = Storage(str(genome_dir / "graph.db"))
    genome.add_episode(
        id="gep1", session_id="s1", content="user is a mathematician",
        episode_type="observation",
    )
    genome.mark_core("gep1", tier=2)
    genome.conn.commit()

    # Set up instance DB — empty
    inst_dir = tmp_path / "instance"
    inst_dir.mkdir()
    instance = Storage(str(inst_dir / "graph.db"))

    # Sync
    synced = sync_genome(genome_path=str(genome_dir / "graph.db"), instance_storage=instance)

    assert synced == 1
    # Episode should exist locally with core=2
    row = instance.conn.execute(
        "SELECT core, content FROM episodes WHERE content_hash = ?",
        (hashlib.sha256("user is a mathematician".encode()).hexdigest(),)
    ).fetchone()
    assert row is not None
    assert row["core"] == 2

    # Second sync should be idempotent
    synced2 = sync_genome(genome_path=str(genome_dir / "graph.db"), instance_storage=instance)
    assert synced2 == 0

    genome.close()
    instance.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_federation.py::test_genome_sync -v`
Expected: FAIL — `cannot import name 'sync_genome'`

- [ ] **Step 3: Implement sync_genome**

```python
def sync_genome(genome_path: str, instance_storage) -> int:
    """Pull genome-core episodes not yet present in instance. Returns count synced.

    Note: Synced episodes are inserted without embeddings. The existing
    backfill_vectors step in server.py _init() runs after sync_genome and
    will embed any orphaned episodes (those without vectors).
    """
    import sqlite3 as _sqlite3
    genome_conn = _sqlite3.connect(genome_path)
    genome_conn.row_factory = _sqlite3.Row

    # Get all genome-core episode hashes from genome
    genome_rows = genome_conn.execute(
        "SELECT id, content, content_hash, source, created_at "
        "FROM episodes WHERE core >= 2"
    ).fetchall()

    synced = 0
    for row in genome_rows:
        # Check if already present locally by content_hash
        existing = instance_storage.conn.execute(
            "SELECT 1 FROM episodes WHERE content_hash = ?",
            (row["content_hash"],)
        ).fetchone()
        if existing:
            continue

        # Insert with a new local ID but same content
        import uuid as _uuid
        local_id = str(_uuid.uuid4())
        instance_storage.add_episode(
            id=local_id, session_id=None,
            content=row["content"], episode_type="genome_sync",
        )
        instance_storage.mark_core(local_id, tier=2)
        if row["source"]:
            instance_storage.set_episode_source(local_id, row["source"])
        synced += 1

    instance_storage.conn.commit()
    genome_conn.close()
    return synced
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_federation.py::test_genome_sync -v`
Expected: PASS

- [ ] **Step 5: Run full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add federation.py tests/test_federation.py
git commit -m "feat: sync_genome — pull genome-core episodes into instance"
```

---

## Task 7: Federation module — inbox processing

**Files:**
- Modify: `federation.py`
- Test: `tests/test_federation.py`

- [ ] **Step 1: Write failing test for inbox processing**

```python
def test_process_inbox(tmp_path):
    """process_inbox should store signal messages as local episodes with source tag."""
    from federation import SignalBus, process_inbox
    from storage import Storage

    bus = SignalBus(tmp_path / "signals.db")
    bus.send("agi", "blocks", "instinct_formed", "prefer simple decomposition")
    bus.send("why", None, "semantic_promoted", "governance tick runs weekly")

    inst = Storage(str(tmp_path / "graph.db"))
    processed = process_inbox(bus, "blocks", inst)

    assert processed == 2  # 1 directed + 1 broadcast

    # Check episodes were created with source tags
    rows = inst.conn.execute(
        "SELECT content, source FROM episodes WHERE source LIKE 'signal/%'"
    ).fetchall()
    assert len(rows) == 2
    sources = {r["source"] for r in rows}
    assert "signal/agi" in sources
    assert "signal/why" in sources

    # Inbox should now be empty
    assert len(bus.inbox("blocks")) == 0

    bus.close()
    inst.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_federation.py::test_process_inbox -v`
Expected: FAIL — `cannot import name 'process_inbox'`

- [ ] **Step 3: Implement process_inbox**

```python
def process_inbox(bus: SignalBus, instance_name: str, storage) -> int:
    """Process unseen messages for this instance. Returns count processed."""
    import uuid as _uuid
    messages = bus.inbox(instance_name)
    processed = 0

    for msg in messages:
        # Store as local episode with signal provenance
        ep_id = str(_uuid.uuid4())
        source_tag = f"signal/{msg['from_instance']}"
        content = f"[{msg['type']}] {msg['content']}"

        storage.add_episode(
            id=ep_id, session_id=None,
            content=content, episode_type="signal",
        )
        storage.set_episode_source(ep_id, source_tag)
        bus.mark_seen(msg["id"], instance_name)
        processed += 1

    storage.conn.commit()
    return processed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_federation.py::test_process_inbox -v`
Expected: PASS

- [ ] **Step 5: Run full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add federation.py tests/test_federation.py
git commit -m "feat: process_inbox — ingest inter-instance signals as episodes"
```

---

## Task 8: Server integration — genome and inbox in init sequence

**Files:**
- Modify: `server.py:37-140` (_init function), `server.py:155-195` (remember tool)
- Test: `tests/test_server.py` (add federation cases)

- [ ] **Step 1: Write failing test for federated remember with genome=True**

```python
# Add to tests/test_server.py or tests/test_federation.py
def test_remember_genome_writes_to_both(tmp_path, monkeypatch):
    """remember(genome=True) should write to both instance and genome DBs."""
    import server

    genome_dir = tmp_path / "genome"
    genome_dir.mkdir(parents=True)
    # Initialize genome DB
    from storage import Storage
    genome = Storage(str(genome_dir / "graph.db"))
    genome.close()

    monkeypatch.setattr(server, "GENOME_DB_PATH", genome_dir / "graph.db")
    # ... call remember with genome=True, verify both DBs have the episode
```

Note: The exact test shape depends on how server.py exposes the genome path. The implementation should:

1. Add module-level globals to server.py (alongside `_storage`, `_session_id`, etc.):
   ```python
   _instance_name = None
   _genome_db_path = None
   _signals_db_path = None
   ```
2. In `_init()`, set these globals when federation config is present.
3. In the `remember` tool, when `genome=True`:
   - Write to local DB as `core=2`
   - Open a short-lived `Storage` against genome DB, write there too, close it
   - Send a `genome_updated` signal via SignalBus

- [ ] **Step 2: Implement genome=True in remember tool**

Add to the `remember` function in `server.py`:

```python
# Note: remember() stays synchronous (def, not async) to match existing server.py pattern.
# context= is episode metadata, NOT session_context (which is a config field).
@mcp.tool()
def remember(
    content: str,
    context: dict | None = None,
    core: bool = False,
    genome: bool = False,
    source: str | None = None,
) -> dict:
    # ... existing code ...
    if genome:
        _storage.mark_core(episode_id, tier=2)
        # Write to genome DB
        from federation import write_to_genome, SignalBus
        if _genome_db_path:
            write_to_genome(_genome_db_path, content, source)
        # Signal other instances
        if _instance_name and _signals_db_path:
            bus = SignalBus(_signals_db_path)
            bus.send(_instance_name, None, "genome_updated", content)
            bus.close()
    elif core:
        _storage.mark_core(episode_id, tier=1)
```

- [ ] **Step 3: Add genome sync and inbox processing to _init()**

In `server.py._init()`, before the existing decay/prune sequence, add:

```python
# Federation: genome sync + inbox processing
global _instance_name, _genome_db_path, _signals_db_path
if _config and _config.instance:
    _instance_name = _config.instance
    _genome_db_path = ENGRAM_DIR / "genome" / "graph.db"
    _signals_db_path = ENGRAM_DIR / "signals.db"
    try:
        from federation import sync_genome, process_inbox, SignalBus

        if _genome_db_path.exists():
            synced = sync_genome(str(_genome_db_path), _storage)
            if synced:
                logger.info("Synced %d genome items", synced)

        if _signals_db_path.exists():
            bus = SignalBus(_signals_db_path)
            processed = process_inbox(bus, _instance_name, _storage)
            if processed:
                logger.info("Processed %d inbox messages", processed)
            bus.close()
    except Exception:
        logger.warning("Federation sync failed — continuing without", exc_info=True)
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_server.py -v`
Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 5: Update server.py status() and mark_core tool**

In `server.py`, update the `status()` tool's core count query from `WHERE core = 1`
to `WHERE core >= 1`. Also update the `mark_core` MCP tool to accept an optional
`tier: int = 1` parameter and pass it to `_storage.mark_core(episode_id, tier=tier)`.

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/test_server.py -v`
Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: integrate genome sync and inbox processing into server init"
```

---

## Task 9: CLI — engram fork/drop/list

**Files:**
- Create: `cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing test for fork command**

```python
# tests/test_cli.py
import subprocess
import sys
from pathlib import Path

def test_fork_creates_instance(tmp_path, monkeypatch):
    from federation import InstanceRegistry
    from cli import fork_instance
    from storage import Storage

    engram_dir = tmp_path / ".engram"
    engram_dir.mkdir()

    # Create a genome DB
    genome_dir = engram_dir / "genome"
    genome_dir.mkdir()
    genome = Storage(str(genome_dir / "graph.db"))
    genome.add_episode(
        id="gep1", session_id="s1", content="shared knowledge",
        episode_type="observation",
    )
    genome.mark_core("gep1", tier=2)
    genome.conn.commit()
    genome.close()

    # Fork
    fork_instance("agi", engram_dir)

    # Verify instance DB exists and has the genome episode
    inst_db = engram_dir / "instances" / "agi" / "graph.db"
    assert inst_db.exists()

    inst = Storage(str(inst_db))
    cores = inst.get_core_episodes()
    assert len(cores) == 1
    assert cores[0]["content"] == "shared knowledge"
    inst.close()

    # Verify registry
    reg = InstanceRegistry(engram_dir / "instances.json")
    assert "agi" in reg.list()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli.py::test_fork_creates_instance -v`
Expected: FAIL — `No module named 'cli'`

- [ ] **Step 3: Implement cli.py**

```python
# cli.py
"""Engram CLI — administrative commands for federation."""

import argparse
import shutil
import sys
from pathlib import Path

from federation import InstanceRegistry

ENGRAM_DIR = Path.home() / ".engram"


def fork_instance(name: str, engram_dir: Path | None = None):
    """Fork a new instance from the genome."""
    if engram_dir is None:
        engram_dir = ENGRAM_DIR
    genome_db = engram_dir / "genome" / "graph.db"
    if not genome_db.exists():
        print(f"Error: genome database not found at {genome_db}", file=sys.stderr)
        sys.exit(1)

    inst_dir = engram_dir / "instances" / name
    inst_dir.mkdir(parents=True, exist_ok=True)
    inst_db = inst_dir / "graph.db"

    if inst_db.exists():
        print(f"Error: instance '{name}' already exists at {inst_db}", file=sys.stderr)
        sys.exit(1)

    # Safe copy via SQLite backup API (handles WAL correctly)
    import sqlite3
    src = sqlite3.connect(str(genome_db))
    dst = sqlite3.connect(str(inst_db))
    src.backup(dst)
    src.close()
    dst.close()

    # Register
    reg = InstanceRegistry(engram_dir / "instances.json")
    reg.register(name, inst_db, forked_from="genome")
    print(f"Forked instance '{name}' from genome → {inst_db}")


def drop_instance(name: str, engram_dir: Path | None = None):
    """Remove an instance and clean up signals."""
    if engram_dir is None:
        engram_dir = ENGRAM_DIR

    reg = InstanceRegistry(engram_dir / "instances.json")
    info = reg.get(name)
    if not info:
        print(f"Error: instance '{name}' not found", file=sys.stderr)
        sys.exit(1)

    # Remove database directory
    inst_dir = engram_dir / "instances" / name
    if inst_dir.exists():
        shutil.rmtree(inst_dir)

    # Clean up signals.db — remove dropped instance from seen_by tracking
    signals_db = engram_dir / "signals.db"
    if signals_db.exists():
        from federation import SignalBus
        bus = SignalBus(signals_db)
        # Remove instance from seen_by on all messages
        rows = bus.conn.execute("SELECT id, seen_by FROM messages").fetchall()
        for row in rows:
            seen = json.loads(row["seen_by"])
            if name in seen:
                del seen[name]
                bus.conn.execute(
                    "UPDATE messages SET seen_by = ? WHERE id = ?",
                    (json.dumps(seen), row["id"])
                )
        bus.conn.commit()
        bus.close()

    # Unregister
    reg.remove(name)
    print(f"Dropped instance '{name}'")


def list_instances(engram_dir: Path | None = None):
    """List all registered instances."""
    if engram_dir is None:
        engram_dir = ENGRAM_DIR

    reg = InstanceRegistry(engram_dir / "instances.json")
    instances = reg.list()
    if not instances:
        print("No instances registered.")
        return

    for name, info in instances.items():
        print(f"  {name}: forked from {info['forked_from']} at {info['forked_at']}")


def main():
    parser = argparse.ArgumentParser(prog="engram", description="Engram federation CLI")
    sub = parser.add_subparsers(dest="command")

    fork_p = sub.add_parser("fork", help="Fork a new instance from genome or another instance")
    fork_p.add_argument("name", help="Instance name")
    fork_p.add_argument("--from", dest="from_source", default="genome",
                        help="Source to fork from: 'genome' (default) or another instance name")

    drop_p = sub.add_parser("drop", help="Remove an instance")
    drop_p.add_argument("name", help="Instance name")

    sub.add_parser("list", help="List all instances")

    args = parser.parse_args()
    if args.command == "fork":
        fork_instance(args.name)
    elif args.command == "drop":
        drop_instance(args.name)
    elif args.command == "list":
        list_instances()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_cli.py::test_fork_creates_instance -v`
Expected: PASS

- [ ] **Step 5: Write test for drop**

```python
def test_drop_removes_instance(tmp_path):
    from cli import fork_instance, drop_instance
    from federation import InstanceRegistry
    from storage import Storage

    engram_dir = tmp_path / ".engram"
    engram_dir.mkdir()
    genome_dir = engram_dir / "genome"
    genome_dir.mkdir()
    Storage(str(genome_dir / "graph.db")).close()

    fork_instance("agi", engram_dir)
    assert (engram_dir / "instances" / "agi" / "graph.db").exists()

    drop_instance("agi", engram_dir)
    assert not (engram_dir / "instances" / "agi").exists()
    assert "agi" not in InstanceRegistry(engram_dir / "instances.json").list()
```

- [ ] **Step 6: Run test, then full suite**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add cli.py tests/test_cli.py
git commit -m "feat: engram CLI — fork, drop, list commands"
```

---

## Task 10: Wake hook — instance identity, inbox count, context filtering

**Files:**
- Modify: `hooks/wake.py`
- Test: `tests/test_wake.py` (add federation cases)

- [ ] **Step 1: Write failing test for federated wake output**

```python
# Add to tests/test_wake.py
def test_wake_shows_instance_identity(tmp_path):
    """Wake hook should show instance name when configured."""
    # Set up a DB with instance config
    db = tmp_path / "graph.db"
    conn = sqlite3.connect(str(db))
    # ... set up schema, instincts, config with instance="agi" ...
    # The wake output should contain "Engram (agi)"
```

- [ ] **Step 2: Modify wake.py to read instance config and show identity**

Key changes to `hooks/wake.py`:

1. Read `config.toml` to get `instance` and `session_context`
2. Change header: `"# Engram (agi) — Memory Orientation"` when instance is set
3. Filter instincts by session_context: load `NULL` context + matching context instincts
4. Read signals.db inbox count and display: `"📬 3 unread signals"`

```python
# In wake.py, read instance config from the PROJECT root (CWD), not ENGRAM_HOME.
# The instance binding lives in each repo's .engram/config.toml.
config_path = Path.cwd() / ".engram" / "config.toml"
instance_name = None
session_context = None
if config_path.exists():
    import tomllib
    with open(config_path, "rb") as f:
        config = tomllib.load(f)
    instance_name = config.get("instance")
    session_context = config.get("session_context")

# Header
if instance_name:
    lines.append(f"# Engram ({instance_name}) — Memory Orientation")
else:
    lines.append("# Engram — Memory Orientation")

# Instinct filtering by session_context
if session_context:
    instincts = conn.execute(
        "SELECT id, trigger, action, strength, fired_count, followed_count "
        "FROM instincts WHERE strength > 0.1 "
        "AND (context IS NULL OR context = ?) "
        "ORDER BY strength DESC LIMIT 15",
        (session_context,)
    ).fetchall()

# Inbox count
if instance_name:
    signals_db = ENGRAM_HOME / ".engram" / "signals.db"
    if signals_db.exists():
        sig_conn = sqlite3.connect(str(signals_db))
        unread = sig_conn.execute(
            "SELECT COUNT(*) FROM messages "
            "WHERE (to_instance = ? OR to_instance IS NULL) "
            "AND seen_by NOT LIKE ?",
            (instance_name, f'%"{instance_name}"%')
        ).fetchone()[0]
        sig_conn.close()
        if unread > 0:
            lines.append(f"\n📬 {unread} unread signal(s)")
```

- [ ] **Step 3: Run tests**

Run: `.venv/bin/python -m pytest tests/test_wake.py -v`
Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add hooks/wake.py tests/test_wake.py
git commit -m "feat: wake hook — instance identity, inbox count, context filtering"
```

---

## Task 11: Reflection — genome drift and signal health awareness

**Files:**
- Modify: `reflection.py`
- Test: `tests/test_reflection.py` (add federation cases)

- [ ] **Step 1: Write failing test for genome drift detection**

```python
# Add to tests/test_reflection.py
def test_reflect_detects_genome_drift(tmp_path):
    """Reflector should detect contradictions between local and genome instincts."""
    from reflection import Reflector
    from storage import Storage

    store = Storage(str(tmp_path / "graph.db"))
    # Create a local instinct
    store.add_instinct(
        id="local1", trigger="preference",
        action="prefer complex decomposition", strength=0.7,
        source_semantic_ids=[],
    )
    store.conn.commit()

    # Create genome DB with contradicting instinct
    genome_dir = tmp_path / "genome"
    genome_dir.mkdir()
    genome = Storage(str(genome_dir / "graph.db"))
    genome.add_instinct(
        id="genome1", trigger="preference",
        action="prefer simple approaches", strength=0.6,
        source_semantic_ids=[],
    )
    genome.conn.commit()

    reflector = Reflector(store, genome_db_path=str(genome_dir / "graph.db"))
    drift = reflector.detect_genome_drift()
    assert len(drift) > 0  # Should find at least one potential contradiction
    genome.close()
    store.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reflection.py::test_reflect_detects_genome_drift -v`
Expected: FAIL — `Reflector() got unexpected keyword argument 'genome_db_path'`

- [ ] **Step 3: Update Reflector to accept genome_db_path and signals_db_path**

```python
class Reflector:
    def __init__(self, storage, staleness_days=30,
                 genome_db_path: str | None = None,
                 signals_db_path: str | None = None):
        self._storage = storage
        self._staleness_days = staleness_days
        self._genome_db_path = genome_db_path
        self._signals_db_path = signals_db_path

    def detect_genome_drift(self) -> list[dict]:
        """Compare local instincts against genome instincts. Returns drift observations."""
        if not self._genome_db_path:
            return []
        import sqlite3
        genome_conn = sqlite3.connect(self._genome_db_path)
        genome_conn.row_factory = sqlite3.Row
        genome_instincts = genome_conn.execute(
            "SELECT action, strength FROM instincts WHERE strength > 0.1"
        ).fetchall()
        local_instincts = self._storage.get_all_instincts()
        genome_conn.close()

        drift = []
        for gi in genome_instincts:
            for li in local_instincts:
                # Simple keyword overlap check for contradiction detection
                # (embedding-based comparison is a future enhancement)
                g_words = set(gi["action"].lower().split())
                l_words = set(li["action"].lower().split())
                overlap = g_words & l_words
                if len(overlap) > 2 and gi["action"] != li["action"]:
                    drift.append({
                        "type": "potential_drift",
                        "genome_instinct": gi["action"],
                        "genome_strength": gi["strength"],
                        "local_instinct": li["action"],
                        "local_strength": li["strength"],
                    })
        return drift

    def signal_health(self) -> dict | None:
        """Analyze signal responsiveness for this instance."""
        if not self._signals_db_path:
            return None
        # Read signal stats from signals.db
        import sqlite3
        conn = sqlite3.connect(self._signals_db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        conn.close()
        return {"total_messages": total}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_reflection.py::test_reflect_detects_genome_drift -v`
Expected: PASS

- [ ] **Step 5: Update server.py to pass genome/signals paths to Reflector**

In `server.py._init()`, when creating the Reflector:

```python
_reflector = Reflector(
    _storage,
    _config.reflection.staleness_days if _config else 30,
    genome_db_path=str(GENOME_DB_PATH) if GENOME_DB_PATH.exists() else None,
    signals_db_path=str(SIGNALS_DB_PATH) if SIGNALS_DB_PATH.exists() else None,
)
```

- [ ] **Step 6: Run full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add reflection.py server.py tests/test_reflection.py
git commit -m "feat: reflect gains genome drift detection and signal health"
```

---

## Task 12: Integration test — full federation lifecycle

**Files:**
- Modify: `tests/test_federation.py`

- [ ] **Step 1: Write end-to-end federation test**

```python
def test_full_federation_lifecycle(tmp_path):
    """End-to-end: create genome → fork instances → remember with genome=True →
    sync → send signals → process inbox → verify drift detection."""
    from storage import Storage
    from federation import SignalBus, InstanceRegistry, sync_genome, process_inbox
    from cli import fork_instance

    engram_dir = tmp_path / ".engram"
    engram_dir.mkdir()

    # 1. Create genome with initial knowledge
    genome_dir = engram_dir / "genome"
    genome_dir.mkdir()
    genome = Storage(str(genome_dir / "graph.db"))
    genome.add_episode(
        id="gep1", session_id="s1", content="user is a mathematician in healthcare",
        episode_type="observation",
    )
    genome.mark_core("gep1", tier=2)
    genome.conn.commit()
    genome.close()

    # 2. Fork two instances
    fork_instance("agi", engram_dir)
    fork_instance("blocks", engram_dir)

    # 3. Both instances should have the genome episode
    agi = Storage(str(engram_dir / "instances" / "agi" / "graph.db"))
    blocks = Storage(str(engram_dir / "instances" / "blocks" / "graph.db"))
    assert len(agi.get_core_episodes()) == 1
    assert len(blocks.get_core_episodes()) == 1

    # 4. Add local knowledge to agi (not shared)
    agi.add_episode(
        id="aep1", session_id="s2", content="arena fitness improves with diversity",
        episode_type="observation",
    )
    agi.conn.commit()

    # 5. Send signal from agi to blocks
    bus = SignalBus(engram_dir / "signals.db")
    bus.send("agi", "blocks", "instinct_formed", "prefer diverse strategy selection")

    # 6. Process blocks inbox
    processed = process_inbox(bus, "blocks", blocks)
    assert processed == 1

    # 7. Blocks should have the signal as a local episode
    signal_eps = blocks.conn.execute(
        "SELECT content, source FROM episodes WHERE source LIKE 'signal/%'"
    ).fetchall()
    assert len(signal_eps) == 1
    assert signal_eps[0]["source"] == "signal/agi"

    # 8. Agi's local episode should NOT be in blocks
    agi_only = blocks.conn.execute(
        "SELECT 1 FROM episodes WHERE content = 'arena fitness improves with diversity'"
    ).fetchone()
    assert agi_only is None

    # 9. Add new genome-core episode
    genome2 = Storage(str(genome_dir / "graph.db"))
    genome2.add_episode(
        id="gep2", session_id="s3", content="system goal is bridging digital and biological",
        episode_type="observation",
    )
    genome2.mark_core("gep2", tier=2)
    genome2.conn.commit()
    genome2.close()

    # 10. Sync agi — should pick up new genome episode
    synced = sync_genome(str(genome_dir / "graph.db"), agi)
    assert synced == 1
    assert len(agi.get_core_episodes()) == 2

    bus.close()
    agi.close()
    blocks.close()
```

- [ ] **Step 2: Run the integration test**

Run: `.venv/bin/python -m pytest tests/test_federation.py::test_full_federation_lifecycle -v`
Expected: PASS

- [ ] **Step 3: Run full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: All existing tests still pass + new federation tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_federation.py
git commit -m "test: end-to-end federation lifecycle — fork, sync, signal, inbox"
```

---

## Summary

| Task | What | New tests |
|------|------|-----------|
| 1 | Migration + content_hash on insert | 3 |
| 2 | Core tiers (mark_core tier=, get_core_episodes) | 2 |
| 3 | Config fields (instance, session_context, signals) | 2 |
| 4 | SignalBus (signals.db, send, inbox, mark_seen) | 3 |
| 5 | InstanceRegistry (register, remove, list) | 1 |
| 6 | sync_genome (genome → instance replication) | 1 |
| 7 | process_inbox (signals → local episodes) | 1 |
| 8 | Server integration (init sequence, remember genome=True) | 1 |
| 9 | CLI (fork, drop, list) | 2 |
| 10 | Wake hook (identity, inbox, context filtering) | 1 |
| 11 | Reflection (genome drift, signal health) | 1 |
| 12 | Integration test (full lifecycle) | 1 |

**Total: 12 tasks, ~19 new tests, 12 commits**

Build order matters: Tasks 1-3 are schema/config foundation. Tasks 4-7 are the federation module (can be done in sequence). Task 8 wires federation into the server. Tasks 9-11 are independent from each other. Task 12 validates everything together.
