# Kairos Apps: Ratchet — Implementation Plan

> **Status:** Not started

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the block-ratchet MCP service from `~/Projects/code/block-ratchet/` into the kairos monorepo as `apps/ratchet/` — block lifecycle management with multi-stage validation, graph-based tier calculation, and session coordination.

**Architecture:** Ratchet keeps its own sync EventBus internally for the handler pattern (stats, tiers, capabilities, outcomes fire synchronously during submit/compose) but publishes to the platform Bus for cross-worker communication (`block.submitted`, `block.composed`, `tests.failed`). OutcomeHandler writes to platform Ledger instead of its own JSONL. Each handler module is collapsed into a single `handlers.py` file (four small classes don't warrant separate files in the kairos layout).

**Tech Stack:** Python 3.12+, no external dependencies beyond kplatform

**Spec:** `docs/superpowers/specs/2026-03-21-kairos-platform-design.md` (Applications Layer > Ratchet section)

**Source (reference only — port, don't copy):** `/Users/kairos/Projects/code/block-ratchet/`

---

## File Structure

```
kairos/
  apps/
    __init__.py
    ratchet/
      __init__.py             -- exports: BlockGraph, Block, Coordinator, RatchetWorker
      graph.py                -- Block dataclass, BlockStats, BlockGraph, effective_tier
      coordinator.py          -- Session claim/release with stale timeout
      validators.py           -- Contract, events, isolation validators
      capabilities.py         -- Taxonomy matching + auto-registration
      handlers.py             -- StatsHandler, TierHandler, OutcomeHandler (uses Ledger)
      worker.py               -- MCP service entrypoint with submit_block, compose, audit
      CLAUDE.md
  tests/
    apps/
      __init__.py
      ratchet/
        __init__.py
        conftest.py           -- fixtures: tmp blocks dir, graph, coordinator, bus
        test_graph.py         -- Block model, BlockGraph, effective_tier
        test_coordinator.py   -- Claim/release, stale timeout
        test_validators.py    -- Contract, events, isolation
        test_capabilities.py  -- Taxonomy matching, auto-registration
        test_handlers.py      -- Stats, tiers, outcomes via Ledger
        test_integration.py   -- Full lifecycle: claim → submit → compose → promote
```

**Key decisions:**
- Ratchet's internal EventBus is sync (matches source — handlers run in submit/compose call path, not async)
- Platform Bus publishing is async — worker.py bridges sync handlers to async platform bus via `asyncio.run()` or by publishing after handler pipeline completes
- OutcomeHandler takes a `Ledger` instance instead of managing its own JSONL file
- seed.py is NOT ported (bootstrap seeding is reference-only, not needed in kairos)
- server.py tools (MCP registration) go in worker.py
- The four handler files (stats.py, tiers.py, capabilities.py, outcomes.py) are consolidated into handlers.py + capabilities.py (capabilities is large enough to stay separate)
- Block.save() and Block.from_dir() are preserved — blocks are still filesystem-based with block.json

---

### Task 1: Block Model + Graph

**Files:**
- Create: `apps/__init__.py`
- Create: `apps/ratchet/__init__.py`
- Create: `apps/ratchet/graph.py`
- Create: `tests/apps/__init__.py`
- Create: `tests/apps/ratchet/__init__.py`
- Create: `tests/apps/ratchet/conftest.py`
- Create: `tests/apps/ratchet/test_graph.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/apps/ratchet/conftest.py
import json
from pathlib import Path

import pytest


def make_block_dir(blocks_dir: Path, block_id: str, **overrides) -> Path:
    """Create a block directory with block.json for testing."""
    d = blocks_dir / block_id
    d.mkdir(parents=True, exist_ok=True)
    data = {
        "id": block_id,
        "description": overrides.get("description", f"Block {block_id}"),
        "tags": overrides.get("tags", []),
        "depends_on": overrides.get("depends_on", []),
        "capabilities": overrides.get("capabilities", []),
        "tier": overrides.get("tier", 1),
        "stats": {
            "uses": overrides.get("uses", 0),
            "failures": overrides.get("failures", 0),
            "last_used": overrides.get("last_used", ""),
        },
        "metadata": overrides.get("metadata", {}),
        "events": overrides.get("events", {}),
        "entrypoint": overrides.get("entrypoint"),
        "trust_score": overrides.get("trust_score"),
    }
    (d / "block.json").write_text(json.dumps(data, indent=2) + "\n")
    return d
```

```python
# tests/apps/ratchet/test_graph.py
"""Tests for Block model and BlockGraph."""
import json
from pathlib import Path

import pytest

from apps.ratchet.graph import Block, BlockGraph, BlockStats
from tests.apps.ratchet.conftest import make_block_dir


class TestBlockModel:
    def test_from_dir(self, tmp_path):
        make_block_dir(tmp_path, "my-block", tags=["test", "demo"], tier=1)
        block = Block.from_dir(tmp_path / "my-block")
        assert block.id == "my-block"
        assert block.tier == 1
        assert "test" in block.tags

    def test_save_and_reload(self, tmp_path):
        block = Block(
            id="roundtrip", description="Test roundtrip.",
            tags=["a"], depends_on=[], tier=1,
            path=tmp_path / "roundtrip",
        )
        block.save()
        loaded = Block.from_dir(tmp_path / "roundtrip")
        assert loaded.id == block.id
        assert loaded.description == block.description

    def test_to_dict_contains_all_fields(self):
        block = Block(
            id="x", description="test", tags=["t"], depends_on=["dep"],
            capabilities=["search.vector"], tier=2,
            metadata={"k": "v"}, events={"publishes": ["a"]},
            entrypoint="src/x.py", trust_score=0.85,
        )
        d = block.to_dict()
        assert d["id"] == "x"
        assert d["capabilities"] == ["search.vector"]
        assert d["metadata"] == {"k": "v"}
        assert d["events"] == {"publishes": ["a"]}
        assert d["entrypoint"] == "src/x.py"
        assert d["trust_score"] == 0.85

    def test_metadata_default_empty(self):
        b = Block(id="x", description="test")
        assert b.metadata == {}

    def test_capabilities_default_empty(self):
        b = Block(id="x", description="test")
        assert b.capabilities == []

    def test_trust_score_default_none(self):
        b = Block(id="x", description="test")
        assert b.trust_score is None

    def test_events_default_empty(self):
        b = Block(id="x", description="test")
        assert b.events == {}
        assert b.entrypoint is None

    def test_save_without_path_raises(self):
        b = Block(id="x", description="test")
        with pytest.raises(ValueError, match="no path"):
            b.save()


class TestBlockStats:
    def test_default_values(self):
        s = BlockStats()
        assert s.uses == 0
        assert s.failures == 0
        assert s.last_used == ""

    def test_roundtrip(self):
        s = BlockStats(uses=5, failures=2, last_used="2026-01-01")
        d = s.to_dict()
        loaded = BlockStats.from_dict(d)
        assert loaded.uses == 5
        assert loaded.failures == 2
        assert loaded.last_used == "2026-01-01"


class TestBlockGraph:
    def test_scan_blocks_dir(self, tmp_path):
        make_block_dir(tmp_path, "alpha")
        make_block_dir(tmp_path, "beta")
        graph = BlockGraph(tmp_path)
        assert len(graph.blocks) == 2
        assert graph.get("alpha") is not None

    def test_empty_dir(self, tmp_path):
        graph = BlockGraph(tmp_path)
        assert len(graph.blocks) == 0

    def test_nonexistent_dir(self, tmp_path):
        graph = BlockGraph(tmp_path / "nope")
        assert len(graph.blocks) == 0

    def test_upsert_adds_new_block(self, tmp_path):
        graph = BlockGraph(tmp_path)
        block = Block(id="new", description="New block", path=tmp_path / "new")
        graph.upsert(block)
        assert graph.get("new") is not None

    def test_upsert_updates_existing(self, tmp_path):
        make_block_dir(tmp_path, "alpha")
        graph = BlockGraph(tmp_path)
        updated = Block(id="alpha", description="Updated", tier=2, path=tmp_path / "alpha")
        graph.upsert(updated)
        assert graph.get("alpha").description == "Updated"
        assert graph.get("alpha").tier == 2

    def test_remove_existing(self, tmp_path):
        make_block_dir(tmp_path, "alpha")
        graph = BlockGraph(tmp_path)
        graph.remove("alpha")
        assert graph.get("alpha") is None

    def test_remove_nonexistent_is_noop(self, tmp_path):
        graph = BlockGraph(tmp_path)
        graph.remove("ghost")  # should not raise

    def test_dependents_of(self, tmp_path):
        make_block_dir(tmp_path, "base")
        make_block_dir(tmp_path, "child", depends_on=["base"])
        graph = BlockGraph(tmp_path)
        dependents = graph.dependents_of("base")
        assert "child" in dependents

    def test_effective_tier_no_deps(self, tmp_path):
        make_block_dir(tmp_path, "solo", tier=3)
        graph = BlockGraph(tmp_path)
        assert graph.effective_tier("solo") == 3

    def test_effective_tier_capped_by_dep(self, tmp_path):
        make_block_dir(tmp_path, "low", tier=1)
        make_block_dir(tmp_path, "high", tier=3, depends_on=["low"])
        graph = BlockGraph(tmp_path)
        assert graph.effective_tier("high") == 1

    def test_effective_tier_missing_block(self, tmp_path):
        graph = BlockGraph(tmp_path)
        assert graph.effective_tier("ghost") == 0

    def test_effective_tier_cycle_detection(self, tmp_path):
        make_block_dir(tmp_path, "a", depends_on=["b"])
        make_block_dir(tmp_path, "b", depends_on=["a"])
        graph = BlockGraph(tmp_path)
        # Should not infinite loop — cycles return 0
        assert graph.effective_tier("a") == 0

    def test_rescan_picks_up_new_blocks(self, tmp_path):
        graph = BlockGraph(tmp_path)
        assert len(graph.blocks) == 0
        make_block_dir(tmp_path, "late-arrival")
        graph.rescan()
        assert graph.get("late-arrival") is not None

    def test_list_all(self, tmp_path):
        make_block_dir(tmp_path, "a")
        make_block_dir(tmp_path, "b")
        graph = BlockGraph(tmp_path)
        assert len(graph.list_all()) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/apps/ratchet/test_graph.py -v`

- [ ] **Step 3: Write graph.py**

```python
# apps/ratchet/graph.py
"""Block model and in-memory graph built from blocks/*/block.json files."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class BlockStats:
    """Usage and failure tracking."""
    uses: int = 0
    failures: int = 0
    last_used: str = ""

    def to_dict(self) -> dict:
        return {"uses": self.uses, "failures": self.failures, "last_used": self.last_used}

    @classmethod
    def from_dict(cls, d: dict) -> BlockStats:
        return cls(
            uses=d.get("uses", 0),
            failures=d.get("failures", 0),
            last_used=d.get("last_used", ""),
        )


@dataclass
class Block:
    """A tested, composable unit of functionality."""
    id: str
    description: str
    tags: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    tier: int = 0
    stats: BlockStats = field(default_factory=BlockStats)
    path: Path | None = None
    metadata: dict = field(default_factory=dict)
    events: dict = field(default_factory=dict)
    entrypoint: str | None = None
    trust_score: float | None = None

    @classmethod
    def from_dir(cls, block_dir: Path) -> Block:
        """Load a block from its directory's block.json."""
        data = json.loads((block_dir / "block.json").read_text())
        return cls(
            id=data["id"],
            description=data.get("description", ""),
            tags=data.get("tags", []),
            depends_on=data.get("depends_on", []),
            capabilities=data.get("capabilities", []),
            tier=data.get("tier", 0),
            stats=BlockStats.from_dict(data.get("stats", {})),
            path=block_dir,
            metadata=data.get("metadata", {}),
            events=data.get("events", {}),
            entrypoint=data.get("entrypoint"),
            trust_score=data.get("trust_score"),
        )

    def save(self) -> None:
        """Write block.json to the block's directory."""
        if self.path is None:
            raise ValueError(f"Block {self.id} has no path set")
        self.path.mkdir(parents=True, exist_ok=True)
        data = {
            "id": self.id,
            "description": self.description,
            "tags": self.tags,
            "depends_on": self.depends_on,
            "capabilities": self.capabilities,
            "tier": self.tier,
            "stats": self.stats.to_dict(),
            "metadata": self.metadata,
            "events": self.events,
            "entrypoint": self.entrypoint,
            "trust_score": self.trust_score,
        }
        (self.path / "block.json").write_text(json.dumps(data, indent=2) + "\n")

    def to_dict(self) -> dict:
        """Serialize for tool responses."""
        return {
            "id": self.id,
            "description": self.description,
            "tags": self.tags,
            "depends_on": self.depends_on,
            "capabilities": self.capabilities,
            "tier": self.tier,
            "stats": self.stats.to_dict(),
            "metadata": self.metadata,
            "events": self.events,
            "entrypoint": self.entrypoint,
            "trust_score": self.trust_score,
        }


class BlockGraph:
    """In-memory graph built by scanning blocks/*/block.json files."""

    def __init__(self, blocks_dir: Path) -> None:
        self._blocks_dir = blocks_dir
        self._blocks: dict[str, Block] = {}
        self.rescan()

    def rescan(self) -> None:
        """Scan the blocks directory and rebuild the in-memory graph."""
        self._blocks.clear()
        if not self._blocks_dir.exists():
            return
        for child in sorted(self._blocks_dir.iterdir()):
            block_json = child / "block.json"
            if child.is_dir() and block_json.exists():
                try:
                    block = Block.from_dir(child)
                    self._blocks[block.id] = block
                except (json.JSONDecodeError, KeyError) as e:
                    log.warning("Skipping %s: %s", child.name, e)

    @property
    def blocks(self) -> dict[str, Block]:
        return dict(self._blocks)

    def get(self, block_id: str) -> Block | None:
        return self._blocks.get(block_id)

    def list_all(self) -> list[Block]:
        return list(self._blocks.values())

    def upsert(self, block: Block) -> None:
        """Update or insert a block in the in-memory graph."""
        self._blocks[block.id] = block

    def remove(self, block_id: str) -> None:
        """Remove a block from the in-memory graph."""
        self._blocks.pop(block_id, None)

    def dependents_of(self, block_id: str) -> list[str]:
        """Return IDs of blocks that depend on the given block."""
        return [b.id for b in self._blocks.values() if block_id in b.depends_on]

    def effective_tier(self, block_id: str, _visited: set[str] | None = None) -> int:
        """A block's effective tier = min(own tier, min(dependency tiers)).

        Handles cycles by treating revisited blocks as tier 0.
        """
        if _visited is None:
            _visited = set()
        if block_id in _visited:
            return 0
        _visited.add(block_id)

        block = self._blocks.get(block_id)
        if block is None:
            return 0
        if not block.depends_on:
            return block.tier
        dep_tiers = [
            self.effective_tier(dep, _visited)
            for dep in block.depends_on
            if dep in self._blocks
        ]
        if not dep_tiers:
            return block.tier
        return min(block.tier, min(dep_tiers))
```

- [ ] **Step 4: Write __init__.py files**

```python
# apps/__init__.py
```

```python
# apps/ratchet/__init__.py
"""Block lifecycle management — claim, build, validate, submit, promote."""
```

```python
# tests/apps/__init__.py
```

```python
# tests/apps/ratchet/__init__.py
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/apps/ratchet/test_graph.py -v`
Expected: All 20 tests PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/kairos/Projects/kairos
git add apps/ tests/apps/
git commit -m "feat(ratchet): Block model and BlockGraph with effective_tier"
```

---

### Task 2: Session Coordinator

**Files:**
- Create: `apps/ratchet/coordinator.py`
- Create: `tests/apps/ratchet/test_coordinator.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/apps/ratchet/test_coordinator.py
"""Tests for session coordinator — claim/release locking."""
import time

import pytest

from apps.ratchet.coordinator import Coordinator, Claim


class TestCoordinator:
    def test_claim_gap(self):
        coord = Coordinator(stale_timeout_seconds=60)
        claim = coord.claim_gap("session-1", "Build an HTML parser")
        assert claim is not None
        assert claim["session_id"] == "session-1"
        assert claim["gap_description"] == "Build an HTML parser"

    def test_cannot_double_claim_same_gap(self):
        coord = Coordinator(stale_timeout_seconds=60)
        coord.claim_gap("session-1", "Build an HTML parser")
        claim2 = coord.claim_gap("session-2", "Build an HTML parser")
        assert claim2 is None

    def test_session_can_only_hold_one_claim(self):
        coord = Coordinator(stale_timeout_seconds=60)
        coord.claim_gap("session-1", "Build A")
        claim2 = coord.claim_gap("session-1", "Build B")
        assert claim2 is None

    def test_release_and_reclaim(self):
        coord = Coordinator(stale_timeout_seconds=60)
        coord.claim_gap("session-1", "Build X")
        coord.release_claim("session-1")
        claim = coord.claim_gap("session-2", "Build X")
        assert claim is not None

    def test_release_nonexistent_returns_false(self):
        coord = Coordinator(stale_timeout_seconds=60)
        assert coord.release_claim("ghost") is False

    def test_stale_claim_auto_releases(self):
        coord = Coordinator(stale_timeout_seconds=0)
        coord.claim_gap("session-1", "Build X")
        time.sleep(0.01)
        coord.cleanup_stale()
        claim = coord.claim_gap("session-2", "Build X")
        assert claim is not None

    def test_list_active_claims(self):
        coord = Coordinator(stale_timeout_seconds=60)
        coord.claim_gap("s1", "Build A")
        coord.claim_gap("s2", "Build B")
        claims = coord.list_claims()
        assert len(claims) == 2

    def test_get_claim(self):
        coord = Coordinator(stale_timeout_seconds=60)
        coord.claim_gap("s1", "Build A")
        claim = coord.get_claim("s1")
        assert claim is not None
        assert claim["gap_description"] == "Build A"

    def test_get_claim_nonexistent(self):
        coord = Coordinator(stale_timeout_seconds=60)
        assert coord.get_claim("ghost") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/apps/ratchet/test_coordinator.py -v`

- [ ] **Step 3: Write coordinator.py**

```python
# apps/ratchet/coordinator.py
"""Session coordinator — claim/release locking for concurrent block building."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class Claim:
    """An active claim on a gap."""
    session_id: str
    gap_description: str
    claimed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "gap_description": self.gap_description,
            "claimed_at": self.claimed_at,
        }


class Coordinator:
    """Manages session claims on gaps to prevent duplicate work.

    Two-index dict: by session and by gap description.
    All state is in-memory. Server restart releases all claims.
    """

    def __init__(self, stale_timeout_seconds: int = 600) -> None:
        self._stale_timeout = stale_timeout_seconds
        self._claims_by_session: dict[str, Claim] = {}
        self._claims_by_gap: dict[str, Claim] = {}

    def claim_gap(self, session_id: str, gap_description: str) -> dict | None:
        """Claim a gap for a session. Returns claim dict or None if unavailable."""
        self.cleanup_stale()

        if session_id in self._claims_by_session:
            log.info("Session %s already holds a claim", session_id)
            return None

        if gap_description in self._claims_by_gap:
            log.info("Gap %r already claimed", gap_description)
            return None

        claim = Claim(session_id=session_id, gap_description=gap_description)
        self._claims_by_session[session_id] = claim
        self._claims_by_gap[gap_description] = claim
        log.info("Session %s claimed: %s", session_id, gap_description)
        return claim.to_dict()

    def release_claim(self, session_id: str) -> bool:
        """Release a session's claim. Returns True if a claim was released."""
        claim = self._claims_by_session.pop(session_id, None)
        if claim is None:
            return False
        self._claims_by_gap.pop(claim.gap_description, None)
        log.info("Released claim for session %s", session_id)
        return True

    def cleanup_stale(self) -> int:
        """Release claims older than the stale timeout. Returns count released."""
        now = time.time()
        stale = [
            sid for sid, claim in self._claims_by_session.items()
            if now - claim.claimed_at > self._stale_timeout
        ]
        for sid in stale:
            self.release_claim(sid)
        return len(stale)

    def list_claims(self) -> list[dict]:
        """Return all active claims."""
        self.cleanup_stale()
        return [c.to_dict() for c in self._claims_by_session.values()]

    def get_claim(self, session_id: str) -> dict | None:
        """Get a session's current claim."""
        claim = self._claims_by_session.get(session_id)
        return claim.to_dict() if claim else None
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/apps/ratchet/test_coordinator.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/kairos/Projects/kairos
git add apps/ratchet/coordinator.py tests/apps/ratchet/test_coordinator.py
git commit -m "feat(ratchet): session coordinator with claim/release and stale timeout"
```

---

### Task 3: Validators

**Files:**
- Create: `apps/ratchet/validators.py`
- Create: `tests/apps/ratchet/test_validators.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/apps/ratchet/test_validators.py
"""Tests for block validators — contract, event declarations, isolation."""
import json

import pytest

from apps.ratchet.validators import (
    validate_contract,
    validate_events,
    validate_isolation,
)


class TestContractValidation:
    def _make_block_with_src(self, blocks_dir, block_id, src_content):
        d = blocks_dir / block_id
        d.mkdir(parents=True)
        (d / "src").mkdir()
        mod_name = block_id.replace("-", "_")
        (d / "src" / f"{mod_name}.py").write_text(src_content)
        return d

    def test_valid_setup_passes(self, tmp_path):
        d = self._make_block_with_src(tmp_path, "good-block", "def setup(bus): pass\n")
        errors = validate_contract(d, "src/good_block.py")
        assert errors == []

    def test_missing_setup_fails(self, tmp_path):
        d = self._make_block_with_src(tmp_path, "no-setup", "def other(): pass\n")
        errors = validate_contract(d, "src/no_setup.py")
        assert len(errors) == 1
        assert "setup" in errors[0].lower()

    def test_setup_not_callable_fails(self, tmp_path):
        d = self._make_block_with_src(tmp_path, "bad-setup", "setup = 42\n")
        errors = validate_contract(d, "src/bad_setup.py")
        assert len(errors) == 1

    def test_missing_entrypoint_fails(self, tmp_path):
        d = tmp_path / "ghost"
        d.mkdir()
        (d / "src").mkdir()
        errors = validate_contract(d, "src/ghost.py")
        assert len(errors) == 1
        assert "not found" in errors[0].lower()

    def test_none_entrypoint_skips(self, tmp_path):
        d = tmp_path / "legacy"
        d.mkdir()
        errors = validate_contract(d, None)
        assert errors == []


class TestEventValidation:
    def _make_block_with_src(self, blocks_dir, block_id, src_content):
        d = blocks_dir / block_id
        d.mkdir(parents=True)
        (d / "src").mkdir()
        mod_name = block_id.replace("-", "_")
        (d / "src" / f"{mod_name}.py").write_text(src_content)
        return d

    def test_matching_events_passes(self, tmp_path):
        d = self._make_block_with_src(tmp_path, "ok",
            "def setup(bus):\n    bus.subscribe('a.requested', lambda e: None)\n")
        errors = validate_events(d, "src/ok.py",
            declared={"publishes": [], "subscribes": ["a.requested"]})
        assert errors == []

    def test_undeclared_subscribe_warns(self, tmp_path):
        d = self._make_block_with_src(tmp_path, "sneaky",
            "def setup(bus):\n    bus.subscribe('secret', lambda e: None)\n")
        errors = validate_events(d, "src/sneaky.py",
            declared={"publishes": [], "subscribes": []})
        assert any("secret" in e for e in errors)

    def test_undeclared_publish_warns(self, tmp_path):
        d = self._make_block_with_src(tmp_path, "leak",
            "def setup(bus):\n    bus.publish('hidden', {})\n")
        errors = validate_events(d, "src/leak.py",
            declared={"publishes": [], "subscribes": []})
        assert any("hidden" in e for e in errors)

    def test_empty_declared_skips(self, tmp_path):
        errors = validate_events(tmp_path, "src/x.py", declared={})
        assert errors == []

    def test_none_entrypoint_skips(self, tmp_path):
        errors = validate_events(tmp_path, None, declared={"subscribes": ["a"]})
        assert errors == []

    def test_scoped_bus_calls_ignored(self, tmp_path):
        """Events on scoped (child) bus should not be validated against declarations."""
        d = self._make_block_with_src(tmp_path, "scoped",
            "def setup(bus):\n"
            "    child = bus.scope('internal')\n"
            "    child.subscribe('internal.event', lambda e: None)\n")
        errors = validate_events(d, "src/scoped.py",
            declared={"publishes": [], "subscribes": []})
        assert errors == []


class TestIsolationValidation:
    def _write_src(self, tmp_path, filename, content):
        p = tmp_path / filename
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    def test_stdlib_import_ok(self, tmp_path):
        p = self._write_src(tmp_path, "src/clean.py",
            "import json\nfrom pathlib import Path\ndef setup(bus): pass\n")
        errors = validate_isolation(p, known_block_ids=["other-block"])
        assert errors == []

    def test_cross_block_import_from_fails(self, tmp_path):
        p = self._write_src(tmp_path, "src/dirty.py",
            "from other_block import helper\ndef setup(bus): pass\n")
        errors = validate_isolation(p, known_block_ids=["other-block"])
        assert len(errors) == 1
        assert "other_block" in errors[0]

    def test_cross_block_import_stmt_fails(self, tmp_path):
        p = self._write_src(tmp_path, "src/dirty2.py",
            "import other_block\ndef setup(bus): pass\n")
        errors = validate_isolation(p, known_block_ids=["other-block"])
        assert len(errors) == 1

    def test_third_party_import_ok(self, tmp_path):
        p = self._write_src(tmp_path, "src/vendor.py",
            "import numpy\nfrom pydantic import BaseModel\ndef setup(bus): pass\n")
        errors = validate_isolation(p, known_block_ids=["other-block"])
        assert errors == []

    def test_none_entrypoint_skips(self, tmp_path):
        errors = validate_isolation(None, known_block_ids=["x"])
        assert errors == []

    def test_syntax_error_reported(self, tmp_path):
        p = self._write_src(tmp_path, "src/broken.py", "def setup(bus\n")
        errors = validate_isolation(p, known_block_ids=["x"])
        assert len(errors) == 1
        assert "syntax" in errors[0].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/apps/ratchet/test_validators.py -v`

- [ ] **Step 3: Write validators.py**

```python
# apps/ratchet/validators.py
"""Block validators — contract, event declaration, and isolation checks."""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)


@contextlib.contextmanager
def _extended_sys_path(block_dir: Path):
    """Temporarily add block src/ to sys.path."""
    src_dir = str(block_dir / "src")
    added = []
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
        added.append(src_dir)
    try:
        yield
    finally:
        for p in added:
            try:
                sys.path.remove(p)
            except ValueError:
                pass


def validate_contract(block_dir: Path, entrypoint: str | None) -> list[str]:
    """Check that a block exports a callable setup(bus).

    Returns a list of error strings (empty means valid).
    """
    if entrypoint is None:
        return []

    ep_path = block_dir / entrypoint
    if not ep_path.exists():
        return [f"Entrypoint not found: {entrypoint}"]

    mod_name = f"_block_check_{ep_path.stem}"
    spec = importlib.util.spec_from_file_location(mod_name, ep_path)
    if spec is None or spec.loader is None:
        return [f"Cannot create module spec for {entrypoint}"]

    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        with _extended_sys_path(block_dir):
            spec.loader.exec_module(module)
    except Exception as exc:
        return [f"Failed to load entrypoint {entrypoint}: {exc}"]
    finally:
        sys.modules.pop(mod_name, None)

    setup = getattr(module, "setup", None)
    if setup is None:
        return [f"Entrypoint {entrypoint} does not export a 'setup' function"]
    if not callable(setup):
        return [f"'setup' in {entrypoint} is not callable (got {type(setup).__name__})"]

    return []


class _RecordingBus:
    """Minimal bus stand-in that records subscribe/publish calls.

    Supports scope() — scoped (child) buses swallow calls since internal
    wiring is encapsulated.
    """

    def __init__(self, *, _is_scoped: bool = False) -> None:
        self._is_scoped = _is_scoped
        self.subscribed: list[str] = []
        self.published: list[str] = []

    def subscribe(self, event_type: str, handler=None) -> None:
        if not self._is_scoped:
            self.subscribed.append(event_type)

    def publish(self, event_type: str, payload=None) -> None:
        if not self._is_scoped:
            self.published.append(event_type)

    def emit(self, event_type: str, **payload) -> None:
        if not self._is_scoped:
            self.published.append(event_type)

    def scope(self, prefix: str) -> _RecordingBus:
        return _RecordingBus(_is_scoped=True)


def validate_events(
    block_dir: Path,
    entrypoint: str | None,
    *,
    declared: dict,
) -> list[str]:
    """Compare actual subscribe/publish calls in setup() against declarations.

    Returns a list of warning/error strings.
    """
    if not declared:
        return []
    if entrypoint is None:
        return []

    ep_path = block_dir / entrypoint
    if not ep_path.exists():
        return []

    mod_name = f"_event_check_{ep_path.stem}"
    spec = importlib.util.spec_from_file_location(mod_name, ep_path)
    if spec is None or spec.loader is None:
        return [f"Cannot create module spec for {entrypoint}"]

    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        with _extended_sys_path(block_dir):
            spec.loader.exec_module(module)
    except Exception as exc:
        return [f"Failed to load entrypoint for event check: {exc}"]
    finally:
        sys.modules.pop(mod_name, None)

    setup_fn = getattr(module, "setup", None)
    if not callable(setup_fn):
        return []

    bus = _RecordingBus()
    try:
        setup_fn(bus)
    except Exception as exc:
        return [f"setup() raised during event recording: {exc}"]

    errors: list[str] = []
    declared_subs = set(declared.get("subscribes", []))
    declared_pubs = set(declared.get("publishes", []))

    for event in bus.subscribed:
        if event not in declared_subs:
            errors.append(
                f"Undeclared subscribe: '{event}' used in setup() "
                f"but not listed in subscribes"
            )

    for event in bus.published:
        if event not in declared_pubs:
            errors.append(
                f"Undeclared publish: '{event}' used in setup() "
                f"but not listed in publishes"
            )

    return errors


def validate_isolation(
    entrypoint_path: Path | None,
    *,
    known_block_ids: list[str],
) -> list[str]:
    """AST-scan entrypoint for imports of other block modules.

    Converts each block ID to its Python module name (- -> _) and
    checks import/from-import statements.

    Returns a list of error strings.
    """
    if entrypoint_path is None:
        return []

    block_modules = {bid.replace("-", "_") for bid in known_block_ids}

    try:
        source = entrypoint_path.read_text()
    except (OSError, UnicodeDecodeError) as exc:
        return [f"Cannot read entrypoint: {exc}"]

    try:
        tree = ast.parse(source, filename=str(entrypoint_path))
    except SyntaxError as exc:
        return [f"Syntax error in entrypoint: {exc}"]

    errors: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_module = alias.name.split(".")[0]
                if root_module in block_modules:
                    errors.append(
                        f"Cross-block import: 'import {alias.name}' "
                        f"references block module '{root_module}'"
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                root_module = node.module.split(".")[0]
                if root_module in block_modules:
                    errors.append(
                        f"Cross-block import: 'from {node.module} import ...' "
                        f"references block module '{root_module}'"
                    )

    return errors
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/apps/ratchet/test_validators.py -v`
Expected: All 13 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/kairos/Projects/kairos
git add apps/ratchet/validators.py tests/apps/ratchet/test_validators.py
git commit -m "feat(ratchet): three-stage validators — contract, events, isolation"
```

---

### Task 4: Capability Matcher

**Files:**
- Create: `apps/ratchet/capabilities.py`
- Create: `tests/apps/ratchet/test_capabilities.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/apps/ratchet/test_capabilities.py
"""Tests for capability taxonomy matching."""
import json
from pathlib import Path

import pytest

from apps.ratchet.graph import Block, BlockGraph
from apps.ratchet.capabilities import CapabilityMatcher
from tests.apps.ratchet.conftest import make_block_dir


class TestCapabilityMatcher:
    def test_exact_match(self, tmp_path):
        make_block_dir(tmp_path, "vec", capabilities=["search.vector"])
        graph = BlockGraph(tmp_path)
        matcher = CapabilityMatcher(graph, tmp_path)
        matches, gaps = matcher.match(["search.vector"])
        assert len(matches) == 1
        assert matches[0]["block_ids"] == ["vec"]
        assert gaps == []

    def test_prefix_match_returns_all(self, tmp_path):
        make_block_dir(tmp_path, "vec", capabilities=["search.vector"])
        make_block_dir(tmp_path, "rrf", capabilities=["search.rank-fusion"])
        graph = BlockGraph(tmp_path)
        matcher = CapabilityMatcher(graph, tmp_path)
        matches, gaps = matcher.match(["search"])
        assert len(matches) == 1
        assert set(matches[0]["block_ids"]) == {"vec", "rrf"}

    def test_gap_when_no_match(self, tmp_path):
        make_block_dir(tmp_path, "vec", capabilities=["search.vector"])
        graph = BlockGraph(tmp_path)
        matcher = CapabilityMatcher(graph, tmp_path)
        matches, gaps = matcher.match(["planning.dual-process"])
        assert matches == []
        assert gaps == ["planning.dual-process"]

    def test_multiple_queries(self, tmp_path):
        make_block_dir(tmp_path, "vec", capabilities=["search.vector"])
        make_block_dir(tmp_path, "emb", capabilities=["embedding.text-to-vector"])
        graph = BlockGraph(tmp_path)
        matcher = CapabilityMatcher(graph, tmp_path)
        matches, gaps = matcher.match(["search.vector", "embedding", "cache"])
        by_cap = {m["capability"]: m["block_ids"] for m in matches}
        assert by_cap["search.vector"] == ["vec"]
        assert by_cap["embedding"] == ["emb"]
        assert gaps == ["cache"]

    def test_empty_queries(self, tmp_path):
        graph = BlockGraph(tmp_path)
        matcher = CapabilityMatcher(graph, tmp_path)
        matches, gaps = matcher.match([])
        assert matches == []
        assert gaps == []

    def test_block_with_no_capabilities_never_matches(self, tmp_path):
        make_block_dir(tmp_path, "legacy", capabilities=[])
        graph = BlockGraph(tmp_path)
        matcher = CapabilityMatcher(graph, tmp_path)
        matches, gaps = matcher.match(["search"])
        assert matches == []
        assert gaps == ["search"]

    def test_deep_nesting(self, tmp_path):
        make_block_dir(tmp_path, "deep", capabilities=["reasoning.inference.backward"])
        graph = BlockGraph(tmp_path)
        matcher = CapabilityMatcher(graph, tmp_path)
        matches, _ = matcher.match(["reasoning"])
        assert matches[0]["block_ids"] == ["deep"]
        matches, _ = matcher.match(["reasoning.inference"])
        assert matches[0]["block_ids"] == ["deep"]
        _, gaps = matcher.match(["reasoning.verification"])
        assert gaps == ["reasoning.verification"]


class TestTaxonomy:
    def test_taxonomy_created_on_init_if_missing(self, tmp_path):
        graph = BlockGraph(tmp_path)
        CapabilityMatcher(graph, tmp_path)
        assert (tmp_path / "taxonomy.json").exists()

    def test_validate_known_capability(self, tmp_path):
        (tmp_path / "taxonomy.json").write_text(json.dumps({
            "search": {"_reviewed": True, "vector": {"_reviewed": True}},
        }))
        graph = BlockGraph(tmp_path)
        matcher = CapabilityMatcher(graph, tmp_path)
        new = matcher.validate_and_register(["search.vector"])
        assert new == []

    def test_unknown_capability_auto_added_unreviewed(self, tmp_path):
        (tmp_path / "taxonomy.json").write_text(json.dumps({}))
        graph = BlockGraph(tmp_path)
        matcher = CapabilityMatcher(graph, tmp_path)
        new = matcher.validate_and_register(["search.vector"])
        assert new == ["search.vector"]
        taxonomy = json.loads((tmp_path / "taxonomy.json").read_text())
        assert taxonomy["search"]["vector"]["_reviewed"] is False

    def test_unreviewed_reports_paths(self, tmp_path):
        (tmp_path / "taxonomy.json").write_text(json.dumps({
            "search": {
                "_reviewed": True,
                "vector": {"_reviewed": True},
                "semantic": {"_reviewed": False},
            },
        }))
        graph = BlockGraph(tmp_path)
        matcher = CapabilityMatcher(graph, tmp_path)
        unreviewed = matcher.unreviewed()
        assert "search.semantic" in unreviewed
        assert "search.vector" not in unreviewed

    def test_underscore_prefix_rejected(self, tmp_path):
        graph = BlockGraph(tmp_path)
        matcher = CapabilityMatcher(graph, tmp_path)
        with pytest.raises(ValueError, match="underscore"):
            matcher.validate_and_register(["search._desc"])
        with pytest.raises(ValueError, match="underscore"):
            matcher.validate_and_register(["_private.thing"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/apps/ratchet/test_capabilities.py -v`

- [ ] **Step 3: Write capabilities.py**

```python
# apps/ratchet/capabilities.py
"""Capability taxonomy matching — deterministic, hierarchical, self-growing."""
from __future__ import annotations

import json
from pathlib import Path

from apps.ratchet.graph import BlockGraph


class CapabilityMatcher:
    """Matches capability queries against block capabilities using dot-notation hierarchy."""

    def __init__(self, graph: BlockGraph, blocks_dir: Path) -> None:
        self._graph = graph
        self._taxonomy_path = blocks_dir / "taxonomy.json"
        self._taxonomy: dict = {}
        self._load_taxonomy()

    def _load_taxonomy(self) -> None:
        if self._taxonomy_path.exists():
            self._taxonomy = json.loads(self._taxonomy_path.read_text())
        else:
            self._taxonomy = {}
            self._save_taxonomy()

    def _save_taxonomy(self) -> None:
        self._taxonomy_path.parent.mkdir(parents=True, exist_ok=True)
        self._taxonomy_path.write_text(json.dumps(self._taxonomy, indent=2) + "\n")

    def match(self, queries: list[str]) -> tuple[list[dict], list[str]]:
        """Match capability queries against blocks.

        Returns (matches, gaps). Prefix matching: query "search" matches
        block capability "search.vector". All matching blocks returned.
        """
        matches: list[dict] = []
        gaps: list[str] = []
        blocks = self._graph.list_all()

        for query in queries:
            matched_ids: list[str] = []
            for block in blocks:
                for cap in block.capabilities:
                    if self._prefix_match(query, cap):
                        matched_ids.append(block.id)
                        break
            if matched_ids:
                matches.append({"capability": query, "block_ids": matched_ids})
            else:
                gaps.append(query)

        return matches, gaps

    def validate_and_register(self, capabilities: list[str]) -> list[str]:
        """Validate capabilities against taxonomy. Auto-add unknown ones as unreviewed.

        Returns list of newly added capability paths.
        Raises ValueError if any segment starts with underscore.
        """
        for cap in capabilities:
            parts = cap.split(".")
            if any(p.startswith("_") for p in parts):
                raise ValueError(f"Capability segments cannot start with underscore: {cap}")
        new: list[str] = []
        for cap in capabilities:
            if not self._exists_in_taxonomy(cap):
                self._add_to_taxonomy(cap)
                new.append(cap)
        if new:
            self._save_taxonomy()
        return new

    def unreviewed(self) -> list[str]:
        """Return all unreviewed capability paths in the taxonomy."""
        result: list[str] = []
        self._walk_unreviewed(self._taxonomy, [], result)
        return result

    @staticmethod
    def _prefix_match(query: str, capability: str) -> bool:
        """True if capability equals query or is a child of query."""
        return capability == query or capability.startswith(query + ".")

    def _exists_in_taxonomy(self, cap: str) -> bool:
        parts = cap.split(".")
        node = self._taxonomy
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return False
            node = node[part]
        return True

    def _add_to_taxonomy(self, cap: str) -> None:
        parts = cap.split(".")
        node = self._taxonomy
        for part in parts:
            if part not in node:
                node[part] = {"_reviewed": False}
            node = node[part]

    def _walk_unreviewed(self, node: dict, path: list[str], result: list[str]) -> None:
        for key, value in node.items():
            if key.startswith("_"):
                continue
            child_path = path + [key]
            if isinstance(value, dict):
                if value.get("_reviewed") is False:
                    result.append(".".join(child_path))
                self._walk_unreviewed(value, child_path, result)
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/apps/ratchet/test_capabilities.py -v`
Expected: All 12 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/kairos/Projects/kairos
git add apps/ratchet/capabilities.py tests/apps/ratchet/test_capabilities.py
git commit -m "feat(ratchet): capability taxonomy matching with prefix search and auto-registration"
```

---

### Task 5: Handlers — Stats, Tiers, Outcomes

**Files:**
- Create: `apps/ratchet/handlers.py`
- Create: `tests/apps/ratchet/test_handlers.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/apps/ratchet/test_handlers.py
"""Tests for event handlers — stats, tiers, outcomes."""
import json
from pathlib import Path

import pytest

from apps.ratchet.graph import Block, BlockGraph
from apps.ratchet.handlers import StatsHandler, TierHandler, OutcomeHandler
from kplatform.ledger import Ledger
from tests.apps.ratchet.conftest import make_block_dir


class TestStatsHandler:
    def test_submitted_bumps_dependency_uses(self, tmp_path):
        make_block_dir(tmp_path, "dep-a")
        make_block_dir(tmp_path, "dep-b")
        graph = BlockGraph(tmp_path)
        handler = StatsHandler(graph)
        handler.on_block_submitted(block_id="child", depends_on=["dep-a", "dep-b"])
        assert graph.get("dep-a").stats.uses == 1
        assert graph.get("dep-b").stats.uses == 1

    def test_submitted_sets_last_used(self, tmp_path):
        make_block_dir(tmp_path, "dep")
        graph = BlockGraph(tmp_path)
        handler = StatsHandler(graph)
        handler.on_block_submitted(block_id="child", depends_on=["dep"])
        assert graph.get("dep").stats.last_used != ""

    def test_composed_bumps_dependency_uses(self, tmp_path):
        make_block_dir(tmp_path, "dep")
        graph = BlockGraph(tmp_path)
        handler = StatsHandler(graph)
        handler.on_block_composed(block_id="comp", depends_on=["dep"])
        assert graph.get("dep").stats.uses == 1

    def test_tests_failed_bumps_failures(self, tmp_path):
        make_block_dir(tmp_path, "flaky")
        graph = BlockGraph(tmp_path)
        handler = StatsHandler(graph)
        handler.on_tests_failed(block_id="flaky")
        assert graph.get("flaky").stats.failures == 1

    def test_stats_persisted_to_disk(self, tmp_path):
        make_block_dir(tmp_path, "dep")
        graph = BlockGraph(tmp_path)
        handler = StatsHandler(graph)
        handler.on_block_submitted(block_id="child", depends_on=["dep"])
        reloaded = Block.from_dir(tmp_path / "dep")
        assert reloaded.stats.uses == 1

    def test_unknown_dependency_is_skipped(self, tmp_path):
        graph = BlockGraph(tmp_path)
        handler = StatsHandler(graph)
        handler.on_block_submitted(block_id="child", depends_on=["ghost"])

    def test_no_depends_on_is_noop(self, tmp_path):
        graph = BlockGraph(tmp_path)
        handler = StatsHandler(graph)
        handler.on_block_submitted(block_id="child")


class TestTierHandler:
    def test_compose_promotes_deps_to_validated(self, tmp_path):
        make_block_dir(tmp_path, "dep-a", tier=1)
        make_block_dir(tmp_path, "dep-b", tier=1)
        graph = BlockGraph(tmp_path)
        handler = TierHandler(graph)
        handler.on_block_composed(block_id="comp", depends_on=["dep-a", "dep-b"])
        assert graph.get("dep-a").tier == 2
        assert graph.get("dep-b").tier == 2

    def test_compose_does_not_demote(self, tmp_path):
        make_block_dir(tmp_path, "strong", tier=3)
        graph = BlockGraph(tmp_path)
        handler = TierHandler(graph)
        handler.on_block_composed(block_id="comp", depends_on=["strong"])
        assert graph.get("strong").tier == 3

    def test_neighbor_failure_promotes_survivor(self, tmp_path):
        make_block_dir(tmp_path, "good", tier=2, failures=0)
        make_block_dir(tmp_path, "bad", tier=2, failures=0)
        make_block_dir(tmp_path, "comp", depends_on=["good", "bad"], tier=1)
        graph = BlockGraph(tmp_path)
        handler = TierHandler(graph)
        handler.on_tests_failed(block_id="bad")
        assert graph.get("good").tier == 3

    def test_no_promotion_if_not_validated(self, tmp_path):
        make_block_dir(tmp_path, "tested-only", tier=1, failures=0)
        make_block_dir(tmp_path, "bad", tier=1, failures=0)
        make_block_dir(tmp_path, "comp", depends_on=["tested-only", "bad"], tier=1)
        graph = BlockGraph(tmp_path)
        handler = TierHandler(graph)
        handler.on_tests_failed(block_id="bad")
        assert graph.get("tested-only").tier == 1

    def test_no_promotion_if_has_failures(self, tmp_path):
        make_block_dir(tmp_path, "also-flaky", tier=2, failures=2)
        make_block_dir(tmp_path, "bad", tier=2, failures=0)
        make_block_dir(tmp_path, "comp", depends_on=["also-flaky", "bad"], tier=1)
        graph = BlockGraph(tmp_path)
        handler = TierHandler(graph)
        handler.on_tests_failed(block_id="bad")
        assert graph.get("also-flaky").tier == 2

    def test_low_trust_blocks_promotion(self, tmp_path):
        make_block_dir(tmp_path, "untrusted", tier=1, trust_score=0.2)
        graph = BlockGraph(tmp_path)
        handler = TierHandler(graph)
        handler.on_block_composed(block_id="comp", depends_on=["untrusted"])
        assert graph.get("untrusted").tier == 1

    def test_high_trust_allows_promotion(self, tmp_path):
        make_block_dir(tmp_path, "trusted", tier=1, trust_score=0.9)
        graph = BlockGraph(tmp_path)
        handler = TierHandler(graph)
        handler.on_block_composed(block_id="comp", depends_on=["trusted"])
        assert graph.get("trusted").tier == 2

    def test_no_trust_score_allows_promotion(self, tmp_path):
        make_block_dir(tmp_path, "unscored", tier=1)
        graph = BlockGraph(tmp_path)
        handler = TierHandler(graph)
        handler.on_block_composed(block_id="comp", depends_on=["unscored"])
        assert graph.get("unscored").tier == 2

    def test_tier_persisted_to_disk(self, tmp_path):
        make_block_dir(tmp_path, "dep", tier=1)
        graph = BlockGraph(tmp_path)
        handler = TierHandler(graph)
        handler.on_block_composed(block_id="comp", depends_on=["dep"])
        reloaded = Block.from_dir(tmp_path / "dep")
        assert reloaded.tier == 2

    def test_unknown_dependency_is_skipped(self, tmp_path):
        graph = BlockGraph(tmp_path)
        handler = TierHandler(graph)
        handler.on_block_composed(block_id="comp", depends_on=["ghost"])


class TestOutcomeHandler:
    def test_records_successful_submission(self, tmp_path):
        ledger = Ledger(tmp_path / "outcomes.jsonl")
        handler = OutcomeHandler(ledger)
        handler.on_block_submitted(block_id="good", session_id="s1", depends_on=[])
        entries = ledger.read_all()
        assert len(entries) == 1
        assert entries[0]["block_id"] == "good"
        assert entries[0]["result"] == "success"

    def test_records_test_failure(self, tmp_path):
        ledger = Ledger(tmp_path / "outcomes.jsonl")
        handler = OutcomeHandler(ledger)
        handler.on_tests_failed(block_id="bad", session_id="s1", output="AssertionError")
        entries = ledger.read_all()
        assert len(entries) == 1
        assert entries[0]["result"] == "test_failure"
        assert "AssertionError" in entries[0].get("detail", "")

    def test_failure_detail_truncated(self, tmp_path):
        ledger = Ledger(tmp_path / "outcomes.jsonl")
        handler = OutcomeHandler(ledger)
        long_output = "X" * 1000
        handler.on_tests_failed(block_id="long", session_id="s1", output=long_output)
        entries = ledger.read_all()
        assert len(entries[0]["detail"]) == 500

    def test_session_id_recorded(self, tmp_path):
        ledger = Ledger(tmp_path / "outcomes.jsonl")
        handler = OutcomeHandler(ledger)
        handler.on_block_submitted(block_id="sess", session_id="session-42", depends_on=[])
        entries = ledger.read_all()
        assert entries[0]["session_id"] == "session-42"

    def test_capabilities_recorded(self, tmp_path):
        ledger = Ledger(tmp_path / "outcomes.jsonl")
        handler = OutcomeHandler(ledger)
        handler.on_block_submitted(
            block_id="multi", session_id="s1",
            depends_on=[], capabilities=["search.vector", "storage.kv"])
        entries = ledger.read_all()
        assert entries[0]["capabilities"] == ["search.vector", "storage.kv"]

    def test_hash_chain_integrity(self, tmp_path):
        ledger = Ledger(tmp_path / "outcomes.jsonl")
        handler = OutcomeHandler(ledger)
        handler.on_block_submitted(block_id="a", session_id="s1", depends_on=[])
        handler.on_tests_failed(block_id="b", session_id="s2", output="fail")
        handler.on_block_submitted(block_id="c", session_id="s3", depends_on=[])
        assert ledger.verify() is True

    def test_extra_kwargs_ignored(self, tmp_path):
        ledger = Ledger(tmp_path / "outcomes.jsonl")
        handler = OutcomeHandler(ledger)
        handler.on_block_submitted(
            block_id="ok", session_id="s1", depends_on=[], extra_field="ignored")
        handler.on_tests_failed(
            block_id="fail", session_id="s1", output="err", extra_field="ignored")
        assert len(ledger.read_all()) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/apps/ratchet/test_handlers.py -v`

- [ ] **Step 3: Write handlers.py**

```python
# apps/ratchet/handlers.py
"""Event handlers — stats tracking, tier promotion, outcome recording.

These handlers subscribe to ratchet's internal sync EventBus. They fire
synchronously during submit/compose operations. OutcomeHandler writes
to the platform Ledger instead of a standalone JSONL file.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from apps.ratchet.graph import BlockGraph
from kplatform.ledger import Ledger

log = logging.getLogger(__name__)

# Trust score below this threshold blocks tier promotion
TRUST_THROTTLE = 0.4


class StatsHandler:
    """Tracks block usage and failure statistics."""

    def __init__(self, graph: BlockGraph) -> None:
        self._graph = graph

    def on_block_submitted(self, block_id: str, depends_on: list[str] | None = None, **_) -> None:
        self._bump_deps(depends_on or [])

    def on_block_composed(self, block_id: str, depends_on: list[str] | None = None, **_) -> None:
        self._bump_deps(depends_on or [])

    def on_tests_failed(self, block_id: str, **_) -> None:
        block = self._graph.get(block_id)
        if block is None:
            return
        block.stats.failures += 1
        block.save()
        self._graph.upsert(block)

    def _bump_deps(self, depends_on: list[str]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for dep_id in depends_on:
            block = self._graph.get(dep_id)
            if block is None:
                continue
            block.stats.uses += 1
            block.stats.last_used = now
            block.save()
            self._graph.upsert(block)


class TierHandler:
    """Promotes block tiers based on usage, survival, and trust."""

    def __init__(self, graph: BlockGraph) -> None:
        self._graph = graph

    def _trust_ok(self, block) -> bool:
        """Return True if the block's trust score allows promotion."""
        if block.trust_score is None:
            return True
        if block.trust_score < TRUST_THROTTLE:
            log.info("Trust gate: %s blocked (score=%.2f < %.2f)",
                     block.id, block.trust_score, TRUST_THROTTLE)
            return False
        return True

    def on_block_composed(self, block_id: str, depends_on: list[str] | None = None, **_) -> None:
        """Promote dependencies to VALIDATED (tier 2) when used in a composition."""
        for dep_id in (depends_on or []):
            block = self._graph.get(dep_id)
            if block is None:
                continue
            if block.tier < 2 and self._trust_ok(block):
                block.tier = 2
                block.save()
                self._graph.upsert(block)

    def on_tests_failed(self, block_id: str, **_) -> None:
        """Promote surviving siblings to BATTLE_TESTED (tier 3) when a neighbor fails."""
        composites = self._graph.dependents_of(block_id)
        for comp_id in composites:
            comp = self._graph.get(comp_id)
            if comp is None:
                continue
            for sibling_id in comp.depends_on:
                if sibling_id == block_id:
                    continue
                sibling = self._graph.get(sibling_id)
                if (sibling and sibling.tier == 2
                        and sibling.stats.failures == 0
                        and self._trust_ok(sibling)):
                    sibling.tier = 3
                    sibling.save()
                    self._graph.upsert(sibling)


class OutcomeHandler:
    """Records block submission outcomes to platform Ledger.

    Replaces the standalone outcomes.jsonl from block-ratchet.
    Outcomes are hash-chained and tamper-evident via Ledger.
    """

    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    def on_block_submitted(self, block_id: str, session_id: str,
                           depends_on: list[str] | None = None,
                           capabilities: list[str] | None = None, **_) -> None:
        self._ledger.append({
            "event": "block.outcome",
            "block_id": block_id,
            "session_id": session_id,
            "result": "success",
            "capabilities": capabilities or [],
        })

    def on_tests_failed(self, block_id: str, session_id: str = "",
                        output: str = "",
                        capabilities: list[str] | None = None, **_) -> None:
        self._ledger.append({
            "event": "block.outcome",
            "block_id": block_id,
            "session_id": session_id,
            "result": "test_failure",
            "detail": output[:500],
            "capabilities": capabilities or [],
        })
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/apps/ratchet/test_handlers.py -v`
Expected: All 17 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/kairos/Projects/kairos
git add apps/ratchet/handlers.py tests/apps/ratchet/test_handlers.py
git commit -m "feat(ratchet): stats, tier promotion, and outcome handlers (Ledger-backed)"
```

---

### Task 6: Worker + Integration

**Files:**
- Create: `apps/ratchet/worker.py`
- Create: `tests/apps/ratchet/test_integration.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/apps/ratchet/test_integration.py
"""Integration tests — full block lifecycle through the ratchet."""
import json
from collections import defaultdict
from pathlib import Path

import pytest

from apps.ratchet.graph import Block, BlockGraph
from apps.ratchet.coordinator import Coordinator
from apps.ratchet.capabilities import CapabilityMatcher
from apps.ratchet.handlers import StatsHandler, TierHandler, OutcomeHandler
from apps.ratchet.worker import EventBus, BLOCK_SUBMITTED, BLOCK_COMPOSED, TESTS_FAILED
from kplatform.ledger import Ledger
from tests.apps.ratchet.conftest import make_block_dir


@pytest.fixture
def ratchet_system(tmp_path):
    """Set up a complete ratchet system with blocks dir, handlers, and bus."""
    blocks_dir = tmp_path / "blocks"
    blocks_dir.mkdir()

    graph = BlockGraph(blocks_dir)
    coordinator = Coordinator()
    ledger = Ledger(tmp_path / "outcomes.jsonl")

    bus = EventBus()
    stats = StatsHandler(graph)
    tiers = TierHandler(graph)
    outcomes = OutcomeHandler(ledger)

    bus.subscribe(BLOCK_SUBMITTED, stats.on_block_submitted)
    bus.subscribe(BLOCK_COMPOSED, stats.on_block_composed)
    bus.subscribe(TESTS_FAILED, stats.on_tests_failed)
    bus.subscribe(BLOCK_COMPOSED, tiers.on_block_composed)
    bus.subscribe(TESTS_FAILED, tiers.on_tests_failed)
    bus.subscribe(BLOCK_SUBMITTED, outcomes.on_block_submitted)
    bus.subscribe(TESTS_FAILED, outcomes.on_tests_failed)

    return {
        "blocks_dir": blocks_dir,
        "graph": graph,
        "coordinator": coordinator,
        "ledger": ledger,
        "bus": bus,
        "matcher": CapabilityMatcher(graph, blocks_dir),
    }


class TestEventBus:
    def test_subscribe_and_emit(self):
        bus = EventBus()
        received = []
        bus.subscribe("test_event", lambda **kw: received.append(kw))
        bus.emit("test_event", block_id="abc")
        assert received == [{"block_id": "abc"}]

    def test_multiple_handlers_called_in_order(self):
        bus = EventBus()
        order = []
        bus.subscribe("evt", lambda **_: order.append("first"))
        bus.subscribe("evt", lambda **_: order.append("second"))
        bus.emit("evt")
        assert order == ["first", "second"]

    def test_handler_error_does_not_block_others(self):
        bus = EventBus()
        order = []

        def bad_handler(**_):
            raise RuntimeError("handler crashed")

        bus.subscribe("evt", lambda **_: order.append("first"))
        bus.subscribe("evt", bad_handler)
        bus.subscribe("evt", lambda **_: order.append("third"))
        bus.emit("evt")
        assert order == ["first", "third"]

    def test_emit_unknown_event_is_noop(self):
        bus = EventBus()
        bus.emit("nonexistent", x=1)


class TestFullLifecycle:
    def test_submit_compose_promote(self, ratchet_system):
        """Full lifecycle: submit blocks -> compose -> tier promoted -> outcomes recorded."""
        sys = ratchet_system
        blocks_dir = sys["blocks_dir"]
        graph = sys["graph"]
        bus = sys["bus"]

        # Create two leaf blocks
        for name, caps in [("http-client", ["networking.http"]),
                           ("json-parser", ["parsing.json"])]:
            d = make_block_dir(blocks_dir, name, capabilities=caps)
        graph.rescan()

        # Submit events
        bus.emit(BLOCK_SUBMITTED, block_id="http-client",
                 session_id="s1", depends_on=[], capabilities=["networking.http"])
        bus.emit(BLOCK_SUBMITTED, block_id="json-parser",
                 session_id="s2", depends_on=[], capabilities=["parsing.json"])

        # Compose: creates a composite that depends on both
        make_block_dir(blocks_dir, "api-client",
                       depends_on=["http-client", "json-parser"])
        graph.rescan()
        bus.emit(BLOCK_COMPOSED, block_id="api-client",
                 depends_on=["http-client", "json-parser"])

        # Dependencies promoted to VALIDATED (tier 2)
        assert graph.get("http-client").tier == 2
        assert graph.get("json-parser").tier == 2

        # Stats bumped
        assert graph.get("http-client").stats.uses == 1
        assert graph.get("json-parser").stats.uses == 1

        # Outcomes recorded in ledger
        entries = sys["ledger"].read_all()
        assert len(entries) == 2  # two submissions
        assert sys["ledger"].verify() is True

    def test_failure_promotes_survivor(self, ratchet_system):
        """Sibling survival: when one block fails, surviving siblings get BATTLE_TESTED."""
        sys = ratchet_system
        blocks_dir = sys["blocks_dir"]
        graph = sys["graph"]
        bus = sys["bus"]

        make_block_dir(blocks_dir, "good", tier=2, failures=0)
        make_block_dir(blocks_dir, "bad", tier=2, failures=0)
        make_block_dir(blocks_dir, "comp", depends_on=["good", "bad"], tier=1)
        graph.rescan()

        bus.emit(TESTS_FAILED, block_id="bad", session_id="s1", output="AssertionError")

        assert graph.get("good").tier == 3  # BATTLE_TESTED
        assert graph.get("bad").stats.failures == 1

        # Failure recorded in ledger
        entries = sys["ledger"].read_all()
        assert len(entries) == 1
        assert entries[0]["result"] == "test_failure"

    def test_claim_submit_release_flow(self, ratchet_system):
        """Coordinator integrates with the lifecycle."""
        sys = ratchet_system
        coordinator = sys["coordinator"]

        claim = coordinator.claim_gap("s1", "Build auth handler")
        assert claim is not None

        # Cannot double-claim
        assert coordinator.claim_gap("s2", "Build auth handler") is None
        assert coordinator.claim_gap("s1", "Build something else") is None

        coordinator.release_claim("s1")

        # Now available
        claim2 = coordinator.claim_gap("s2", "Build auth handler")
        assert claim2 is not None

    def test_capability_matching_after_submit(self, ratchet_system):
        """Capabilities are matchable after blocks are registered."""
        sys = ratchet_system
        blocks_dir = sys["blocks_dir"]
        graph = sys["graph"]
        matcher = sys["matcher"]

        make_block_dir(blocks_dir, "vec", capabilities=["search.vector"])
        make_block_dir(blocks_dir, "emb", capabilities=["embedding.text-to-vector"])
        graph.rescan()

        matches, gaps = matcher.match(["search", "embedding", "auth"])
        by_cap = {m["capability"]: m["block_ids"] for m in matches}
        assert "vec" in by_cap["search"]
        assert "emb" in by_cap["embedding"]
        assert gaps == ["auth"]

    def test_effective_tier_capped_by_deps(self, ratchet_system):
        """Composite's effective tier is capped by its weakest dependency."""
        sys = ratchet_system
        blocks_dir = sys["blocks_dir"]
        graph = sys["graph"]
        bus = sys["bus"]

        make_block_dir(blocks_dir, "strong", tier=3)
        make_block_dir(blocks_dir, "weak", tier=1)
        make_block_dir(blocks_dir, "comp", depends_on=["strong", "weak"], tier=2)
        graph.rescan()

        assert graph.effective_tier("comp") == 1  # capped by weak

    def test_ledger_audit_trail_integrity(self, ratchet_system):
        """Multiple operations produce a valid hash-chained ledger."""
        sys = ratchet_system
        blocks_dir = sys["blocks_dir"]
        graph = sys["graph"]
        bus = sys["bus"]
        ledger = sys["ledger"]

        make_block_dir(blocks_dir, "a")
        make_block_dir(blocks_dir, "b")
        graph.rescan()

        bus.emit(BLOCK_SUBMITTED, block_id="a", session_id="s1",
                 depends_on=[], capabilities=[])
        bus.emit(BLOCK_SUBMITTED, block_id="b", session_id="s2",
                 depends_on=["a"], capabilities=[])
        bus.emit(TESTS_FAILED, block_id="b", session_id="s2", output="error")
        bus.emit(BLOCK_SUBMITTED, block_id="b", session_id="s3",
                 depends_on=["a"], capabilities=[])

        entries = ledger.read_all()
        assert len(entries) == 4
        assert ledger.verify() is True

        # Check hash chain
        for i in range(1, len(entries)):
            assert entries[i]["prev_hash"] == entries[i - 1]["hash"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/apps/ratchet/test_integration.py -v`

- [ ] **Step 3: Write worker.py**

```python
# apps/ratchet/worker.py
"""Ratchet worker — block lifecycle MCP service.

Contains the sync EventBus for internal handler dispatch and the
RatchetWorker class that wires everything together. The worker publishes
to the platform Bus for cross-worker communication after internal
handlers have run.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Callable

from apps.ratchet.graph import BlockGraph
from apps.ratchet.coordinator import Coordinator
from apps.ratchet.capabilities import CapabilityMatcher
from apps.ratchet.handlers import StatsHandler, TierHandler, OutcomeHandler
from kplatform.ledger import Ledger

log = logging.getLogger(__name__)

# Event types
BLOCK_SUBMITTED = "block_submitted"
BLOCK_COMPOSED = "block_composed"
TESTS_FAILED = "tests_failed"


class EventBus:
    """Lightweight sync event bus. Handlers called in registration order.

    This is ratchet's internal bus — not the platform Bus. It fires
    synchronously during submit/compose so handlers can update state
    before the tool returns.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Callable) -> None:
        self._handlers[event_type].append(handler)

    def emit(self, event_type: str, **payload) -> None:
        for handler in self._handlers.get(event_type, []):
            try:
                handler(**payload)
            except Exception:
                log.exception("Handler %s failed for event %s", handler, event_type)


class RatchetWorker:
    """Wires graph, coordinator, handlers, and bus into a single service.

    Intended to run as a long-lived MCP service. Platform Bus integration
    (cross-worker publishing) is handled by the caller — this class focuses
    on the internal lifecycle.
    """

    def __init__(self, blocks_dir: Path, ledger: Ledger) -> None:
        self._blocks_dir = blocks_dir
        self._graph = BlockGraph(blocks_dir)
        self._coordinator = Coordinator()
        self._bus = EventBus()
        self._ledger = ledger
        self._capability_matcher = CapabilityMatcher(self._graph, blocks_dir)

        # Wire handlers
        stats = StatsHandler(self._graph)
        tiers = TierHandler(self._graph)
        outcomes = OutcomeHandler(self._ledger)

        self._bus.subscribe(BLOCK_SUBMITTED, stats.on_block_submitted)
        self._bus.subscribe(BLOCK_COMPOSED, stats.on_block_composed)
        self._bus.subscribe(TESTS_FAILED, stats.on_tests_failed)
        self._bus.subscribe(BLOCK_COMPOSED, tiers.on_block_composed)
        self._bus.subscribe(TESTS_FAILED, tiers.on_tests_failed)
        self._bus.subscribe(BLOCK_SUBMITTED, outcomes.on_block_submitted)
        self._bus.subscribe(TESTS_FAILED, outcomes.on_tests_failed)

    @property
    def graph(self) -> BlockGraph:
        return self._graph

    @property
    def coordinator(self) -> Coordinator:
        return self._coordinator

    @property
    def bus(self) -> EventBus:
        return self._bus

    @property
    def capability_matcher(self) -> CapabilityMatcher:
        return self._capability_matcher
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/apps/ratchet/test_integration.py -v`
Expected: All 11 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/kairos/Projects/kairos
git add apps/ratchet/worker.py tests/apps/ratchet/test_integration.py
git commit -m "feat(ratchet): worker entrypoint and full lifecycle integration tests"
```

---

### Task 7: Package Exports + Verification

**Files:**
- Modify: `apps/ratchet/__init__.py`
- Create: `apps/ratchet/CLAUDE.md`

- [ ] **Step 1: Update __init__.py with exports**

```python
# apps/ratchet/__init__.py
"""Block lifecycle management — claim, build, validate, submit, promote."""

from apps.ratchet.graph import Block, BlockGraph, BlockStats
from apps.ratchet.coordinator import Coordinator
from apps.ratchet.worker import RatchetWorker, EventBus

__all__ = [
    "Block",
    "BlockGraph",
    "BlockStats",
    "Coordinator",
    "RatchetWorker",
    "EventBus",
]
```

- [ ] **Step 2: Write CLAUDE.md**

The CLAUDE.md should describe the ratchet app's purpose, file layout, how to run tests, and key APIs. Content depends on what conventions are established in the kairos monorepo.

- [ ] **Step 3: Run full ratchet test suite**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/apps/ratchet/ -v --tb=short`
Expected: All ~53 tests PASS

- [ ] **Step 4: Verify imports**

```bash
cd /Users/kairos/Projects/kairos && uv run python -c "
from apps.ratchet import Block, BlockGraph, Coordinator, RatchetWorker, EventBus
from apps.ratchet.validators import validate_contract, validate_events, validate_isolation
from apps.ratchet.capabilities import CapabilityMatcher
from apps.ratchet.handlers import StatsHandler, TierHandler, OutcomeHandler
print('All ratchet imports OK')
"
```

- [ ] **Step 5: Run full kairos test suite**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/ -v --tb=short`
Expected: All tests PASS (memory 53 + bus 11 + ledger 8 + bridge 7 + LLM + sandbox + runtime + ratchet ~53 = all green)

- [ ] **Step 6: Commit**

```bash
cd /Users/kairos/Projects/kairos
git add apps/ratchet/
git commit -m "feat(ratchet): package exports, CLAUDE.md, full verification"
```

---

## Summary

| Task | What | Tests |
|------|------|-------|
| 1 | Block model + BlockGraph with effective_tier | ~20 |
| 2 | Session coordinator with claim/release and stale timeout | ~9 |
| 3 | Three-stage validators (contract, events, isolation) | ~13 |
| 4 | Capability taxonomy matching with prefix search | ~12 |
| 5 | Handlers: stats, tiers, outcomes (Ledger-backed) | ~17 |
| 6 | Worker + full lifecycle integration | ~11 |
| 7 | Package exports + verification | ~2 |
| **Total** | **7 tasks** | **~84 tests** |

## Key Differences from Source

| Aspect | block-ratchet (source) | apps/ratchet (kairos) |
|--------|----------------------|----------------------|
| Outcomes | Own `outcomes.jsonl` via `OutcomeHandler` | Platform `Ledger` (hash-chained, tamper-evident) |
| Event bus | Own `events.py` `EventBus` | Internal sync EventBus preserved; platform `Bus` for cross-worker |
| Handlers | Four files in `handlers/` | Consolidated into `handlers.py` + `capabilities.py` |
| Imports | `from graph import Block` | `from apps.ratchet.graph import Block` |
| Seed | `seed.py` bootstrap | Not ported (reference only) |
| MCP server | `server.py` with FastMCP | `worker.py` (MCP registration deferred to plugins plan) |
| Test runner | Subprocess pytest in `_run_block_tests()` | Not in scope — stays in MCP tool layer |

## Next Plans

After this plan is complete:
1. **Apps: Atlas** — research engine (from claw)
2. **Apps: Arena** — goal execution (from agi)
3. **Apps: Governor** — observe and decide (from why)
4. **Plugins: ratchet** — MCP plugin wrapping apps/ratchet for Claude Code
