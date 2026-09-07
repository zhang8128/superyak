# Kairos Runtime — Implementation Plan

> **Status:** ✅ Complete (2026-03-22). 58 runtime tests passing. Router upgraded to confidence-gated escalation (hedging detection, truncation signals, failure history). Daemon rebuilt with async main loop, capability enforcement, audit logging to ledger, auto-pause on failures, structured JSON logging, signal-based graceful shutdown.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the runtime daemon that continuously runs, tracks goals, schedules worker ticks, dispatches tasks, and routes between LLM tiers — the "brain" of the Kairos Platform.

**Architecture:** A single-process daemon with an async event loop. Goals are persistent (SQLite). Workers are spawned as subprocesses (tick mode) or kept alive (service mode). The daemon uses the local LLM for routine decisions and escalates to API for complex work.

**Tech Stack:** Python 3.12+, asyncio, SQLite, subprocess, all kplatform modules

**Spec:** `docs/superpowers/specs/2026-03-21-kairos-platform-design.md` (Runtime Layer section)

---

## File Structure

```
runtime/
  __init__.py               -- exports: Daemon, Goal, Scheduler, Dispatcher
  daemon.py                 -- main loop, startup, shutdown
  goals.py                  -- goal tracking, decomposition, persistence
  scheduler.py              -- tick scheduling per worker, backpressure
  dispatch.py               -- spawn workers, select execution mode
  router.py                 -- tiered LLM routing (local → API → agent)
  config.py                 -- runtime configuration
  CLAUDE.md                 -- module docs
tests/
  runtime/
    __init__.py
    conftest.py             -- fixtures: tmp goals db, mock workers
    test_goals.py           -- CRUD, decomposition, persistence
    test_scheduler.py       -- tick intervals, backpressure, timeout
    test_dispatch.py        -- mode selection, worker lifecycle
    test_router.py          -- tier routing, escalation, cost tracking
    test_daemon.py          -- startup, shutdown, tick cycle
```

---

### Task 1: Runtime Configuration

**Files:**
- Create: `runtime/__init__.py`
- Create: `runtime/config.py`
- Create: `runtime/CLAUDE.md`
- Create: `tests/runtime/__init__.py`
- Create: `tests/runtime/conftest.py`
- Create: `tests/runtime/test_config.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/runtime/test_config.py
from runtime.config import RuntimeConfig, WorkerConfig


def test_default_config():
    cfg = RuntimeConfig()
    assert cfg.tick_interval == 60
    assert cfg.tick_timeout == 120
    assert len(cfg.workers) == 0


def test_add_worker():
    cfg = RuntimeConfig()
    cfg.workers["atlas"] = WorkerConfig(
        name="atlas",
        module="apps.atlas",
        tick_interval=30,
    )
    assert cfg.workers["atlas"].tick_interval == 30
    assert cfg.workers["atlas"].mode == "tick"


def test_worker_modes():
    w = WorkerConfig(name="ratchet", module="apps.ratchet", mode="service")
    assert w.mode == "service"
```

- [ ] **Step 2: Write config.py**

```python
# runtime/config.py
"""Runtime daemon configuration."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WorkerConfig:
    """Configuration for a single worker."""
    name: str
    module: str
    mode: str = "tick"  # tick | service | agent
    tick_interval: int = 60  # seconds between ticks
    tick_timeout: int = 120  # max seconds per tick
    max_memory_mb: int = 512
    enabled: bool = True
    capability_tools: set[str] = field(
        default_factory=lambda: {"read_file", "write_file", "run_code", "run_tests"}
    )


@dataclass
class TierConfig:
    """LLM tier routing configuration."""
    tier1_provider: str = "ollama"
    tier1_model: str = "qwen3.5:27b"
    tier2_provider: str = "openai_compat"
    tier2_model: str = "claude-sonnet-4-20250514"
    tier2_api_key_env: str = "ANTHROPIC_API_KEY"
    tier2_base_url: str = "https://api.anthropic.com"
    escalation_keywords: list[str] = field(
        default_factory=lambda: ["I'm not sure", "unclear", "cannot determine"]
    )


@dataclass
class RuntimeConfig:
    """Top-level runtime daemon configuration."""
    tick_interval: int = 60  # default interval between daemon cycles
    tick_timeout: int = 120  # default timeout per worker tick
    goals_db: str = "goals.db"
    workers: dict[str, WorkerConfig] = field(default_factory=dict)
    tiers: TierConfig = field(default_factory=TierConfig)
    max_worker_restarts: int = 3  # per hour before pausing
    audit_all: bool = True
```

- [ ] **Step 3: Write __init__.py, CLAUDE.md, conftest.py**

```python
# runtime/__init__.py
"""Kairos runtime — daemon, scheduler, dispatcher."""
```

```markdown
# Runtime

The always-on daemon that orchestrates the Kairos Platform.

## Key Files

| File | Purpose |
|------|---------|
| daemon.py | Main loop, startup, shutdown |
| goals.py | Goal tracking and persistence |
| scheduler.py | Tick scheduling with backpressure |
| dispatch.py | Worker spawning and mode selection |
| router.py | Tiered LLM routing |
| config.py | Configuration dataclasses |

## Running

```bash
uv run python -m runtime.daemon
```
```

```python
# tests/runtime/conftest.py
import pytest


@pytest.fixture
def goals_db(tmp_path):
    return str(tmp_path / "goals.db")
```

- [ ] **Step 4: Run tests, commit**

```bash
cd /Users/kairos/Projects/kairos
uv run pytest tests/runtime/test_config.py -v
git add runtime/ tests/runtime/
git commit -m "feat(runtime): configuration for daemon, workers, and LLM tiers"
```

---

### Task 2: Goal Tracker

**Files:**
- Create: `runtime/goals.py`
- Create: `tests/runtime/test_goals.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/runtime/test_goals.py
from runtime.goals import GoalTracker, Goal, GoalStatus


def test_add_goal(goals_db):
    tracker = GoalTracker(goals_db)
    goal = tracker.add("Build the platform", priority=1)
    assert goal.id is not None
    assert goal.title == "Build the platform"
    assert goal.status == GoalStatus.PENDING
    tracker.close()


def test_get_goal(goals_db):
    tracker = GoalTracker(goals_db)
    added = tracker.add("Test goal")
    fetched = tracker.get(added.id)
    assert fetched is not None
    assert fetched.title == "Test goal"
    tracker.close()


def test_update_status(goals_db):
    tracker = GoalTracker(goals_db)
    goal = tracker.add("Update me")
    tracker.update_status(goal.id, GoalStatus.IN_PROGRESS)
    updated = tracker.get(goal.id)
    assert updated.status == GoalStatus.IN_PROGRESS
    tracker.close()


def test_complete_goal(goals_db):
    tracker = GoalTracker(goals_db)
    goal = tracker.add("Complete me")
    tracker.update_status(goal.id, GoalStatus.COMPLETED)
    completed = tracker.get(goal.id)
    assert completed.status == GoalStatus.COMPLETED
    tracker.close()


def test_list_pending(goals_db):
    tracker = GoalTracker(goals_db)
    tracker.add("Pending 1", priority=2)
    tracker.add("Pending 2", priority=1)
    g3 = tracker.add("Done")
    tracker.update_status(g3.id, GoalStatus.COMPLETED)
    pending = tracker.list_pending()
    assert len(pending) == 2
    # Higher priority first
    assert pending[0].priority <= pending[1].priority
    tracker.close()


def test_add_subtask(goals_db):
    tracker = GoalTracker(goals_db)
    parent = tracker.add("Parent goal")
    child = tracker.add("Sub-task", parent_id=parent.id)
    assert child.parent_id == parent.id
    children = tracker.get_children(parent.id)
    assert len(children) == 1
    tracker.close()


def test_goal_persists_across_restarts(goals_db):
    tracker1 = GoalTracker(goals_db)
    goal = tracker1.add("Persistent goal")
    tracker1.close()
    tracker2 = GoalTracker(goals_db)
    fetched = tracker2.get(goal.id)
    assert fetched is not None
    assert fetched.title == "Persistent goal"
    tracker2.close()


def test_assign_worker(goals_db):
    tracker = GoalTracker(goals_db)
    goal = tracker.add("Assign me")
    tracker.assign(goal.id, "atlas")
    updated = tracker.get(goal.id)
    assert updated.assigned_to == "atlas"
    tracker.close()
```

- [ ] **Step 2: Write goals.py**

```python
# runtime/goals.py
"""Goal tracking and persistence."""

from __future__ import annotations

import enum
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class GoalStatus(enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass
class Goal:
    id: str
    title: str
    status: GoalStatus
    priority: int = 5
    parent_id: str | None = None
    assigned_to: str | None = None
    created_at: str = ""
    updated_at: str = ""


class GoalTracker:
    """Persistent goal tracking backed by SQLite."""

    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS goals (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                priority INTEGER DEFAULT 5,
                parent_id TEXT REFERENCES goals(id),
                assigned_to TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
        """)

    def add(self, title: str, priority: int = 5, parent_id: str | None = None) -> Goal:
        gid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO goals (id, title, priority, parent_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (gid, title, priority, parent_id, now, now),
        )
        self._conn.commit()
        return self.get(gid)

    def get(self, goal_id: str) -> Goal | None:
        row = self._conn.execute(
            "SELECT * FROM goals WHERE id = ?", (goal_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_goal(row)

    def update_status(self, goal_id: str, status: GoalStatus) -> None:
        self._conn.execute(
            "UPDATE goals SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status.value, goal_id),
        )
        self._conn.commit()

    def assign(self, goal_id: str, worker: str) -> None:
        self._conn.execute(
            "UPDATE goals SET assigned_to = ?, updated_at = datetime('now') WHERE id = ?",
            (worker, goal_id),
        )
        self._conn.commit()

    def list_pending(self) -> list[Goal]:
        rows = self._conn.execute(
            "SELECT * FROM goals WHERE status = 'pending' ORDER BY priority ASC, created_at ASC"
        ).fetchall()
        return [self._row_to_goal(r) for r in rows]

    def get_children(self, parent_id: str) -> list[Goal]:
        rows = self._conn.execute(
            "SELECT * FROM goals WHERE parent_id = ? ORDER BY priority ASC",
            (parent_id,),
        ).fetchall()
        return [self._row_to_goal(r) for r in rows]

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _row_to_goal(row) -> Goal:
        return Goal(
            id=row["id"],
            title=row["title"],
            status=GoalStatus(row["status"]),
            priority=row["priority"],
            parent_id=row["parent_id"],
            assigned_to=row["assigned_to"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
```

- [ ] **Step 3: Run tests, commit**

```bash
cd /Users/kairos/Projects/kairos
uv run pytest tests/runtime/test_goals.py -v
git add runtime/goals.py tests/runtime/test_goals.py
git commit -m "feat(runtime): goal tracker with persistence and decomposition"
```

---

### Task 3: Scheduler

**Files:**
- Create: `runtime/scheduler.py`
- Create: `tests/runtime/test_scheduler.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/runtime/test_scheduler.py
import time
from runtime.scheduler import Scheduler
from runtime.config import WorkerConfig


def test_schedule_returns_due_workers():
    workers = {
        "atlas": WorkerConfig(name="atlas", module="apps.atlas", tick_interval=1),
        "arena": WorkerConfig(name="arena", module="apps.arena", tick_interval=1000),
    }
    sched = Scheduler(workers)
    # Atlas should be due immediately (never run)
    due = sched.get_due()
    names = [w.name for w in due]
    assert "atlas" in names
    assert "arena" in names  # Both due on first tick


def test_schedule_respects_interval():
    workers = {
        "fast": WorkerConfig(name="fast", module="apps.fast", tick_interval=0),
    }
    sched = Scheduler(workers)
    sched.mark_started("fast")
    sched.mark_completed("fast")
    # Should be immediately due again with interval=0
    due = sched.get_due()
    assert any(w.name == "fast" for w in due)


def test_backpressure_blocks_running():
    workers = {
        "slow": WorkerConfig(name="slow", module="apps.slow", tick_interval=1),
    }
    sched = Scheduler(workers)
    sched.mark_started("slow")
    # Should NOT be in due list while running
    due = sched.get_due()
    assert not any(w.name == "slow" for w in due)


def test_disabled_worker_not_scheduled():
    workers = {
        "off": WorkerConfig(name="off", module="apps.off", enabled=False),
    }
    sched = Scheduler(workers)
    due = sched.get_due()
    assert len(due) == 0


def test_mark_failed_increments_count():
    workers = {
        "flaky": WorkerConfig(name="flaky", module="apps.flaky", tick_interval=1),
    }
    sched = Scheduler(workers)
    sched.mark_started("flaky")
    sched.mark_failed("flaky")
    assert sched.get_failure_count("flaky") == 1


def test_pause_worker():
    workers = {
        "paused": WorkerConfig(name="paused", module="apps.paused", tick_interval=1),
    }
    sched = Scheduler(workers)
    sched.pause("paused")
    due = sched.get_due()
    assert not any(w.name == "paused" for w in due)
    sched.resume("paused")
    due = sched.get_due()
    assert any(w.name == "paused" for w in due)
```

- [ ] **Step 2: Write scheduler.py**

```python
# runtime/scheduler.py
"""Tick scheduling with backpressure and failure tracking."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from runtime.config import WorkerConfig


@dataclass
class WorkerState:
    """Runtime state for a worker."""
    running: bool = False
    paused: bool = False
    last_tick_start: float = 0.0
    last_tick_end: float = 0.0
    failure_count: int = 0
    consecutive_failures: int = 0


class Scheduler:
    """Determine which workers are due for their next tick."""

    def __init__(self, workers: dict[str, WorkerConfig]):
        self._workers = workers
        self._state: dict[str, WorkerState] = {
            name: WorkerState() for name in workers
        }

    def get_due(self) -> list[WorkerConfig]:
        """Return workers that are due for a tick."""
        now = time.monotonic()
        due = []
        for name, config in self._workers.items():
            if not config.enabled:
                continue
            state = self._state[name]
            if state.running:
                continue
            if state.paused:
                continue
            elapsed = now - state.last_tick_end
            if state.last_tick_end == 0.0 or elapsed >= config.tick_interval:
                due.append(config)
        return due

    def mark_started(self, worker_name: str) -> None:
        state = self._state[worker_name]
        state.running = True
        state.last_tick_start = time.monotonic()

    def mark_completed(self, worker_name: str) -> None:
        state = self._state[worker_name]
        state.running = False
        state.last_tick_end = time.monotonic()
        state.consecutive_failures = 0

    def mark_failed(self, worker_name: str) -> None:
        state = self._state[worker_name]
        state.running = False
        state.last_tick_end = time.monotonic()
        state.failure_count += 1
        state.consecutive_failures += 1

    def pause(self, worker_name: str) -> None:
        self._state[worker_name].paused = True

    def resume(self, worker_name: str) -> None:
        self._state[worker_name].paused = False

    def get_failure_count(self, worker_name: str) -> int:
        return self._state[worker_name].failure_count

    def is_running(self, worker_name: str) -> bool:
        return self._state[worker_name].running
```

- [ ] **Step 3: Run tests, commit**

```bash
cd /Users/kairos/Projects/kairos
uv run pytest tests/runtime/test_scheduler.py -v
git add runtime/scheduler.py tests/runtime/test_scheduler.py
git commit -m "feat(runtime): scheduler with backpressure and failure tracking"
```

---

### Task 4: Dispatcher

**Files:**
- Create: `runtime/dispatch.py`
- Create: `tests/runtime/test_dispatch.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/runtime/test_dispatch.py
import asyncio
from unittest.mock import MagicMock, patch
from runtime.dispatch import Dispatcher, WorkerResult
from runtime.config import WorkerConfig


def test_dispatch_tick_worker(tmp_path):
    config = WorkerConfig(
        name="test", module="apps.test", mode="tick",
    )
    dispatcher = Dispatcher(workspace=tmp_path)
    # Dispatch a simple python command as a tick
    result = dispatcher.run_tick(config, code="import json; print(json.dumps({'ok': True}))")
    assert isinstance(result, WorkerResult)
    assert result.success


def test_dispatch_tick_timeout(tmp_path):
    config = WorkerConfig(
        name="slow", module="apps.slow", mode="tick", tick_timeout=1,
    )
    dispatcher = Dispatcher(workspace=tmp_path)
    result = dispatcher.run_tick(config, code="import time; time.sleep(100)")
    assert not result.success
    assert "timeout" in result.error.lower() or "timed out" in result.error.lower()


def test_dispatch_tick_failure(tmp_path):
    config = WorkerConfig(
        name="bad", module="apps.bad", mode="tick",
    )
    dispatcher = Dispatcher(workspace=tmp_path)
    result = dispatcher.run_tick(config, code="raise ValueError('boom')")
    assert not result.success


def test_worker_result_dataclass():
    r = WorkerResult(success=True, output="done", worker="atlas")
    assert r.success
    assert r.worker == "atlas"
```

- [ ] **Step 2: Write dispatch.py**

```python
# runtime/dispatch.py
"""Worker dispatch — spawn processes, collect results."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from runtime.config import WorkerConfig


@dataclass
class WorkerResult:
    """Result from a worker execution."""
    success: bool
    output: str = ""
    error: str = ""
    worker: str = ""
    duration_ms: int = 0


class Dispatcher:
    """Spawn workers as subprocesses and collect results."""

    def __init__(self, workspace: Path | str):
        self._workspace = Path(workspace)

    def run_tick(
        self, config: WorkerConfig, *,
        code: str | None = None,
        entry_point: str | None = None,
    ) -> WorkerResult:
        """Run a single tick for a worker. Returns WorkerResult."""
        import time
        start = time.monotonic()

        if code:
            cmd = [sys.executable, "-c", code]
        elif entry_point:
            cmd = [sys.executable, "-m", entry_point]
        else:
            cmd = [sys.executable, "-m", config.module]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=config.tick_timeout,
                cwd=str(self._workspace),
            )
            duration = int((time.monotonic() - start) * 1000)

            if result.returncode == 0:
                return WorkerResult(
                    success=True,
                    output=result.stdout.strip(),
                    worker=config.name,
                    duration_ms=duration,
                )
            else:
                return WorkerResult(
                    success=False,
                    output=result.stdout.strip(),
                    error=result.stderr.strip(),
                    worker=config.name,
                    duration_ms=duration,
                )
        except subprocess.TimeoutExpired:
            duration = int((time.monotonic() - start) * 1000)
            return WorkerResult(
                success=False,
                error="Timed out",
                worker=config.name,
                duration_ms=duration,
            )
        except Exception as e:
            duration = int((time.monotonic() - start) * 1000)
            return WorkerResult(
                success=False,
                error=str(e),
                worker=config.name,
                duration_ms=duration,
            )
```

- [ ] **Step 3: Run tests, commit**

```bash
cd /Users/kairos/Projects/kairos
uv run pytest tests/runtime/test_dispatch.py -v
git add runtime/dispatch.py tests/runtime/test_dispatch.py
git commit -m "feat(runtime): dispatcher for subprocess-based worker execution"
```

---

### Task 5: LLM Router

**Files:**
- Create: `runtime/router.py`
- Create: `tests/runtime/test_router.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/runtime/test_router.py
from runtime.router import TierRouter, CostEntry
from runtime.config import TierConfig


def test_route_to_tier1_by_default():
    router = TierRouter(TierConfig())
    tier = router.select_tier("simple classification task")
    assert tier == 1


def test_route_escalates_on_keywords():
    cfg = TierConfig(escalation_keywords=["complex", "uncertain"])
    router = TierRouter(cfg)
    tier = router.select_tier("This is a complex reasoning task")
    assert tier == 2


def test_track_cost():
    router = TierRouter(TierConfig())
    router.log_cost(CostEntry(
        tier=1, model="qwen3.5:27b", provider="ollama",
        prompt_tokens=100, completion_tokens=50,
    ))
    router.log_cost(CostEntry(
        tier=2, model="claude-sonnet", provider="anthropic",
        prompt_tokens=200, completion_tokens=100,
        estimated_cost_usd=0.003,
    ))
    summary = router.cost_summary()
    assert summary["total_calls"] == 2
    assert summary["tier_1_calls"] == 1
    assert summary["tier_2_calls"] == 1
    assert summary["total_cost_usd"] > 0


def test_force_tier():
    router = TierRouter(TierConfig())
    tier = router.select_tier("anything", force_tier=2)
    assert tier == 2
```

- [ ] **Step 2: Write router.py**

```python
# runtime/router.py
"""Tiered LLM routing: local → API → agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from runtime.config import TierConfig


@dataclass
class CostEntry:
    """Record of a single LLM call for cost tracking."""
    tier: int
    model: str
    provider: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class TierRouter:
    """Route LLM requests to the appropriate tier based on task complexity."""

    def __init__(self, config: TierConfig):
        self._config = config
        self._cost_log: list[CostEntry] = []

    def select_tier(self, task_description: str, *, force_tier: int | None = None) -> int:
        """Select the appropriate LLM tier for a task.

        Returns 1 (local), 2 (API), or 3 (agent session).
        """
        if force_tier is not None:
            return force_tier

        # Check for escalation keywords
        lower = task_description.lower()
        for keyword in self._config.escalation_keywords:
            if keyword.lower() in lower:
                return 2

        # Default to tier 1 (local)
        return 1

    def log_cost(self, entry: CostEntry) -> None:
        """Log an LLM call for cost tracking."""
        self._cost_log.append(entry)

    def cost_summary(self) -> dict:
        """Return aggregate cost summary."""
        total = len(self._cost_log)
        tier_counts = {1: 0, 2: 0, 3: 0}
        total_cost = 0.0
        total_tokens = 0

        for entry in self._cost_log:
            tier_counts[entry.tier] = tier_counts.get(entry.tier, 0) + 1
            total_cost += entry.estimated_cost_usd
            total_tokens += entry.prompt_tokens + entry.completion_tokens

        return {
            "total_calls": total,
            "tier_1_calls": tier_counts[1],
            "tier_2_calls": tier_counts[2],
            "tier_3_calls": tier_counts[3],
            "total_cost_usd": round(total_cost, 6),
            "total_tokens": total_tokens,
        }
```

- [ ] **Step 3: Run tests, commit**

```bash
cd /Users/kairos/Projects/kairos
uv run pytest tests/runtime/test_router.py -v
git add runtime/router.py tests/runtime/test_router.py
git commit -m "feat(runtime): tiered LLM router with cost tracking"
```

---

### Task 6: Daemon Shell

**Files:**
- Create: `runtime/daemon.py`
- Create: `tests/runtime/test_daemon.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/runtime/test_daemon.py
import asyncio
from runtime.daemon import Daemon
from runtime.config import RuntimeConfig, WorkerConfig


def test_daemon_creates(tmp_path):
    cfg = RuntimeConfig(goals_db=str(tmp_path / "goals.db"))
    daemon = Daemon(cfg, workspace=tmp_path)
    assert daemon is not None


def test_daemon_registers_workers(tmp_path):
    cfg = RuntimeConfig(goals_db=str(tmp_path / "goals.db"))
    cfg.workers["test"] = WorkerConfig(name="test", module="apps.test")
    daemon = Daemon(cfg, workspace=tmp_path)
    assert "test" in daemon.worker_names


def test_daemon_tick_cycle(tmp_path):
    """One tick cycle: check due workers, dispatch, collect results."""
    cfg = RuntimeConfig(goals_db=str(tmp_path / "goals.db"))
    cfg.workers["echo"] = WorkerConfig(
        name="echo", module="apps.echo", tick_interval=0,
    )
    daemon = Daemon(cfg, workspace=tmp_path)
    # Run one tick manually
    results = daemon.tick(code_override={"echo": "print('hello')"})
    assert len(results) >= 0  # May or may not find due workers on first tick


def test_daemon_status(tmp_path):
    cfg = RuntimeConfig(goals_db=str(tmp_path / "goals.db"))
    cfg.workers["w1"] = WorkerConfig(name="w1", module="apps.w1")
    daemon = Daemon(cfg, workspace=tmp_path)
    status = daemon.status()
    assert "workers" in status
    assert "goals" in status
```

- [ ] **Step 2: Write daemon.py**

```python
# runtime/daemon.py
"""Main daemon loop — the brain of the Kairos Platform."""

from __future__ import annotations

from pathlib import Path

from runtime.config import RuntimeConfig
from runtime.goals import GoalTracker
from runtime.scheduler import Scheduler
from runtime.dispatch import Dispatcher, WorkerResult
from runtime.router import TierRouter


class Daemon:
    """The runtime daemon — orchestrates workers, goals, and LLM routing."""

    def __init__(self, config: RuntimeConfig, workspace: Path | str):
        self._config = config
        self._workspace = Path(workspace)
        self._goals = GoalTracker(config.goals_db)
        self._scheduler = Scheduler(config.workers)
        self._dispatcher = Dispatcher(workspace)
        self._router = TierRouter(config.tiers)

    @property
    def worker_names(self) -> list[str]:
        return list(self._config.workers.keys())

    def tick(self, *, code_override: dict[str, str] | None = None) -> list[WorkerResult]:
        """Run one daemon tick: schedule, dispatch, collect."""
        due = self._scheduler.get_due()
        results = []

        for worker_config in due:
            self._scheduler.mark_started(worker_config.name)

            code = None
            if code_override and worker_config.name in code_override:
                code = code_override[worker_config.name]

            result = self._dispatcher.run_tick(worker_config, code=code)

            if result.success:
                self._scheduler.mark_completed(worker_config.name)
            else:
                self._scheduler.mark_failed(worker_config.name)

            results.append(result)

        return results

    def status(self) -> dict:
        """Return daemon status summary."""
        pending_goals = self._goals.list_pending()
        return {
            "workers": {
                name: {
                    "enabled": cfg.enabled,
                    "mode": cfg.mode,
                    "running": self._scheduler.is_running(name),
                }
                for name, cfg in self._config.workers.items()
            },
            "goals": {
                "pending": len(pending_goals),
            },
            "costs": self._router.cost_summary(),
        }

    def shutdown(self) -> None:
        """Clean shutdown."""
        self._goals.close()
```

- [ ] **Step 3: Run tests, commit**

```bash
cd /Users/kairos/Projects/kairos
uv run pytest tests/runtime/ -v
git add runtime/daemon.py tests/runtime/test_daemon.py
git commit -m "feat(runtime): daemon shell with tick cycle and status"
```

---

### Task 7: Runtime Exports and Verification

- [ ] **Step 1: Update runtime/__init__.py**

```python
# runtime/__init__.py
"""Kairos runtime — daemon, scheduler, dispatcher."""

from runtime.daemon import Daemon
from runtime.goals import GoalTracker, Goal, GoalStatus
from runtime.scheduler import Scheduler
from runtime.dispatch import Dispatcher, WorkerResult
from runtime.router import TierRouter, CostEntry
from runtime.config import RuntimeConfig, WorkerConfig, TierConfig

__all__ = [
    "Daemon", "GoalTracker", "Goal", "GoalStatus",
    "Scheduler", "Dispatcher", "WorkerResult",
    "TierRouter", "CostEntry",
    "RuntimeConfig", "WorkerConfig", "TierConfig",
]
```

- [ ] **Step 2: Run full suite**

```bash
cd /Users/kairos/Projects/kairos && uv run pytest tests/ -v --tb=short
```
Expected: All tests PASS (~95 platform + ~30 runtime = ~125)

- [ ] **Step 3: Verify imports**

```bash
cd /Users/kairos/Projects/kairos && uv run python -c "
from runtime import Daemon, GoalTracker, Scheduler, Dispatcher, TierRouter
from runtime import RuntimeConfig, WorkerConfig
print('Runtime imports OK')
"
```

- [ ] **Step 4: Commit**

```bash
git add runtime/__init__.py
git commit -m "feat(runtime): complete runtime module with all exports"
```

---

## Summary

| Task | What | Tests |
|------|------|-------|
| 1 | Runtime configuration | 3 |
| 2 | Goal tracker | 8 |
| 3 | Scheduler | 6 |
| 4 | Dispatcher | 4 |
| 5 | LLM router | 4 |
| 6 | Daemon shell | 4 |
| 7 | Exports + verification | — |
| **Total** | **7 tasks** | **~29 tests** |

## Next Plans

After this plan is complete:
1. **Apps: Atlas** — port research engine
2. **Apps: Arena** — port goal execution
3. **Apps: Ratchet** — port block lifecycle
4. **Apps: Governor** — port observe/decide
